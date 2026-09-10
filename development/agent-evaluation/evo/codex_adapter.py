from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import agentbase_codex
from evaluation_core import EvaluationError, PreconditionError, read_json, write_json_atomic, write_text_atomic
from evo.runtime_home import cleanup_runtime_auth_after, prepare_runtime_home, runtime_home_from_receipt


EVO_CODEX_RESULT_SCHEMA = "agentbase.evo-codex-run/v1"


class CodexAdapterPrecondition(PreconditionError):
    """A failure proven to have happened before the subject process started."""

    model_invoked = False


def _by_id(entries: list[dict[str, Any]], where: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        identity = entry.get("id")
        if not isinstance(identity, str) or identity in result:
            raise CodexAdapterPrecondition(f"invalid or duplicate {where} id")
        result[identity] = entry
    return result


def _runtime(spec: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for candidate in (spec.get("runtime", {}), item.get("runtime", {})):
        if not isinstance(candidate, Mapping):
            raise CodexAdapterPrecondition("Evo runtime must be an object")
        value.update(candidate)
    return value


def _terminate_tree(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    if os.name != "nt":
        raise CodexAdapterPrecondition("Evo Codex process termination requires Windows")
    completed = subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0 or process.returncode is not None


def _load_audit_owner(project_root: Path):
    audit_path = (
        project_root.resolve()
        / "skills"
        / "codex-event-logger"
        / "scripts"
        / "read_codex_session_audit.py"
    )
    spec = importlib.util.spec_from_file_location("agentbase_evo_session_audit", audit_path)
    if spec is None or spec.loader is None:
        raise EvaluationError("cannot load the repository session audit owner")
    module = importlib.util.module_from_spec(spec)
    audit_directory = str(audit_path.parent)
    sys.path.insert(0, audit_directory)
    try:
        spec.loader.exec_module(module)
    finally:
        if sys.path[0] == audit_directory:
            sys.path.pop(0)
    return module


def _audit_trace(
    project_root: Path,
    codex_home: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    module = _load_audit_owner(project_root)
    traces: list[dict[str, Any]] = []
    for agent in receipt.get("agent_usage", []):
        rollout = agent.get("rollout", {}) if isinstance(agent, Mapping) else {}
        relative = rollout.get("path") if isinstance(rollout, Mapping) else None
        path = (codex_home / relative).resolve() if isinstance(relative, str) else None
        if path is not None and path.is_relative_to(codex_home) and path.is_file():
            traces.append(
                module.scan(
                    path,
                    max_bytes=agentbase_codex.MAX_ATTEMPT_ROLLOUT_BYTES,
                    max_line_bytes=agentbase_codex.MAX_ROLLOUT_LINE_BYTES,
                    include_text=True,
                )
            )
    return {
        "schema": "agentbase.evo-codex-trace/v1",
        "capability": "partial" if receipt.get("agent_usage") else "unavailable",
        "observed": traces,
        "missing": [] if traces else ["native rollout path was not available in the public usage receipt"],
        "private_reasoning_archived": False,
    }


def refresh_codex_trace(
    *,
    project_root: Path,
    attempt_root: Path,
    installed_codex_root: Path | None,
) -> dict[str, Any]:
    """Rebuild the bounded public native trace without changing the subject receipt."""

    attempt = attempt_root.resolve()
    receipt = read_json(attempt / "codex-result.json")
    codex_home = runtime_home_from_receipt(
        attempt_root=attempt,
        installed_codex_root=installed_codex_root,
    )
    trace = _audit_trace(project_root.resolve(), codex_home, receipt)
    trace_path = attempt / "codex-trace.json"
    write_json_atomic(trace_path, trace)
    return {"trace": trace, "trace_path": str(trace_path)}


def _codex_preflight(
    *,
    project_root: Path,
    workspace: Path,
    attempt_root: Path,
    installed_codex_root: Path,
    executable: Path,
    environment: Mapping[str, str],
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    if not (installed_codex_root / "auth.json").is_file():
        raise CodexAdapterPrecondition("installed Codex root has no auth.json")
    if any((attempt_root / name).exists() for name in ("codex-result.json", "codex-rollout-before.json")):
        raise CodexAdapterPrecondition("Codex receipt paths must be unused before launch")
    if not Path(str(projection.get("config_path", ""))).is_file():
        raise CodexAdapterPrecondition("projected Codex config is unavailable")
    audit = _load_audit_owner(project_root)
    if not callable(getattr(audit, "scan", None)):
        raise CodexAdapterPrecondition("repository native audit owner omits scan")
    try:
        version = subprocess.run(
            [str(executable), "--version"],
            cwd=str(workspace),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexAdapterPrecondition(f"Codex CLI identity preflight failed: {exc}") from exc
    if version.returncode != 0:
        raise CodexAdapterPrecondition("Codex CLI --version preflight failed")
    version_text = (version.stdout + version.stderr).decode("utf-8", errors="replace").strip()
    launcher = (project_root / "development" / "agent-evaluation" / "invoke_candidate.ps1").read_text(encoding="utf-8")
    required = ("'--ignore-user-config'", "'--strict-config'", "projects={$projectTrustKey=")
    if any(token not in launcher for token in required):
        raise CodexAdapterPrecondition("shared launcher omits a required isolated-config or trust argument")
    return {
        "schema": "agentbase.evo-codex-preflight/v1",
        "model_invoked": False,
        "codex_version": agentbase_codex.bounded_text(version_text, 200),
        "config_parsed_and_projected": True,
        "v2_agent_capacity_projected": True,
        "authentication": "attempt-scoped-hardlink-present",
        "launcher_contract": {
            "ignore_user_config": True,
            "strict_config": True,
            "workspace_trust_override": True,
        },
        "native_audit_imported": True,
        "receipt_paths_unused": True,
        "subject_dry_run": "not-invoked",
    }


@cleanup_runtime_auth_after
def recover_codex_artifacts(
    *,
    project_root: Path,
    attempt_root: Path,
    installed_codex_root: Path | None,
) -> dict[str, Any]:
    """Finalize an already-written Codex receipt and trace without invoking a model."""

    attempt = attempt_root.resolve()
    codex_home = runtime_home_from_receipt(
        attempt_root=attempt,
        installed_codex_root=installed_codex_root,
    )
    result_path = attempt / "codex-result.json"
    before_path = attempt / "codex-rollout-before.json"
    if not result_path.is_file() or not before_path.is_file():
        raise CodexAdapterPrecondition("Codex recovery requires its raw result and pre-launch rollout snapshot")
    receipt = read_json(result_path)
    before = read_json(before_path)
    if receipt.get("schema") != EVO_CODEX_RESULT_SCHEMA:
        raise EvaluationError("Codex recovery result schema is invalid")
    if (
        receipt.get("model_invoked") is True
        and receipt.get("root_thread_id") in {None, ""}
        and receipt.get("thread_started_count", 0) == 0
        and receipt.get("event_count", 0) == 0
        and receipt.get("exit_code") not in {None, 0}
        and "agents.max_concurrent_threads_per_session must be at least 1"
        in str(receipt.get("diagnostic", ""))
    ):
        receipt["process_started"] = True
        receipt["model_invoked"] = False
        receipt["status"] = "precondition_failed"
        receipt["usage_complete"] = False
        receipt["usage_collection_status"] = "not_applicable_model_not_invoked"
        write_json_atomic(result_path, receipt)
    agent_usage = receipt.get("agent_usage")
    requests_missing = isinstance(agent_usage, list) and any(
        isinstance(agent, Mapping) and "requests" not in agent for agent in agent_usage
    )
    if receipt.get("model_invoked") is True and (
        not receipt.get("agent_usage_receipt_sha256") or requests_missing
    ):
        receipt = agentbase_codex.finalize_candidate_agent_usage(
            receipt,
            codex_home=codex_home,
            before=before,
        )
        write_json_atomic(result_path, receipt)
    return {
        "raw_receipt": receipt,
        "raw_receipt_path": str(result_path),
        "trace": _audit_trace(project_root.resolve(), codex_home, receipt),
    }


@cleanup_runtime_auth_after
def run_codex_job(
    *,
    project_root: Path,
    workspace: Path,
    attempt_root: Path,
    installed_codex_root: Path,
    spec: Mapping[str, Any],
    job: Mapping[str, Any],
    process_environment: Mapping[str, str] | None = None,
    timeout_seconds: int = 3600,
    cancel_check: Callable[[], bool] | None = None,
    task_runtime_bin: Path | None = None,
    skill_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Run one frozen Evo job with its selected Codex-facing component projection."""

    if os.environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED") == "1":
        raise CodexAdapterPrecondition("candidate model evaluator is disabled by the deterministic test gate")
    if os.name != "nt":
        raise CodexAdapterPrecondition("Evo Codex jobs require Windows")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 60 <= timeout_seconds <= 14400:
        raise CodexAdapterPrecondition("Codex timeout_seconds must be an integer from 60 to 14400")
    roots = [path.resolve() for path in (project_root, workspace, attempt_root, installed_codex_root)]
    project, work, attempt, installed_home = roots
    if not project.is_dir() or not work.is_dir() or not attempt.is_dir() or not installed_home.is_dir():
        raise CodexAdapterPrecondition("Evo Codex job roots must exist before preparation")
    if not (installed_home / "auth.json").is_file():
        raise CodexAdapterPrecondition("installed Codex root has no auth.json")
    combinations = _by_id(list(spec.get("combinations", [])), "combination")
    items = _by_id(list(spec.get("evaluations", {}).get("items", [])), "evaluation item")
    combination = combinations.get(job.get("combination"))
    item = items.get(job.get("item"))
    if combination is None or item is None:
        raise CodexAdapterPrecondition("Evo job references an unknown combination or item")
    runtime = _runtime(spec, item)
    if runtime.get("adapter") not in {None, "codex"}:
        raise CodexAdapterPrecondition("Evo job does not select the Codex adapter")
    model = runtime.get("model")
    reasoning = runtime.get("reasoning_effort")
    prompt = item.get("prompt", runtime.get("prompt"))
    if not all(isinstance(value, str) and value for value in (model, reasoning, prompt)):
        raise CodexAdapterPrecondition("Codex runtime requires model, reasoning_effort, and prompt")
    max_agents = runtime.get("max_agents")
    if max_agents is not None and (isinstance(max_agents, bool) or not isinstance(max_agents, int) or max_agents < 1):
        raise CodexAdapterPrecondition("Codex runtime max_agents must be a positive integer")
    components = spec.get("components")
    members = combination.get("members")
    if not isinstance(components, Mapping) or not isinstance(members, Mapping):
        raise CodexAdapterPrecondition("Evo component selection is invalid")
    selected: dict[str, list[Mapping[str, Any]]] = {}
    for kind, identities in members.items():
        catalog = _by_id(list(components.get(kind, [])), f"component {kind}")
        selected[kind] = []
        for identity in identities:
            if identity not in catalog:
                raise CodexAdapterPrecondition(f"combination references unknown {kind}: {identity}")
            selected[kind].append(catalog[identity])
    source_roots = runtime.get("candidate_source_roots", [])
    if not isinstance(source_roots, list) or any(not isinstance(value, str) for value in source_roots):
        raise CodexAdapterPrecondition("candidate_source_roots must be an array of paths")
    try:
        projection = agentbase_codex.stage_codex_component_projection(
            project_root=project,
            workspace=work,
            selected=selected,
            max_agents=max_agents,
            candidate_source_roots=[Path(value) for value in source_roots],
            skill_cache_root=skill_cache_root,
            cache_cancel_check=cancel_check,
        )
    except (EvaluationError, OSError) as exc:
        raise CodexAdapterPrecondition(str(exc)) from exc
    prompt_path = attempt / "candidate-prompt.txt"
    result_path = attempt / "codex-result.json"
    before_path = attempt / "codex-rollout-before.json"
    launcher_stdout_path = attempt / "codex-launcher.stdout"
    launcher_stderr_path = attempt / "codex-launcher.stderr"
    if any(path.exists() for path in (prompt_path, result_path, before_path, launcher_stdout_path, launcher_stderr_path)):
        raise CodexAdapterPrecondition("Evo attempt owns pre-existing Codex adapter artifacts")
    try:
        write_text_atomic(prompt_path, str(prompt))
    except OSError as exc:
        raise CodexAdapterPrecondition(f"cannot persist the bounded Codex prompt: {exc}") from exc
    environment = dict(os.environ if process_environment is None else process_environment)
    explicit = environment.get("AGENTBASE_CODEX_EXECUTABLE_PATH")
    try:
        executable = agentbase_codex.resolve_codex_executable(
            Path(explicit) if explicit else None, environment=environment,
        )
    except EvaluationError as exc:
        raise CodexAdapterPrecondition(str(exc)) from exc
    if task_runtime_bin is not None:
        task_runtime_bin = task_runtime_bin.resolve()
        # The dependency owner supplies a workspace venv/pnpm or the host npm bin.
        if not task_runtime_bin.is_dir():
            raise CodexAdapterPrecondition("task runtime bin must be an existing directory")
    try:
        codex_home, runtime_home_record = prepare_runtime_home(
            attempt_root=attempt,
            installed_codex_root=installed_home,
        )
    except (OSError, PreconditionError) as exc:
        raise CodexAdapterPrecondition(str(exc)) from exc
    argv = [
        "pwsh.exe", "-NoProfile", "-NonInteractive", "-File",
        str(project / "development" / "agent-evaluation" / "invoke_candidate.ps1"),
        "-ProjectRoot", str(project), "-Workspace", str(work),
        "-InstalledCodexRoot", str(installed_home), "-RuntimeCodexRoot", str(codex_home),
        "-PromptPath", str(prompt_path),
        "-ResultPath", str(result_path), "-Model", str(model),
        "-ReasoningEffort", str(reasoning), "-CodexExecutablePath", str(executable),
        "-TimeoutSeconds", str(timeout_seconds), "-ResultSchema", EVO_CODEX_RESULT_SCHEMA,
    ]
    if task_runtime_bin is not None:
        argv.extend(["-TaskRuntimeBinPath", str(task_runtime_bin)])
    if projection.get("hooks_enabled") is True:
        argv.append("-EnableHooks")
    tool_paths = projection.get("tool_paths", [])
    if not isinstance(tool_paths, list) or any(not isinstance(path, str) for path in tool_paths):
        raise CodexAdapterPrecondition("candidate tool path projection is invalid")
    if tool_paths:
        current_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join([*tool_paths, current_path]) if current_path else os.pathsep.join(tool_paths)
    try:
        preflight = _codex_preflight(
            project_root=project,
            workspace=work,
            attempt_root=attempt,
            installed_codex_root=codex_home,
            executable=executable,
            environment=environment,
            projection=projection,
        )
        before = agentbase_codex.candidate_rollout_snapshot(codex_home)
        write_json_atomic(before_path, before)
    except (EvaluationError, OSError) as exc:
        if isinstance(exc, CodexAdapterPrecondition):
            raise
        raise CodexAdapterPrecondition(str(exc)) from exc
    started = time.monotonic()
    cancelled = timed_out = False
    process_tree_terminated = True
    with launcher_stdout_path.open("xb") as launcher_stdout, launcher_stderr_path.open("xb") as launcher_stderr:
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(work),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=launcher_stdout,
                stderr=launcher_stderr,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise CodexAdapterPrecondition(f"shared Codex launcher did not start: {exc}") from exc
        try:
            while process.poll() is None:
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    process_tree_terminated = _terminate_tree(process)
                    break
                if time.monotonic() - started > timeout_seconds + 300:
                    timed_out = True
                    process_tree_terminated = _terminate_tree(process)
                    break
                if launcher_stdout_path.stat().st_size > 2 * 1024 * 1024 or launcher_stderr_path.stat().st_size > 2 * 1024 * 1024:
                    process_tree_terminated = _terminate_tree(process)
                    timed_out = True
                    break
                time.sleep(0.1)
        except BaseException:
            process_tree_terminated = _terminate_tree(process)
            raise
    receipt: dict[str, Any] | None = None
    trace = {"schema": "agentbase.evo-codex-trace/v1", "capability": "unavailable", "observed": [], "missing": ["raw receipt unavailable"], "private_reasoning_archived": False}
    if result_path.is_file():
        try:
            recovered = recover_codex_artifacts(
                project_root=project,
                attempt_root=attempt,
                installed_codex_root=installed_home,
            )
            receipt = recovered["raw_receipt"]
            trace = recovered["trace"]
        except EvaluationError as exc:
            receipt = read_json(result_path)
            receipt["usage_complete"] = False
            receipt["usage_collection_error"] = str(exc)
            write_json_atomic(result_path, receipt)
    if receipt is not None and receipt.get("model_invoked") is False:
        raise CodexAdapterPrecondition(
            str(receipt.get("diagnostic") or "shared launcher failed before the Codex model process started")
        )
    receipt_valid = receipt is not None and receipt.get("schema") == EVO_CODEX_RESULT_SCHEMA
    status = (
        "uncertain"
        if not process_tree_terminated or timed_out or receipt is None
        else "cancelled"
        if cancelled
        else "completed"
        if process.returncode == 0 and receipt_valid and receipt.get("status") == "completed"
        else "failed"
    )
    if projection.get("skill_references"):
        if skill_cache_root is None:
            raise EvaluationError("managed skill references lost their cache root after model execution")
        from evo.skill_cache import SkillCache
        cache = SkillCache(project, skill_cache_root.resolve().parent)
        try:
            cache.validate_workspace_references(work, projection["skill_references"])
        except Exception as exc:
            write_json_atomic(attempt / 'skill-cache-invalid.json', {
                'schema': 'agentbase-evo-skill-cache-invalid/v1',
                'model_invoked': True, 'error': str(exc)[:700],
                'versions': sorted({reference['version_alias'] for reference in projection['skill_references']}),
            })
            raise EvaluationError(f'post-model shared skill payload validation failed: {exc}') from exc
    return {
        "schema": "agentbase.evo-codex-adapter-result/v1",
        "status": status,
        "model_invoked": receipt.get("model_invoked") if receipt is not None else None,
        "launcher_exit_code": process.returncode,
        "owned_process_alive": not process_tree_terminated,
        "launcher_stdout_path": str(launcher_stdout_path),
        "launcher_stderr_path": str(launcher_stderr_path),
        "projection": projection,
        "preflight": preflight,
        "runtime_home": runtime_home_record,
        "raw_receipt": receipt,
        "raw_receipt_path": str(result_path),
        "trace": trace,
    }
