"""Bridge Evo's Codex runner to the existing Windows SWE owners."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from agent_eval import run_candidate_verifier, verifier_runtime_identity
from evaluation_core import (
    CaseLock,
    EvaluationError,
    PreconditionError,
    apply_windows_adapter_baseline,
    canonical_bytes,
    capture_candidate_patch,
    create_workspace,
    ensure_evaluation_roots,
    find_matching_qualification,
    find_qualification_receipts,
    load_corpus,
    qualification_base_identity,
    remove_managed_tree,
    require_task,
    require_within,
    sha256_file,
    verify_deep_swe,
    verify_upstream_source,
    verify_windows_adapter_assets,
)
from windows_verifier import prepare_dependencies

from .spec import EvoError, read_json


SWE_STATE_SCHEMA = "agentbase.evo-swe-attempt/v1"


def _absolute_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise EvoError(f"runtime.swe.{field} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise EvoError(f"runtime.swe.{field} must be an absolute path without parent traversal")
    return path.resolve()


def validate_binding(runtime: Mapping[str, Any], *, project_root: Path) -> dict[str, Any] | None:
    """Validate the static corpus/task binding without inspecting runtime preparation."""
    value = runtime.get("swe")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EvoError("runtime.swe must be an object")
    if any(runtime.get(key) for key in ('files', 'verifier', 'answer_contains')):
        raise EvoError('SWE task inputs and grader belong to the corpus; runtime files/verifier/answer_contains cannot replace them')
    required = {"corpus", "corpus_sha256", "task", "state_root", "work_root", "work_reservation_mb"}
    if set(value) not in {frozenset(required), frozenset({*required, "owner_namespace"})}:
        raise EvoError(
            "runtime.swe requires only corpus, corpus_sha256, task, state_root, work_root, and work_reservation_mb"
        )
    corpus_path = _absolute_path(value.get("corpus"), "corpus")
    state_root = _absolute_path(value.get("state_root"), "state_root")
    work_root = _absolute_path(value.get("work_root"), "work_root")
    expected_hash = value.get("corpus_sha256")
    task_id = value.get("task")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise EvoError("runtime.swe.corpus_sha256 must be SHA-256")
    try:
        int(expected_hash, 16)
    except ValueError as exc:
        raise EvoError("runtime.swe.corpus_sha256 must be SHA-256") from exc
    if not isinstance(task_id, str) or not task_id:
        raise EvoError("runtime.swe.task must be a non-empty task id")
    reservation = value.get("work_reservation_mb")
    if isinstance(reservation, bool) or not isinstance(reservation, int) or not 1 <= reservation <= 1024 * 1024:
        raise EvoError("runtime.swe.work_reservation_mb must be an integer from 1 to 1048576")
    if not corpus_path.is_file() or sha256_file(corpus_path) != expected_hash.lower():
        raise EvoError("runtime.swe corpus is unavailable or differs from corpus_sha256")
    corpus = load_corpus(corpus_path)
    verify_windows_adapter_assets(project_root, corpus)
    require_task(corpus, task_id)
    return {
        "corpus": str(corpus_path),
        "corpus_sha256": expected_hash.lower(),
        "task": task_id,
        "state_root": str(state_root),
        "work_root": str(work_root),
        "work_reservation_mb": reservation,
    }


def validate_runtime(
    runtime: Mapping[str, Any],
    *,
    project_root: Path,
    evo_state_root: Path,
    evo_work_root: Path,
    installed_codex_root: Path | None = None,
) -> dict[str, Any] | None:
    """Validate and freeze the optional SWE runtime without preparing any task assets."""

    binding = validate_binding(runtime, project_root=project_root)
    if binding is None:
        return None
    state_root = Path(binding["state_root"])
    work_root = Path(binding["work_root"])
    ensure_evaluation_roots(project_root, state_root, work_root, installed_codex_root)
    roots = [project_root.resolve(), evo_state_root.resolve(), evo_work_root.resolve(), state_root, work_root]
    if installed_codex_root is not None:
        roots.append(installed_codex_root.resolve())
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise EvoError("Evo and SWE project/state/work/Codex roots must be disjoint")
    namespace = hashlib.sha256(os.path.normcase(str(evo_state_root.resolve())).encode("utf-8")).hexdigest()[:16]
    return {**binding, "owner_namespace": namespace}


def _write_state(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return payload


def _context(project_root: Path, runtime: Mapping[str, Any]) -> tuple[dict[str, Any], Path, Path, Path, dict[str, Any]]:
    swe = runtime["swe"]
    corpus_path = Path(swe["corpus"]).resolve()
    state_root = Path(swe["state_root"]).resolve()
    work_root = Path(swe["work_root"]).resolve()
    corpus = load_corpus(corpus_path)
    if sha256_file(corpus_path) != swe["corpus_sha256"]:
        raise PreconditionError("the frozen SWE corpus changed after Evo submit")
    verify_windows_adapter_assets(project_root, corpus)
    return swe, corpus_path, state_root, work_root, corpus


def _qualified_context(project_root: Path, runtime: Mapping[str, Any]) -> dict[str, Any]:
    swe, corpus_path, state_root, work_root, corpus = _context(project_root, runtime)
    task_id = swe["task"]
    task = require_task(corpus, task_id)
    verify_deep_swe(state_root, corpus)
    verify_upstream_source(state_root, corpus, task_id)
    base = qualification_base_identity(project_root, corpus_path, state_root, corpus, task_id)
    import agentbase_codex
    verifier_runtime = verifier_runtime_identity(task, agentbase_codex.verifier_runtime_tools(task))
    receipts = find_qualification_receipts(state_root, task_id, base["identity_sha256"])
    matches = [
        receipt for receipt in receipts
        if receipt.get("verifier_runtime_identity_sha256") == verifier_runtime["identity_sha256"]
        and receipt.get("qualified") is True
    ]
    if not matches:
        raise PreconditionError(
            "no current Windows qualification matches the SWE task and verifier runtime; run oracle explicitly"
        )
    return {
        "swe": swe, "corpus_path": corpus_path, "state_root": state_root,
        "work_root": work_root, "corpus": corpus, "task": task,
        "qualifications": matches, "verifier_runtime": verifier_runtime,
    }


def prepare_job(
    *, project_root: Path, runtime: Mapping[str, Any], study_id: int, job_id: int,
    attempt_root: Path, environment: Mapping[str, str],
) -> dict[str, Any]:
    """Create one owned candidate workspace after proving qualification exists."""

    context = _qualified_context(project_root, runtime)
    state_path = attempt_root / "swe-state.json"
    if state_path.exists():
        return read_json(state_path)
    state_root, work_root = context["state_root"], context["work_root"]
    lock_key = f"candidate:evo:{context['swe']['owner_namespace']}:s{study_id}:j{job_id}"
    with CaseLock(state_root, lock_key):
        relative_name = f"evo/{context['swe']['owner_namespace']}/s{study_id}/j{job_id}/candidate"
        workspace = create_workspace(state_root, work_root, context["corpus"], context["swe"]["task"], relative_name)
        try:
            dependency, dependency_values = prepare_dependencies(
                context["task"], workspace, attempt_root / "swe-candidate-setup", environment
            )
            qualification = find_matching_qualification(
                context["qualifications"], dependency["identity_sha256"],
                context["verifier_runtime"]["identity_sha256"],
            )
            if qualification is None:
                raise PreconditionError("prepared SWE dependency identity differs from the current qualification")
            windows_adapter = apply_windows_adapter_baseline(project_root, workspace, context["task"])
            import agentbase_codex
            task_context = agentbase_codex.stage_candidate_task_context(
                state_root, context["corpus"], context["swe"]["task"], workspace,
                dependency_values,
            )
            return _write_state(state_path, {
                "schema": SWE_STATE_SCHEMA, "stage": "prepared", "study": study_id, "job": job_id,
                "workspace": str(workspace), "task": context["swe"]["task"],
                "qualification": qualification, "dependency_identity": dependency,
                "dependency_values": dependency_values, "windows_adapter_baseline": windows_adapter,
                "task_prompt": task_context["prompt"],
                "task_runtime": task_context["task_runtime"],
            })
        except Exception:
            if workspace.exists():
                remove_managed_tree(work_root, require_within(work_root, workspace))
            raise


def mark_codex_completed(attempt_root: Path, raw_receipt: Mapping[str, Any]) -> dict[str, Any]:
    state_path = attempt_root / "swe-state.json"
    state = read_json(state_path)
    if raw_receipt.get("model_invoked") is not True or raw_receipt.get("status") != "completed":
        raise EvaluationError("SWE post-processing requires a completed model receipt")
    state.update(stage="candidate-finished", codex_result_sha256=hashlib.sha256(canonical_bytes(raw_receipt)).hexdigest())
    return _write_state(state_path, state)


def finalize_job(
    *, project_root: Path, runtime: Mapping[str, Any], study_id: int, job_id: int,
    attempt_root: Path, environment: Mapping[str, str], raw_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture and verify a completed candidate; safe to call again during recovery."""

    state_path = attempt_root / "swe-state.json"
    state = read_json(state_path)
    if state.get("schema") != SWE_STATE_SCHEMA or state.get("study") != study_id or state.get("job") != job_id:
        raise EvaluationError("SWE attempt state does not match the Evo job")
    if state.get("stage") in {"verified", "invalid-candidate"}:
        verifier = state.get("verifier")
        reward = (verifier or {}).get("grade", {}).get("reward", {}).get("reward")
        if state.get("stage") == "invalid-candidate":
            reward = 0
        return {
            "schema": "agentbase.evo-swe-result/v1", "task": state["task"],
            "valid": state.get("stage") == "verified", "terminal_reason": state.get("terminal_reason"),
            "qualification_receipt_sha256": state["qualification"].get("receipt_sha256"),
            "candidate_patch": state.get("candidate_patch"), "verifier": verifier,
            "values": {"quality.reward": reward} if reward is not None else {},
        }
    context = _qualified_context(project_root, runtime)
    workspace = Path(str(state["workspace"])).resolve()
    require_within(context["work_root"], workspace)
    lock_key = f"candidate:evo:{context['swe']['owner_namespace']}:s{study_id}:j{job_id}"
    with CaseLock(context["state_root"], lock_key):
        if state.get("stage") == "prepared":
            state = mark_codex_completed(attempt_root, raw_receipt)
        if state.get("stage") == "candidate-finished":
            patch = attempt_root / "candidate.patch"
            try:
                descriptor = capture_candidate_patch(workspace, context["task"], patch)
            except EvaluationError as exc:
                state.update(stage="invalid-candidate", terminal_reason=str(exc))
                state = _write_state(state_path, state)
                return {
                    "schema": "agentbase.evo-swe-result/v1", "task": state["task"], "valid": False,
                    "terminal_reason": str(exc),
                    "qualification_receipt_sha256": state["qualification"].get("receipt_sha256"),
                    "candidate_patch": None, "verifier": None, "values": {"quality.reward": 0},
                }
            state.update(stage="patch-captured", candidate_patch=descriptor)
            state = _write_state(state_path, state)
        if state.get("stage") == "patch-captured":
            patch_path = Path(state["candidate_patch"]["path"])
            if not patch_path.is_file() or sha256_file(patch_path) != state["candidate_patch"].get("sha256"):
                raise EvaluationError("captured candidate patch changed before verifier recovery")
            verifier = run_candidate_verifier(
                project_root=project_root, state_root=context["state_root"], work_root=context["work_root"],
                corpus=context["corpus"], task_id=context["swe"]["task"],
                attempt_id=f"evo/{context['swe']['owner_namespace']}/s{study_id}/j{job_id}",
                attempt_root=attempt_root, patch=patch_path,
                environment=environment,
                expected_dependency_sha256=state["qualification"]["dependency_identity_sha256"],
                p2p_exclusions=list(state["qualification"].get("p2p_exclusions", [])), retain_workspace=False,
            )
            state.update(stage="verified", verifier=verifier)
            state = _write_state(state_path, state)
        if state.get("stage") != "verified":
            raise EvaluationError(f"SWE attempt cannot be finalized from stage {state.get('stage')}")
        grade = state["verifier"].get("grade", {})
        reward = grade.get("reward", {}).get("reward")
        return {
            "schema": "agentbase.evo-swe-result/v1", "task": context["swe"]["task"], "valid": True,
            "qualification_receipt_sha256": state["qualification"].get("receipt_sha256"),
            "candidate_patch": state["candidate_patch"], "verifier": state["verifier"],
            "values": {"quality.reward": reward} if reward is not None else {},
        }


def cleanup_job(runtime: Mapping[str, Any], attempt_root: Path) -> dict[str, Any]:
    state_path = attempt_root / "swe-state.json"
    if not state_path.is_file():
        return {"removed": False}
    state = read_json(state_path)
    work_root = Path(runtime["swe"]["work_root"]).resolve()
    workspace = Path(str(state["workspace"])).resolve()
    managed = require_within(work_root, workspace)
    if managed.exists():
        remove_managed_tree(work_root, managed)
    return {"removed": True}
