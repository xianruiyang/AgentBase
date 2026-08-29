#!/usr/bin/env python3
"""CLI owner for the AgentBase Windows SWE final evaluation set."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
PROJECT_ROOT_HINT = HERE.parents[1]
COMMON = PROJECT_ROOT_HINT / "development" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from codex_runtime import (  # noqa: E402
    CodexRuntimeError,
    materialize_runtime_environment,
    resolve_runtime_environment,
    sanitized_process_environment,
)

from agentbase_codex import (  # noqa: E402
    API_EQUIVALENT_COST_SCHEMA,
    CODEX_RUN_RESULT_SCHEMA,
    CODEX_USAGE_FIELDS,
    REQUIRED_CANDIDATE_TOOLS,
    WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY,
    api_pricing_snapshot,
    candidate_capability_contract,
    candidate_preflight_failed_checks,
    candidate_runtime_tools,
    cleanup_candidate_runtime_temp,
    cleanup_evaluation_runtime_transients,
    evaluation_runtime_config_identity_descriptor,
    evaluation_runtime_home_controlled_identity,
    evaluation_runtime_transients_absent,
    format_usd_nanos,
    invalidate_sandbox_runtime,
    invoke_candidate,
    invoke_candidate_preflight,
    invoke_sandbox_setup,
    resolve_codex_identity,
    sandbox_backend_snapshot,
    sandbox_runtime_status as get_sandbox_runtime_status,
    stage_candidate_metadata,
    stage_candidate_skill_projection,
    stage_candidate_tool_probe_manifest,
    sync_evaluation_runtime_home,
    write_ready_sandbox_runtime_state,
)
from evaluation_core import (  # noqa: E402
    CaseLock,
    ControlledRuntimeDriftError,
    EvaluationError,
    PreconditionError,
    QUALIFICATION_SCHEMA,
    RECOVERABLE_ATTEMPT_STAGES,
    SandboxRuntimeInvalidError,
    SandboxSetupApprovalError,
    apply_windows_adapter_baseline,
    bounded_text,
    candidate_receipt_dir,
    candidate_run_identity,
    candidate_surface_identity,
    canonical_bytes,
    capture_candidate_patch,
    create_workspace,
    default_corpus_path,
    default_project_root,
    default_state_root,
    default_work_root,
    enforce_retry_policy,
    ensure_evaluation_roots,
    find_matching_qualification,
    find_qualification_receipts,
    framework_identity,
    load_attempt,
    load_corpus,
    new_attempt,
    prepare_sources,
    qualification_base_identity,
    qualification_receipt_dir,
    read_json,
    remove_managed_tree,
    require_profile,
    require_task,
    require_within,
    sha256_bytes,
    sha256_file,
    sandbox_runtime_home,
    sandbox_runtime_root,
    suite_task_ids,
    task_map,
    update_attempt as persist_attempt,
    utc_now,
    validate_identity,
    validate_receipt,
    verify_deep_swe,
    verify_upstream_source,
    verify_windows_adapter_assets,
    with_receipt_hash,
    write_immutable_receipt,
    write_json_atomic,
    write_text_atomic,
)
from windows_verifier import (  # noqa: E402
    VERIFIER_RESULT_SCHEMA,
    prepare_dependencies,
    verify_patch,
)


CANDIDATE_SCHEMA = "agentbase.windows-swe-candidate-result/v2"


def resolve_context(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    project_root = Path(args.project_root).resolve()
    corpus_path = Path(args.corpus).resolve() if args.corpus else default_corpus_path(project_root)
    state_root = Path(args.state_root).resolve()
    work_root = Path(args.work_root).resolve()
    ensure_evaluation_roots(
        project_root,
        state_root,
        work_root,
        installed_codex_root_from_args(args),
    )
    corpus = load_corpus(corpus_path)
    verify_windows_adapter_assets(project_root, corpus)
    return project_root, corpus_path, state_root, work_root, corpus


def default_codex_root() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).resolve() if configured else (Path.home() / ".codex").resolve()


def installed_codex_root_from_args(args: argparse.Namespace) -> Path:
    configured = getattr(args, "installed_codex_root", None)
    return Path(configured).resolve() if configured else default_codex_root()


def default_dotenv_path() -> Path:
    return default_codex_root() / ".env"


def require_installed_codex_runtime(
    installed_codex_root: Path,
    *,
    require_model_catalog: bool,
) -> None:
    required = ["auth.json"]
    if require_model_catalog:
        required.append("models_cache.json")
    missing = [name for name in required if not (installed_codex_root / name).is_file()]
    if missing:
        raise PreconditionError(
            "installed Codex runtime is incomplete under "
            f"{installed_codex_root}: missing {', '.join(missing)}"
        )


def resolve_network(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    raw = {
        "dotenv_path": str(Path(args.dotenv).resolve()),
        "required_keys": list(args.required_network_key),
        "proxy_dns": args.proxy_dns,
        "all_proxy_fanout": args.all_proxy_fanout,
    }
    try:
        return resolve_runtime_environment(raw)
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc


def process_environment(projection: Mapping[str, str]) -> dict[str, str]:
    try:
        environment = sanitized_process_environment(projection)
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc
    environment[WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY] = "1"
    return environment


def rematerialize_network(descriptor: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        projection = materialize_runtime_environment(dict(descriptor))
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc
    return dict(descriptor), projection


def print_result(value: Mapping[str, Any], *, view: str, human: str) -> None:
    if view == "machine":
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(human)


def update_attempt(
    root: Path,
    attempt: Mapping[str, Any],
    **changes: Any,
) -> dict[str, Any]:
    """Persist an attempt update and expose only meaningful stage transitions."""

    previous_stage = attempt.get("stage")
    value = persist_attempt(root, attempt, **changes)
    current_stage = value.get("stage")
    if current_stage != previous_stage:
        print(
            f"STAGE {value.get('attempt_id', 'unknown')} {current_stage}",
            file=sys.stderr,
            flush=True,
        )
    return value


def selected_task_ids(args: argparse.Namespace, corpus: Mapping[str, Any]) -> list[str]:
    if getattr(args, "task", None):
        require_task(corpus, args.task)
        return [args.task]
    return suite_task_ids(corpus, getattr(args, "suite", "smoke"))


def _qualification_state(
    project_root: Path,
    corpus_path: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        base = qualification_base_identity(
            project_root,
            corpus_path,
            state_root,
            corpus,
            task_id,
        )
    except EvaluationError:
        return None, []
    receipts = find_qualification_receipts(state_root, task_id, base["identity_sha256"])
    return base, receipts


def command_validate(args: argparse.Namespace) -> int:
    project_root, corpus_path, _, _, corpus = resolve_context(args)
    candidate = candidate_surface_identity(project_root)
    framework = framework_identity(project_root)
    result = {
        "schema": "agentbase.windows-swe-static-validation/v1",
        "corpus": corpus["id"],
        "corpus_path": str(corpus_path),
        "task_count": len(corpus["tasks"]),
        "candidate_surface_identity_sha256": candidate["identity_sha256"],
        "framework_identity_sha256": framework["identity_sha256"],
        "external_actions": False,
    }
    print_result(
        result,
        view=args.view,
        human=(
            f"VALID {corpus['id']}: 9 Windows-native tasks; "
            "no source clone, dependency install, model call, or verifier run was performed."
        ),
    )
    return 0


def _task_statuses(
    project_root: Path,
    corpus_path: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    task_ids: Sequence[str],
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for task_id in task_ids:
        task = require_task(corpus, task_id)
        source = "missing"
        try:
            verify_upstream_source(state_root, corpus, task_id)
            source = "prepared"
        except EvaluationError:
            pass
        base, qualifications = _qualification_state(
            project_root,
            corpus_path,
            state_root,
            corpus,
            task_id,
        )
        statuses.append(
            {
                "task_id": task_id,
                "difficulty": task["difficulty"],
                "success_rollouts": task["difficulty_evidence"]["successful_rollouts"],
                "source": source,
                "qualification": "qualified" if qualifications else "pending",
                "qualification_count": len(qualifications),
                "base_identity_sha256": base["identity_sha256"] if base else None,
            }
        )
    return statuses


def _status_tree(statuses: Sequence[Mapping[str, Any]]) -> str:
    difficulty_labels = {
        "easy": "easy",
        "medium": "medium",
        "hard": "hard",
        "very-hard": "very-hard",
    }
    grouped: dict[str, list[Mapping[str, Any]]] = {
        name: [] for name in difficulty_labels
    }
    for status in statuses:
        grouped[str(status["difficulty"])].append(status)
    lines = ["AgentBase Windows SWE"]
    nonempty = [(key, values) for key, values in grouped.items() if values]
    for group_index, (difficulty, values) in enumerate(nonempty):
        group_branch = "└─" if group_index == len(nonempty) - 1 else "├─"
        lines.append(f"{group_branch} {difficulty_labels[difficulty]}")
        prefix = "   " if group_index == len(nonempty) - 1 else "│  "
        for index, value in enumerate(values):
            branch = "└─" if index == len(values) - 1 else "├─"
            lines.append(
                f"{prefix}{branch} {value['task_id']} "
                f"[{value['success_rollouts']}/116; {value['source']}; {value['qualification']}]"
            )
    return "\n".join(lines)


def command_list(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, _, corpus = resolve_context(args)
    task_ids = selected_task_ids(args, corpus)
    statuses = _task_statuses(project_root, corpus_path, state_root, corpus, task_ids)
    result = {
        "schema": "agentbase.windows-swe-task-status/v1",
        "suite": args.suite if not args.task else None,
        "tasks": statuses,
    }
    print_result(result, view=args.view, human=_status_tree(statuses))
    return 0


def command_next(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, _, corpus = resolve_context(args)
    statuses = _task_statuses(
        project_root,
        corpus_path,
        state_root,
        corpus,
        suite_task_ids(corpus, args.suite),
    )
    selected = next(
        (status for status in statuses if status["qualification"] == "qualified"),
        None,
    )
    result = {
        "schema": "agentbase.windows-swe-next/v1",
        "suite": args.suite,
        "selected": selected,
        "reason": "first-qualified-in-suite-order" if selected else "no-qualified-task",
    }
    human = (
        f"NEXT {selected['task_id']} ({selected['difficulty']})"
        if selected
        else "No task is selectable: prepare a case and complete its no-op/reference oracle first."
    )
    print_result(result, view=args.view, human=human)
    return 0 if selected else 3


def command_check(args: argparse.Namespace) -> int:
    project_root, _, state_root, _, corpus = resolve_context(args)
    task_ids = selected_task_ids(args, corpus)
    required: dict[str, tuple[str, ...]] = {
        **REQUIRED_CANDIDATE_TOOLS,
        "npm": ("npm.cmd", "npm.exe", "npm"),
        "codex": ("codex.cmd", "codex.exe", "codex"),
    }
    if any(
        require_task(corpus, task_id)["toolchain"].get("package_manager") == "pnpm"
        for task_id in task_ids
    ):
        required["pnpm"] = ("pnpm.cmd", "pnpm.exe", "pnpm")

    tools: dict[str, str | None] = {}
    for name, candidates in required.items():
        resolved = None
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                break
        if resolved and "\\WindowsApps\\" in str(Path(resolved).resolve()):
            resolved = None
        tools[name] = resolved
    missing = [name for name, path in tools.items() if not path]
    prepared: dict[str, bool] = {}
    for task_id in task_ids:
        try:
            verify_deep_swe(state_root, corpus)
            verify_upstream_source(state_root, corpus, task_id)
            prepared[task_id] = True
        except EvaluationError:
            prepared[task_id] = False
    result = {
        "schema": "agentbase.windows-swe-host-check/v1",
        "tools": tools,
        "missing": missing,
        "prepared": prepared,
        "installed_or_modified": False,
    }
    passed = not missing
    human = (
        "CHECK PASS: required host tools are discoverable; no software was installed."
        if passed
        else f"CHECK FAIL: missing {', '.join(missing)}; no software was installed."
    )
    print_result(result, view=args.view, human=human)
    return 0 if passed else 2


def command_prepare(args: argparse.Namespace) -> int:
    _, _, state_root, _, corpus = resolve_context(args)
    task_ids = selected_task_ids(args, corpus)
    descriptor, projection = resolve_network(args)
    prepared = prepare_sources(
        state_root,
        corpus,
        task_ids,
        process_environment(projection),
    )
    result = {
        "schema": "agentbase.windows-swe-prepare/v1",
        "task_ids": task_ids,
        "source": prepared,
        "runtime_environment": descriptor,
    }
    print_result(
        result,
        view=args.view,
        human=f"PREPARED {len(task_ids)} task source set(s) at pinned commits; no model was run.",
    )
    return 0


def _codex_executable_from_tools(tools: Mapping[str, Any]) -> Path:
    try:
        identity = tools["tools"]["codex"]
        path = Path(str(identity["path"])).resolve()
        expected_sha256 = str(identity["sha256"])
    except (KeyError, TypeError) as exc:
        raise EvaluationError("runtime tool identity omits the Codex executable") from exc
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise EvaluationError("runtime Codex executable changed after identity capture")
    return path


def _pwsh_executable_from_tools(tools: Mapping[str, Any]) -> Path:
    try:
        identity = tools["tools"]["pwsh"]
        path = Path(str(identity["path"])).resolve()
        expected_sha256 = str(identity["sha256"])
    except (KeyError, TypeError) as exc:
        raise EvaluationError("runtime tool identity omits PowerShell") from exc
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise EvaluationError("runtime PowerShell changed after identity capture")
    return path


def _resolve_current_codex_identity(
    project_root: Path,
    explicit_path: Path | None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="codex-identity-",
        ignore_cleanup_errors=True,
    ) as directory:
        return resolve_codex_identity(
            project_root,
            Path(directory) / "codex.json",
            explicit_path,
        )


def _prepare_ready_sandbox_runtime(
    *,
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    codex_identity: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    home, controlled = sync_evaluation_runtime_home(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
    )
    cleanup_evaluation_runtime_transients(home)
    status = get_sandbox_runtime_status(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
        codex_identity,
    )
    runtime_use = status.get("runtime_use")
    if status.get("ready") is not True or not isinstance(runtime_use, dict):
        reasons = ", ".join(str(item) for item in status.get("reason_codes", []))
        raise PreconditionError(
            "evaluation sandbox runtime is not ready"
            + (f" ({reasons})" if reasons else "")
            + "; run sandbox-setup explicitly"
        )
    if runtime_use.get("controlled_identity_sha256") != controlled.get(
        "identity_sha256"
    ):
        raise EvaluationError("sandbox runtime controlled identity changed during preparation")
    return home, dict(runtime_use), controlled


def _precheck_sandbox_runtime(
    *,
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    explicit_codex_path: Path | None,
) -> None:
    codex_identity = _resolve_current_codex_identity(
        project_root,
        explicit_codex_path,
    )
    with CaseLock(state_root, "sandbox-runtime"):
        _prepare_ready_sandbox_runtime(
            project_root=project_root,
            state_root=state_root,
            installed_codex_root=installed_codex_root,
            corpus=corpus,
            codex_identity=codex_identity,
        )


def _invalidate_runtime_after_rejection(
    state_root: Path,
    error: SandboxRuntimeInvalidError,
    *,
    expected_identity_sha256: str,
    runtime_lock_held: bool = False,
) -> PreconditionError:
    def invalidate() -> dict[str, Any]:
        return invalidate_sandbox_runtime(
            state_root,
            "codex-rejected-prepared-runtime",
            expected_identity_sha256=expected_identity_sha256,
        )

    state = invalidate() if runtime_lock_held else None
    if state is None:
        with CaseLock(state_root, "sandbox-runtime"):
            state = invalidate()
    if (
        state.get("status") == "ready"
        and state.get("identity_sha256") != expected_identity_sha256
    ):
        return PreconditionError(
            f"{bounded_text(str(error), 400)}; the rejected runtime was superseded "
            "by a newer ready runtime, so retry the command"
        )
    return PreconditionError(
        f"{bounded_text(str(error), 400)}; runtime was invalidated and sandbox-setup is required"
    )


def _verifier_runtime_identity(
    task: Mapping[str, Any],
    runtime_tools: Mapping[str, Any],
) -> dict[str, Any]:
    names = ["codex", "git", "pwsh"]
    names.append("python" if task["toolchain"]["kind"] == "python" else "node")
    try:
        selected = {name: dict(runtime_tools["tools"][name]) for name in names}
    except (KeyError, TypeError) as exc:
        raise EvaluationError("runtime tool identity omits a verifier dependency") from exc
    payload = {
        "schema": "agentbase.windows-swe-verifier-runtime/v1",
        "tools": selected,
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def command_oracle(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, work_root, corpus = resolve_context(args)
    installed_codex_root = installed_codex_root_from_args(args)
    task_id = args.task
    require_task(corpus, task_id)
    _precheck_sandbox_runtime(
        project_root=project_root,
        state_root=state_root,
        installed_codex_root=installed_codex_root,
        corpus=corpus,
        explicit_codex_path=args.codex_executable,
    )
    descriptor, projection = resolve_network(args)
    environment = process_environment(projection)
    prepare_sources(state_root, corpus, [task_id], environment)
    base = qualification_base_identity(
        project_root,
        corpus_path,
        state_root,
        corpus,
        task_id,
    )
    run_id = f"oracle-{task_id}-{int(time.time())}-{os.getpid()}"
    run_root = state_root / "qualification-runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    tools = candidate_runtime_tools(project_root, run_root, args.codex_executable)
    verifier_runtime = _verifier_runtime_identity(require_task(corpus, task_id), tools)
    codex_executable = _codex_executable_from_tools(tools)
    pwsh_executable = _pwsh_executable_from_tools(tools)
    repetitions: list[dict[str, Any]] = []
    p2p_exclusions: list[str] = []
    baseline_policy = require_task(corpus, task_id).get("windows_oracle", {}).get(
        "p2p_baseline_policy"
    )
    sandbox_runtime: dict[str, Any] | None = None
    with CaseLock(state_root, f"oracle:{task_id}"):
        with CaseLock(state_root, "sandbox-runtime"):
            codex_home, sandbox_runtime, _ = _prepare_ready_sandbox_runtime(
                project_root=project_root,
                state_root=state_root,
                installed_codex_root=installed_codex_root,
                corpus=corpus,
                codex_identity=tools["tools"]["codex"],
            )
            try:
                for index in range(
                    int(corpus["adapter"]["qualification_repetitions"])
                ):
                    noop = verify_patch(
                        project_root=project_root,
                        state_root=state_root,
                        work_root=work_root,
                        corpus=corpus,
                        task_id=task_id,
                        run_name=f"{run_id}/{index:02d}-noop",
                        patch_kind="noop",
                        candidate_patch=None,
                        artifact_root=run_root / f"{index:02d}-noop",
                        network_environment=environment,
                        codex_executable=codex_executable,
                        pwsh_executable=pwsh_executable,
                        codex_home=codex_home,
                        sandbox_runtime=sandbox_runtime,
                        retain_workspace=args.retain_workspace,
                        p2p_exclusions=p2p_exclusions,
                    )
                    if noop["grade"]["reward"]["reward"] != 0:
                        raise EvaluationError("Windows no-op oracle must score 0")
                    observed_noop_exclusions = list(
                        noop.get("observed_baseline_p2p_exclusions", [])
                    )
                    if baseline_policy in {
                        "exclude-stable-skips",
                        "exclude-stable-nonpassing",
                    }:
                        if index == 0:
                            p2p_exclusions = observed_noop_exclusions
                        elif observed_noop_exclusions != p2p_exclusions:
                            raise EvaluationError(
                                "Windows no-op baseline exclusions changed across repetitions"
                            )
                    elif observed_noop_exclusions:
                        raise EvaluationError(
                            "Windows baseline outcomes were projected without an enabled policy"
                        )
                    reference = verify_patch(
                        project_root=project_root,
                        state_root=state_root,
                        work_root=work_root,
                        corpus=corpus,
                        task_id=task_id,
                        run_name=f"{run_id}/{index:02d}-reference",
                        patch_kind="reference",
                        candidate_patch=None,
                        artifact_root=run_root / f"{index:02d}-reference",
                        network_environment=environment,
                        codex_executable=codex_executable,
                        pwsh_executable=pwsh_executable,
                        codex_home=codex_home,
                        sandbox_runtime=sandbox_runtime,
                        retain_workspace=args.retain_workspace,
                        p2p_exclusions=p2p_exclusions,
                    )
                    if reference["grade"]["reward"]["reward"] != 1:
                        raise EvaluationError("Windows reference oracle must score 1")
                    if list(
                        reference.get("observed_baseline_p2p_exclusions", [])
                    ) != p2p_exclusions:
                        raise EvaluationError(
                            "Windows reference changed the stable P2P exclusion frontier"
                        )
                    if (
                        noop["dependency_identity"]["identity_sha256"]
                        != reference["dependency_identity"]["identity_sha256"]
                    ):
                        raise EvaluationError(
                            "no-op and reference dependency identities differ"
                        )
                    repetitions.append({"noop": noop, "reference": reference})
            except SandboxRuntimeInvalidError as exc:
                raise _invalidate_runtime_after_rejection(
                    state_root,
                    exc,
                    expected_identity_sha256=str(sandbox_runtime["identity_sha256"]),
                    runtime_lock_held=True,
                ) from exc
            finally:
                cleanup_evaluation_runtime_transients(codex_home)
    dependency_ids = {
        item[mode]["dependency_identity"]["identity_sha256"]
        for item in repetitions
        for mode in ("noop", "reference")
    }
    if len(dependency_ids) != 1:
        raise EvaluationError("qualification repetitions resolved different dependencies")
    dependency_id = next(iter(dependency_ids))
    full_identity = sha256_bytes(
        canonical_bytes(
            {
                "base_identity_sha256": base["identity_sha256"],
                "dependency_identity_sha256": dependency_id,
                "verifier_runtime_identity_sha256": verifier_runtime["identity_sha256"],
                "p2p_exclusions": p2p_exclusions,
            }
        )
    )
    receipt = {
        "schema": QUALIFICATION_SCHEMA,
        "task_id": task_id,
        "created_at": utc_now(),
        "identity_sha256": full_identity,
        "base_identity_sha256": base["identity_sha256"],
        "base_identity": base,
        "dependency_identity_sha256": dependency_id,
        "verifier_runtime_identity_sha256": verifier_runtime["identity_sha256"],
        "verifier_runtime": verifier_runtime,
        "runtime_environment": descriptor,
        "runtime_tools_identity_sha256": tools["identity_sha256"],
        "p2p_exclusions": p2p_exclusions,
        "sandbox_runtime": {
            "identity_sha256": sandbox_runtime["identity_sha256"],
            "controlled_identity_sha256": sandbox_runtime[
                "controlled_identity_sha256"
            ],
            "backend_identity_sha256": sandbox_runtime[
                "backend_identity_sha256"
            ],
            "persistent_and_shared": True,
            "setup_invoked": False,
        },
        "repetitions": repetitions,
        "qualified": True,
        "leaderboard_comparable": False,
    }
    path = qualification_receipt_dir(state_root, task_id) / f"{full_identity}.json"
    receipt = write_immutable_receipt(path, receipt)
    print_result(
        receipt,
        view=args.view,
        human=f"QUALIFIED {task_id}: no-op=0 and reference=1 across {len(repetitions)} Windows repetitions.",
    )
    return 0


def _candidate_receipt_path(
    state_root: Path,
    task_id: str,
    profile: str,
    identity_sha256: str,
) -> Path:
    return candidate_receipt_dir(state_root, task_id, profile) / f"{identity_sha256}.json"


def _write_candidate_receipt(
    state_root: Path,
    task_id: str,
    profile: str,
    identity: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = {
        "schema": CANDIDATE_SCHEMA,
        "task_id": task_id,
        "profile": profile,
        "created_at": utc_now(),
        "candidate_identity_sha256": identity["identity_sha256"],
        "candidate_identity": dict(identity),
        **dict(payload),
    }
    return write_immutable_receipt(
        _candidate_receipt_path(
            state_root,
            task_id,
            profile,
            str(identity["identity_sha256"]),
        ),
        receipt,
    )


def _run_candidate_verifier(
    *,
    project_root: Path,
    state_root: Path,
    work_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    attempt_id: str,
    attempt_root: Path,
    patch: Path,
    environment: Mapping[str, str],
    runtime_tools: Mapping[str, Any],
    codex_home: Path,
    sandbox_runtime: Mapping[str, Any],
    expected_dependency_sha256: str,
    p2p_exclusions: Sequence[str],
    retain_workspace: bool,
) -> dict[str, Any]:
    verifier = verify_patch(
        project_root=project_root,
        state_root=state_root,
        work_root=work_root,
        corpus=corpus,
        task_id=task_id,
        run_name=f"{attempt_id}/candidate-verification",
        patch_kind="candidate",
        candidate_patch=patch,
        artifact_root=attempt_root / "verifier",
        network_environment=environment,
        codex_executable=_codex_executable_from_tools(runtime_tools),
        pwsh_executable=_pwsh_executable_from_tools(runtime_tools),
        codex_home=codex_home,
        sandbox_runtime=sandbox_runtime,
        retain_workspace=retain_workspace,
        p2p_exclusions=p2p_exclusions,
    )
    actual = verifier["dependency_identity"]["identity_sha256"]
    if actual != expected_dependency_sha256:
        raise EvaluationError(
            "candidate verifier dependency identity differs from the qualified oracle"
        )
    gate_failed = any(
        check.get("bucket") == "gate" and check.get("exit_code") != 0
        for check in verifier.get("checks", [])
    )
    if not gate_failed and list(
        verifier.get("observed_baseline_p2p_exclusions", [])
    ) != list(p2p_exclusions):
        raise EvaluationError(
            "candidate changed the qualified Windows P2P exclusion frontier"
        )
    return verifier


def _cleanup_candidate_workspace(
    work_root: Path,
    workspace: Path,
    *,
    retain_workspace: bool,
) -> dict[str, Any]:
    if retain_workspace:
        return {"retained": True, "path": str(workspace.resolve())}
    try:
        managed = require_within(work_root, workspace)
        if managed.exists():
            remove_managed_tree(work_root, managed)
        return {"retained": False, "removed": True}
    except (EvaluationError, OSError) as exc:
        return {
            "retained": True,
            "removed": False,
            "path": str(workspace.resolve()),
            "cleanup_error": bounded_text(str(exc), 400),
        }


def command_run(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, work_root, corpus = resolve_context(args)
    installed_codex_root = installed_codex_root_from_args(args)
    require_installed_codex_runtime(
        installed_codex_root,
        require_model_catalog=True,
    )
    task_id = args.task
    profile_name = args.profile
    task = require_task(corpus, task_id)
    require_profile(corpus, profile_name)
    _precheck_sandbox_runtime(
        project_root=project_root,
        state_root=state_root,
        installed_codex_root=installed_codex_root,
        corpus=corpus,
        explicit_codex_path=args.codex_executable,
    )
    descriptor, projection = resolve_network(args)
    environment = process_environment(projection)
    verify_deep_swe(state_root, corpus)
    verify_upstream_source(state_root, corpus, task_id)

    attempt_id, attempt_root, attempt = new_attempt(
        state_root,
        task_id=task_id,
        profile=profile_name,
        retry_reason=args.retry_reason,
    )
    codex_home: Path | None = None
    sandbox_runtime: dict[str, Any] | None = None
    try:
        with (
            CaseLock(state_root, f"candidate:{task_id}:{profile_name}"),
            CaseLock(state_root, "sandbox-runtime"),
        ):
            candidate_workspace = create_workspace(
                state_root,
                work_root,
                corpus,
                task_id,
                f"{attempt_id}/candidate",
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                stage="candidate-setup",
                candidate_workspace=str(candidate_workspace),
                runtime_environment=descriptor,
            )
            dependency, dependency_values = prepare_dependencies(
                task,
                candidate_workspace,
                attempt_root / "candidate-setup",
                environment,
            )
            windows_adapter = apply_windows_adapter_baseline(
                project_root,
                candidate_workspace,
                task,
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                windows_adapter_baseline=windows_adapter,
            )
            base = qualification_base_identity(
                project_root,
                corpus_path,
                state_root,
                corpus,
                task_id,
            )
            qualifications = find_qualification_receipts(
                state_root,
                task_id,
                base["identity_sha256"],
            )
            runtime_tools = candidate_runtime_tools(
                project_root,
                attempt_root,
                args.codex_executable,
            )
            verifier_runtime = _verifier_runtime_identity(task, runtime_tools)
            qualification = find_matching_qualification(
                qualifications,
                dependency["identity_sha256"],
                verifier_runtime["identity_sha256"],
            )
            if qualification is None:
                raise PreconditionError(
                    "no current Windows qualification matches the resolved dependencies; run oracle"
                )
            expected_config_identity = evaluation_runtime_config_identity_descriptor(
                project_root,
                state_root,
                installed_codex_root,
                corpus,
            )
            identity = candidate_run_identity(
                project_root=project_root,
                corpus_path=corpus_path,
                corpus=corpus,
                task_id=task_id,
                profile_name=profile_name,
                qualification_receipt=qualification,
                dependency_identity=dependency,
                runtime_environment=descriptor,
                runtime_tools=runtime_tools,
                config_descriptor=expected_config_identity,
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                candidate_identity_sha256=identity["identity_sha256"],
                candidate_identity=identity,
                qualification_receipt=qualification,
                dependency_identity=dependency,
                runtime_tools=runtime_tools,
            )
            existing_path = _candidate_receipt_path(
                state_root,
                task_id,
                profile_name,
                identity["identity_sha256"],
            )
            if existing_path.is_file():
                receipt = validate_receipt(read_json(existing_path), schema=CANDIDATE_SCHEMA)
                if receipt.get("candidate_identity_sha256") != identity["identity_sha256"]:
                    raise EvaluationError("candidate result path and identity disagree")
                workspace_cleanup = _cleanup_candidate_workspace(
                    work_root,
                    candidate_workspace,
                    retain_workspace=args.retain_workspace,
                )
                update_attempt(
                    attempt_root,
                    attempt,
                    status="reused",
                    stage="terminal",
                    receipt_path=str(existing_path),
                    workspace_cleanup=workspace_cleanup,
                )
                print_result(
                    receipt,
                    view=args.view,
                    human=f"REUSED {task_id}/{profile_name}: reward={receipt.get('reward')}",
                )
                return 0
            enforce_retry_policy(
                state_root,
                identity["identity_sha256"],
                args.retry_reason,
            )
            codex_home, sandbox_runtime, controlled = _prepare_ready_sandbox_runtime(
                project_root=project_root,
                state_root=state_root,
                installed_codex_root=installed_codex_root,
                corpus=corpus,
                codex_identity=runtime_tools["tools"]["codex"],
            )
            config_descriptor = controlled["config"]
            if config_descriptor.get("identity") != expected_config_identity:
                raise EvaluationError("evaluation runtime config identity changed")
            metadata = stage_candidate_metadata(
                project_root,
                state_root,
                corpus,
                task_id,
                candidate_workspace,
                attempt_root,
                runtime_tools,
                dependency,
                dependency_values,
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                status="running",
                stage="candidate-running",
                config_descriptor=config_descriptor,
                candidate_metadata=metadata,
            )
            codex_result = invoke_candidate(
                project_root=project_root,
                workspace=candidate_workspace,
                state_root=state_root,
                attempt_root=attempt_root,
                codex_home=codex_home,
                runtime_temp=attempt_root / "runtime-temp",
                sandbox_runtime=sandbox_runtime,
                installed_codex_root=installed_codex_root,
                corpus=corpus,
                profile_name=profile_name,
                metadata=metadata,
                process_environment=environment,
                codex_executable_path=_codex_executable_from_tools(runtime_tools),
                timeout_seconds=args.timeout_seconds,
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                stage="candidate-finished",
                codex_result=codex_result,
            )
            if codex_result.get("runtime_cleanup", {}).get("passed") is not True:
                raise EvaluationError(
                    "candidate output is preserved, but same-sandbox runtime cleanup failed; "
                    f"recover --attempt-id {attempt_id} after correcting the cleanup path"
                )
            patch_path = attempt_root / "candidate.patch"
            try:
                patch = capture_candidate_patch(candidate_workspace, task, patch_path)
            except EvaluationError as exc:
                receipt = _write_candidate_receipt(
                    state_root,
                    task_id,
                    profile_name,
                    identity,
                    {
                        "attempt_id": attempt_id,
                        "valid": False,
                        "reward": 0,
                        "terminal_reason": str(exc),
                        "codex_result": codex_result,
                        "qualification_receipt_sha256": qualification["receipt_sha256"],
                    },
                )
                workspace_cleanup = _cleanup_candidate_workspace(
                    work_root,
                    candidate_workspace,
                    retain_workspace=args.retain_workspace,
                )
                update_attempt(
                    attempt_root,
                    attempt,
                    status="candidate-invalid",
                    stage="terminal",
                    receipt_path=str(
                        _candidate_receipt_path(
                            state_root,
                            task_id,
                            profile_name,
                            identity["identity_sha256"],
                        )
                    ),
                    workspace_cleanup=workspace_cleanup,
                )
                print_result(
                    receipt,
                    view=args.view,
                    human=f"INVALID {task_id}/{profile_name}: reward=0; {exc}",
                )
                return 0
            attempt = update_attempt(
                attempt_root,
                attempt,
                stage="patch-captured",
                patch=patch,
            )
            attempt = update_attempt(
                attempt_root,
                attempt,
                stage="verifier-running",
            )
            verifier = _run_candidate_verifier(
                project_root=project_root,
                state_root=state_root,
                work_root=work_root,
                corpus=corpus,
                task_id=task_id,
                attempt_id=attempt_id,
                attempt_root=attempt_root,
                patch=patch_path,
                environment=environment,
                runtime_tools=runtime_tools,
                codex_home=codex_home,
                sandbox_runtime=sandbox_runtime,
                expected_dependency_sha256=dependency["identity_sha256"],
                p2p_exclusions=qualification.get("p2p_exclusions", []),
                retain_workspace=args.retain_workspace,
            )
            reward = int(verifier["grade"]["reward"]["reward"])
            receipt = _write_candidate_receipt(
                state_root,
                task_id,
                profile_name,
                identity,
                {
                    "attempt_id": attempt_id,
                    "valid": True,
                    "reward": reward,
                    "patch": patch,
                    "codex_result": codex_result,
                    "verifier": verifier,
                    "qualification_receipt_sha256": qualification["receipt_sha256"],
                    "leaderboard_comparable": False,
                },
            )
            receipt_path = _candidate_receipt_path(
                state_root,
                task_id,
                profile_name,
                identity["identity_sha256"],
            )
            workspace_cleanup = _cleanup_candidate_workspace(
                work_root,
                candidate_workspace,
                retain_workspace=args.retain_workspace,
            )
            update_attempt(
                attempt_root,
                attempt,
                status="completed",
                stage="terminal",
                receipt_path=str(receipt_path),
                workspace_cleanup=workspace_cleanup,
            )
            print_result(
                receipt,
                view=args.view,
                human=f"COMPLETED {task_id}/{profile_name}: reward={reward}; Windows-derived, not DeepSWE leaderboard-comparable.",
            )
            return 0
    except PreconditionError as exc:
        failure: PreconditionError = exc
        if isinstance(exc, SandboxRuntimeInvalidError):
            if sandbox_runtime is None:
                raise EvaluationError(
                    "sandbox runtime rejection omitted the prepared runtime identity"
                ) from exc
            failure = _invalidate_runtime_after_rejection(
                state_root,
                exc,
                expected_identity_sha256=str(sandbox_runtime["identity_sha256"]),
            )
        workspace_value = attempt.get("candidate_workspace")
        workspace_cleanup = (
            _cleanup_candidate_workspace(
                work_root,
                Path(str(workspace_value)),
                retain_workspace=args.retain_workspace,
            )
            if workspace_value
            else None
        )
        update_attempt(
            attempt_root,
            attempt,
            status="blocked-precondition",
            stage=attempt.get("stage", "unknown"),
            failure=str(failure),
            workspace_cleanup=workspace_cleanup,
        )
        if failure is not exc:
            raise failure from exc
        raise
    except Exception as exc:
        failure_changes: dict[str, Any] = {
            "status": "infrastructure-failed",
            "stage": attempt.get("stage", "unknown"),
            "failure": str(exc),
        }
        codex_result_path = attempt_root / "codex-result.json"
        if codex_result_path.is_file() and "codex_result" not in attempt:
            try:
                recovered_codex_result = read_json(codex_result_path)
                if (
                    recovered_codex_result.get("schema") == CODEX_RUN_RESULT_SCHEMA
                    and recovered_codex_result.get("model_invoked") is True
                ):
                    failure_changes["codex_result"] = recovered_codex_result
                    failure_changes["stage"] = "candidate-finished"
            except Exception as recovery_exc:
                failure_changes["codex_result_recovery_failure"] = bounded_text(
                    str(recovery_exc), 240
                )
        update_attempt(
            attempt_root,
            attempt,
            **failure_changes,
        )
        raise
    finally:
        if codex_home is not None:
            cleanup_evaluation_runtime_transients(codex_home)
        runtime_temp = attempt_root / "runtime-temp"
        if runtime_temp.exists():
            try:
                runtime_temp.rmdir()
            except OSError:
                pass


def command_recover(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, work_root, corpus = resolve_context(args)
    installed_codex_root = installed_codex_root_from_args(args)
    attempt_root, attempt = load_attempt(state_root, args.attempt_id)
    if attempt.get("stage") == "terminal":
        receipt_path = attempt.get("receipt_path")
        if receipt_path:
            expected_path = _candidate_receipt_path(
                state_root,
                str(attempt["task_id"]),
                str(attempt["profile"]),
                str(attempt["candidate_identity_sha256"]),
            )
            if Path(str(receipt_path)).resolve() != expected_path.resolve():
                raise EvaluationError("terminal attempt references an unexpected result path")
            result = validate_receipt(read_json(expected_path), schema=CANDIDATE_SCHEMA)
            if result.get("candidate_identity_sha256") != attempt["candidate_identity_sha256"]:
                raise EvaluationError("terminal attempt and candidate result identity disagree")
        else:
            result = attempt
        print_result(result, view=args.view, human=f"TERMINAL {args.attempt_id}: {attempt.get('status')}")
        return 0
    if attempt.get("stage") not in RECOVERABLE_ATTEMPT_STAGES:
        raise EvaluationError(
            "recovery never reruns a model; this attempt has no completed candidate output"
        )
    task_id = str(attempt["task_id"])
    profile_name = str(attempt["profile"])
    task = require_task(corpus, task_id)
    workspace = Path(str(attempt["candidate_workspace"])).resolve()
    require_within(work_root, workspace)
    codex_home: Path | None = None
    sandbox_runtime: dict[str, Any] | None = None
    try:
        with (
            CaseLock(state_root, f"candidate:{task_id}:{profile_name}"),
            CaseLock(state_root, "sandbox-runtime"),
        ):
            descriptor, projection = rematerialize_network(attempt["runtime_environment"])
            environment = process_environment(projection)
            verify_deep_swe(state_root, corpus)
            verify_upstream_source(state_root, corpus, task_id)

            qualification = validate_receipt(
                attempt["qualification_receipt"],
                schema=QUALIFICATION_SCHEMA,
            )
            base = qualification_base_identity(
                project_root,
                corpus_path,
                state_root,
                corpus,
                task_id,
            )
            current_qualifications = find_qualification_receipts(
                state_root,
                task_id,
                base["identity_sha256"],
            )
            if not any(
                item["receipt_sha256"] == qualification["receipt_sha256"]
                for item in current_qualifications
            ):
                raise PreconditionError("the attempt qualification is no longer current")

            try:
                recorded_codex = Path(
                    str(attempt["runtime_tools"]["tools"]["codex"]["path"])
                ).resolve()
            except (KeyError, TypeError) as exc:
                raise EvaluationError("attempt runtime identity omits Codex") from exc
            current_tools = candidate_runtime_tools(
                project_root,
                attempt_root / "recovery-runtime",
                recorded_codex,
            )
            config_identity = evaluation_runtime_config_identity_descriptor(
                project_root,
                state_root,
                installed_codex_root,
                corpus,
            )
            identity = candidate_run_identity(
                project_root=project_root,
                corpus_path=corpus_path,
                corpus=corpus,
                task_id=task_id,
                profile_name=profile_name,
                qualification_receipt=qualification,
                dependency_identity=attempt["dependency_identity"],
                runtime_environment=descriptor,
                runtime_tools=current_tools,
                config_descriptor=config_identity,
            )
            if identity["identity_sha256"] != attempt.get("candidate_identity_sha256"):
                raise PreconditionError(
                    "the frozen candidate identity changed; this attempt cannot be recovered"
                )
            recorded_identity = attempt.get("candidate_identity")
            if recorded_identity is not None:
                validate_identity(
                    recorded_identity,
                    schema="agentbase.windows-swe-candidate-identity/v1",
                )
                if canonical_bytes(recorded_identity) != canonical_bytes(identity):
                    raise EvaluationError(
                        "recorded candidate identity payload does not match its hash"
                    )

            codex_result = attempt.get("codex_result")
            if not isinstance(codex_result, dict):
                raise EvaluationError("recoverable attempt omits its completed candidate result")
            runtime_cleanup = codex_result.get("runtime_cleanup")
            if not isinstance(runtime_cleanup, dict) or runtime_cleanup.get("passed") is not True:
                metadata = attempt.get("candidate_metadata")
                if not isinstance(metadata, dict):
                    raise EvaluationError(
                        "recoverable attempt omits the staged runtime cleanup identity"
                    )
                codex_home, sandbox_runtime, _ = _prepare_ready_sandbox_runtime(
                    project_root=project_root,
                    state_root=state_root,
                    installed_codex_root=installed_codex_root,
                    corpus=corpus,
                    codex_identity=current_tools["tools"]["codex"],
                )
                runtime_cleanup = cleanup_candidate_runtime_temp(
                    workspace=workspace,
                    attempt_root=attempt_root,
                    runtime_temp=attempt_root / "runtime-temp",
                    codex_home=codex_home,
                    codex_executable_path=_codex_executable_from_tools(current_tools),
                    pwsh_executable_path=Path(
                        str(metadata["runtime_cleanup_shell_path"])
                    ),
                    expected_pwsh_sha256=str(
                        metadata["runtime_cleanup_shell_sha256"]
                    ),
                    cleanup_script_path=Path(
                        str(metadata["runtime_cleanup_script_path"])
                    ),
                    expected_cleanup_script_sha256=str(
                        metadata["runtime_cleanup_script_sha256"]
                    ),
                    permission_profile=str(
                        corpus["codex"]["candidate_permission_profile"]
                    ),
                    process_environment=environment,
                )
                codex_result = {**codex_result, "runtime_cleanup": runtime_cleanup}
                write_json_atomic(attempt_root / "codex-result.json", codex_result)
                attempt = update_attempt(
                    attempt_root,
                    attempt,
                    codex_result=codex_result,
                    recovery_runtime_cleanup=runtime_cleanup,
                )
                if runtime_cleanup.get("passed") is not True:
                    raise EvaluationError(
                        "candidate runtime cleanup still fails; preserved output was not rerun"
                    )

            patch_path = attempt_root / "candidate.patch"
            if not patch_path.is_file():
                patch = capture_candidate_patch(workspace, task, patch_path)
                attempt = update_attempt(
                    attempt_root,
                    attempt,
                    stage="patch-captured",
                    patch=patch,
                )
            patch_descriptor = attempt.get("patch")
            if not isinstance(patch_descriptor, dict):
                raise EvaluationError("recoverable attempt omits its candidate patch descriptor")
            if (
                patch_descriptor.get("sha256") != sha256_file(patch_path)
                or patch_descriptor.get("bytes") != patch_path.stat().st_size
            ):
                raise EvaluationError("candidate patch changed after capture")

            path = _candidate_receipt_path(
                state_root,
                task_id,
                profile_name,
                identity["identity_sha256"],
            )
            if path.is_file():
                receipt = validate_receipt(read_json(path), schema=CANDIDATE_SCHEMA)
                if receipt.get("candidate_identity_sha256") != identity["identity_sha256"]:
                    raise EvaluationError("candidate result path and identity disagree")
                workspace_cleanup = _cleanup_candidate_workspace(
                    work_root,
                    workspace,
                    retain_workspace=args.retain_workspace,
                )
                update_attempt(
                    attempt_root,
                    attempt,
                    status="completed",
                    stage="terminal",
                    receipt_path=str(path),
                    workspace_cleanup=workspace_cleanup,
                    recovery_reused_candidate_receipt=True,
                )
                print_result(
                    receipt,
                    view=args.view,
                    human=f"RECOVERED {args.attempt_id}: existing immutable result reused; no model or verifier rerun.",
                )
                return 0

            cached_verifier_path = attempt_root / "verifier" / "verifier-result.json"
            reused_verifier_receipt = cached_verifier_path.is_file()
            if reused_verifier_receipt:
                verifier = validate_receipt(
                    read_json(cached_verifier_path),
                    schema=VERIFIER_RESULT_SCHEMA,
                )
                candidate_patches = [
                    item
                    for item in verifier.get("applied_patches", [])
                    if isinstance(item, dict) and item.get("kind") == "candidate"
                ]
                if (
                    verifier.get("task_id") != task_id
                    or verifier.get("patch_kind") != "candidate"
                    or verifier.get("dependency_identity", {}).get("identity_sha256")
                    != attempt["dependency_identity"]["identity_sha256"]
                    or len(candidate_patches) != 1
                    or candidate_patches[0].get("source_sha256")
                    != patch_descriptor["sha256"]
                ):
                    raise EvaluationError("cached verifier receipt does not match the attempt")
            else:
                if codex_home is None or sandbox_runtime is None:
                    codex_home, sandbox_runtime, _ = _prepare_ready_sandbox_runtime(
                        project_root=project_root,
                        state_root=state_root,
                        installed_codex_root=installed_codex_root,
                        corpus=corpus,
                        codex_identity=current_tools["tools"]["codex"],
                    )
                attempt = update_attempt(
                    attempt_root,
                    attempt,
                    stage="verifier-running",
                )
                verifier = _run_candidate_verifier(
                    project_root=project_root,
                    state_root=state_root,
                    work_root=work_root,
                    corpus=corpus,
                    task_id=task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    attempt_root=attempt_root,
                    patch=patch_path,
                    environment=environment,
                    runtime_tools=current_tools,
                    codex_home=codex_home,
                    sandbox_runtime=sandbox_runtime,
                    expected_dependency_sha256=attempt["dependency_identity"][
                        "identity_sha256"
                    ],
                    p2p_exclusions=qualification.get("p2p_exclusions", []),
                    retain_workspace=args.retain_workspace,
                )
            reward = int(verifier["grade"]["reward"]["reward"])
            receipt = _write_candidate_receipt(
                state_root,
                task_id,
                profile_name,
                identity,
                {
                    "attempt_id": attempt["attempt_id"],
                    "valid": True,
                    "reward": reward,
                    "patch": patch_descriptor,
                    "codex_result": attempt["codex_result"],
                    "verifier": verifier,
                    "qualification_receipt_sha256": qualification["receipt_sha256"],
                    "leaderboard_comparable": False,
                    "recovered_without_model_rerun": True,
                    "reused_verifier_receipt": reused_verifier_receipt,
                },
            )
            workspace_cleanup = _cleanup_candidate_workspace(
                work_root,
                workspace,
                retain_workspace=args.retain_workspace,
            )
            update_attempt(
                attempt_root,
                attempt,
                status="completed",
                stage="terminal",
                receipt_path=str(path),
                workspace_cleanup=workspace_cleanup,
            )
            print_result(
                receipt,
                view=args.view,
                human=f"RECOVERED {args.attempt_id}: verifier completed without rerunning the model; reward={reward}.",
            )
            return 0
    except Exception as exc:
        failure: Exception = exc
        if isinstance(exc, SandboxRuntimeInvalidError):
            if sandbox_runtime is None:
                raise EvaluationError(
                    "sandbox runtime rejection omitted the prepared runtime identity"
                ) from exc
            failure = _invalidate_runtime_after_rejection(
                state_root,
                exc,
                expected_identity_sha256=str(sandbox_runtime["identity_sha256"]),
            )
        update_attempt(
            attempt_root,
            attempt,
            recovery_failure=bounded_text(str(failure), 600),
        )
        if failure is not exc:
            raise failure from exc
        raise
    finally:
        if codex_home is not None:
            cleanup_evaluation_runtime_transients(codex_home)


def command_sandbox_status(args: argparse.Namespace) -> int:
    project_root, _, state_root, _, corpus = resolve_context(args)
    installed_codex_root = installed_codex_root_from_args(args)
    codex_identity = _resolve_current_codex_identity(
        project_root,
        args.codex_executable,
    )
    status = get_sandbox_runtime_status(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
        codex_identity,
    )
    result = {
        **status,
        "external_actions": {
            "sandbox_process_launched": False,
            "host_sandbox_setup_invoked": False,
            "administrator_approval_requested": False,
            "model_invoked": False,
            "published": False,
        },
    }
    reasons = ", ".join(status["reason_codes"]) or "none"
    human = (
        f"SANDBOX STATUS: {status['status']}\n"
        f"├─ reasons: {reasons}\n"
        "├─ setup/UAC: not invoked\n"
        "└─ recovery: "
        + (status["recovery_action"] or "none")
    )
    print_result(result, view=args.view, human=human)
    return 0


def command_sandbox_setup(args: argparse.Namespace) -> int:
    if os.environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED") == "1":
        raise EvaluationError("sandbox setup is disabled by the deterministic test gate")
    project_root, _, state_root, work_root, corpus = resolve_context(args)
    installed_codex_root = installed_codex_root_from_args(args)
    state_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    codex_identity = _resolve_current_codex_identity(
        project_root,
        args.codex_executable,
    )
    setup_result: dict[str, Any] | None = None
    setup_attempted = False
    runtime_state_refreshed = False
    approval_error: SandboxSetupApprovalError | None = None
    with CaseLock(state_root, "sandbox-runtime"):
        codex_home, _ = sync_evaluation_runtime_home(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
        )
        cleanup_evaluation_runtime_transients(codex_home)
        before = get_sandbox_runtime_status(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
            codex_identity,
        )
        if (
            before.get("ready") is not True
            and before.get("checks", {}).get("runtime_state_refreshable") is True
        ):
            backend = sandbox_backend_snapshot(codex_home)
            write_ready_sandbox_runtime_state(
                state_root,
                codex_identity,
                backend,
            )
            runtime_state_refreshed = True
        if before.get("ready") is not True and not runtime_state_refreshed:
            runtime_root = sandbox_runtime_root(state_root)
            runtime_root.mkdir(parents=True, exist_ok=True)
            runtime_directory_path: Path | None = None
            setup_workspace_path: Path | None = None
            setup_backend_committed = False
            try:
                try:
                    with (
                        tempfile.TemporaryDirectory(
                            prefix="setup-",
                            dir=runtime_root,
                            ignore_cleanup_errors=True,
                        ) as runtime_directory,
                        tempfile.TemporaryDirectory(
                            prefix="sandbox-setup-",
                            dir=work_root,
                            ignore_cleanup_errors=True,
                        ) as workspace_directory,
                    ):
                        runtime_directory_path = Path(runtime_directory).resolve()
                        setup_workspace_path = Path(workspace_directory).resolve()
                        setup_attempted = True
                        setup_result = invoke_sandbox_setup(
                            project_root=project_root,
                            workspace=setup_workspace_path,
                            state_root=state_root,
                            codex_home=codex_home,
                            runtime_temp=runtime_directory_path / "process-temp",
                            result_path=runtime_directory_path / "setup-result.json",
                            codex_executable_path=Path(str(codex_identity["path"])),
                            permission_profile=str(
                                corpus["codex"]["verifier_permission_profile"]
                            ),
                            process_environment=process_environment({}),
                        )
                        backend = sandbox_backend_snapshot(codex_home)
                        write_ready_sandbox_runtime_state(
                            state_root,
                            codex_identity,
                            backend,
                        )
                        setup_backend_committed = True
                finally:
                    if runtime_directory_path is not None and runtime_directory_path.exists():
                        remove_managed_tree(runtime_root, runtime_directory_path)
                    if setup_workspace_path is not None and setup_workspace_path.exists():
                        remove_managed_tree(work_root, setup_workspace_path)
            except SandboxSetupApprovalError as exc:
                invalidate_sandbox_runtime(state_root, "explicit-sandbox-setup-failed")
                approval_error = exc
            except Exception:
                invalidate_sandbox_runtime(
                    state_root,
                    (
                        "explicit-sandbox-setup-cleanup-failed"
                        if setup_backend_committed
                        else "explicit-sandbox-setup-failed"
                    ),
                )
                raise
        cleanup_evaluation_runtime_transients(codex_home)
        after = get_sandbox_runtime_status(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
            codex_identity,
        )
        if approval_error is None and after.get("ready") is not True:
            raise EvaluationError(
                "sandbox setup completed without establishing a reusable ready state"
            )
    if approval_error is not None:
        result = {
            "schema": "agentbase.windows-swe-sandbox-setup-command/v1",
            "status": "blocked-precondition",
            "setup_invoked": setup_attempted,
            "setup_completed": False,
            "runtime_state_refreshed": runtime_state_refreshed,
            "reused_existing_runtime": False,
            "setup_result": None,
            "sandbox_runtime": after,
            "blocking_precondition": {
                "reason_code": "windows-sandbox-administrator-approval-not-completed",
                "summary": "The one-time explicit Windows sandbox setup was not approved.",
                "diagnostic": bounded_text(str(approval_error), 600),
                "recovery_action": (
                    "When ready to approve one Windows UAC prompt, run sandbox-setup "
                    "explicitly once; normal evaluation commands will not retry it."
                ),
            },
            "external_actions": {
                "sandbox_process_launched": setup_attempted,
                "host_sandbox_setup_attempted": setup_attempted,
                "administrator_approval_may_have_been_requested": setup_attempted,
                "administrator_approval_completed": False,
                "model_invoked": False,
                "network_enabled": False,
                "software_installed": False,
                "published": False,
            },
        }
        human = (
            "SANDBOX SETUP blocked-precondition\n"
            "├─ administrator approval: not completed\n"
            "├─ automatic retry: disabled\n"
            "├─ temporary assets: removed; runtime invalidated\n"
            "└─ model/network/install/publish: not invoked"
        )
        print_result(result, view=args.view, human=human)
        return 3
    result = {
        "schema": "agentbase.windows-swe-sandbox-setup-command/v1",
        "status": "ready",
        "setup_invoked": setup_attempted,
        "setup_completed": setup_attempted,
        "runtime_state_refreshed": runtime_state_refreshed,
        "reused_existing_runtime": not setup_attempted,
        "setup_result": setup_result,
        "sandbox_runtime": after,
        "external_actions": {
            "sandbox_process_launched": setup_attempted,
            "host_sandbox_setup_attempted": setup_attempted,
            "administrator_approval_may_have_been_requested": setup_attempted,
            "administrator_approval_completed": setup_attempted,
            "model_invoked": False,
            "network_enabled": False,
            "software_installed": False,
            "published": False,
        },
    }
    human = (
        "SANDBOX SETUP ready\n"
        f"├─ elevated setup invoked: {'yes' if setup_attempted else 'no; existing runtime reused'}\n"
        f"├─ runtime state refreshed: {'yes' if runtime_state_refreshed else 'no'}\n"
        "├─ future evaluation commands: setup disabled; reuse only\n"
        "└─ model/network/install/publish: not invoked"
    )
    print_result(result, view=args.view, human=human)
    return 0


def build_sandbox_assessment(
    *,
    project_root: Path,
    state_root: Path,
    work_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    codex_executable: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    installed_codex_root = installed_codex_root.resolve()
    ensure_evaluation_roots(project_root, state_root, work_root, installed_codex_root)
    require_installed_codex_runtime(
        installed_codex_root,
        require_model_catalog=False,
    )
    state_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    capability_contract = candidate_capability_contract(project_root, corpus)
    launcher_result: dict[str, Any] | None = None
    blocking_precondition: dict[str, Any] | None = None
    runtime_failure: dict[str, Any] | None = None
    skill_projection: dict[str, Any] | None = None
    sandbox_runtime: dict[str, Any] | None = None
    runtime_status: dict[str, Any] | None = None
    controlled: dict[str, Any] | None = None
    with (
        tempfile.TemporaryDirectory(
            prefix="sandbox-check-",
            dir=state_root,
            ignore_cleanup_errors=True,
        ) as state_directory,
        tempfile.TemporaryDirectory(
            prefix="sandbox-check-",
            dir=work_root,
            ignore_cleanup_errors=True,
        ) as work_directory,
        CaseLock(state_root, "sandbox-runtime"),
    ):
        runtime_root = Path(state_directory).resolve()
        workspace = Path(work_directory).resolve()
        runtime_tools = candidate_runtime_tools(
            project_root,
            runtime_root,
            codex_executable,
        )
        codex_home, controlled = sync_evaluation_runtime_home(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
        )
        cleanup_evaluation_runtime_transients(codex_home)
        runtime_status = get_sandbox_runtime_status(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
            runtime_tools["tools"]["codex"],
        )
        if runtime_status.get("ready") is not True:
            blocking_precondition = {
                "reason_code": "windows-elevated-sandbox-setup-required",
                "summary": (
                    "The persistent elevated Windows sandbox runtime is not ready. "
                    "No Codex sandbox process was launched."
                ),
                "diagnostic": ", ".join(runtime_status.get("reason_codes", [])),
                "recovery_action": "Run sandbox-setup explicitly, then rerun sandbox-check.",
                "retryable_after_environment_change": True,
            }
        else:
            sandbox_runtime = dict(runtime_status["runtime_use"])
            metadata_root = workspace / ".agentbase"
            metadata_root.mkdir(parents=True, exist_ok=False)
            shutil.copy2(
                project_root
                / "development"
                / "agent-evaluation"
                / "candidate_preflight.ps1",
                metadata_root / "preflight.ps1",
            )
            cleanup_script_path = metadata_root / "runtime-cleanup.ps1"
            shutil.copy2(
                project_root
                / "development"
                / "agent-evaluation"
                / "sandbox_runtime_cleanup.ps1",
                cleanup_script_path,
            )
            canary_path = runtime_root / "denied-state-canary.txt"
            denied_auth_path = codex_home / "auth.json"
            write_text_atomic(canary_path, "agentbase-denied-state-canary\n")
            write_text_atomic(
                denied_auth_path,
                "agentbase-fake-auth-canary-no-credentials\n",
            )
            skill_projection = stage_candidate_skill_projection(
                project_root,
                workspace,
                metadata_root,
            )
            tool_probe = stage_candidate_tool_probe_manifest(
                metadata_root,
                runtime_tools,
            )
            sandbox_process_environment = process_environment({})
            try:
                launcher_result = invoke_candidate_preflight(
                    project_root=project_root,
                    workspace=workspace,
                    state_root=state_root,
                    codex_home=codex_home,
                    runtime_temp=runtime_root / "runtime-temp",
                    sandbox_runtime=sandbox_runtime,
                    canary_path=canary_path,
                    denied_auth_path=denied_auth_path,
                    installed_codex_root=installed_codex_root,
                    skill_root_path=Path(str(skill_projection["root"])),
                    skill_probe_manifest_path=Path(
                        str(skill_projection["manifest_path"])
                    ),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    tool_probe_manifest_path=Path(str(tool_probe["path"])),
                    expected_tool_probe_manifest_sha256=str(tool_probe["sha256"]),
                    expected_tool_probes={
                        str(name): str(expected_sha256)
                        for name, expected_sha256 in tool_probe["expected_tools"].items()
                    },
                    preflight_output_path=metadata_root / "preflight.json",
                    result_path=runtime_root / "sandbox-check.json",
                    permission_profile=str(
                        corpus["codex"]["candidate_permission_profile"]
                    ),
                    codex_executable_path=_codex_executable_from_tools(runtime_tools),
                    cleanup_script_path=cleanup_script_path,
                    expected_cleanup_script_sha256=sha256_file(cleanup_script_path),
                    cleanup_shell_path=Path(runtime_tools["tools"]["pwsh"]["path"]),
                    expected_cleanup_shell_sha256=str(
                        runtime_tools["tools"]["pwsh"]["sha256"]
                    ),
                    process_environment=sandbox_process_environment,
                )
                actual_controlled = evaluation_runtime_home_controlled_identity(
                    codex_home
                )
                if actual_controlled.get("identity_sha256") != controlled.get(
                    "identity_sha256"
                ):
                    raise ControlledRuntimeDriftError(
                        "evaluation runtime controlled assets changed during candidate preflight"
                    )
                if launcher_result["status"] == "failed":
                    failed_checks = candidate_preflight_failed_checks(
                        launcher_result["preflight"],
                        expected_skill_file_count=int(skill_projection["file_count"]),
                        expected_skill_probe_manifest_sha256=str(
                            skill_projection["manifest_sha256"]
                        ),
                        expected_tool_probe_manifest_sha256=str(tool_probe["sha256"]),
                        expected_tool_probes={
                            str(name): str(expected_sha256)
                            for name, expected_sha256 in tool_probe[
                                "expected_tools"
                            ].items()
                        },
                    )
                    runtime_failure = {
                        "reason_code": "candidate-preflight-failed",
                        "failed_checks": failed_checks,
                        "summary": (
                            "The prepared sandbox ran, but one or more acceptance "
                            "checks failed."
                        ),
                    }
            except ControlledRuntimeDriftError as exc:
                cleanup_evaluation_runtime_transients(codex_home)
                codex_home, controlled = sync_evaluation_runtime_home(
                    project_root,
                    state_root,
                    installed_codex_root,
                    corpus,
                )
                runtime_status = get_sandbox_runtime_status(
                    project_root,
                    state_root,
                    installed_codex_root,
                    corpus,
                    runtime_tools["tools"]["codex"],
                )
                blocking_precondition = {
                    "reason_code": "evaluation-runtime-controlled-assets-drifted",
                    "summary": (
                        "A generated evaluation runtime asset changed during preflight; "
                        "the sandbox backend was preserved and the controlled assets "
                        "were restored."
                    ),
                    "diagnostic": bounded_text(str(exc), 600),
                    "recovery_action": "Rerun sandbox-check; sandbox-setup is not required.",
                    "retryable_after_environment_change": True,
                }
            except SandboxRuntimeInvalidError as exc:
                invalidate_sandbox_runtime(
                    state_root,
                    "codex-rejected-prepared-runtime",
                    expected_identity_sha256=str(sandbox_runtime["identity_sha256"]),
                )
                runtime_status = get_sandbox_runtime_status(
                    project_root,
                    state_root,
                    installed_codex_root,
                    corpus,
                    runtime_tools["tools"]["codex"],
                )
                blocking_precondition = {
                    "reason_code": "windows-elevated-sandbox-runtime-invalidated",
                    "summary": "Codex rejected the prepared persistent sandbox runtime.",
                    "diagnostic": bounded_text(str(exc), 600),
                    "recovery_action": "Run sandbox-setup explicitly, then rerun sandbox-check.",
                    "retryable_after_environment_change": True,
                }
            finally:
                cleanup_evaluation_runtime_transients(codex_home)
    temporary_assets_removed = not runtime_root.exists() and not workspace.exists()
    if not temporary_assets_removed:
        raise EvaluationError("sandbox assessment did not remove its temporary assets")
    if not evaluation_runtime_transients_absent(sandbox_runtime_home(state_root)):
        raise EvaluationError("sandbox assessment left authentication or model-catalog state")
    if blocking_precondition is not None:
        status = "blocked-precondition"
    elif runtime_failure is not None:
        status = "failed"
    elif launcher_result is not None:
        status = "passed"
    else:
        raise EvaluationError("sandbox assessment reached no terminal status")
    return {
        "schema": "agentbase.windows-swe-sandbox-assessment/v5",
        "status": status,
        "passed": status == "passed",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "candidate_config_identity": controlled["config"]["identity"],
        "skill_projection": (
            {
                "identity_sha256": skill_projection[
                    "projection_identity_sha256"
                ],
                "file_count": skill_projection["file_count"],
                "temporary": True,
            }
            if skill_projection is not None
            else None
        ),
        "runtime_tools_identity_sha256": runtime_tools["identity_sha256"],
        "runtime_tools": runtime_tools,
        "sandbox_runtime": {
            "status": runtime_status["status"],
            "persistent": True,
            "setup_invoked": False,
            "runtime_use": sandbox_runtime,
        },
        "capability_contract": capability_contract,
        "runtime_probe": launcher_result,
        "blocking_precondition": blocking_precondition,
        "failure": runtime_failure,
        "temporary_assets_removed": temporary_assets_removed,
        "external_actions": {
            "model_invoked": False,
            "network_enabled": False,
            "host_sandbox_setup_invoked": False,
            "host_sandbox_setup_may_be_requested": False,
            "software_installed": False,
            "published": False,
        },
    }


def command_sandbox_check(args: argparse.Namespace) -> int:
    project_root, _, state_root, work_root, corpus = resolve_context(args)
    result = build_sandbox_assessment(
        project_root=project_root,
        state_root=state_root,
        work_root=work_root,
        installed_codex_root=installed_codex_root_from_args(args),
        corpus=corpus,
        codex_executable=args.codex_executable,
    )
    if result["status"] == "passed":
        runtime_probe = result.get("runtime_probe")
        if not isinstance(runtime_probe, dict):
            raise EvaluationError("candidate sandbox assessment omitted its runtime probe")
        preflight = runtime_probe.get("preflight")
        if not isinstance(preflight, dict) or preflight.get("passed") is not True:
            raise EvaluationError("candidate sandbox assessment did not pass")
        human = (
            "SANDBOX CHECK passed\n"
            "├─ host default/project/state/auth boundaries: denied\n"
            "├─ complete skill projection: hash-readable and write-denied\n"
            "├─ workspace write + attempt temp/appdata/home scope: passed\n"
            "├─ exact CLI identities + srcq doctors/workflow round trips: passed\n"
            "└─ model/network/install/publish: not invoked"
        )
        exit_code = 0
    elif result["status"] == "blocked-precondition":
        blocking = result.get("blocking_precondition")
        if not isinstance(blocking, dict):
            raise EvaluationError("blocked sandbox assessment omitted its precondition")
        human = (
            "SANDBOX CHECK blocked-precondition\n"
            "├─ required backend: elevated native Windows sandbox\n"
            "├─ reason: persistent runtime is absent, stale, or invalidated\n"
            f"├─ recovery: {blocking['recovery_action']}\n"
            "└─ sandbox/model/network/install/publish: not invoked"
        )
        exit_code = 3
    elif result["status"] == "failed":
        failure = result.get("failure")
        if not isinstance(failure, dict) or not isinstance(failure.get("failed_checks"), list):
            raise EvaluationError("failed sandbox assessment omitted its failed checks")
        failed_checks = ", ".join(str(item) for item in failure["failed_checks"])
        human = (
            "SANDBOX CHECK failed\n"
            "├─ elevated sandbox: launched\n"
            f"├─ failed checks: {failed_checks}\n"
            "├─ candidate model: not invoked\n"
            "└─ install/publish: not invoked"
        )
        exit_code = 2
    else:
        raise EvaluationError("candidate sandbox assessment returned an unknown status")
    print_result(result, view=args.view, human=human)
    return exit_code


def _nonnegative_number(value: Any, *, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise EvaluationError(f"{field} must be a non-negative number or null")
    return value


def _api_equivalent_cost_projection(
    value: object,
    *,
    context: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{context} must be an object")
    if (
        value.get("schema") != API_EQUIVALENT_COST_SCHEMA
        or value.get("basis") != "official-openai-standard-api-text-token-pricing"
        or value.get("currency") != "USD"
        or value.get("actual_billing_observed") is not False
        or value.get("scope") != "root-and-descendant-model-requests"
        or not isinstance(value.get("pricing_snapshot_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("pricing_snapshot_sha256"))) is None
        or not isinstance(value.get("pricing_observed_at"), str)
        or not isinstance(value.get("complete"), bool)
    ):
        raise EvaluationError(f"{context} has an invalid contract")
    integers: dict[str, int] = {}
    for field in (
        "request_count",
        "subagent_request_count",
        "long_context_request_count",
        "total_usd_nanos",
        "root_usd_nanos",
        "subagent_usd_nanos",
    ):
        field_value = value.get(field)
        if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value < 0:
            raise EvaluationError(f"{context}.{field} must be a non-negative integer")
        integers[field] = field_value
    if integers["subagent_request_count"] > integers["request_count"]:
        raise EvaluationError(f"{context} subagent request count exceeds total")
    if integers["long_context_request_count"] > integers["request_count"]:
        raise EvaluationError(f"{context} long-context request count exceeds total")
    if integers["root_usd_nanos"] + integers["subagent_usd_nanos"] != integers["total_usd_nanos"]:
        raise EvaluationError(f"{context} root and subagent costs disagree with total")
    for field, nanos_field in (
        ("total_usd", "total_usd_nanos"),
        ("root_usd", "root_usd_nanos"),
        ("subagent_usd", "subagent_usd_nanos"),
    ):
        if value.get(field) != format_usd_nanos(integers[nanos_field]):
            raise EvaluationError(f"{context}.{field} disagrees with USD nanos")
    return dict(value)


def _candidate_result_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    valid = receipt.get("valid")
    reward = receipt.get("reward")
    if not isinstance(valid, bool) or reward not in {0, 1}:
        raise EvaluationError("candidate result has an invalid validity or reward value")
    codex_result = receipt.get("codex_result")
    if codex_result is not None and not isinstance(codex_result, dict):
        raise EvaluationError("candidate result codex_result must be an object")
    verifier = receipt.get("verifier")
    if verifier is not None and not isinstance(verifier, dict):
        raise EvaluationError("candidate result verifier must be an object")
    candidate_duration = _nonnegative_number(
        (codex_result or {}).get("duration_seconds"),
        field="codex_result.duration_seconds",
    )
    verifier_duration = _nonnegative_number(
        (verifier or {}).get("duration_seconds"),
        field="verifier.duration_seconds",
    )
    usage_value = (codex_result or {}).get("usage")
    if usage_value is not None and not isinstance(usage_value, dict):
        raise EvaluationError("codex_result.usage must be an object")
    usage: dict[str, int | None] = {}
    for field in CODEX_USAGE_FIELDS:
        token_value = (usage_value or {}).get(field)
        if token_value is not None and (
            isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0
        ):
            raise EvaluationError(f"codex_result.usage.{field} must be a non-negative integer")
        usage[field] = token_value
    usage_scope = (codex_result or {}).get("usage_scope")
    if usage_scope is not None and not isinstance(usage_scope, str):
        raise EvaluationError("codex_result.usage_scope must be a string")
    declared_usage_complete = (codex_result or {}).get("usage_complete")
    if declared_usage_complete is not None and not isinstance(declared_usage_complete, bool):
        raise EvaluationError("codex_result.usage_complete must be a boolean")
    usage_complete = (
        declared_usage_complete is True
        and usage_scope == "root-and-descendant-threads"
        and all(value is not None for value in usage.values())
    )
    agent_thread_count = (codex_result or {}).get("agent_thread_count")
    subagent_thread_count = (codex_result or {}).get("subagent_thread_count")
    for field, value in (
        ("agent_thread_count", agent_thread_count),
        ("subagent_thread_count", subagent_thread_count),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise EvaluationError(f"codex_result.{field} must be a non-negative integer")
    if (
        agent_thread_count is not None
        and subagent_thread_count is not None
        and agent_thread_count != subagent_thread_count + 1
    ):
        raise EvaluationError("codex_result agent and subagent thread counts disagree")
    api_cost = _api_equivalent_cost_projection(
        (codex_result or {}).get("api_equivalent_cost"),
        context="codex_result.api_equivalent_cost",
    )
    return {
        "attempt_id": receipt.get("attempt_id"),
        "valid": valid,
        "reward": reward,
        "created_at": receipt.get("created_at"),
        "receipt_sha256": receipt["receipt_sha256"],
        "candidate_duration_seconds": candidate_duration,
        "verifier_duration_seconds": verifier_duration,
        "usage_complete": usage_complete,
        "usage_scope": usage_scope,
        "usage": usage,
        "agent_thread_count": agent_thread_count,
        "subagent_thread_count": subagent_thread_count,
        "api_equivalent_cost": api_cost,
    }


def _attempt_health(
    state_root: Path,
    task_ids: set[str],
    *,
    recent_limit: int,
    current_candidate_surface_sha256: str,
    current_framework_sha256: str,
    current_corpus_sha256: str,
) -> dict[str, Any]:
    if recent_limit < 1 or recent_limit > 100:
        raise EvaluationError("attempt limit must be between 1 and 100")
    root = state_root.resolve() / "attempts"
    attempts: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*/attempt.json")):
            value = read_json(path)
            if (
                value.get("schema") != "agentbase.windows-swe-attempt/v1"
                or value.get("attempt_id") != path.parent.name
                or not isinstance(value.get("status"), str)
                or not isinstance(value.get("stage"), str)
            ):
                raise EvaluationError(f"invalid candidate attempt record: {path}")
            if value.get("task_id") in task_ids:
                attempts.append(dict(value))
    status_counts: dict[str, int] = {}
    recent_failures: list[dict[str, Any]] = []
    cleanup_error_count = 0
    recoverable_count = 0
    nonterminal_count = 0
    current_identity_attempts: list[dict[str, Any]] = []
    for attempt in attempts:
        status = str(attempt["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        if attempt.get("stage") != "terminal":
            nonterminal_count += 1
        if status == "infrastructure-failed" and attempt.get("stage") in {
            "candidate-finished",
            "patch-captured",
        }:
            recoverable_count += 1
        cleanup = attempt.get("workspace_cleanup")
        if isinstance(cleanup, dict) and cleanup.get("cleanup_error"):
            cleanup_error_count += 1
        if status in {"infrastructure-failed", "blocked-precondition"}:
            recent_failures.append(
                {
                    "attempt_id": attempt["attempt_id"],
                    "task_id": attempt.get("task_id"),
                    "profile": attempt.get("profile"),
                    "status": status,
                    "stage": attempt["stage"],
                    "updated_at": attempt.get("updated_at"),
                    "failure": bounded_text(
                        str(attempt.get("failure") or attempt.get("recovery_failure") or ""),
                        240,
                    ),
                }
            )
        identity = attempt.get("candidate_identity")
        if (
            isinstance(identity, dict)
            and identity.get("candidate_surface_identity_sha256")
            == current_candidate_surface_sha256
            and identity.get("framework_identity_sha256") == current_framework_sha256
            and identity.get("corpus_sha256") == current_corpus_sha256
        ):
            current_identity_attempts.append(attempt)
    recent_failures.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    attempt_usage_totals = {field: 0 for field in CODEX_USAGE_FIELDS}
    model_attempts = 0
    usage_complete_attempts = 0
    known_agent_threads = 0
    known_subagent_threads = 0
    candidate_duration_seconds = 0.0
    candidate_duration_known = 0
    usage_scopes: dict[str, int] = {}
    priced_attempts = 0
    price_complete_attempts = 0
    pricing_snapshot_ids: set[str] = set()
    api_cost_totals = {
        "total_usd_nanos": 0,
        "root_usd_nanos": 0,
        "subagent_usd_nanos": 0,
        "request_count": 0,
        "subagent_request_count": 0,
        "long_context_request_count": 0,
    }
    for attempt in current_identity_attempts:
        codex_result = attempt.get("codex_result")
        if not isinstance(codex_result, dict) or codex_result.get("model_invoked") is not True:
            continue
        model_attempts += 1
        scope = str(codex_result.get("usage_scope") or "missing")
        usage_scopes[scope] = usage_scopes.get(scope, 0) + 1
        usage_value = codex_result.get("usage")
        field_complete = isinstance(usage_value, dict)
        if isinstance(usage_value, dict):
            for field in CODEX_USAGE_FIELDS:
                token_value = usage_value.get(field)
                if isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0:
                    field_complete = False
                    continue
                attempt_usage_totals[field] += token_value
        usage_is_complete = (
            field_complete
            and codex_result.get("usage_complete") is True
            and scope == "root-and-descendant-threads"
        )
        if usage_is_complete:
            usage_complete_attempts += 1
        for field, target in (
            ("agent_thread_count", "agent"),
            ("subagent_thread_count", "subagent"),
        ):
            count = codex_result.get(field)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                if target == "agent":
                    known_agent_threads += count
                else:
                    known_subagent_threads += count
        duration = codex_result.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            candidate_duration_seconds += float(duration)
            candidate_duration_known += 1
        api_cost = _api_equivalent_cost_projection(
            codex_result.get("api_equivalent_cost"),
            context=f"attempt {attempt['attempt_id']} api_equivalent_cost",
        )
        if api_cost is not None:
            priced_attempts += 1
            if api_cost["complete"] is True:
                price_complete_attempts += 1
            pricing_snapshot_ids.add(str(api_cost["pricing_snapshot_sha256"]))
            for field in api_cost_totals:
                api_cost_totals[field] += int(api_cost[field])
    api_cost_summary = {
        "basis": "official-openai-standard-api-text-token-pricing",
        "currency": "USD",
        "actual_billing_observed": False,
        "scope": "all model-invoked attempts with the current candidate/framework/corpus identity",
        "priced_attempts": priced_attempts,
        "complete_attempts": price_complete_attempts,
        "missing_or_incomplete_attempts": model_attempts - price_complete_attempts,
        "pricing_snapshot_sha256": (
            next(iter(pricing_snapshot_ids)) if len(pricing_snapshot_ids) == 1 else None
        ),
        **api_cost_totals,
        "total_usd": format_usd_nanos(api_cost_totals["total_usd_nanos"]),
        "root_usd": format_usd_nanos(api_cost_totals["root_usd_nanos"]),
        "subagent_usd": format_usd_nanos(api_cost_totals["subagent_usd_nanos"]),
    }
    return {
        "attempt_count": len(attempts),
        "status_counts": dict(sorted(status_counts.items())),
        "infrastructure_failed": status_counts.get("infrastructure-failed", 0),
        "blocked_precondition": status_counts.get("blocked-precondition", 0),
        "recoverable": recoverable_count,
        "nonterminal": nonterminal_count,
        "cleanup_errors": cleanup_error_count,
        "recent_failures": {
            "limit": recent_limit,
            "total": len(recent_failures),
            "items": recent_failures[:recent_limit],
        },
        "current_identity_cost_and_time": {
            "attempt_count": len(current_identity_attempts),
            "model_attempts": model_attempts,
            "usage_complete_attempts": usage_complete_attempts,
            "usage_missing_attempts": model_attempts - usage_complete_attempts,
            "usage_scopes": dict(sorted(usage_scopes.items())),
            "known_agent_threads": known_agent_threads,
            "known_subagent_threads": known_subagent_threads,
            "candidate_duration_seconds_known": round(candidate_duration_seconds, 3),
            "candidate_duration_known_attempts": candidate_duration_known,
            **{f"known_{field}": value for field, value in attempt_usage_totals.items()},
            "api_equivalent_cost": api_cost_summary,
        },
    }


def build_swe_report(
    *,
    project_root: Path,
    corpus_path: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    suite: str,
    result_offset: int = 0,
    result_limit: int = 100,
    attempt_limit: int = 20,
) -> dict[str, Any]:
    if result_offset < 0:
        raise EvaluationError("result offset must be non-negative")
    if result_limit < 1 or result_limit > 500:
        raise EvaluationError("result limit must be between 1 and 500")
    task_ids = suite_task_ids(corpus, suite)
    current_candidate = candidate_surface_identity(project_root)["identity_sha256"]
    current_framework = framework_identity(project_root)["identity_sha256"]
    current_corpus = sha256_file(corpus_path)
    statuses = _task_statuses(
        project_root,
        corpus_path,
        state_root,
        corpus,
        task_ids,
    )
    status_by_task = {str(item["task_id"]): item for item in statuses}
    current_qualification_hashes: dict[str, set[str]] = {}
    for task_id in task_ids:
        _, receipts = _qualification_state(
            project_root,
            corpus_path,
            state_root,
            corpus,
            task_id,
        )
        current_qualification_hashes[task_id] = {
            str(receipt["receipt_sha256"]) for receipt in receipts
        }
    results: list[dict[str, Any]] = []
    results_by_case: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for task_id in task_ids:
        for profile in corpus["profiles"]:
            root = candidate_receipt_dir(state_root, task_id, profile)
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.json")):
                receipt = validate_receipt(read_json(path), schema=CANDIDATE_SCHEMA)
                if receipt.get("task_id") != task_id or receipt.get("profile") != profile:
                    raise EvaluationError(f"candidate result is filed under the wrong case: {path}")
                identity = validate_identity(
                    receipt.get("candidate_identity"),
                    schema="agentbase.windows-swe-candidate-identity/v1",
                )
                if identity["identity_sha256"] != receipt.get("candidate_identity_sha256"):
                    raise EvaluationError(f"candidate result embeds a different identity: {path}")
                static_identity_current = (
                    identity.get("corpus_sha256") == current_corpus
                    and identity.get("candidate_surface_identity_sha256")
                    == current_candidate
                    and identity.get("framework_identity_sha256") == current_framework
                    and receipt.get("qualification_receipt_sha256")
                    in current_qualification_hashes[task_id]
                )
                projection = {
                    "task_id": task_id,
                    "profile": profile,
                    **_candidate_result_projection(receipt),
                    "static_identity_current": static_identity_current,
                    "runtime_identity_checked": False,
                }
                results.append(projection)
                results_by_case.setdefault((task_id, profile), []).append(projection)
    results.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item["task_id"]),
            str(item["profile"]),
            str(item["receipt_sha256"]),
        ),
        reverse=True,
    )
    coverage: list[dict[str, Any]] = []
    selected_current: list[dict[str, Any]] = []
    for task_id in task_ids:
        for profile in corpus["profiles"]:
            case_results = results_by_case.get((task_id, profile), [])
            static_current = [item for item in case_results if item["static_identity_current"]]
            static_current.sort(
                key=lambda item: (str(item.get("created_at") or ""), item["receipt_sha256"]),
                reverse=True,
            )
            selected = static_current[0] if static_current else None
            if selected is not None:
                selected_current.append(selected)
            qualification = str(status_by_task[task_id]["qualification"])
            status = (
                "unqualified"
                if qualification != "qualified"
                else "result-recorded-static-current"
                if selected is not None
                else "missing-current-result"
            )
            coverage.append(
                {
                    "task_id": task_id,
                    "difficulty": require_task(corpus, task_id)["difficulty"],
                    "profile": profile,
                    "qualification": qualification,
                    "status": status,
                    "static_current_result_count": len(static_current),
                    "historical_result_count": len(case_results),
                    "selected_result": selected,
                }
            )
    known_usage_totals = {
        field: sum(
            int(item["usage"][field])
            for item in selected_current
            if item["usage"][field] is not None
        )
        for field in CODEX_USAGE_FIELDS
    }
    complete_usage = [item for item in selected_current if item["usage_complete"]]
    selected_costs = [
        item["api_equivalent_cost"]
        for item in selected_current
        if item["api_equivalent_cost"] is not None
    ]
    complete_costs = [item for item in selected_costs if item["complete"] is True]
    pricing = api_pricing_snapshot()
    selected_cost_totals = {
        field: sum(int(item[field]) for item in selected_costs)
        for field in (
            "total_usd_nanos",
            "root_usd_nanos",
            "subagent_usd_nanos",
            "request_count",
            "subagent_request_count",
            "long_context_request_count",
        )
    }
    known_agent_threads = sum(
        int(item["agent_thread_count"])
        for item in selected_current
        if item["agent_thread_count"] is not None
    )
    known_subagent_threads = sum(
        int(item["subagent_thread_count"])
        for item in selected_current
        if item["subagent_thread_count"] is not None
    )
    candidate_durations = [
        float(item["candidate_duration_seconds"])
        for item in selected_current
        if item["candidate_duration_seconds"] is not None
    ]
    verifier_durations = [
        float(item["verifier_duration_seconds"])
        for item in selected_current
        if item["verifier_duration_seconds"] is not None
    ]
    page_items = results[result_offset : result_offset + result_limit]
    next_offset = result_offset + len(page_items)
    if next_offset >= len(results):
        next_offset = None
    summary = {
        "task_count": len(task_ids),
        "profile_count": len(corpus["profiles"]),
        "expected_runs": len(coverage),
        "qualified_tasks": sum(item["qualification"] == "qualified" for item in statuses),
        "static_current_runs": len(selected_current),
        "missing_current_runs": len(coverage) - len(selected_current),
        "static_current_valid_runs": sum(item["valid"] for item in selected_current),
        "static_current_reward_one": sum(
            item["valid"] and item["reward"] == 1 for item in selected_current
        ),
        "static_current_reward_zero": sum(item["reward"] == 0 for item in selected_current),
        "historical_result_count": len(results),
        "historical_or_unqualified_runs": sum(
            item["static_identity_current"] is not True for item in results
        ),
    }
    return {
        "schema": "agentbase.windows-swe-report/v4",
        "suite": suite,
        "qualification": statuses,
        "coverage": coverage,
        "results": {
            "offset": result_offset,
            "limit": result_limit,
            "total": len(results),
            "next_offset": next_offset,
            "items": page_items,
        },
        "summary": summary,
        "cost_and_time": {
            "scope": "selected latest static-current result per task/profile",
            "runtime_identity_checked": False,
            "candidate_duration_seconds_known": round(sum(candidate_durations), 3),
            "candidate_duration_known_runs": len(candidate_durations),
            "verifier_duration_seconds_known": round(sum(verifier_durations), 3),
            "verifier_duration_known_runs": len(verifier_durations),
            "usage_complete_runs": len(complete_usage),
            "usage_missing_runs": len(selected_current) - len(complete_usage),
            "known_agent_threads": known_agent_threads,
            "known_subagent_threads": known_subagent_threads,
            **{f"known_{field}": value for field, value in known_usage_totals.items()},
            "api_equivalent_cost": {
                "basis": pricing["basis"],
                "currency": pricing["currency"],
                "actual_billing_observed": False,
                "pricing_snapshot_sha256": pricing["identity_sha256"],
                "pricing_observed_at": pricing["observed_at"],
                "scope": "candidate model requests in selected results, including descendant subagents",
                "complete_runs": len(complete_costs),
                "missing_or_incomplete_runs": len(selected_current) - len(complete_costs),
                **selected_cost_totals,
                "total_usd": format_usd_nanos(selected_cost_totals["total_usd_nanos"]),
                "root_usd": format_usd_nanos(selected_cost_totals["root_usd_nanos"]),
                "subagent_usd": format_usd_nanos(
                    selected_cost_totals["subagent_usd_nanos"]
                ),
            },
        },
        "infrastructure_health": _attempt_health(
            state_root,
            set(task_ids),
            recent_limit=attempt_limit,
            current_candidate_surface_sha256=current_candidate,
            current_framework_sha256=current_framework,
            current_corpus_sha256=current_corpus,
        ),
        "candidate_capabilities": candidate_capability_contract(project_root, corpus),
        "composite_score": None,
        "leaderboard_comparable": False,
        "external_actions": {
            "model_invoked": False,
            "qualification_run": False,
            "software_installed": False,
            "published": False,
        },
    }


def command_report(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, _, corpus = resolve_context(args)
    result = build_swe_report(
        project_root=project_root,
        corpus_path=corpus_path,
        state_root=state_root,
        corpus=corpus,
        suite=args.suite,
        result_offset=args.result_offset,
        result_limit=args.result_limit,
        attempt_limit=args.attempt_limit,
    )
    selected_cost = result["cost_and_time"]["api_equivalent_cost"]
    attempt_cost = result["infrastructure_health"]["current_identity_cost_and_time"][
        "api_equivalent_cost"
    ]
    human = (
        f"WINDOWS SWE {args.suite}\n"
        f"├─ qualification: {result['summary']['qualified_tasks']}/{result['summary']['task_count']} tasks\n"
        f"├─ current coverage: {result['summary']['static_current_runs']}/{result['summary']['expected_runs']} task/profile runs\n"
        f"├─ reward=1: {result['summary']['static_current_reward_one']}\n"
        f"├─ selected API-equivalent cost: ${selected_cost['total_usd']} "
        f"(subagents ${selected_cost['subagent_usd']})\n"
        f"├─ all current-identity attempts: ${attempt_cost['total_usd']} "
        f"(subagents ${attempt_cost['subagent_usd']})\n"
        f"├─ infrastructure failures: {result['infrastructure_health']['infrastructure_failed']}\n"
        "└─ composite score: none; runtime identity not rechecked"
    )
    print_result(result, view=args.view, human=human)
    return 0


def _run_json_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    label: str,
) -> dict[str, Any]:
    completed = run_capture(argv, cwd=cwd, timeout=timeout)
    try:
        text = completed.stdout.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"{label} did not return one JSON document") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} result must be an object")
    return value


def _collect_native_validation(project_root: Path) -> dict[str, Any]:
    value = _run_json_command(
        [
            "pwsh.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(project_root / "development" / "agent-evaluation" / "collect_native_validation.ps1"),
            "-ProjectRoot",
            str(project_root),
        ],
        cwd=project_root,
        timeout=1800,
        label="native validation",
    )
    validation = value.get("validation")
    status = value.get("status")
    passed = value.get("passed")
    if value.get("schema") != "agentbase.native-validation/v2":
        raise EvaluationError("native validation returned an invalid evidence envelope")
    if status == "passed":
        if passed is not True or not isinstance(validation, dict) or validation.get("action") != "Validate":
            raise EvaluationError("passed native validation omitted its Validate result")
        if value.get("diagnostic") is not None:
            raise EvaluationError("passed native validation returned a failure diagnostic")
    elif status == "failed":
        if passed is not False or validation is not None:
            raise EvaluationError("failed native validation returned inconsistent evidence")
        diagnostic = value.get("diagnostic")
        if not isinstance(diagnostic, str) or not diagnostic.strip():
            raise EvaluationError("failed native validation omitted its diagnostic")
    else:
        raise EvaluationError("native validation returned an unknown status")
    if _nonnegative_number(
        value.get("duration_seconds"), field="native duration_seconds"
    ) is None:
        raise EvaluationError("native validation omitted duration_seconds")
    return value


def _collect_routing_assessment(project_root: Path) -> dict[str, Any]:
    routing_root = project_root / "development" / "skill-routing"
    plan = _run_json_command(
        [
            "pwsh.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(routing_root / "get_routing_evaluation_plan.ps1"),
            "-ProjectRoot",
            str(project_root),
            "-View",
            "machine",
        ],
        cwd=project_root,
        timeout=600,
        label="routing evaluation plan",
    )
    phases = plan.get("phases")
    if plan.get("schema_version") != 1 or not isinstance(phases, dict):
        raise EvaluationError("routing evaluation plan has an invalid schema")
    phase_names = ("Routing", "Policy", "References")
    if set(phases) != set(phase_names):
        raise EvaluationError("routing evaluation plan omits or adds phases")
    for field in ("evaluation_count", "reuse_count", "blocked_count", "pending_count"):
        value = plan.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EvaluationError(f"routing plan {field} must be a non-negative integer")
    current_path = routing_root / "evidence" / "current.json"
    attempts_path = routing_root / "evidence" / "attempts.json"
    current = read_json(current_path) if current_path.is_file() else None
    ledger = read_json(attempts_path) if attempts_path.is_file() else None
    if current is not None and current.get("schema_version") != 4:
        raise EvaluationError("routing current evidence has an invalid schema")
    if ledger is not None and (
        ledger.get("schema_version") != 3 or not isinstance(ledger.get("attempts"), list)
    ):
        raise EvaluationError("routing attempt ledger has an invalid schema")
    generation = str(plan.get("evaluation_generation_sha256") or "")
    cycle_attempts = []
    if ledger is not None:
        for attempt in ledger["attempts"]:
            if not isinstance(attempt, dict):
                raise EvaluationError("routing attempt ledger contains a non-object attempt")
            if attempt.get("cycle_id") == generation:
                cycle_attempts.append(attempt)
    usage_totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    duration_ms = 0
    usage_complete_attempts = 0
    outcomes: dict[str, int] = {}
    origins: dict[str, int] = {}
    failure_count = 0
    for attempt in cycle_attempts:
        duration = attempt.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise EvaluationError("routing attempt duration_ms must be a non-negative integer")
        duration_ms += duration
        values: dict[str, int | None] = {}
        for field in usage_totals:
            token_value = attempt.get(field)
            if token_value is not None and (
                isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0
            ):
                raise EvaluationError(f"routing attempt {field} must be non-negative or null")
            values[field] = token_value
            if token_value is not None:
                usage_totals[field] += token_value
        if all(value is not None for value in values.values()):
            usage_complete_attempts += 1
        outcome = str(attempt.get("outcome") or "unknown")
        origin = str(attempt.get("origin") or "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        origins[origin] = origins.get(origin, 0) + 1
        if outcome != "passed":
            failure_count += 1
    if plan["blocked_count"] > 0:
        status = "blocked"
    elif plan["evaluation_count"] > 0 or plan["pending_count"] > 0:
        status = "pending-evaluation"
    elif plan["reuse_count"] == len(phase_names) and current is not None:
        status = "current"
    else:
        status = "incomplete"
    receipt_ids = None
    case_counts = None
    if current is not None:
        policy = current.get("policy_evaluation")
        references = current.get("reference_evaluation")
        if not isinstance(policy, dict) or not isinstance(references, dict):
            raise EvaluationError("routing current evidence omits nested phase evidence")
        receipt_ids = {
            "Routing": current.get("receipt_id"),
            "Policy": policy.get("receipt_id"),
            "References": references.get("receipt_id"),
        }
        case_counts = {
            "Routing": len(current.get("cases", [])),
            "Policy": len(policy.get("cases", [])),
            "References": len(references.get("cases", [])),
        }
    return {
        "schema": "agentbase.routing-assessment/v1",
        "status": status,
        "generation_sha256": generation,
        "phase_plan": {
            name: {
                "action": phases[name].get("action"),
                "reason": phases[name].get("reason"),
            }
            for name in phase_names
        },
        "plan_counts": {
            "evaluate": plan["evaluation_count"],
            "reuse": plan["reuse_count"],
            "blocked": plan["blocked_count"],
            "pending": plan["pending_count"],
        },
        "current_evidence": {
            "present": current is not None,
            "sha256": sha256_file(current_path) if current is not None else None,
            "receipt_ids": receipt_ids,
            "case_counts": case_counts,
        },
        "current_cycle_attempts": {
            "ledger_present": ledger is not None,
            "count": len(cycle_attempts),
            "outcomes": dict(sorted(outcomes.items())),
            "origins": dict(sorted(origins.items())),
            "failures": failure_count,
            "duration_ms": duration_ms,
            "usage_complete_attempts": usage_complete_attempts,
            "usage_missing_attempts": len(cycle_attempts) - usage_complete_attempts,
            **usage_totals,
            "total_tokens": usage_totals["input_tokens"] + usage_totals["output_tokens"],
        },
        "external_actions": {"model_invoked": False, "evidence_refreshed": False},
    }


def build_final_assessment(
    *,
    project_root: Path,
    corpus_path: Path,
    state_root: Path,
    work_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    suite: str,
    result_offset: int,
    result_limit: int,
    attempt_limit: int,
    codex_executable: Path | None,
) -> dict[str, Any]:
    native = _collect_native_validation(project_root)
    sandbox = build_sandbox_assessment(
        project_root=project_root,
        state_root=state_root,
        work_root=work_root,
        installed_codex_root=installed_codex_root,
        corpus=corpus,
        codex_executable=codex_executable,
    )
    routing = _collect_routing_assessment(project_root)
    swe = build_swe_report(
        project_root=project_root,
        corpus_path=corpus_path,
        state_root=state_root,
        corpus=corpus,
        suite=suite,
        result_offset=result_offset,
        result_limit=result_limit,
        attempt_limit=attempt_limit,
    )
    sandbox_status = sandbox.get("status")
    if sandbox.get("schema") != "agentbase.windows-swe-sandbox-assessment/v5":
        raise EvaluationError("sandbox assessment returned an invalid evidence envelope")
    if sandbox_status == "passed":
        if sandbox.get("passed") is not True or not isinstance(sandbox.get("runtime_probe"), dict):
            raise EvaluationError("passed sandbox assessment omitted its runtime probe")
        if sandbox.get("blocking_precondition") is not None or sandbox.get("failure") is not None:
            raise EvaluationError("passed sandbox assessment returned failure evidence")
    elif sandbox_status == "blocked-precondition":
        if sandbox.get("passed") is not False or sandbox.get("runtime_probe") is not None:
            raise EvaluationError("blocked sandbox assessment returned inconsistent evidence")
        if not isinstance(sandbox.get("blocking_precondition"), dict):
            raise EvaluationError("blocked sandbox assessment omitted its precondition")
        if sandbox.get("failure") is not None:
            raise EvaluationError("blocked sandbox assessment also returned a runtime failure")
    elif sandbox_status == "failed":
        if sandbox.get("passed") is not False or not isinstance(
            sandbox.get("runtime_probe"), dict
        ):
            raise EvaluationError("failed sandbox assessment omitted its runtime probe")
        if sandbox.get("blocking_precondition") is not None or not isinstance(
            sandbox.get("failure"), dict
        ):
            raise EvaluationError("failed sandbox assessment returned inconsistent evidence")
    else:
        raise EvaluationError("sandbox assessment returned an unknown status")
    if _nonnegative_number(
        sandbox.get("duration_seconds"), field="sandbox duration_seconds"
    ) is None:
        raise EvaluationError("sandbox assessment omitted duration_seconds")
    if sandbox.get("capability_contract") != swe["candidate_capabilities"]:
        raise EvaluationError("sandbox and SWE reports disagree on candidate capabilities")
    external_status = (
        "complete"
        if swe["summary"]["qualified_tasks"] == swe["summary"]["task_count"]
        and swe["summary"]["static_current_runs"] == swe["summary"]["expected_runs"]
        else "pending-evidence"
    )
    swe_health = swe["infrastructure_health"]
    routing_health = routing["current_cycle_attempts"]
    failed_dimensions = []
    blocked_dimensions = []
    pending_dimensions = []
    if native["status"] != "passed":
        failed_dimensions.append("windows-native-contract")
    if sandbox_status == "failed":
        failed_dimensions.append("candidate-verifier-isolation")
    elif sandbox_status == "blocked-precondition":
        blocked_dimensions.append("candidate-verifier-isolation")
    if routing["status"] == "blocked":
        blocked_dimensions.append("routing-behavior")
    elif routing["status"] != "current":
        pending_dimensions.append("routing-behavior")
    if external_status != "complete":
        pending_dimensions.append("external-generalization-reward")
    health_failures = (
        swe_health["infrastructure_failed"]
        + swe_health["cleanup_errors"]
        + routing_health["failures"]
        + (1 if native["status"] != "passed" else 0)
        + (1 if sandbox_status == "failed" else 0)
    )
    if health_failures > 0:
        infrastructure_status = "degraded"
        assessment_status = "degraded"
    elif blocked_dimensions:
        infrastructure_status = "blocked-precondition"
        assessment_status = "blocked-precondition"
    elif pending_dimensions:
        infrastructure_status = "healthy"
        assessment_status = "evidence-pending"
    else:
        infrastructure_status = "healthy"
        assessment_status = "current"
    dimensions = {
        "windows-native-contract": {
            "status": native["status"],
            "evidence": native,
        },
        "candidate-verifier-isolation": {
            "status": sandbox_status,
            "evidence": sandbox,
        },
        "routing-behavior": {
            "status": routing["status"],
            "evidence": routing,
        },
        "external-generalization-reward": {
            "status": external_status,
            "evidence": swe,
        },
        "cost-and-time": {
            "status": "reported",
            "known_total_tokens": (
                swe["cost_and_time"]["known_total_tokens"]
                + routing_health["total_tokens"]
            ),
            "known_cached_input_tokens": (
                swe["cost_and_time"]["known_cached_input_tokens"]
                + routing_health["cached_input_tokens"]
            ),
            "swe": swe["cost_and_time"],
            "swe_selected_api_equivalent_cost": swe["cost_and_time"][
                "api_equivalent_cost"
            ],
            "swe_current_identity_attempt_api_equivalent_cost": swe_health[
                "current_identity_cost_and_time"
            ]["api_equivalent_cost"],
            "routing_current_cycle": routing_health,
            "unpriced_scopes": [
                "routing model calls lack per-response model/cache-write evidence in this contract",
                "Codex subscription billing and deterministic host work are not API token charges",
            ],
            "native_validation_duration_seconds": native["duration_seconds"],
            "sandbox_assessment_duration_seconds": sandbox["duration_seconds"],
        },
        "infrastructure-health": {
            "status": infrastructure_status,
            "known_failure_count": health_failures,
            "swe": swe_health,
            "routing_current_cycle": routing_health,
            "failed_dimensions": failed_dimensions,
            "blocked_preconditions": blocked_dimensions,
            "pending_evidence": pending_dimensions,
        },
    }
    return {
        "schema": "agentbase.final-assessment/v2",
        "suite": suite,
        "status": assessment_status,
        "evidence_state": {
            "failed_dimensions": failed_dimensions,
            "blocked_dimensions": blocked_dimensions,
            "pending_dimensions": pending_dimensions,
        },
        "dimensions": dimensions,
        "candidate_capability_contract": swe["candidate_capabilities"],
        "installation_status": "not-assessed",
        "composite_score": None,
        "leaderboard_comparable": False,
        "external_actions": {
            "model_invoked": False,
            "routing_evidence_refreshed": False,
            "qualification_run": False,
            "host_sandbox_setup_invoked": False,
            "host_sandbox_setup_may_be_requested": False,
            "software_installed": False,
            "published": False,
        },
    }


def command_assess(args: argparse.Namespace) -> int:
    project_root, corpus_path, state_root, work_root, corpus = resolve_context(args)
    result = build_final_assessment(
        project_root=project_root,
        corpus_path=corpus_path,
        state_root=state_root,
        work_root=work_root,
        installed_codex_root=installed_codex_root_from_args(args),
        corpus=corpus,
        suite=args.suite,
        result_offset=args.result_offset,
        result_limit=args.result_limit,
        attempt_limit=args.attempt_limit,
        codex_executable=args.codex_executable,
    )
    dimensions = result["dimensions"]
    swe_summary = dimensions["external-generalization-reward"]["evidence"]["summary"]
    human = (
        f"AGENTBASE FINAL ASSESSMENT ({args.suite}): {result['status']}\n"
        f"├─ Windows native contracts: {dimensions['windows-native-contract']['status']}\n"
        f"├─ candidate/verifier isolation: {dimensions['candidate-verifier-isolation']['status']}\n"
        f"├─ routing behavior: {dimensions['routing-behavior']['status']}\n"
        f"├─ Windows SWE: qualified {swe_summary['qualified_tasks']}/{swe_summary['task_count']}, "
        f"runs {swe_summary['static_current_runs']}/{swe_summary['expected_runs']}\n"
        f"├─ infrastructure: {dimensions['infrastructure-health']['status']}\n"
        f"├─ installation: {result['installation_status']}\n"
        "└─ composite score: none; no model, install, qualification, or publish was invoked"
    )
    print_result(result, view=args.view, human=human)
    return 0


def add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=str(default_project_root()))
    parser.add_argument("--corpus")
    parser.add_argument("--state-root", default=str(default_state_root()))
    parser.add_argument("--work-root", default=str(default_work_root()))


def add_view_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--view", choices=("human", "machine"), default="human")


def add_network_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dotenv", default=str(default_dotenv_path()))
    parser.add_argument(
        "--required-network-key",
        action="append",
        default=["ALL_PROXY"],
        choices=("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "CODEX_CA_CERTIFICATE", "SSL_CERT_FILE"),
    )
    parser.add_argument("--proxy-dns", choices=("as-configured", "remote"), default="remote")
    parser.add_argument("--all-proxy-fanout", choices=("none", "http-and-https"), default="http-and-https")


def add_installed_codex_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--installed-codex-root",
        type=Path,
        default=default_codex_root(),
        help="installed Codex root that owns auth.json and models_cache.json",
    )


def add_selection_arguments(parser: argparse.ArgumentParser, *, task_required: bool = False) -> None:
    group = parser.add_mutually_exclusive_group(required=task_required)
    group.add_argument("--task")
    if not task_required:
        group.add_argument("--suite", choices=("smoke", "core", "rotation", "all"), default="smoke")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate static contracts only")
    add_context_arguments(validate)
    add_view_argument(validate)
    validate.set_defaults(handler=command_validate)

    listing = subparsers.add_parser("list", help="show bounded task status")
    add_context_arguments(listing)
    add_view_argument(listing)
    add_selection_arguments(listing)
    listing.set_defaults(handler=command_list)

    next_parser = subparsers.add_parser("next", help="select the first qualified case")
    add_context_arguments(next_parser)
    add_view_argument(next_parser)
    next_parser.add_argument("--suite", choices=("smoke", "core", "rotation", "all"), default="core")
    next_parser.set_defaults(handler=command_next)

    check = subparsers.add_parser("check", help="read-only host and source check")
    add_context_arguments(check)
    add_view_argument(check)
    add_selection_arguments(check)
    check.set_defaults(handler=command_check)

    prepare = subparsers.add_parser("prepare", help="clone pinned task sources")
    add_context_arguments(prepare)
    add_view_argument(prepare)
    add_network_arguments(prepare)
    add_selection_arguments(prepare)
    prepare.set_defaults(handler=command_prepare)

    oracle = subparsers.add_parser("oracle", help="qualify one Windows task adapter")
    add_context_arguments(oracle)
    add_view_argument(oracle)
    add_network_arguments(oracle)
    add_installed_codex_root_argument(oracle)
    oracle.add_argument("--task", required=True)
    oracle.add_argument("--codex-executable", type=Path)
    oracle.add_argument("--retain-workspace", action="store_true")
    oracle.set_defaults(handler=command_oracle)

    run = subparsers.add_parser("run", help="run one qualified task/profile")
    add_context_arguments(run)
    add_view_argument(run)
    add_network_arguments(run)
    add_installed_codex_root_argument(run)
    run.add_argument("--task", required=True)
    run.add_argument("--profile", choices=("sol", "luna"), required=True)
    run.add_argument("--codex-executable", type=Path)
    run.add_argument("--timeout-seconds", type=int, default=3600)
    run.add_argument("--retry-reason")
    run.add_argument("--retain-workspace", action="store_true")
    run.set_defaults(handler=command_run)

    recover = subparsers.add_parser("recover", help="resume verifier work without rerunning a model")
    add_context_arguments(recover)
    add_view_argument(recover)
    add_installed_codex_root_argument(recover)
    recover.add_argument("--attempt-id", required=True)
    recover.add_argument("--retain-workspace", action="store_true")
    recover.set_defaults(handler=command_recover)

    sandbox_status = subparsers.add_parser(
        "sandbox-status",
        help="read persistent sandbox readiness without launching Codex or requesting UAC",
    )
    add_context_arguments(sandbox_status)
    add_view_argument(sandbox_status)
    add_installed_codex_root_argument(sandbox_status)
    sandbox_status.add_argument("--codex-executable", type=Path)
    sandbox_status.set_defaults(handler=command_sandbox_status)

    sandbox_setup = subparsers.add_parser(
        "sandbox-setup",
        help="explicitly initialize the persistent elevated sandbox; may request UAC once",
    )
    add_context_arguments(sandbox_setup)
    add_view_argument(sandbox_setup)
    add_installed_codex_root_argument(sandbox_setup)
    sandbox_setup.add_argument("--codex-executable", type=Path)
    sandbox_setup.set_defaults(handler=command_sandbox_setup)

    sandbox_check = subparsers.add_parser(
        "sandbox-check",
        help="reuse the prepared runtime for a no-model permission and tool probe",
    )
    add_context_arguments(sandbox_check)
    add_view_argument(sandbox_check)
    add_installed_codex_root_argument(sandbox_check)
    sandbox_check.add_argument("--codex-executable", type=Path)
    sandbox_check.set_defaults(handler=command_sandbox_check)

    assess = subparsers.add_parser(
        "assess",
        help="run no-model native/isolation checks and aggregate all final evidence dimensions",
    )
    add_context_arguments(assess)
    add_view_argument(assess)
    add_installed_codex_root_argument(assess)
    assess.add_argument("--suite", choices=("smoke", "core", "rotation", "all"), default="all")
    assess.add_argument("--result-offset", type=int, default=0)
    assess.add_argument("--result-limit", type=int, default=100)
    assess.add_argument("--attempt-limit", type=int, default=20)
    assess.add_argument("--codex-executable", type=Path)
    assess.set_defaults(handler=command_assess)

    report = subparsers.add_parser("report", help="aggregate immutable evidence")
    add_context_arguments(report)
    add_view_argument(report)
    report.add_argument("--suite", choices=("smoke", "core", "rotation", "all"), default="all")
    report.add_argument("--result-offset", type=int, default=0)
    report.add_argument("--result-limit", type=int, default=100)
    report.add_argument("--attempt-limit", type=int, default=20)
    report.set_defaults(handler=command_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except EvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
