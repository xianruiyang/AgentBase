#!/usr/bin/env python3
"""Manage task contracts, dependency queries, execution state, and bounded context."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_RESULT_RECORDS = 100_000
MAX_LIST_ITEMS = 200
MAX_STRING = 8_000
DEFAULT_LIMIT = 50
DEFAULT_BUDGET = 16_000
TASK_ID_RE = re.compile(r"^T[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_ID_RE = re.compile(
    r"^(?:REQ|AC|CON|UDES|DEC|DES|OBS|GAP|SOL|DCR)-[A-Za-z0-9][A-Za-z0-9._-]*$"
)
STATUSES = ("todo", "claimed", "in_progress", "review", "blocked", "done")
ACTIVE_STATUSES = {"claimed", "in_progress", "review", "blocked"}
ACTIVE_STATUS_CHOICES = ("claimed", "in_progress", "review", "blocked")
DEPENDENCY_TYPES = ("hard", "ordering", "informational")
REASONING_HINTS = ("low", "medium", "high", "xhigh", "max", "ultra")
WORKFLOW_STAGES = (
    "requirements",
    "user_design",
    "design",
    "current_state",
    "solution",
    "deferred_changes",
)
PROTECTED_PREFIXES = {
    "requirements": {"REQ", "AC", "CON"},
    "user_design": {"UDES"},
}
HEADING_ID_RE = re.compile(
    r"^##\s+(?P<id>(?:REQ|AC|CON|UDES|DEC|DES|OBS|GAP|SOL|DCR)-"
    r"[A-Za-z0-9][A-Za-z0-9._-]*)(?:\s+.*?)?\s*$"
)


class TaskctlError(RuntimeError):
    pass


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def emit(value: Any, *, pretty: bool = False, stream: Any = sys.stdout) -> None:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = compact_json(value)
    stream.write(text + "\n")


def read_text_bounded(path: Path, limit: int) -> str:
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise TaskctlError(f"missing file: {path}") from exc
    if size > limit:
        raise TaskctlError(f"file exceeds {limit} bytes: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TaskctlError(f"file is not UTF-8: {path}") from exc


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> Any:
    text = read_text_bounded(path, limit)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskctlError(f"invalid JSON in {path}: {exc}") from exc


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def resolve_root(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def resolve_inside(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise TaskctlError(f"manifest path must be relative: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise TaskctlError(f"path escapes task directory: {relative}") from exc
    return resolved


@contextmanager
def workspace_lock(root: Path) -> Iterator[None]:
    lock_path = resolve_inside(root, ".work-cache/workspace.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolve_inside(root, ".work-cache/workspace.lock")
    try:
        handle = lock_path.open("r+b")
    except FileNotFoundError:
        try:
            handle = lock_path.open("x+b")
        except FileExistsError:
            handle = lock_path.open("r+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TaskctlError("task workspace is being updated by another process") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def load_table(root: Path) -> dict[str, Any]:
    path = root / "task-table.json"
    table = read_json(path)
    if not isinstance(table, dict) or table.get("schema") != "task.table":
        raise TaskctlError(f"unsupported task table manifest: {path}")
    resolved_paths: dict[str, Path] = {}
    for field, default in (
        ("task_dir", "tasks"),
        ("state_dir", "state"),
        ("result_dir", "results"),
        ("table_view", "TASK_TABLE.md"),
    ):
        value = table.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise TaskctlError(f"task-table.json {field} must be a non-empty string")
        if value != default:
            raise TaskctlError(f"task-table.json {field} must remain {default}")
        resolved_paths[field] = resolve_inside(root, value)
    source_index = table.get("source_index")
    if source_index is not None:
        if not isinstance(source_index, str) or not source_index.strip():
            raise TaskctlError("task-table.json source_index must be a non-empty string")
        if source_index != ".work-cache/index.json":
            raise TaskctlError("task-table.json source_index must remain .work-cache/index.json")
        resolved_paths["source_index"] = resolve_inside(root, source_index)
    storage_paths = [
        resolved_paths["task_dir"],
        resolved_paths["state_dir"],
        resolved_paths["result_dir"],
    ]
    if any(path == root for path in storage_paths):
        raise TaskctlError("task, state, and result storage must not use the workspace root")
    if len(set(storage_paths)) != len(storage_paths):
        raise TaskctlError("task, state, and result storage must use distinct directories")
    for index, left in enumerate(storage_paths):
        for right in storage_paths[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise TaskctlError("task, state, and result storage directories must not overlap")
    reserved_files = {(root / "task-table.json").resolve(), (root / "workflow.json").resolve()}
    workflow = load_workflow(root)
    if workflow is not None:
        for relative in workflow["documents"].values():
            reserved_files.add(resolve_inside(root, relative))
        reserved_files.add((root / "protected-baseline.json").resolve())
    if "source_index" in resolved_paths:
        reserved_files.add(resolved_paths["source_index"])
    if resolved_paths["table_view"] in reserved_files:
        raise TaskctlError("generated task view must not overwrite workflow truth")
    if "source_index" in resolved_paths and resolved_paths["table_view"] == resolved_paths["source_index"]:
        raise TaskctlError("generated task view must not overwrite the semantic index")
    if any(
        resolved_paths["table_view"] == storage or storage in resolved_paths["table_view"].parents
        for storage in storage_paths
    ):
        raise TaskctlError("generated task view must not overwrite task storage")
    for storage_path in storage_paths:
        if any(storage_path == reserved.parent or storage_path in reserved.parents for reserved in reserved_files):
            raise TaskctlError("task storage must not contain workflow truth")
    verify_protected_sources(root, workflow)
    return table


def table_paths(root: Path, table: dict[str, Any]) -> tuple[Path, Path, Path]:
    return (
        resolve_inside(root, str(table.get("task_dir", "tasks"))),
        resolve_inside(root, str(table.get("state_dir", "state"))),
        resolve_inside(root, str(table.get("result_dir", "results"))),
    )


def require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TaskctlError(f"{field} must be a string")
    cleaned = value.strip()
    if not allow_empty and not cleaned:
        raise TaskctlError(f"{field} must not be empty")
    if len(cleaned) > MAX_STRING:
        raise TaskctlError(f"{field} exceeds {MAX_STRING} characters")
    return cleaned


def string_list(value: Any, field: str, *, maximum: int = MAX_LIST_ITEMS) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskctlError(f"{field} must be an array")
    if len(value) > maximum:
        raise TaskctlError(f"{field} contains more than {maximum} items")
    result = [require_string(item, f"{field}[]") for item in value]
    if len(set(result)) != len(result):
        raise TaskctlError(f"{field} contains duplicate values")
    return result


def validate_relative(value: str, field: str, *, allow_glob: bool = True) -> str:
    cleaned = require_string(value, field).replace("\\", "/")
    if Path(cleaned).is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
        raise TaskctlError(f"{field} must be project-relative: {value}")
    pieces = [piece for piece in cleaned.split("/") if piece not in ("", ".")]
    if ".." in pieces:
        raise TaskctlError(f"{field} escapes the project: {value}")
    if not allow_glob and any(token in cleaned for token in ("*", "?", "[", "]")):
        raise TaskctlError(f"{field} must not contain glob syntax: {value}")
    return cleaned


def validate_task(raw: Any, *, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "task.record":
        raise TaskctlError("task file must use schema task.record")
    task_id = require_string(raw.get("id"), "task.id")
    if not TASK_ID_RE.fullmatch(task_id):
        raise TaskctlError(f"invalid task id: {task_id}")
    if expected_id is not None and task_id != expected_id:
        raise TaskctlError(f"task id mismatch: expected {expected_id}, got {task_id}")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise TaskctlError("task.revision must be a positive integer")
    source_ids = string_list(raw.get("source_ids"), "task.source_ids")
    for source_id in source_ids:
        if not SOURCE_ID_RE.fullmatch(source_id):
            raise TaskctlError(f"invalid source id: {source_id}")

    raw_dependencies = raw.get("dependencies", [])
    if not isinstance(raw_dependencies, list) or len(raw_dependencies) > MAX_LIST_ITEMS:
        raise TaskctlError(f"task.dependencies must contain at most {MAX_LIST_ITEMS} items")
    dependencies: list[dict[str, Any]] = []
    seen_dependencies: set[str] = set()
    for index, dependency in enumerate(raw_dependencies):
        if not isinstance(dependency, dict):
            raise TaskctlError(f"task.dependencies[{index}] must be an object")
        dependency_id = require_string(dependency.get("id"), f"task.dependencies[{index}].id")
        if not TASK_ID_RE.fullmatch(dependency_id):
            raise TaskctlError(f"invalid dependency id: {dependency_id}")
        if dependency_id == task_id:
            raise TaskctlError(f"task {task_id} depends on itself")
        if dependency_id in seen_dependencies:
            raise TaskctlError(f"task {task_id} repeats dependency {dependency_id}")
        dependency_type = dependency.get("type")
        if dependency_type not in DEPENDENCY_TYPES:
            raise TaskctlError(
                f"task.dependencies[{index}].type must be one of {', '.join(DEPENDENCY_TYPES)}"
            )
        dependencies.append(
            {
                "id": dependency_id,
                "type": dependency_type,
                "consumes": string_list(
                    dependency.get("consumes"), f"task.dependencies[{index}].consumes"
                ),
            }
        )
        seen_dependencies.add(dependency_id)

    mutation_scope = [
        validate_relative(value, "task.mutation_scope[]")
        for value in string_list(raw.get("mutation_scope"), "task.mutation_scope")
    ]
    reasoning_hint = raw.get("reasoning_hint")
    if reasoning_hint is not None and reasoning_hint not in REASONING_HINTS:
        raise TaskctlError(f"task.reasoning_hint must be one of {', '.join(REASONING_HINTS)}")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TaskctlError("task.metadata must be an object")
    normalized = {
        "schema": "task.record",
        "id": task_id,
        "title": require_string(raw.get("title"), "task.title"),
        "outcome": require_string(raw.get("outcome"), "task.outcome"),
        "source_ids": source_ids,
        "dependencies": dependencies,
        "mutation_scope": mutation_scope,
        "outputs": string_list(raw.get("outputs"), "task.outputs"),
        "verification": string_list(raw.get("verification"), "task.verification"),
        "suggested_skills": string_list(
            raw.get("suggested_skills"), "task.suggested_skills"
        ),
        "reasoning_hint": reasoning_hint,
        "revision": revision,
    }
    if metadata:
        normalized["metadata"] = metadata
    return normalized


def validate_state(raw: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "task.state":
        raise TaskctlError(f"state for {task_id} must use schema task.state")
    if raw.get("task_id") != task_id:
        raise TaskctlError(f"state identity mismatch for {task_id}")
    status = raw.get("status")
    if status not in STATUSES:
        raise TaskctlError(f"invalid state status for {task_id}: {status}")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise TaskctlError(f"state revision for {task_id} must be a positive integer")
    owner = raw.get("owner")
    if owner is not None:
        owner = require_string(owner, f"state.owner[{task_id}]")
    if status == "todo" and owner is not None:
        raise TaskctlError(f"todo state for {task_id} must not have an owner")
    if status != "todo" and owner is None:
        raise TaskctlError(f"active or completed state for {task_id} must have an owner")
    result_ref = raw.get("result_ref")
    if result_ref is not None:
        result_ref = validate_relative(
            require_string(result_ref, f"state.result_ref[{task_id}]"),
            f"state.result_ref[{task_id}]",
            allow_glob=False,
        )
    if status == "done" and result_ref is None:
        raise TaskctlError(f"completed state for {task_id} must reference a result")
    if status != "done" and result_ref is not None:
        raise TaskctlError(f"non-completed state for {task_id} must not reference a result")
    return {
        "schema": "task.state",
        "task_id": task_id,
        "status": status,
        "owner": owner,
        "revision": revision,
        "note": require_string(raw.get("note", ""), f"state.note[{task_id}]", allow_empty=True),
        "blocked_reason": require_string(
            raw.get("blocked_reason", ""),
            f"state.blocked_reason[{task_id}]",
            allow_empty=True,
        ),
        "next_action": require_string(
            raw.get("next_action", ""),
            f"state.next_action[{task_id}]",
            allow_empty=True,
        ),
        "result_ref": result_ref,
    }


def validate_result(raw: Any, task: dict[str, Any]) -> dict[str, Any]:
    return validate_result_for_task(raw, task, require_current_revision=True)


def validate_result_for_task(
    raw: Any, task: dict[str, Any], *, require_current_revision: bool
) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "task.result":
        raise TaskctlError("result file must use schema task.result")
    if raw.get("task_id") != task["id"]:
        raise TaskctlError("result.task_id does not match the task")
    result_revision = raw.get("task_revision")
    if (
        not isinstance(result_revision, int)
        or isinstance(result_revision, bool)
        or result_revision < 1
        or result_revision > task["revision"]
    ):
        raise TaskctlError("result.task_revision is invalid for the task")
    if require_current_revision and result_revision != task["revision"]:
        raise TaskctlError("result.task_revision does not match the current task contract")
    changed_files = [
        validate_relative(value, "result.changed_files[]", allow_glob=False)
        for value in string_list(raw.get("changed_files"), "result.changed_files")
    ]
    invalidated_ids = string_list(
        raw.get("invalidated_source_ids"), "result.invalidated_source_ids"
    )
    for source_id in invalidated_ids:
        if not SOURCE_ID_RE.fullmatch(source_id):
            raise TaskctlError(f"invalid source id in result: {source_id}")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TaskctlError("result.metadata must be an object")
    result = {
        "schema": "task.result",
        "task_id": task["id"],
        "task_revision": result_revision,
        "outcome": require_string(raw.get("outcome"), "result.outcome"),
        "outputs": string_list(raw.get("outputs"), "result.outputs"),
        "changed_files": changed_files,
        "verification": string_list(raw.get("verification"), "result.verification"),
        "unresolved": string_list(raw.get("unresolved"), "result.unresolved"),
        "invalidated_source_ids": invalidated_ids,
    }
    if metadata:
        result["metadata"] = metadata
    return result


def load_tasks(root: Path, table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    task_dir, _, _ = table_paths(root, table)
    if not task_dir.exists():
        raise TaskctlError(f"missing task directory: {task_dir}")
    paths = sorted(task_dir.glob("*.json"))
    if len(paths) > MAX_RECORDS:
        raise TaskctlError(f"task directory contains more than {MAX_RECORDS} records")
    tasks: dict[str, dict[str, Any]] = {}
    for path in paths:
        resolved_path = path.resolve()
        if resolved_path.parent != task_dir:
            raise TaskctlError(f"task record escapes task storage: {path}")
        path = resolved_path
        task = validate_task(read_json(path), expected_id=path.stem)
        if task["id"] in tasks:
            raise TaskctlError(f"duplicate task id: {task['id']}")
        tasks[task["id"]] = task
    ensure_acyclic(tasks)
    return tasks


def load_state(root: Path, table: dict[str, Any], task_id: str) -> dict[str, Any]:
    _, state_dir, _ = table_paths(root, table)
    path = (state_dir / f"{task_id}.json").resolve()
    if path.parent != state_dir:
        raise TaskctlError(f"task state escapes state storage: {path}")
    return validate_state(read_json(path), task_id)


def load_states(
    root: Path, table: dict[str, Any], tasks: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    _, state_dir, _ = table_paths(root, table)
    state_paths = sorted(state_dir.glob("*.json"))
    if len(state_paths) > MAX_RECORDS:
        raise TaskctlError(f"state directory contains more than {MAX_RECORDS} records")
    state_ids = {path.stem for path in state_paths}
    task_ids = set(tasks)
    if state_ids != task_ids:
        missing = sorted(task_ids - state_ids)
        extra = sorted(state_ids - task_ids)
        raise TaskctlError(
            "task/state storage mismatch: "
            f"missing={','.join(missing[:10]) or '-'}; extra={','.join(extra[:10]) or '-'}"
        )
    return {task_id: load_state(root, table, task_id) for task_id in tasks}


def validate_result_history(
    root: Path,
    table: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
) -> None:
    _, _, result_dir = table_paths(root, table)
    paths = sorted(result_dir.glob(f"{task['id']}.r*.json"))
    if len(paths) > MAX_RESULT_RECORDS:
        raise TaskctlError(
            f"task {task['id']} has more than {MAX_RESULT_RECORDS} result records"
        )
    for path in paths:
        path = path.resolve()
        if path.parent != result_dir:
            raise TaskctlError(f"task result history escapes result storage: {path}")
        match = re.fullmatch(rf"{re.escape(task['id'])}\.r(?P<revision>[1-9][0-9]*)\.json", path.name)
        if match is None:
            raise TaskctlError(f"invalid task result history name: {path}")
        historical = validate_result_for_task(
            read_json(path), task, require_current_revision=False
        )
        if historical["task_id"] != task["id"]:
            raise TaskctlError(f"task result history identity mismatch: {path}")


def load_workflow(root: Path) -> dict[str, Any] | None:
    path = root / "workflow.json"
    if not path.exists():
        return None
    workflow = read_json(path)
    if not isinstance(workflow, dict) or workflow.get("schema") != "delivery.workflow":
        raise TaskctlError(f"unsupported workflow manifest: {path}")
    fixed_fields = {
        "task_table": "task-table.json",
        "protected_baseline": "protected-baseline.json",
        "semantic_index": ".work-cache/index.json",
        "status_view": "WORK_STATUS.md",
    }
    for field, expected in fixed_fields.items():
        if workflow.get(field, expected) != expected:
            raise TaskctlError(f"workflow.json {field} must remain {expected}")
    documents = workflow.get("documents")
    if not isinstance(documents, dict):
        raise TaskctlError("workflow.json documents must be an object")
    resolved: list[Path] = []
    for stage in WORKFLOW_STAGES:
        relative = documents.get(stage)
        if not isinstance(relative, str) or not relative.strip():
            raise TaskctlError(f"workflow.json is missing documents.{stage}")
        resolved.append(resolve_inside(root, relative))
    if len(set(resolved)) != len(resolved):
        raise TaskctlError("workflow documents must use distinct paths")
    return workflow


def document_semantic_ids(text: str) -> list[str]:
    return sorted(
        match.group("id")
        for line in text.splitlines()
        if (match := HEADING_ID_RE.match(line)) is not None
    )


def verify_protected_sources(
    root: Path, workflow: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    workflow = workflow if workflow is not None else load_workflow(root)
    baseline_path = root / "protected-baseline.json"
    if not baseline_path.exists():
        return None
    if workflow is None:
        raise TaskctlError("protected baseline requires workflow.json")
    baseline = read_json(baseline_path)
    if not isinstance(baseline, dict) or baseline.get("schema") != "delivery.protected-baseline":
        raise TaskctlError(f"unsupported protected baseline: {baseline_path}")
    if baseline.get("workflow_id") != workflow.get("id"):
        raise TaskctlError("protected baseline belongs to a different workflow")
    documents = baseline.get("documents")
    if not isinstance(documents, dict):
        raise TaskctlError("protected baseline documents must be an object")
    for stage, allowed_prefixes in PROTECTED_PREFIXES.items():
        record = documents.get(stage)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise TaskctlError(f"protected baseline is missing {stage}")
        expected_path = workflow["documents"][stage]
        if record["path"] != expected_path:
            raise TaskctlError(f"protected baseline path mismatch for {stage}")
        source_path = resolve_inside(root, expected_path)
        source_text = read_text_bounded(source_path, MAX_INDEX_BYTES)
        fingerprint = f"sha256:{hashlib.sha256(source_text.encode('utf-8')).hexdigest()}"
        if record.get("fingerprint") != fingerprint:
            raise TaskctlError(
                f"protected source changed: {record['path']}; restore it and record a deferred change"
            )
        ids = record.get("ids")
        if (
            not isinstance(ids, list)
            or any(not isinstance(value, str) for value in ids)
            or len(ids) != len(set(ids))
        ):
            raise TaskctlError(f"protected baseline ids are invalid for {stage}")
        actual_ids = document_semantic_ids(source_text)
        if sorted(ids) != actual_ids:
            raise TaskctlError(f"protected baseline ids do not match {expected_path}")
        if any(value.split("-", 1)[0] not in allowed_prefixes for value in ids):
            raise TaskctlError(f"protected baseline contains an invalid {stage} id")
    return baseline


def ensure_acyclic(tasks: dict[str, dict[str, Any]]) -> None:
    indegree = {task_id: 0 for task_id in tasks}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task_id, task in tasks.items():
        for dependency in task["dependencies"]:
            dependency_id = dependency["id"]
            if dependency_id not in tasks:
                continue
            indegree[task_id] += 1
            dependents[dependency_id].append(task_id)
    ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    processed = 0
    while ready:
        task_id = ready.popleft()
        processed += 1
        for dependent_id in sorted(dependents[task_id]):
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                ready.append(dependent_id)
    if processed != len(tasks):
        cycle_ids = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        raise TaskctlError(
            f"task dependency cycle involving: {', '.join(cycle_ids[:20])}"
        )


def rebuild_delivery_index(root: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    script_path = (
        Path(__file__).resolve().parents[2]
        / "delivery-workflow"
        / "scripts"
        / "workctl.py"
    )
    if not script_path.is_file():
        return None, {
            "kind": "delivery_index_builder_missing",
            "path": str(script_path),
        }
    spec = importlib.util.spec_from_file_location("_agentbase_delivery_workctl", script_path)
    if spec is None or spec.loader is None:
        return None, {"kind": "delivery_index_builder_unreadable"}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        rebuilt = module.build_index(root)
    except Exception as exc:
        return None, {
            "kind": "delivery_index_rebuild_failed",
            "message": str(exc),
        }
    if not isinstance(rebuilt, dict) or rebuilt.get("schema") != "delivery.index":
        return None, {"kind": "delivery_index_rebuild_unsupported"}
    return rebuilt, None


def maybe_load_index(root: Path, table: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    source_index = table.get("source_index")
    if not source_index:
        return None, [{"kind": "upstream_index_not_configured"}]
    path = resolve_inside(root, str(source_index))
    if not path.exists():
        return None, [{"kind": "upstream_index_missing", "path": str(source_index)}]
    try:
        index = read_json(path, MAX_INDEX_BYTES)
    except TaskctlError as exc:
        return None, [{"kind": "upstream_index_unreadable", "message": str(exc)}]
    if not isinstance(index, dict) or index.get("schema") != "delivery.index":
        return None, [{"kind": "upstream_index_unsupported", "path": str(source_index)}]
    workflow = load_workflow(root)
    if workflow is None:
        return None, [{"kind": "upstream_workflow_missing"}]
    if index.get("workflow_id") != workflow.get("id"):
        return None, [{"kind": "upstream_index_workflow_mismatch"}]
    if index.get("documents") != workflow.get("documents"):
        return None, [{"kind": "upstream_index_document_map_stale"}]
    hashes = index.get("document_hashes")
    if not isinstance(hashes, dict):
        return None, [{"kind": "upstream_index_hashes_missing"}]
    for stage in WORKFLOW_STAGES:
        relative = workflow["documents"][stage]
        text = read_text_bounded(resolve_inside(root, relative), MAX_INDEX_BYTES)
        current = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        if hashes.get(stage) != current:
            return None, [
                {
                    "kind": "upstream_index_stale",
                    "stage": stage,
                    "path": relative,
                }
            ]
    baseline = verify_protected_sources(root, workflow)
    indexed_baseline = index.get("protected_baseline")
    expected_status = "protected" if baseline is not None else "unprotected"
    if not isinstance(indexed_baseline, dict) or indexed_baseline.get("status") != expected_status:
        return None, [{"kind": "upstream_index_baseline_stale"}]
    if baseline is not None:
        expected_count = sum(
            len(baseline["documents"][stage]["ids"])
            for stage in PROTECTED_PREFIXES
        )
        if indexed_baseline.get("protected_ids") != expected_count:
            return None, [{"kind": "upstream_index_baseline_stale"}]
    rebuilt, rebuild_diagnostic = rebuild_delivery_index(root)
    if rebuilt is None:
        return None, [rebuild_diagnostic or {"kind": "delivery_index_rebuild_failed"}]
    if compact_json(index) != compact_json(rebuilt):
        return None, [{"kind": "upstream_index_derived_content_mismatch"}]
    return rebuilt, []


def current_result(
    root: Path,
    table: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    validate_result_history(root, table, task, state)
    result_ref = state.get("result_ref")
    if not result_ref:
        return None
    path = resolve_inside(root, result_ref)
    _, _, result_dir = table_paths(root, table)
    if path.parent != result_dir:
        raise TaskctlError(f"current task result must be stored in {result_dir}: {path}")
    expected_name = f"{task['id']}.r{state['revision']}.json"
    if path.name != expected_name:
        raise TaskctlError(f"current task result must be named {expected_name}: {path}")
    return validate_result(read_json(path), task)


def task_diagnostics(
    task: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    index: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if not task["source_ids"]:
        diagnostics.append({"kind": "source_ids_empty"})
    if not task["outputs"]:
        diagnostics.append({"kind": "outputs_empty"})
    if not task["verification"]:
        diagnostics.append({"kind": "verification_empty"})
    for dependency in task["dependencies"]:
        dependency_id = dependency["id"]
        if dependency_id not in tasks:
            diagnostics.append(
                {
                    "kind": "unknown_dependency",
                    "dependency_id": dependency_id,
                    "dependency_type": dependency["type"],
                }
            )
            continue
        if states[dependency_id]["status"] != "done":
            diagnostics.append(
                {
                    "kind": f"{dependency['type']}_dependency_incomplete",
                    "dependency_id": dependency_id,
                    "status": states[dependency_id]["status"],
                }
            )
    if index is not None:
        sections: dict[str, list[dict[str, Any]]] = {}
        for section in index.get("sections", []):
            if isinstance(section, dict) and isinstance(section.get("id"), str):
                sections.setdefault(section["id"], []).append(section)
        unresolved = set(index.get("unresolved_ids", []))
        for source_id in task["source_ids"]:
            if source_id not in sections:
                diagnostics.append({"kind": "unknown_source_id", "source_id": source_id})
            elif len(sections[source_id]) > 1:
                diagnostics.append({"kind": "ambiguous_source_id", "source_id": source_id})
            if source_id in unresolved:
                diagnostics.append({"kind": "upstream_unresolved", "source_id": source_id})
        baseline = index.get("protected_baseline", {})
        if baseline.get("status") != "protected":
            diagnostics.append({"kind": "protected_baseline_unconfirmed"})
    return diagnostics


def counts_for(states: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for state in states.values():
        counts[state["status"]] += 1
    return counts


def parse_dependency(raw: str) -> dict[str, Any]:
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise TaskctlError("--dependency must use TASK_ID:type[:consumed-output]")
    dependency_id, dependency_type = parts[0], parts[1]
    consumes = [parts[2]] if len(parts) == 3 and parts[2].strip() else []
    return {"id": dependency_id, "type": dependency_type, "consumes": consumes}


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    root.mkdir(parents=True, exist_ok=True)
    conflicts = [
        relative
        for relative in ("task-table.json", "TASK_TABLE.md")
        if (root / relative).exists()
    ]
    conflicts.extend(
        directory
        for directory in ("tasks", "state", "results")
        if (root / directory).is_dir() and any((root / directory).iterdir())
    )
    if conflicts:
        raise TaskctlError(f"refusing to overwrite existing task workspace: {', '.join(conflicts)}")
    for directory in ("tasks", "state", "results"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    table = {
        "schema": "task.table",
        "id": args.id,
        "title": args.title,
        "task_dir": "tasks",
        "state_dir": "state",
        "result_dir": "results",
        "source_index": ".work-cache/index.json",
        "table_view": "TASK_TABLE.md",
    }
    atomic_write_json(root / "task-table.json", table)
    return {"ok": True, "command": "init", "task_dir": str(root)}


def command_draft(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    load_table(root)
    task = {
        "schema": "task.record",
        "id": args.id,
        "title": args.title,
        "outcome": args.outcome,
        "source_ids": args.source_id,
        "dependencies": [parse_dependency(value) for value in args.dependency],
        "mutation_scope": args.mutation_scope,
        "outputs": args.output,
        "verification": args.verification,
        "suggested_skills": args.suggested_skill,
        "reasoning_hint": args.reasoning_hint,
        "revision": 1,
    }
    normalized = validate_task(task)
    return normalized


def command_add(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    candidate = validate_task(read_json(Path(args.file).expanduser().resolve()))
    if candidate["revision"] != 1:
        raise TaskctlError("a new task must start at revision 1")
    with workspace_lock(root):
        table = load_table(root)
        task_dir, state_dir, _ = table_paths(root, table)
        task_path = task_dir / f"{candidate['id']}.json"
        state_path = state_dir / f"{candidate['id']}.json"
        existing_task = (
            validate_task(read_json(task_path), expected_id=candidate["id"])
            if task_path.exists()
            else None
        )
        initial_state = validate_state(
            {
                "schema": "task.state",
                "task_id": candidate["id"],
                "status": "todo",
                "owner": None,
                "revision": 1,
                "note": "",
                "blocked_reason": "",
                "next_action": "",
                "result_ref": None,
            },
            candidate["id"],
        )
        existing_state = (
            validate_state(read_json(state_path), candidate["id"])
            if state_path.exists()
            else None
        )
        if existing_task is not None and existing_state is not None:
            raise TaskctlError(f"task already exists: {candidate['id']}")
        if existing_task is not None and existing_task != candidate:
            raise TaskctlError(f"conflicting partial task record: {candidate['id']}")
        if existing_state is not None and existing_state != initial_state:
            raise TaskctlError(f"conflicting partial task state: {candidate['id']}")
        tasks = load_tasks(root, table)
        proposed = dict(tasks)
        proposed[candidate["id"]] = candidate
        ensure_acyclic(proposed)
        if existing_task is None:
            atomic_write_json(task_path, candidate)
        if existing_state is None:
            atomic_write_json(state_path, initial_state)
    return {
        "ok": True,
        "command": "add",
        "task_id": candidate["id"],
        "task_revision": 1,
        "state_revision": 1,
        "recovered_partial_write": existing_task is not None or existing_state is not None,
    }


def command_update(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    candidate = validate_task(read_json(Path(args.file).expanduser().resolve()))
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        task_id = candidate["id"]
        if task_id not in tasks:
            raise TaskctlError(f"unknown task: {task_id}")
        current = tasks[task_id]
        if current["revision"] != args.expected_task_revision:
            raise TaskctlError(
                f"task revision conflict: expected {args.expected_task_revision}, "
                f"current {current['revision']}"
            )
        state = load_state(root, table, task_id)
        if state["status"] == "done" or state["result_ref"] is not None:
            raise TaskctlError(
                "reopen the completed task before changing its execution contract"
            )
        if state["owner"] is not None:
            if args.owner is None:
                raise TaskctlError("updating an owned task requires --owner")
            check_owner(state, args.owner)
            if args.expected_state_revision is None:
                raise TaskctlError(
                    "updating an owned task requires --expected-state-revision"
                )
            check_expected_state(state, args.expected_state_revision)
        candidate["revision"] = current["revision"] + 1
        proposed = dict(tasks)
        proposed[task_id] = candidate
        ensure_acyclic(proposed)
        task_dir, _, _ = table_paths(root, table)
        atomic_write_json(task_dir / f"{task_id}.json", candidate)
    return {
        "ok": True,
        "command": "update",
        "task_id": task_id,
        "task_revision": candidate["revision"],
    }


def shrink_value(value: Any, max_string: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "…"
    if isinstance(value, list):
        return [shrink_value(item, max_string) for item in value]
    if isinstance(value, dict):
        return {key: shrink_value(item, max_string) for key, item in value.items()}
    return value


def fit_payload(payload: dict[str, Any], budget: int) -> dict[str, Any]:
    for maximum in (2_000, 1_000, 500, 240, 120):
        candidate = shrink_value(payload, maximum)
        was_shrunk = candidate != payload
        candidate["truncated"] = bool(payload.get("truncated")) or was_shrunk
        if len(compact_json(candidate)) <= budget:
            return candidate
    minimal = {
        "ok": True,
        "command": payload.get("command"),
        "id": payload.get("id") or payload.get("task_id"),
        "snapshot_id": payload.get("snapshot_id"),
        "pagination": payload.get("pagination"),
        "truncated": True,
        "hint": "increase --budget or use show/deps/context with a narrower target",
    }
    if len(compact_json(minimal)) > budget:
        raise TaskctlError("--budget is too small for a minimal response")
    return minimal


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    if args.id not in tasks:
        raise TaskctlError(f"unknown task: {args.id}")
    state = load_state(root, table, args.id)
    result = current_result(root, table, tasks[args.id], state)
    return fit_payload(
        {
            "ok": True,
            "command": "show",
            "id": args.id,
            "task": tasks[args.id],
            "state": state,
            "result": result,
        },
        args.budget,
    )


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    states = load_states(root, table, tasks)
    rows = []
    for task_id in sorted(tasks):
        state = states[task_id]
        if args.status and state["status"] not in args.status:
            continue
        rows.append(
            {
                "id": task_id,
                "title": tasks[task_id]["title"],
                "status": state["status"],
                "owner": state["owner"],
                "task_revision": tasks[task_id]["revision"],
                "state_revision": state["revision"],
            }
        )
    return {
        "ok": True,
        "command": "list",
        "counts": counts_for(states),
        "items": rows[: args.limit],
        "matched_count": len(rows),
        "truncated": len(rows) > args.limit,
    }


def dependency_ids(
    tasks: dict[str, dict[str, Any]], task_id: str, recursive: bool
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    queue = deque(dependency["id"] for dependency in tasks[task_id]["dependencies"])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        if recursive and current in tasks:
            queue.extend(dependency["id"] for dependency in tasks[current]["dependencies"])
    return result


def reverse_graph(tasks: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    reverse = {task_id: [] for task_id in tasks}
    for task_id, task in tasks.items():
        for dependency in task["dependencies"]:
            if dependency["id"] in reverse:
                reverse[dependency["id"]].append(task_id)
    for values in reverse.values():
        values.sort()
    return reverse


def dependent_ids(
    tasks: dict[str, dict[str, Any]], task_id: str, recursive: bool
) -> list[str]:
    reverse = reverse_graph(tasks)
    result: list[str] = []
    seen: set[str] = set()
    queue = deque(reverse[task_id])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        if recursive:
            queue.extend(reverse[current])
    return result


def command_deps(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    if args.id not in tasks:
        raise TaskctlError(f"unknown task: {args.id}")
    states = load_states(root, table, tasks)
    ids = dependency_ids(tasks, args.id, args.recursive)
    items = []
    direct_types = {
        dependency["id"]: dependency["type"] for dependency in tasks[args.id]["dependencies"]
    }
    for dependency_id in ids[: args.limit]:
        if dependency_id in tasks:
            items.append(
                {
                    "id": dependency_id,
                    "title": tasks[dependency_id]["title"],
                    "status": states[dependency_id]["status"],
                    "type": direct_types.get(dependency_id, "transitive"),
                    "result_ref": states[dependency_id]["result_ref"],
                }
            )
        else:
            items.append(
                {
                    "id": dependency_id,
                    "status": "unknown",
                    "type": direct_types.get(dependency_id, "transitive"),
                }
            )
    return {
        "ok": True,
        "command": "deps",
        "id": args.id,
        "items": items,
        "dependency_count": len(ids),
        "truncated": len(ids) > args.limit,
    }


def command_dependents(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    if args.id not in tasks:
        raise TaskctlError(f"unknown task: {args.id}")
    states = load_states(root, table, tasks)
    ids = dependent_ids(tasks, args.id, args.recursive)
    return {
        "ok": True,
        "command": "dependents",
        "id": args.id,
        "items": [
            {
                "id": dependent_id,
                "title": tasks[dependent_id]["title"],
                "status": states[dependent_id]["status"],
            }
            for dependent_id in ids[: args.limit]
        ],
        "dependent_count": len(ids),
        "truncated": len(ids) > args.limit,
    }


def command_next(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    states = load_states(root, table, tasks)
    index, index_diagnostics = maybe_load_index(root, table)
    rows = []
    for task_id, task in tasks.items():
        state = states[task_id]
        if state["status"] == "done":
            continue
        diagnostics = list(index_diagnostics)
        diagnostics.extend(task_diagnostics(task, tasks, states, index))
        if state["owner"] and state["owner"] != args.owner:
            diagnostics.append({"kind": "owned_by_other", "owner": state["owner"]})
        hard_blocked = any(
            item["kind"] in {"hard_dependency_incomplete", "unknown_dependency"}
            and item.get("dependency_type", "hard") == "hard"
            for item in diagnostics
        )
        owned_by_other = any(item["kind"] == "owned_by_other" for item in diagnostics)
        status_blocked = state["status"] == "blocked"
        recommended = not hard_blocked and not owned_by_other and not status_blocked
        if not recommended and not args.include_blocked:
            continue
        status_rank = {
            "in_progress": 0,
            "review": 1,
            "claimed": 2,
            "todo": 3,
            "blocked": 4,
        }[state["status"]]
        owner_rank = 0 if args.owner and state["owner"] == args.owner else 1
        rows.append(
            (
                (0 if recommended else 1, owner_rank, status_rank, task_id),
                {
                    "id": task_id,
                    "title": task["title"],
                    "status": state["status"],
                    "owner": state["owner"],
                    "recommended": recommended,
                    "diagnostics": diagnostics[: args.diagnostic_limit],
                },
            )
        )
    rows.sort(key=lambda row: row[0])
    items = [row[1] for row in rows[: args.limit]]
    return {
        "ok": True,
        "command": "next",
        "items": items,
        "candidate_count": len(rows),
        "recommended_count": sum(row[1]["recommended"] for row in rows),
        "truncated": len(rows) > args.limit,
        "note": "recommendation is advisory and does not grant or deny execution",
    }


def select_upstream_context(
    index: dict[str, Any] | None, source_ids: list[str], maximum: int
) -> tuple[list[dict[str, Any]], bool]:
    if index is None:
        return [], False
    by_id: dict[str, dict[str, Any]] = {}
    for section in index.get("sections", []):
        if isinstance(section, dict) and isinstance(section.get("id"), str):
            by_id.setdefault(section["id"], section)
    selected: list[str] = []
    seen: set[str] = set()
    queue = deque(source_ids)
    while queue and len(selected) < maximum:
        current = queue.popleft()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        selected.append(current)
        queue.extend(by_id[current].get("references", []))
    rows = [
        {
            "id": by_id[section_id].get("id"),
            "title": by_id[section_id].get("title"),
            "stage": by_id[section_id].get("stage"),
            "document": by_id[section_id].get("document"),
            "line": by_id[section_id].get("line"),
            "status": by_id[section_id].get("status"),
            "references": by_id[section_id].get("references", []),
            "body": by_id[section_id].get("body", ""),
        }
        for section_id in selected
    ]
    return rows, bool(queue)


def command_context(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    if args.id not in tasks:
        raise TaskctlError(f"unknown task: {args.id}")
    states = load_states(root, table, tasks)
    index, index_diagnostics = maybe_load_index(root, table)
    task = tasks[args.id]
    dependency_context = []
    for dependency in task["dependencies"]:
        dependency_id = dependency["id"]
        if dependency_id not in tasks:
            dependency_context.append(
                {
                    "id": dependency_id,
                    "type": dependency["type"],
                    "status": "unknown",
                    "consumes": dependency["consumes"],
                }
            )
            continue
        dependency_state = states[dependency_id]
        dependency_context.append(
            {
                "id": dependency_id,
                "type": dependency["type"],
                "status": dependency_state["status"],
                "consumes": dependency["consumes"],
                "result": current_result(
                    root, table, tasks[dependency_id], dependency_state
                ),
            }
        )
    reverse = reverse_graph(tasks)
    all_dependents = reverse[args.id]
    dependents = [
        {
            "id": dependent_id,
            "title": tasks[dependent_id]["title"],
            "status": states[dependent_id]["status"],
        }
        for dependent_id in all_dependents[: args.max_items]
    ]
    all_diagnostics = index_diagnostics + task_diagnostics(task, tasks, states, index)
    upstream, upstream_truncated = select_upstream_context(
        index, task["source_ids"], args.max_items
    )
    truncation = {
        "diagnostics": len(all_diagnostics) > args.max_items,
        "upstream": upstream_truncated,
        "dependents": len(all_dependents) > args.max_items,
    }
    payload = {
        "ok": True,
        "command": "context",
        "id": args.id,
        "task": task,
        "state": states[args.id],
        "diagnostics": all_diagnostics[: args.max_items],
        "protected_baseline": index.get("protected_baseline") if index else None,
        "upstream": upstream,
        "dependencies": dependency_context,
        "dependents": dependents,
        "truncation": truncation,
        "truncated": any(truncation.values()),
    }
    return fit_payload(payload, args.budget)


def semantic_downstream_ids(index: dict[str, Any], source_id: str) -> set[str]:
    reverse = index.get("reverse_references", {})
    seen = {source_id}
    queue = deque([source_id])
    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, []):
            if (
                isinstance(dependent, str)
                and not dependent.startswith("DCR-")
                and dependent not in seen
            ):
                seen.add(dependent)
                queue.append(dependent)
    return seen


def command_completion_context(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        return completion_context_locked(args, root)


def completion_context_locked(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    table = load_table(root)
    tasks = load_tasks(root, table)
    states = load_states(root, table, tasks)
    baseline = verify_protected_sources(root)
    index, index_diagnostics = maybe_load_index(root, table)
    if baseline is None or index is None:
        diagnostics = list(index_diagnostics)
        if baseline is None:
            diagnostics.append({"kind": "protected_baseline_unconfirmed"})
        return {
            "ok": True,
            "command": "completion-context",
            "protected_baseline": (
                None
                if baseline is None
                else {
                    "status": "protected",
                    "protected_ids": sum(
                        len(baseline["documents"][stage]["ids"])
                        for stage in PROTECTED_PREFIXES
                    ),
                }
            ),
            "targets": [],
            "diagnostics": diagnostics,
            "note": "no final judgment is produced",
        }
    current_results = {
        task_id: current_result(root, table, tasks[task_id], states[task_id])
        for task_id in sorted(tasks)
    }
    snapshot_id = "sha256:" + hashlib.sha256(
        compact_json(
            {
                "workflow_id": index.get("workflow_id"),
                "index": index,
                "tasks": tasks,
                "states": states,
                "current_results": current_results,
            }
        ).encode("utf-8")
    ).hexdigest()
    if args.snapshot_id is not None and args.snapshot_id != snapshot_id:
        raise TaskctlError(
            "completion snapshot changed; restart final review from the first page"
        )
    sections = [section for section in index.get("sections", []) if isinstance(section, dict)]
    section_rows: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        section_id = section.get("id")
        if isinstance(section_id, str):
            section_rows.setdefault(section_id, []).append(section)
    baseline_requirement_ids = baseline["documents"]["requirements"]["ids"]
    baseline_user_design_ids = baseline["documents"]["user_design"]["ids"]
    all_target_ids = sorted(
        value
        for value in [*baseline_requirement_ids, *baseline_user_design_ids]
        if value.split("-", 1)[0] in {"REQ", "AC", "UDES"}
    )
    constraint_ids = sorted(
        value
        for value in baseline_requirement_ids
        if value.split("-", 1)[0] == "CON"
    )
    if args.target_id:
        if args.target_id not in all_target_ids:
            raise TaskctlError(f"unknown protected completion target: {args.target_id}")
        filtered_target_ids = [args.target_id]
    else:
        filtered_target_ids = all_target_ids
        if args.after_id:
            filtered_target_ids = [
                target_id for target_id in filtered_target_ids if target_id > args.after_id
            ]
    page_ids = filtered_target_ids[: args.limit]
    diagnostics = list(index_diagnostics)
    target_rows: list[dict[str, Any]] = []
    candidate_next_after_ids: dict[str, str | None] = {}
    for target_id in page_ids:
        definitions = section_rows.get(target_id, [])
        section = definitions[0] if len(definitions) == 1 else {}
        if not definitions:
            diagnostics.append({"kind": "protected_target_missing_from_index", "id": target_id})
        elif len(definitions) > 1:
            diagnostics.append({"kind": "protected_target_ambiguous", "id": target_id})
        semantic_ids = semantic_downstream_ids(index, target_id)
        all_linked_tasks = []
        for task_id in sorted(tasks):
            task = tasks[task_id]
            if not semantic_ids.intersection(task["source_ids"]):
                continue
            state = states[task_id]
            result = current_results[task_id]
            all_linked_tasks.append(
                {
                    "id": task_id,
                    "status": state["status"],
                    "task_revision": task["revision"],
                    "result_ref": state["result_ref"],
                    "result_outcome": result.get("outcome") if result else None,
                    "outputs": result.get("outputs", []) if result else [],
                    "verification": result.get("verification", []) if result else [],
                    "unresolved": result.get("unresolved", []) if result else [],
                    "invalidated_source_ids": (
                        result.get("invalidated_source_ids", []) if result else []
                    ),
                }
            )
        candidate_page = all_linked_tasks
        if args.candidate_after_id:
            candidate_page = [
                row for row in candidate_page if row["id"] > args.candidate_after_id
            ]
        linked_tasks = candidate_page[: args.max_items]
        candidate_more = len(candidate_page) > len(linked_tasks)
        candidate_next_after_ids[target_id] = (
            linked_tasks[-1]["id"] if candidate_more and linked_tasks else None
        )
        target_rows.append(
            {
                "id": target_id,
                "title": section.get("title"),
                "document": section.get("document"),
                "line": section.get("line"),
                "status": section.get("status"),
                "body": section.get("body", ""),
                "candidate_tasks": linked_tasks,
                "candidate_task_count": len(all_linked_tasks),
                "returned_candidate_task_count": len(linked_tasks),
                "candidate_tasks_truncated": candidate_more,
                "candidate_next_after_id": candidate_next_after_ids[target_id],
                "candidate_result_count": sum(
                    linked_task["result_ref"] is not None
                    for linked_task in all_linked_tasks
                ),
                "candidate_result_with_verification_count": sum(
                    bool(linked_task["verification"])
                    for linked_task in all_linked_tasks
                ),
            }
        )
    deferred_ids = sorted(
        value
        for value in index.get("deferred_change_ids", [])
        if isinstance(value, str)
    )
    constraint_page_ids = [
        value for value in constraint_ids if not args.constraint_after_id or value > args.constraint_after_id
    ]
    constraint_page_ids = constraint_page_ids[: args.max_items]
    deferred_page_ids = [
        value for value in deferred_ids if not args.deferred_after_id or value > args.deferred_after_id
    ]
    deferred_page_ids = deferred_page_ids[: args.max_items]

    def section_summary(section_id: str) -> dict[str, Any]:
        definitions = section_rows.get(section_id, [])
        section = definitions[0] if len(definitions) == 1 else {}
        if not definitions:
            diagnostics.append({"kind": "semantic_section_missing", "id": section_id})
        elif len(definitions) > 1:
            diagnostics.append({"kind": "semantic_section_ambiguous", "id": section_id})
        return {
            "id": section_id,
            "title": section.get("title"),
            "document": section.get("document"),
            "line": section.get("line"),
            "body": section.get("body", ""),
        }

    target_more = len(filtered_target_ids) > len(target_rows)
    constraint_remaining = [
        value for value in constraint_ids if not args.constraint_after_id or value > args.constraint_after_id
    ]
    deferred_remaining = [
        value for value in deferred_ids if not args.deferred_after_id or value > args.deferred_after_id
    ]
    pagination = {
        "target_next_after_id": (
            target_rows[-1]["id"] if target_more and target_rows else None
        ),
        "constraint_next_after_id": (
            constraint_page_ids[-1]
            if len(constraint_remaining) > len(constraint_page_ids) and constraint_page_ids
            else None
        ),
        "deferred_next_after_id": (
            deferred_page_ids[-1]
            if len(deferred_remaining) > len(deferred_page_ids) and deferred_page_ids
            else None
        ),
        "candidate_next_after_ids": candidate_next_after_ids,
    }
    payload = {
        "ok": True,
        "command": "completion-context",
        "snapshot_id": snapshot_id,
        "protected_baseline": index.get("protected_baseline"),
        "target_count": len(all_target_ids),
        "returned_target_count": len(target_rows),
        "targets": target_rows,
        "constraint_count": len(constraint_ids),
        "returned_constraint_count": len(constraint_page_ids),
        "constraints": [section_summary(value) for value in constraint_page_ids],
        "open_deferred_change_count": len(deferred_ids),
        "returned_open_deferred_change_count": len(deferred_page_ids),
        "open_deferred_changes": [section_summary(value) for value in deferred_page_ids],
        "pagination": pagination,
        "diagnostics": diagnostics,
        "note": (
            "candidate links and results are inputs to model review; no final pass or fail is produced"
        ),
    }
    while len(compact_json(shrink_value(payload, 500))) > args.budget and len(target_rows) > 1:
        target_rows.pop()
        payload["returned_target_count"] = len(target_rows)
        payload["pagination"]["target_next_after_id"] = (
            target_rows[-1]["id"] if target_rows else args.after_id
        )
        payload["pagination"]["candidate_next_after_ids"] = {
            row["id"]: row["candidate_next_after_id"] for row in target_rows
        }
    return fit_payload(payload, args.budget)


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    states = load_states(root, table, tasks)
    index, index_diagnostics = maybe_load_index(root, table)
    result_count = 0
    result_with_verification_count = 0
    result_with_unresolved_count = 0
    invalidated_source_ids: set[str] = set()
    dependency_blocked_count = 0
    diagnostic_count = len(index_diagnostics)
    for task_id, task in tasks.items():
        diagnostics = task_diagnostics(task, tasks, states, index)
        diagnostic_count += len(diagnostics)
        if any(
            item["kind"] == "hard_dependency_incomplete"
            or (
                item["kind"] == "unknown_dependency"
                and item.get("dependency_type") == "hard"
            )
            for item in diagnostics
        ):
            dependency_blocked_count += 1
        result = current_result(root, table, task, states[task_id])
        if result is None:
            continue
        result_count += 1
        if result.get("verification"):
            result_with_verification_count += 1
        if result.get("unresolved"):
            result_with_unresolved_count += 1
        invalidated_source_ids.update(result.get("invalidated_source_ids", []))
    semantic_summary = index.get("summary", {}) if index else {}
    return {
        "ok": True,
        "command": "status",
        "task_count": len(tasks),
        "status_counts": counts_for(states),
        "needs_review_count": counts_for(states)["review"],
        "dependency_attention_count": dependency_blocked_count,
        "upstream": {
            "protected_baseline": index.get("protected_baseline") if index else None,
            "unresolved_count": semantic_summary.get("unresolved_count"),
            "deferred_change_count": semantic_summary.get("deferred_change_count", 0),
            "invalidated_source_ids": sorted(invalidated_source_ids)[: args.limit],
        },
        "results": {
            "current_result_count": result_count,
            "result_with_verification_count": result_with_verification_count,
            "result_with_unresolved_count": result_with_unresolved_count,
        },
        "diagnostic_count": diagnostic_count,
        "index_diagnostics": index_diagnostics,
    }


def scope_descriptor(scope: str) -> tuple[str, str, bool]:
    normalized = scope.replace("\\", "/").strip("/")
    positions = [normalized.find(token) for token in ("*", "?", "[") if token in normalized]
    has_glob = bool(positions)
    prefix = normalized[: min(positions)] if positions else normalized
    return normalized, prefix.rstrip("/"), has_glob


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    for left_scope in left:
        left_value, left_prefix, left_glob = scope_descriptor(left_scope)
        for right_scope in right:
            right_value, right_prefix, right_glob = scope_descriptor(right_scope)
            if not left_prefix or not right_prefix:
                return True
            if not left_glob and not right_glob:
                if (
                    left_prefix == right_prefix
                    or left_prefix.startswith(right_prefix + "/")
                    or right_prefix.startswith(left_prefix + "/")
                ):
                    return True
                continue
            if left_glob and fnmatch.fnmatchcase(right_value, left_value):
                return True
            if right_glob and fnmatch.fnmatchcase(left_value, right_value):
                return True
            if (
                left_prefix.startswith(right_prefix)
                or right_prefix.startswith(left_prefix)
            ):
                return True
    return False


def mutation_overlap_warnings(
    task_id: str,
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings = []
    for other_id, other_state in states.items():
        if other_id == task_id or other_state["status"] not in ACTIVE_STATUSES:
            continue
        if scopes_overlap(tasks[task_id]["mutation_scope"], tasks[other_id]["mutation_scope"]):
            warnings.append(
                {
                    "kind": "mutation_overlap",
                    "task_id": other_id,
                    "owner": other_state["owner"],
                    "status": other_state["status"],
                }
            )
    return warnings


def check_expected_state(state: dict[str, Any], expected: int | None) -> None:
    if expected is not None and state["revision"] != expected:
        raise TaskctlError(
            f"state revision conflict: expected {expected}, current {state['revision']}"
        )


def check_owner(state: dict[str, Any], owner: str) -> None:
    if state["owner"] is not None and state["owner"] != owner:
        raise TaskctlError(f"task is owned by {state['owner']}")


def write_state(
    root: Path, table: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    _, state_dir, _ = table_paths(root, table)
    state["revision"] += 1
    normalized = validate_state(state, state["task_id"])
    atomic_write_json(state_dir / f"{state['task_id']}.json", normalized)
    return normalized


def command_claim(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        states = load_states(root, table, tasks)
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        if state["status"] == "done":
            raise TaskctlError("a completed task must be reopened before it can be claimed")
        check_owner(state, args.owner)
        state["owner"] = args.owner
        if state["status"] == "todo":
            state["status"] = "claimed"
        state = write_state(root, table, state)
        warnings = mutation_overlap_warnings(args.id, tasks, {**states, args.id: state})
    return {
        "ok": True,
        "command": "claim",
        "id": args.id,
        "state": state,
        "warnings": warnings,
    }


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        states = load_states(root, table, tasks)
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        if state["status"] == "done":
            raise TaskctlError("a completed task must be reopened before it can start")
        check_owner(state, args.owner)
        state["owner"] = args.owner
        state["status"] = "in_progress"
        state["blocked_reason"] = ""
        state = write_state(root, table, state)
        warnings = mutation_overlap_warnings(args.id, tasks, {**states, args.id: state})
    return {
        "ok": True,
        "command": "start",
        "id": args.id,
        "state": state,
        "warnings": warnings,
    }


def command_note(args: argparse.Namespace) -> dict[str, Any]:
    if not any((args.message, args.status, args.blocked_reason, args.next_action)):
        raise TaskctlError("note requires a message, status, blocked reason, or next action")
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        state = load_state(root, table, args.id)
        check_expected_state(state, args.expected_state_revision)
        if state["status"] == "done":
            raise TaskctlError("a completed task must be reopened before adding execution notes")
        check_owner(state, args.owner)
        if state["owner"] is None:
            state["owner"] = args.owner
        if state["status"] == "todo" and args.status is None:
            state["status"] = "claimed"
        if args.status:
            state["status"] = args.status
        if args.message is not None:
            state["note"] = require_string(args.message, "note.message", allow_empty=True)
        if args.blocked_reason is not None:
            state["blocked_reason"] = require_string(
                args.blocked_reason, "note.blocked_reason", allow_empty=True
            )
        if args.next_action is not None:
            state["next_action"] = require_string(
                args.next_action, "note.next_action", allow_empty=True
            )
        if state["status"] != "blocked" and args.blocked_reason is None:
            state["blocked_reason"] = ""
        state = write_state(root, table, state)
    return {"ok": True, "command": "note", "id": args.id, "state": state}


def command_complete(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    raw_result = read_json(Path(args.result_file).expanduser().resolve())
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        states = load_states(root, table, tasks)
        task = tasks[args.id]
        result = validate_result(raw_result, task)
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        if state["status"] == "done":
            raise TaskctlError("task is already complete")
        check_owner(state, args.owner)
        state["owner"] = args.owner
        _, _, result_dir = table_paths(root, table)
        next_state_revision = state["revision"] + 1
        filename = f"{args.id}.r{next_state_revision}.json"
        result_path = result_dir / filename
        relative_ref = result_path.relative_to(root).as_posix()
        next_state = dict(state)
        next_state["revision"] = next_state_revision
        next_state["status"] = "done"
        next_state["result_ref"] = relative_ref
        next_state["blocked_reason"] = ""
        next_state["next_action"] = ""
        next_state = validate_state(next_state, args.id)
        recovered_partial_write = result_path.exists()
        if recovered_partial_write:
            existing_result = validate_result(read_json(result_path), task)
            if existing_result != result:
                raise TaskctlError(f"conflicting partial result: {result_path}")
        else:
            atomic_write_json(result_path, result)
        _, state_dir, _ = table_paths(root, table)
        atomic_write_json(state_dir / f"{args.id}.json", next_state)
        state = next_state
        states = {**states, args.id: state}
        index, _ = maybe_load_index(root, table)
        diagnostics = task_diagnostics(task, tasks, states, index)
        if not result["verification"]:
            diagnostics.append({"kind": "result_verification_empty"})
        if result["unresolved"]:
            diagnostics.append(
                {"kind": "result_has_unresolved", "count": len(result["unresolved"])}
            )
    return {
        "ok": True,
        "command": "complete",
        "id": args.id,
        "state": state,
        "result_ref": relative_ref,
        "recovered_partial_write": recovered_partial_write,
        "diagnostics": diagnostics[: args.diagnostic_limit],
        "note": "completion records the model-provided result; it is not a product audit",
    }


def command_reopen(args: argparse.Namespace) -> dict[str, Any]:
    reason = require_string(args.reason, "reopen.reason")
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        state = load_state(root, table, args.id)
        check_expected_state(state, args.expected_state_revision)
        if state["status"] != "done":
            raise TaskctlError("only a completed task can be reopened")
        check_owner(state, args.owner)
        state["status"] = "todo"
        state["owner"] = None
        state["note"] = f"reopened: {reason}"
        state["blocked_reason"] = ""
        state["next_action"] = ""
        state["result_ref"] = None
        state = write_state(root, table, state)
    return {"ok": True, "command": "reopen", "id": args.id, "state": state}


def command_release(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks = load_tasks(root, table)
        if args.id not in tasks:
            raise TaskctlError(f"unknown task: {args.id}")
        state = load_state(root, table, args.id)
        check_expected_state(state, args.expected_state_revision)
        if state["status"] == "done":
            raise TaskctlError("a completed task cannot be released")
        check_owner(state, args.owner)
        state["status"] = "todo"
        state["owner"] = None
        state["blocked_reason"] = ""
        state = write_state(root, table, state)
    return {"ok": True, "command": "release", "id": args.id, "state": state}


def command_impact(args: argparse.Namespace) -> dict[str, Any]:
    args.recursive = True
    result = command_dependents(args)
    result["command"] = "impact"
    result["note"] = "dependents require model review and are not automatically invalid"
    return result


def markdown_cell(value: Any, maximum: int = 120) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= maximum else text[:maximum] + "…"


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks = load_tasks(root, table)
    states = load_states(root, table, tasks)
    index, _ = maybe_load_index(root, table)
    output_path = resolve_inside(root, str(table.get("table_view", "TASK_TABLE.md")))
    counts = counts_for(states)
    lines = [
        f"# {table.get('title') or table.get('id') or 'Tasks'}",
        "",
        "> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。",
        "",
        "## 状态统计",
        "",
        "| 状态 | 数量 |",
        "| --- | ---: |",
    ]
    for status in STATUSES:
        lines.append(f"| {status} | {counts[status]} |")
    if index is not None:
        summary = index.get("summary", {})
        lines.extend(
            [
                "",
                "## 上游状态",
                "",
                f"- 受保护基线：{index.get('protected_baseline', {}).get('status')}",
                f"- 可修订上游未决：{summary.get('unresolved_count')}",
                f"- 未解决延后讨论项：{summary.get('deferred_change_count', 0)}",
            ]
        )
    lines.extend(
        [
            "",
            "## 任务",
            "",
            "| ID | 状态 | Owner | 标题 | 依赖 | 结果 | 合同修订 |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for task_id in sorted(tasks):
        task = tasks[task_id]
        state = states[task_id]
        dependencies = ", ".join(
            f"{dependency['id']}:{dependency['type']}" for dependency in task["dependencies"]
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(task_id),
                    markdown_cell(state["status"]),
                    markdown_cell(state["owner"] or ""),
                    markdown_cell(task["title"]),
                    markdown_cell(dependencies),
                    markdown_cell(state["result_ref"] or ""),
                    str(task["revision"]),
                ]
            )
            + " |"
        )
    atomic_write_text(output_path, "\n".join(lines) + "\n")
    return {
        "ok": True,
        "command": "render",
        "output": str(output_path),
        "task_count": len(tasks),
        "status_counts": counts,
    }


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--pretty", action="store_true")


def add_limit(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)


def add_state_revision(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-state-revision", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    add_common(init_parser)
    init_parser.add_argument("--id", required=True)
    init_parser.add_argument("--title", required=True)
    init_parser.set_defaults(handler=command_init)

    draft_parser = subparsers.add_parser("draft")
    add_common(draft_parser)
    draft_parser.add_argument("--id", required=True)
    draft_parser.add_argument("--title", required=True)
    draft_parser.add_argument("--outcome", required=True)
    draft_parser.add_argument("--source-id", action="append", default=[])
    draft_parser.add_argument("--dependency", action="append", default=[])
    draft_parser.add_argument("--mutation-scope", action="append", default=[])
    draft_parser.add_argument("--output", action="append", default=[])
    draft_parser.add_argument("--verification", action="append", default=[])
    draft_parser.add_argument("--suggested-skill", action="append", default=[])
    draft_parser.add_argument("--reasoning-hint", choices=REASONING_HINTS)
    draft_parser.set_defaults(handler=command_draft)

    add_parser = subparsers.add_parser("add")
    add_common(add_parser)
    add_parser.add_argument("--file", required=True)
    add_parser.set_defaults(handler=command_add)

    update_parser = subparsers.add_parser("update")
    add_common(update_parser)
    update_parser.add_argument("--file", required=True)
    update_parser.add_argument("--owner")
    update_parser.add_argument("--expected-task-revision", type=int, required=True)
    add_state_revision(update_parser)
    update_parser.set_defaults(handler=command_update)

    show_parser = subparsers.add_parser("show")
    add_common(show_parser)
    show_parser.add_argument("--id", required=True)
    show_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    show_parser.set_defaults(handler=command_show)

    list_parser = subparsers.add_parser("list")
    add_common(list_parser)
    add_limit(list_parser)
    list_parser.add_argument("--status", action="append", choices=STATUSES)
    list_parser.set_defaults(handler=command_list)

    deps_parser = subparsers.add_parser("deps")
    add_common(deps_parser)
    add_limit(deps_parser)
    deps_parser.add_argument("--id", required=True)
    deps_parser.add_argument("--recursive", action="store_true")
    deps_parser.set_defaults(handler=command_deps)

    dependents_parser = subparsers.add_parser("dependents")
    add_common(dependents_parser)
    add_limit(dependents_parser)
    dependents_parser.add_argument("--id", required=True)
    dependents_parser.add_argument("--recursive", action="store_true")
    dependents_parser.set_defaults(handler=command_dependents)

    next_parser = subparsers.add_parser("next")
    add_common(next_parser)
    add_limit(next_parser)
    next_parser.add_argument("--owner")
    next_parser.add_argument("--include-blocked", action="store_true")
    next_parser.add_argument("--diagnostic-limit", type=int, default=10)
    next_parser.set_defaults(handler=command_next)

    context_parser = subparsers.add_parser("context")
    add_common(context_parser)
    context_parser.add_argument("--id", required=True)
    context_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    context_parser.add_argument("--max-items", type=int, default=DEFAULT_LIMIT)
    context_parser.set_defaults(handler=command_context)

    completion_parser = subparsers.add_parser("completion-context")
    add_common(completion_parser)
    add_limit(completion_parser)
    completion_parser.add_argument("--after-id")
    completion_parser.add_argument("--target-id")
    completion_parser.add_argument("--candidate-after-id")
    completion_parser.add_argument("--constraint-after-id")
    completion_parser.add_argument("--deferred-after-id")
    completion_parser.add_argument("--snapshot-id")
    completion_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    completion_parser.add_argument("--max-items", type=int, default=DEFAULT_LIMIT)
    completion_parser.set_defaults(handler=command_completion_context)

    status_parser = subparsers.add_parser("status")
    add_common(status_parser)
    add_limit(status_parser)
    status_parser.set_defaults(handler=command_status)

    claim_parser = subparsers.add_parser("claim")
    add_common(claim_parser)
    claim_parser.add_argument("--id", required=True)
    claim_parser.add_argument("--owner", required=True)
    add_state_revision(claim_parser)
    claim_parser.set_defaults(handler=command_claim)

    start_parser = subparsers.add_parser("start")
    add_common(start_parser)
    start_parser.add_argument("--id", required=True)
    start_parser.add_argument("--owner", required=True)
    add_state_revision(start_parser)
    start_parser.set_defaults(handler=command_start)

    note_parser = subparsers.add_parser("note")
    add_common(note_parser)
    note_parser.add_argument("--id", required=True)
    note_parser.add_argument("--owner", required=True)
    note_parser.add_argument("--message")
    note_parser.add_argument("--status", choices=ACTIVE_STATUS_CHOICES)
    note_parser.add_argument("--blocked-reason")
    note_parser.add_argument("--next-action")
    add_state_revision(note_parser)
    note_parser.set_defaults(handler=command_note)

    complete_parser = subparsers.add_parser("complete")
    add_common(complete_parser)
    complete_parser.add_argument("--id", required=True)
    complete_parser.add_argument("--owner", required=True)
    complete_parser.add_argument("--result-file", required=True)
    complete_parser.add_argument("--diagnostic-limit", type=int, default=20)
    add_state_revision(complete_parser)
    complete_parser.set_defaults(handler=command_complete)

    reopen_parser = subparsers.add_parser("reopen")
    add_common(reopen_parser)
    reopen_parser.add_argument("--id", required=True)
    reopen_parser.add_argument("--owner", required=True)
    reopen_parser.add_argument("--reason", required=True)
    add_state_revision(reopen_parser)
    reopen_parser.set_defaults(handler=command_reopen)

    release_parser = subparsers.add_parser("release")
    add_common(release_parser)
    release_parser.add_argument("--id", required=True)
    release_parser.add_argument("--owner", required=True)
    add_state_revision(release_parser)
    release_parser.set_defaults(handler=command_release)

    impact_parser = subparsers.add_parser("impact")
    add_common(impact_parser)
    add_limit(impact_parser)
    impact_parser.add_argument("--id", required=True)
    impact_parser.set_defaults(handler=command_impact)

    render_parser = subparsers.add_parser("render")
    add_common(render_parser)
    render_parser.set_defaults(handler=command_render)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    for name in ("limit", "max_items", "diagnostic_limit"):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None and not 1 <= value <= 1_000:
                raise TaskctlError(f"--{name.replace('_', '-')} must be between 1 and 1000")
    if hasattr(args, "budget") and not 1_000 <= args.budget <= 100_000:
        raise TaskctlError("--budget must be between 1000 and 100000")
    if hasattr(args, "expected_state_revision"):
        value = args.expected_state_revision
        if value is not None and value < 1:
            raise TaskctlError("--expected-state-revision must be positive")
    if (
        getattr(args, "command", None) == "completion-context"
        and args.target_id
        and args.after_id
    ):
        raise TaskctlError("--target-id and --after-id cannot be combined")
    if (
        getattr(args, "command", None) == "completion-context"
        and args.candidate_after_id
        and not args.target_id
    ):
        raise TaskctlError("--candidate-after-id requires --target-id")
    if getattr(args, "command", None) == "completion-context":
        has_cursor = any(
            value
            for value in (
                args.after_id,
                args.candidate_after_id,
                args.constraint_after_id,
                args.deferred_after_id,
            )
        )
        if has_cursor and not args.snapshot_id:
            raise TaskctlError("completion pagination requires --snapshot-id")
    if hasattr(args, "expected_task_revision") and args.expected_task_revision < 1:
        raise TaskctlError("--expected-task-revision must be positive")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
        result = args.handler(args)
        emit(result, pretty=args.pretty)
        return 0
    except TaskctlError as exc:
        emit({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
