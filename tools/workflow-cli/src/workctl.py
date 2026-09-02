#!/usr/bin/env python3
"""Index and query delivery workflow artifacts without judging their semantics."""

from __future__ import annotations

import argparse
import copy
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


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 20_000
DEFAULT_MAX_ITEMS = 50
DEFAULT_MODEL_TOKEN_BUDGET = 2_048
WORKFLOW_CLI_VERSION = (
    Path(__file__).resolve().parents[1] / "VERSION"
).read_text(encoding="utf-8").strip()
MAX_MANIFEST_TEXT = 2_000
ID_PATTERN = r"(?:REQ|AC|CON|UDES|DEC|DES|OBS|GAP|SOL|DCR)-[A-Za-z0-9][A-Za-z0-9._-]*"
ID_RE = re.compile(rf"\b({ID_PATTERN})\b")
HEADING_RE = re.compile(rf"^##\s+(?P<id>{ID_PATTERN})(?:\s+(?P<title>.*?))?\s*$")
STATUS_RE = re.compile(r"^\s*-\s*状态\s*[:：]\s*(?P<status>[^\s,，;；]+)", re.IGNORECASE)
REFERENCE_FIELD_RE = re.compile(
    r"^\s*-\s*(?:关联|关联需求|关联目标|满足|解决|依赖|后继证据|目标ID|"
    r"references?|satisfies|solves|depends(?:\s+on)?|superseded\s+by|target\s+ids?)"
    r"\s*[:：]\s*(?P<value>.*)$",
    re.IGNORECASE,
)
UNRESOLVED_STATUSES = {"open", "unknown", "unresolved", "deferred", "待决", "未知", "延后"}
DCR_STATUSES = {"deferred", "discussed", "resolved", "withdrawn"}
STAGE_PREFIXES = {
    "requirements": {"REQ", "AC", "CON"},
    "user_design": {"UDES"},
    "design": {"DES", "DEC"},
    "current_state": {"OBS", "GAP", "DEC"},
    "solution": {"SOL", "DEC"},
    "deferred_changes": {"DCR"},
}
DEFAULT_DOCUMENTS = {
    "requirements": "requirements.md",
    "user_design": "user-design.md",
    "design": "design.md",
    "current_state": "current-state.md",
    "solution": "solution.md",
    "deferred_changes": "deferred-changes.md",
}
PUBLIC_STAGES = {stage.replace("_", "-"): stage for stage in STAGE_PREFIXES}
PROTECTED_STAGES = ("requirements", "user_design")


class WorkctlError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        gate_id: str = "WORK-INPUT-UNREADABLE",
        risk: str = "the current command cannot safely interpret a required input",
        scope: str = "current command",
        recovery: str = "repair or narrow the reported input, then retry the command",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.gate = {
            "id": gate_id,
            "risk": risk,
            "scope": scope,
            "recovery": recovery,
            "retryable": retryable,
        }

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "error": str(self), "gate": self.gate}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        error = WorkctlError(
            f"argument error: {message}",
            recovery="correct the command arguments and retry",
            retryable=True,
        )
        emit(error.payload(), view=requested_view(), stream=sys.stderr)
        raise SystemExit(2)


def normalize_manifest_text(value: Any, field: str, *, writing: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkctlError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise WorkctlError(f"{field} must not be empty")
    if len(cleaned) > MAX_MANIFEST_TEXT:
        raise WorkctlError(
            f"{field} exceeds {MAX_MANIFEST_TEXT} characters",
            gate_id="WORK-LIMIT",
            risk="the command cannot keep manifest input bounded",
            recovery="shorten the manifest identity before retrying",
        )
    if not writing and value != cleaned:
        raise WorkctlError(f"{field} must not contain surrounding whitespace")
    return cleaned


def semantic_text(value: Any, field: str) -> str:
    """Preserve semantic metadata; only unreadable types and resource bounds are gates."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WorkctlError(f"{field} must be a string")
    if len(value) > MAX_MANIFEST_TEXT:
        raise WorkctlError(
            f"{field} exceeds {MAX_MANIFEST_TEXT} characters",
            gate_id="WORK-LIMIT",
            risk="the command cannot keep structured input and output bounded",
            recovery="shorten the semantic metadata before retrying",
        )
    return value


def semantic_text_diagnostics(value: str, field: str) -> list[dict[str, Any]]:
    if not value.strip():
        return [{"kind": "semantic_text_empty", "field": field}]
    if value != value.strip():
        return [
            {"kind": "semantic_text_surrounding_whitespace", "field": field}
        ]
    return []


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def requested_view(argv: list[str] | None = None) -> str:
    arguments = sys.argv[1:] if argv is None else argv
    for index, argument in enumerate(arguments):
        if argument == "--view" and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith("--view="):
            return argument.split("=", 1)[1]
    return "model"


def model_text_cost(text: str) -> int:
    total = 0
    ascii_word = 0
    for character in text:
        if character.isascii() and (character.isalnum() or character == "_"):
            ascii_word += 1
            continue
        if ascii_word:
            total += (ascii_word + 3) // 4
            ascii_word = 0
        if character == "\n" or not character.isspace():
            total += 1
    return total + (ascii_word + 3) // 4


def model_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    reserved = {"null", "true", "false", "yes", "no", "on", "off", "~"}
    unsafe_start = "-?:,[]{}#&*!|>'\"%@`"
    if (
        text
        and text == text.strip()
        and "\n" not in text
        and not text.startswith(tuple(unsafe_start))
        and not any(character in text for character in "{}[],:#\"")
        and text.lower() not in reserved
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


def compact_model(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{key}:{compact_model(item)}" for key, item in value.items()
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(compact_model(item) for item in value) + "]"
    return model_scalar(value)


def render_model_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            compact = compact_model(item)
            if len(compact) <= 800:
                lines.append(f"{prefix}{key}:{compact}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(render_model_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}:{model_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            compact = compact_model(item)
            if len(compact) <= 2_400:
                lines.append(f"{prefix}- {compact}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(render_model_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {model_scalar(item)}")
        return lines
    return [f"{prefix}{model_scalar(value)}"]


def render_model(value: Any) -> str:
    lines = render_model_lines(value)
    return "\n".join(lines) if lines else "ok"


def sparse_model_value(value: Any, *, root: bool = False) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if root and key in {"ok", "command", "note"}:
                continue
            projected = sparse_model_value(item)
            if projected is None or projected == "" or projected == [] or projected == {}:
                continue
            result[key] = projected
        return result
    if isinstance(value, list):
        return [sparse_model_value(item) for item in value]
    return value


def without_zero_counts(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            projected = without_zero_counts(item)
            if (
                projected in (None, "", [], {})
                or (projected is False and key == "truncated")
                or (projected == 0 and (key.endswith("_count") or key.endswith("_bytes")))
            ):
                continue
            result[key] = projected
        return result
    if isinstance(value, list):
        return [without_zero_counts(item) for item in value]
    return value


def protected_baseline_issue(
    value: Any, *, include_diagnostics: bool = True
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    diagnostics = value.get("diagnostics", [])
    status = value.get("status")
    if not diagnostics and status in {None, "protected"}:
        return {}
    return without_zero_counts(
        {
            "status": status,
            "cycle_id": value.get("cycle_id"),
            "confirmed_by": value.get("confirmed_by"),
            "diagnostics": diagnostics if include_diagnostics else None,
        }
    )


def work_status_model(payload: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    source_semantic = payload.get("semantic", {})
    semantic = without_zero_counts(
        {
            key: copy.deepcopy(source_semantic.get(key))
            for key in (
                "section_count",
                "stage_counts",
                "unresolved_count",
                "unresolved_ids",
                "deferred_change_count",
                "deferred_change_status_counts",
                "duplicate_count",
                "stage_mismatch_count",
                "unknown_reference_count",
            )
            if isinstance(source_semantic, dict)
        }
    )
    if semantic:
        projected["semantic"] = semantic
    baseline = protected_baseline_issue(
        payload.get("protected_baseline"), include_diagnostics=False
    )
    if baseline:
        projected["protected_baseline"] = baseline
    source_tasks = payload.get("tasks", {})
    task_counts = {
        key: count
        for key, count in source_tasks.get("counts", {}).items()
        if count
    } if isinstance(source_tasks, dict) else {}
    tasks = without_zero_counts(
        {
            "task_count": source_tasks.get("task_count")
            if isinstance(source_tasks, dict)
            else None,
            "states": task_counts,
            "status": (
                source_tasks.get("status")
                if isinstance(source_tasks, dict)
                and source_tasks.get("status") != "available"
                else None
            ),
            "result_count": source_tasks.get("result_count")
            if isinstance(source_tasks, dict)
            else None,
            "result_with_verification_count": source_tasks.get(
                "result_with_verification_count"
            )
            if isinstance(source_tasks, dict)
            else None,
            "result_with_unresolved_count": source_tasks.get(
                "result_with_unresolved_count"
            )
            if isinstance(source_tasks, dict)
            else None,
            "result_diagnostic_count": source_tasks.get("result_diagnostic_count")
            if isinstance(source_tasks, dict)
            else None,
            "result_diagnostic_kind_counts": source_tasks.get(
                "result_diagnostic_kind_counts"
            )
            if isinstance(source_tasks, dict)
            else None,
            "diagnostics": source_tasks.get("diagnostics")
            if isinstance(source_tasks, dict)
            else None,
        }
    )
    if tasks:
        projected["tasks"] = tasks
    if payload.get("diagnostics"):
        projected["diagnostics"] = payload["diagnostics"]
    if payload.get("truncated"):
        projected["more"] = {"truncated": True}
    return sparse_model_value(projected)


def work_context_model(payload: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    if payload.get("sections"):
        projected["sections"] = sparse_model_value(copy.deepcopy(payload["sections"]))
    if payload.get("truncated"):
        projected["more"] = {
            "truncated": True,
            "recovery": "read the returned document and line or raise --model-token-budget",
        }
    return projected


def work_protect_model(payload: dict[str, Any]) -> dict[str, Any]:
    source_baseline = payload.get("baseline", {})
    baseline = without_zero_counts(
        {
            key: copy.deepcopy(source_baseline.get(key))
            for key in (
                "status",
                "cycle_id",
                "confirmed_by",
                "protected_ids",
                "current_target_count",
            )
            if isinstance(source_baseline, dict)
        }
    )
    projected: dict[str, Any] = {"baseline": baseline}
    if payload.get("diagnostics"):
        projected["diagnostics"] = copy.deepcopy(payload["diagnostics"])
    return sparse_model_value(projected)


def work_impact_model(payload: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "id": payload.get("id"),
        "affected": copy.deepcopy(payload.get("affected", [])),
    }
    if payload.get("truncated"):
        projected["more"] = {
            "affected_count": payload.get("affected_count"),
            "truncated": True,
        }
    return sparse_model_value(projected)


def work_render_model(payload: dict[str, Any]) -> dict[str, Any]:
    summary = work_status_model(
        {
            "semantic": payload.get("semantic", {}),
            "tasks": payload.get("tasks", {}),
        }
    )
    return sparse_model_value({"output": payload.get("output"), **summary})


def work_model_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        return sparse_model_value(payload, root=True)
    command = payload.get("command")
    if command == "status":
        return work_status_model(payload)
    if command == "context":
        return work_context_model(payload)
    if command == "protect":
        return work_protect_model(payload)
    if command == "impact":
        return work_impact_model(payload)
    if command == "render":
        return work_render_model(payload)
    candidate = copy.deepcopy(payload)
    if command == "coverage":
        candidate["protected_baseline"] = protected_baseline_issue(
            candidate.get("protected_baseline")
        )
    return without_zero_counts(sparse_model_value(candidate, root=True))


def work_model_variants(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    projected = work_model_projection(payload)
    yield projected
    if payload.get("command") == "context":
        candidate = copy.deepcopy(projected)
        sections = candidate.get("sections")
        omitted: list[str] = []
        if isinstance(sections, list):
            for section in reversed(sections):
                if isinstance(section, dict) and section.get("body"):
                    section.pop("body", None)
                    if section.get("id"):
                        omitted.append(str(section["id"]))
                    candidate["more"] = {
                        "truncated": True,
                        "body_ids": list(reversed(omitted)),
                        "recovery": "read the returned document and line or raise --model-token-budget",
                    }
                    yield copy.deepcopy(candidate)


def fit_work_model(payload: dict[str, Any], budget: int) -> str:
    for candidate in work_model_variants(payload):
        text = render_model(candidate)
        if model_text_cost(text) <= budget:
            return text
    core: dict[str, Any] = {}
    for key in ("id", "stage", "document", "error", "gate"):
        if payload.get(key) not in (None, "", [], {}):
            core[key] = payload[key]
    sections = payload.get("sections")
    if isinstance(sections, list) and sections:
        section = sections[0]
        core["section"] = {
            key: section[key]
            for key in ("id", "title", "stage", "document", "line", "status")
            if section.get(key) not in (None, "", [], {})
        }
    command = payload.get("command")
    if command in {"context", "impact"}:
        recovery = "read the returned document and line, narrow the query, or rerun with a larger --model-token-budget"
    elif isinstance(command, str) and command:
        recovery = f"rerun {command} with a larger --model-token-budget"
    else:
        recovery = "rerun this command with a larger --model-token-budget"
    core["more"] = {
        "reason": "model_token_budget",
        "recovery": recovery,
    }
    text = render_model(sparse_model_value(core))
    if model_text_cost(text) <= budget:
        return text
    minimal = {
        "id": payload.get("id"),
        "more": {
            "reason": "model_token_budget",
            "recovery": recovery,
        },
    }
    text = render_model(sparse_model_value(minimal))
    if model_text_cost(text) > budget:
        raise WorkctlError("--model-token-budget is too small for a recoverable response")
    return text


def emit(
    value: Any,
    *,
    pretty: bool = False,
    view: str = "model",
    model_token_budget: int = DEFAULT_MODEL_TOKEN_BUDGET,
    stream: Any = sys.stdout,
) -> None:
    if view == "machine":
        if pretty:
            text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            text = compact_json(value)
    else:
        text = fit_work_model(value, model_token_budget)
    stream.write(text + "\n")


def read_text_bounded(path: Path, limit: int) -> str:
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise WorkctlError(f"missing file: {path}") from exc
    if size > limit:
        raise WorkctlError(
            f"file exceeds {limit} bytes: {path}",
            gate_id="WORK-LIMIT",
            risk="the command cannot keep input and output resource use bounded",
            recovery="narrow or split the input before retrying",
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkctlError(f"file is not UTF-8: {path}") from exc


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> Any:
    value, _ = read_json_snapshot(path, limit)
    return value


def read_json_snapshot(path: Path, limit: int = MAX_JSON_BYTES) -> tuple[Any, str]:
    text = read_text_bounded(path, limit)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkctlError(f"invalid JSON in {path}: {exc}") from exc
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return value, f"sha256:{digest}"


def ensure_workflow_manifest_unchanged(
    root: Path, expected_fingerprint: str, operation: str
) -> None:
    manifest_path = root / "workflow.json"
    _, current_fingerprint = read_json_snapshot(manifest_path)
    if current_fingerprint != expected_fingerprint:
        raise WorkctlError(
            f"workflow manifest changed while {operation}",
            gate_id="WORK-SNAPSHOT-RACE",
            risk=(
                "one workflow query would combine document mappings or metadata "
                "from different manifest versions"
            ),
            recovery="retry after workflow.json edits have stopped",
            retryable=True,
        )


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


def exclusive_write_json(path: Path, value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise WorkctlError(
            f"refusing to overwrite confirmation snapshot: {path}",
            gate_id="WORK-OVERWRITE",
            risk="an existing snapshot would be destroyed",
            recovery="use --new-cycle to preserve the previous snapshot in history",
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except (OSError, WorkctlError):
            pass
        raise
    return text


def resolve_root(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def resolve_inside(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise WorkctlError(
            f"manifest path must be relative: {relative}",
            gate_id="WORK-PATH",
            risk="the command could read or write outside the selected workflow",
            recovery="use the fixed workflow-relative path",
        )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkctlError(
            f"path escapes work directory: {relative}",
            gate_id="WORK-PATH",
            risk="the command could read or write outside the selected workflow",
            recovery="use a path contained by the workflow directory",
        ) from exc
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
            raise WorkctlError(
                "delivery workspace is being updated by another process",
                gate_id="WORK-LOCK",
                risk="concurrent writes could overwrite workflow data",
                recovery="wait for the other writer to finish, then retry",
                retryable=True,
            ) from exc
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


def load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "workflow.json"
    manifest, manifest_fingerprint = read_json_snapshot(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "delivery.workflow":
        raise WorkctlError(f"unsupported workflow manifest: {manifest_path}")
    normalize_manifest_text(manifest.get("id"), "workflow.json id")
    manifest_title = semantic_text(manifest.get("title"), "workflow.json title")
    manifest_diagnostics = semantic_text_diagnostics(
        manifest_title, "workflow.title"
    )
    documents = manifest.get("documents")
    if not isinstance(documents, dict):
        raise WorkctlError("workflow.json documents must be an object")
    document_paths: dict[str, Path] = {}
    for stage in STAGE_PREFIXES:
        value = documents.get(stage)
        if not isinstance(value, str) or not value.strip():
            raise WorkctlError(f"workflow.json is missing documents.{stage}")
        document_paths[stage] = resolve_inside(root, value)
    if len(set(document_paths.values())) != len(document_paths):
        raise WorkctlError("workflow documents must use distinct paths")
    special_paths: dict[str, Path] = {}
    for field, default in (
        ("task_table", "task-table.json"),
        ("protected_baseline", "protected-baseline.json"),
        ("semantic_index", ".work-cache/index.json"),
        ("status_view", "WORK_STATUS.md"),
    ):
        value = manifest.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise WorkctlError(f"workflow.json {field} must be a non-empty string")
        if value != default:
            raise WorkctlError(f"workflow.json {field} must remain {default}")
        special_paths[field] = resolve_inside(root, value)
    workflow_path = (root / "workflow.json").resolve()
    task_table_path = special_paths["task_table"]
    baseline_path = special_paths["protected_baseline"]
    index_path = special_paths["semantic_index"]
    status_path = special_paths["status_view"]
    semantic_paths = set(document_paths.values())
    reserved_truth = semantic_paths | {workflow_path, task_table_path, baseline_path}
    if index_path in reserved_truth or status_path in reserved_truth:
        raise WorkctlError("generated index and status view must not overwrite workflow truth")
    if index_path == status_path:
        raise WorkctlError("semantic index and status view must use distinct paths")
    if baseline_path in semantic_paths or baseline_path in {workflow_path, task_table_path}:
        raise WorkctlError("confirmation snapshot must use a dedicated path")
    if task_table_path.exists():
        task_table = read_json(task_table_path)
        if not isinstance(task_table, dict) or task_table.get("schema") != "task.table":
            raise WorkctlError(f"unsupported task table manifest: {task_table_path}")
        if task_table.get("id") != manifest.get("id"):
            raise WorkctlError("task table belongs to a different workflow")
        task_table_title = semantic_text(
            task_table.get("title"), "task-table.json title"
        )
        manifest_diagnostics.extend(
            semantic_text_diagnostics(task_table_title, "task_table.title")
        )
        if task_table_title != manifest_title:
            manifest_diagnostics.append(
                {
                    "kind": "task_table_title_differs_from_workflow",
                    "workflow_title": manifest_title,
                    "task_table_title": task_table_title,
                }
            )
        storage_paths = []
        for field, default in (
            ("task_dir", "tasks"),
            ("state_dir", "state"),
            ("result_dir", "results"),
            ("snapshot_dir", "snapshots"),
        ):
            value = task_table.get(field, default)
            if not isinstance(value, str) or not value.strip():
                raise WorkctlError(f"task-table.json {field} must be a non-empty string")
            if value != default:
                raise WorkctlError(f"task-table.json {field} must remain {default}")
            storage_paths.append(resolve_inside(root, value))
        for storage_path in storage_paths:
            if any(
                storage_path == truth_path.parent or storage_path in truth_path.parents
                for truth_path in reserved_truth
            ):
                raise WorkctlError("task storage must not contain workflow truth")
        for generated_path in (index_path, status_path):
            if any(
                generated_path == storage or storage in generated_path.parents
                for storage in storage_paths
            ):
                raise WorkctlError("workflow generated files must not overwrite task storage")
    ensure_workflow_manifest_unchanged(root, manifest_fingerprint, "reading workflow.json")
    manifest["_diagnostics"] = manifest_diagnostics
    manifest["_source_fingerprint"] = manifest_fingerprint
    return manifest


def file_fingerprint(path: Path) -> str:
    text = read_text_bounded(path, MAX_DOCUMENT_BYTES)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def verify_protected_baseline(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    baseline_path = resolve_inside(
        root, str(manifest.get("protected_baseline", "protected-baseline.json"))
    )
    if not baseline_path.exists():
        return {
            "status": "unprotected",
            "path": baseline_path.name,
            "protected_ids": 0,
            "diagnostics": [{"kind": "baseline_snapshot_missing"}],
        }
    try:
        baseline = read_json(baseline_path)
    except (OSError, WorkctlError) as exc:
        return {
            "status": "invalid",
            "path": baseline_path.name,
            "protected_ids": 0,
            "diagnostics": [
                {"kind": "baseline_snapshot_unreadable", "message": str(exc)}
            ],
        }
    diagnostics: list[dict[str, Any]] = []
    invalid = False
    drifted = False
    if not isinstance(baseline, dict) or baseline.get("schema") != "delivery.protected-baseline":
        return {
            "status": "invalid",
            "path": baseline_path.name,
            "protected_ids": 0,
            "diagnostics": [{"kind": "baseline_snapshot_unsupported"}],
        }
    if baseline.get("workflow_id") != manifest.get("id"):
        invalid = True
        diagnostics.append({"kind": "baseline_workflow_mismatch"})
    confirmed_by = baseline.get("confirmed_by")
    if not isinstance(confirmed_by, str):
        confirmed_by = None
        diagnostics.append({"kind": "baseline_confirmation_provenance_invalid"})
    elif not confirmed_by.strip():
        diagnostics.append({"kind": "baseline_confirmation_provenance_missing"})
    elif confirmed_by != "user":
        diagnostics.append({"kind": "baseline_confirmation_provenance_unverified"})
    confirmation_ref: str | None
    try:
        confirmation_ref = semantic_text(
            baseline.get("confirmation_ref"), "protected baseline confirmation_ref"
        )
        if not confirmation_ref.strip():
            diagnostics.append({"kind": "baseline_confirmation_reference_missing"})
        elif confirmation_ref != confirmation_ref.strip():
            diagnostics.append(
                {"kind": "baseline_confirmation_reference_surrounding_whitespace"}
            )
    except WorkctlError as exc:
        confirmation_ref = None
        diagnostics.append(
            {"kind": "baseline_confirmation_reference_invalid", "message": str(exc)}
        )
    documents = baseline.get("documents")
    if not isinstance(documents, dict):
        return {
            "status": "invalid",
            "path": baseline_path.name,
            "cycle_id": baseline.get("cycle_id"),
            "confirmed_by": baseline.get("confirmed_by"),
            "confirmation_ref": confirmation_ref,
            "protected_ids": 0,
            "history_count": 0,
            "diagnostics": [*diagnostics, {"kind": "baseline_documents_invalid"}],
        }
    protected_ids = 0
    for stage in PROTECTED_STAGES:
        record = documents.get(stage)
        if not isinstance(record, dict):
            invalid = True
            diagnostics.append({"kind": "baseline_stage_missing", "stage": stage})
            continue
        expected_path = str(manifest["documents"][stage])
        if record.get("path") != expected_path:
            invalid = True
            diagnostics.append(
                {
                    "kind": "baseline_path_mismatch",
                    "stage": stage,
                    "expected": expected_path,
                    "recorded": record.get("path"),
                }
            )
        current_fingerprint = file_fingerprint(resolve_inside(root, expected_path))
        if record.get("fingerprint") != current_fingerprint:
            drifted = True
            diagnostics.append(
                {
                    "kind": "baseline_source_drift",
                    "stage": stage,
                    "path": expected_path,
                    "recorded": record.get("fingerprint"),
                    "current": current_fingerprint,
                }
            )
        ids = record.get("ids")
        if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
            invalid = True
            diagnostics.append({"kind": "baseline_ids_invalid", "stage": stage})
            continue
        if len(ids) != len(set(ids)):
            diagnostics.append({"kind": "baseline_duplicate_ids", "stage": stage})
        actual_sections, _ = parse_document(
            resolve_inside(root, expected_path), stage, expected_path
        )
        actual_ids = sorted(section["id"] for section in actual_sections)
        if sorted(ids) != actual_ids:
            drifted = True
            diagnostics.append(
                {
                    "kind": "baseline_id_set_drift",
                    "stage": stage,
                    "path": expected_path,
                }
            )
        if any(section_prefix(value) not in STAGE_PREFIXES[stage] for value in ids):
            diagnostics.append({"kind": "baseline_stage_id_mismatch", "stage": stage})
        unconfirmed = [
            section["id"]
            for section in actual_sections
            if section["status"].casefold() != "confirmed"
        ]
        if unconfirmed:
            diagnostics.append(
                {
                    "kind": "baseline_entries_not_confirmed",
                    "stage": stage,
                    "ids": unconfirmed[:20],
                }
            )
        protected_ids += len(ids)
    current_target_ids = sorted(
        section["id"]
        for stage in PROTECTED_STAGES
        for section in parse_document(
            resolve_inside(root, str(manifest["documents"][stage])),
            stage,
            str(manifest["documents"][stage]),
        )[0]
        if section_prefix(section["id"]) in {"REQ", "AC", "UDES"}
    )
    if not current_target_ids:
        diagnostics.append({"kind": "baseline_has_no_final_target"})
    history = baseline.get("history", [])
    if not isinstance(history, list):
        invalid = True
        diagnostics.append({"kind": "baseline_history_invalid"})
        history = []
    return {
        "status": "invalid" if invalid else "drifted" if drifted else "protected",
        "path": baseline_path.name,
        "cycle_id": baseline.get("cycle_id", "cycle-001"),
        "confirmed_by": confirmed_by,
        "confirmation_ref": confirmation_ref,
        "protected_ids": protected_ids,
        "current_target_count": len(current_target_ids),
        "history_count": len(history),
        "diagnostics": diagnostics,
    }


def section_prefix(section_id: str) -> str:
    return section_id.split("-", 1)[0]


def parse_document(
    path: Path, stage: str, document: str
) -> tuple[list[dict[str, Any]], str]:
    text = read_text_bounded(path, MAX_DOCUMENT_BYTES)
    lines = text.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            matches.append((index, match))
    sections: list[dict[str, Any]] = []
    for item_index, (line_index, match) in enumerate(matches):
        end_index = matches[item_index + 1][0] if item_index + 1 < len(matches) else len(lines)
        body_lines = lines[line_index + 1 : end_index]
        body = "\n".join(body_lines).strip()
        status = "unspecified"
        for body_line in body_lines:
            status_match = STATUS_RE.match(body_line)
            if status_match:
                status = status_match.group("status").strip().casefold()
                break
        section_id = match.group("id")
        title = (match.group("title") or "").strip()
        relation_values = [
            relation_match.group("value")
            for body_line in body_lines
            if (relation_match := REFERENCE_FIELD_RE.match(body_line)) is not None
        ]
        refs = sorted(set(ID_RE.findall("\n".join(relation_values))) - {section_id})
        section_digest = hashlib.sha256(
            f"{section_id}\n{title}\n{body}".encode("utf-8")
        ).hexdigest()
        sections.append(
            {
                "id": section_id,
                "title": title,
                "stage": stage,
                "document": document,
                "line": line_index + 1,
                "status": status,
                "references": refs,
                "fingerprint": f"sha256:{section_digest}",
                "body": body,
            }
        )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return sections, f"sha256:{digest}"


def build_index(
    root: Path, manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest = manifest or load_manifest(root)
    manifest_fingerprint = manifest.get("_source_fingerprint")
    if not isinstance(manifest_fingerprint, str):
        raise WorkctlError("workflow manifest snapshot identity is unavailable")
    all_sections: list[dict[str, Any]] = []
    document_hashes: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = list(manifest.get("_diagnostics", []))
    for stage in STAGE_PREFIXES:
        relative_path = str(manifest["documents"][stage])
        path = resolve_inside(root, relative_path)
        sections, digest = parse_document(path, stage, relative_path)
        document_hashes[stage] = digest
        all_sections.extend(sections)
        for section in sections:
            prefix = section_prefix(section["id"])
            if prefix not in STAGE_PREFIXES[stage]:
                diagnostics.append(
                    {
                        "kind": "stage_mismatch",
                        "id": section["id"],
                        "document": section["document"],
                        "message": f"{section['id']} does not belong to {stage}",
                    }
                )
    baseline = verify_protected_baseline(root, manifest)
    diagnostics.extend(baseline.get("diagnostics", []))
    for stage, recorded_fingerprint in document_hashes.items():
        path = resolve_inside(root, str(manifest["documents"][stage]))
        if file_fingerprint(path) != recorded_fingerprint:
            raise WorkctlError(
                f"workflow document changed while building the index: {path.name}",
                gate_id="WORK-SNAPSHOT-RACE",
                risk="one index would combine semantic sections from different document versions",
                recovery="retry after document edits have stopped",
                retryable=True,
            )
    ensure_workflow_manifest_unchanged(root, manifest_fingerprint, "building the index")
    if len(all_sections) > MAX_RECORDS:
        raise WorkctlError(
            f"workflow contains more than {MAX_RECORDS} semantic sections",
            gate_id="WORK-LIMIT",
            risk="the command cannot keep workflow indexing bounded",
            recovery="split or archive the workflow documents before retrying",
        )

    definitions: dict[str, list[dict[str, Any]]] = {}
    for section in all_sections:
        definitions.setdefault(section["id"], []).append(section)
    duplicates = sorted(section_id for section_id, rows in definitions.items() if len(rows) > 1)
    for section_id in duplicates:
        diagnostics.append(
            {
                "kind": "duplicate_id",
                "id": section_id,
                "locations": [
                    f"{row['document']}:{row['line']}" for row in definitions[section_id]
                ],
                "message": f"{section_id} is defined more than once",
            }
        )

    known_ids = set(definitions)
    reverse_refs: dict[str, list[str]] = {section_id: [] for section_id in known_ids}
    for section in all_sections:
        for reference in section["references"]:
            if reference not in known_ids:
                diagnostics.append(
                    {
                        "kind": "unknown_reference",
                        "id": section["id"],
                        "reference": reference,
                        "document": section["document"],
                        "line": section["line"],
                        "message": f"{section['id']} references undefined {reference}",
                    }
                )
            else:
                reverse_refs[reference].append(section["id"])
    for values in reverse_refs.values():
        values.sort()

    prefix_counts = Counter(section_prefix(section["id"]) for section in all_sections)
    stage_counts = Counter(section["stage"] for section in all_sections)
    unresolved_ids = sorted(
        section["id"]
        for section in all_sections
        if section["status"].casefold() in UNRESOLVED_STATUSES
    )
    deferred_changes = [
        section
        for section in all_sections
        if section_prefix(section["id"]) == "DCR"
    ]
    deferred_change_ids = sorted({section["id"] for section in deferred_changes})
    deferred_change_status_counts = Counter(
        section["status"] for section in deferred_changes
    )
    for section in deferred_changes:
        if section["status"] not in DCR_STATUSES:
            diagnostics.append(
                {
                    "kind": "non_standard_deferred_change_status",
                    "id": section["id"],
                    "status": section["status"],
                    "document": section["document"],
                    "line": section["line"],
                }
            )
    summary = {
        "section_count": len(all_sections),
        "stage_counts": dict(sorted(stage_counts.items())),
        "prefix_counts": dict(sorted(prefix_counts.items())),
        "unresolved_count": len(unresolved_ids),
        "deferred_change_count": len(deferred_change_ids),
        "deferred_change_status_counts": dict(
            sorted(deferred_change_status_counts.items())
        ),
        "duplicate_count": len(duplicates),
        "unknown_reference_count": sum(
            diagnostic["kind"] == "unknown_reference" for diagnostic in diagnostics
        ),
        "stage_mismatch_count": sum(
            diagnostic["kind"] == "stage_mismatch" for diagnostic in diagnostics
        ),
    }
    return {
        "schema": "delivery.index",
        "workflow_id": manifest.get("id"),
        "workflow_manifest_fingerprint": manifest_fingerprint,
        "documents": dict(manifest["documents"]),
        "protected_baseline": baseline,
        "document_hashes": document_hashes,
        "summary": summary,
        "unresolved_ids": unresolved_ids,
        "deferred_change_ids": deferred_change_ids,
        "duplicates": duplicates,
        "reverse_references": reverse_refs,
        "diagnostics": diagnostics,
        "sections": all_sections,
    }


def limit_items(items: list[Any], maximum: int) -> tuple[list[Any], bool]:
    return items[:maximum], len(items) > maximum


def task_status_summary(root: Path) -> dict[str, Any]:
    script_path = Path(__file__).resolve().with_name("taskctl.py")
    if not script_path.is_file():
        return unavailable_task_summary(
            "task_table_manager_missing", f"task table manager is unavailable: {script_path}"
        )
    spec = importlib.util.spec_from_file_location("_agentbase_taskctl", script_path)
    if spec is None or spec.loader is None:
        return unavailable_task_summary(
            "task_table_manager_unreadable", f"task table manager is unreadable: {script_path}"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        summary = module.task_storage_summary(root)
    except Exception as exc:
        taskctl_error = getattr(module, "TaskctlError", None)
        if taskctl_error is not None and isinstance(exc, taskctl_error):
            return unavailable_task_summary("task_storage_partially_unreadable", str(exc))
        return unavailable_task_summary("task_table_manager_failed", str(exc))
    if not isinstance(summary, dict):
        return unavailable_task_summary(
            "task_table_summary_invalid", "task table manager returned an invalid storage summary"
        )
    summary.setdefault("status", "available")
    summary.setdefault("diagnostics", [])
    return summary


def unavailable_task_summary(kind: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "counts": {},
        "task_count": None,
        "result_count": None,
        "result_with_verification_count": None,
        "result_with_unresolved_count": None,
        "result_with_diagnostics_count": None,
        "task_revision_stale_result_count": None,
        "source_snapshot_issue_result_count": None,
        "result_diagnostic_count": None,
        "result_diagnostic_kind_counts": {},
        "invalidated_source_ids": [],
        "diagnostics": [{"kind": kind, "message": message}],
    }


def init_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    root.mkdir(parents=True, exist_ok=True)
    with workspace_lock(root):
        return init_workspace_locked(args, root)


def init_workspace_locked(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    workflow_id = normalize_manifest_text(args.id, "--id", writing=True)
    title = semantic_text(args.title, "--title")
    created_files = [
        "workflow.json",
        "task-table.json",
        *DEFAULT_DOCUMENTS.values(),
    ]
    pending_files = [
        "protected-baseline.json",
        ".work-cache/index.json",
        "WORK_STATUS.md",
        "TASK_TABLE.md",
    ]
    managed_files = [*created_files, *pending_files]
    conflicts = [name for name in managed_files if (root / name).exists()]
    conflicts.extend(
        directory
        for directory in ("tasks", "state", "results", "snapshots")
        if (root / directory).is_dir() and any((root / directory).iterdir())
    )
    if conflicts:
        raise WorkctlError(
            f"refusing to overwrite existing workspace files: {', '.join(conflicts)}",
            gate_id="WORK-OVERWRITE",
            risk="initialization would overwrite existing workflow data",
            recovery="choose an empty directory or preserve and inspect the existing workspace",
        )

    for directory in ("tasks", "state", "results", "snapshots"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    template_root = Path(__file__).resolve().parents[1] / "assets" / "templates"
    for filename in DEFAULT_DOCUMENTS.values():
        template = read_text_bounded(template_root / filename, MAX_DOCUMENT_BYTES)
        atomic_write_text(root / filename, template.replace("{{TITLE}}", title))

    manifest = {
        "schema": "delivery.workflow",
        "id": workflow_id,
        "title": title,
        "documents": dict(DEFAULT_DOCUMENTS),
        "protected_baseline": "protected-baseline.json",
        "task_table": "task-table.json",
        "semantic_index": ".work-cache/index.json",
        "status_view": "WORK_STATUS.md",
    }
    table = {
        "schema": "task.table",
        "id": workflow_id,
        "title": title,
        "task_dir": "tasks",
        "state_dir": "state",
        "result_dir": "results",
        "snapshot_dir": "snapshots",
        "source_index": ".work-cache/index.json",
        "table_view": "TASK_TABLE.md",
    }
    atomic_write_json(root / "workflow.json", manifest)
    atomic_write_json(root / "task-table.json", table)
    return {
        "ok": True,
        "command": "init",
        "work_dir": str(root),
        "created": created_files + ["tasks/", "state/", "results/", "snapshots/"],
        "pending": pending_files,
        "diagnostics": semantic_text_diagnostics(title, "workflow.title"),
    }


def protect_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    with workspace_lock(root):
        return protect_workspace_locked(args, root)


def protect_workspace_locked(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    confirmed_by = semantic_text(args.confirmed_by, "--confirmed-by")
    confirmation_ref = semantic_text(args.confirmation_ref, "--confirmation-ref")
    manifest = load_manifest(root)
    baseline_path = resolve_inside(
        root, str(manifest.get("protected_baseline", "protected-baseline.json"))
    )
    existing_text: str | None = None
    history: list[dict[str, Any]] = []
    if baseline_path.exists():
        if not getattr(args, "new_cycle", False):
            raise WorkctlError(
                f"refusing to overwrite confirmation snapshot: {baseline_path}",
                gate_id="WORK-OVERWRITE",
                risk="the existing confirmation snapshot would be destroyed",
                recovery="use --new-cycle to preserve it in history",
            )
        existing_text = read_text_bounded(baseline_path, MAX_JSON_BYTES)
        existing = read_json(baseline_path)
        if (
            not isinstance(existing, dict)
            or existing.get("schema") != "delivery.protected-baseline"
            or existing.get("workflow_id") != manifest.get("id")
        ):
            raise WorkctlError(
                f"cannot preserve unsupported existing baseline: {baseline_path}",
                gate_id="WORK-OVERWRITE",
                risk="replacing an unknown snapshot format could destroy provenance",
                recovery="repair or explicitly archive the existing baseline before retrying",
            )
        existing_history = existing.get("history", [])
        if not isinstance(existing_history, list):
            raise WorkctlError(
                "cannot preserve invalid baseline history",
                gate_id="WORK-OVERWRITE",
                risk="a new snapshot could silently discard prior provenance",
                recovery="repair the history array before starting a new cycle",
            )
        history = [*existing_history]
        history.append(
            {
                key: existing.get(key)
                for key in (
                    "cycle_id",
                    "confirmed_by",
                    "confirmation_ref",
                    "documents",
                )
            }
        )
    index = build_index(root, manifest)
    protected_documents: dict[str, Any] = {}
    for stage in PROTECTED_STAGES:
        sections = [section for section in index["sections"] if section["stage"] == stage]
        relative_path = str(manifest["documents"][stage])
        protected_documents[stage] = {
            "path": relative_path,
            "fingerprint": index["document_hashes"][stage],
            "ids": sorted(section["id"] for section in sections),
        }
    for stage in PROTECTED_STAGES:
        relative_path = str(manifest["documents"][stage])
        if file_fingerprint(resolve_inside(root, relative_path)) != index["document_hashes"][stage]:
            raise WorkctlError(
                f"confirmation source changed while creating the snapshot: {relative_path}; retry",
                gate_id="WORK-SNAPSHOT-RACE",
                risk="one snapshot would combine content from different document versions",
                recovery="retry after document edits have stopped",
                retryable=True,
            )
    if existing_text is not None and read_text_bounded(baseline_path, MAX_JSON_BYTES) != existing_text:
        raise WorkctlError(
            "confirmation snapshot changed while starting a new cycle",
            gate_id="WORK-SNAPSHOT-RACE",
            risk="the new cycle could overwrite newer confirmation provenance",
            recovery="read the current baseline and retry the new-cycle operation",
            retryable=True,
        )
    baseline = {
        "schema": "delivery.protected-baseline",
        "workflow_id": manifest.get("id"),
        "cycle_id": f"cycle-{len(history) + 1:03d}",
        "confirmed_by": confirmed_by,
        "confirmation_ref": confirmation_ref,
        "documents": protected_documents,
        "history": history,
    }
    if existing_text is None:
        exclusive_write_json(baseline_path, baseline)
    else:
        atomic_write_json(baseline_path, baseline)
    summary = verify_protected_baseline(root, manifest)
    return {
        "ok": True,
        "command": "protect",
        "baseline": summary,
        "diagnostics": summary.get("diagnostics", []),
        "note": "snapshot metadata records provenance; workflow documents remain authoritative",
    }


def outline_stage(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    manifest = load_manifest(root)
    stage = PUBLIC_STAGES[args.stage]
    outlines = {
        "requirements": {
            "ids": ["REQ", "AC", "CON"],
            "fields": ["状态", "来源", "关联", "对象与范围", "正文"],
        },
        "user_design": {
            "ids": ["UDES"],
            "fields": ["状态", "来源", "关联需求", "用户明确给出的设计"],
        },
        "design": {
            "ids": ["DES", "DEC"],
            "fields": ["状态", "满足", "职责或接口", "状态与依赖", "生命周期"],
        },
        "current_state": {
            "ids": ["OBS", "GAP", "DEC"],
            "fields": ["状态", "来源或证据", "事实/推断/未知", "关联目标", "可证明上限"],
        },
        "solution": {
            "ids": ["SOL", "DEC"],
            "fields": ["状态", "解决", "满足", "动作与结果", "依赖", "风险", "验证"],
        },
        "deferred_changes": {
            "ids": ["DCR"],
            "fields": ["状态", "目标ID", "直接证据", "必要性", "受影响工作", "仍可继续工作", "讨论建议"],
        },
    }
    return {
        "ok": True,
        "command": "outline",
        "work_dir": str(root),
        "stage": args.stage,
        "document": str(manifest["documents"][stage]),
        "heading": "## <ID> <title>",
        **outlines[stage],
    }


def index_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    manifest_fingerprint = index["workflow_manifest_fingerprint"]
    cache_path = resolve_inside(root, ".work-cache/index.json")
    ensure_workflow_manifest_unchanged(
        root, manifest_fingerprint, "preparing the semantic index write"
    )
    atomic_write_json(cache_path, index)
    ensure_workflow_manifest_unchanged(
        root, manifest_fingerprint, "writing the semantic index"
    )
    diagnostics, truncated = limit_items(index["diagnostics"], args.max_items)
    return {
        "ok": True,
        "command": "index",
        "cache": str(cache_path),
        "summary": index["summary"],
        "unresolved_ids": index["unresolved_ids"][: args.max_items],
        "diagnostics": diagnostics,
        "truncated": truncated or len(index["unresolved_ids"]) > args.max_items,
        "note": "structural diagnostics do not determine semantic correctness or execution readiness",
    }


def status_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    diagnostics, truncated = limit_items(index["diagnostics"], args.max_items)
    return {
        "ok": True,
        "command": "status",
        "semantic": {
            **index["summary"],
            "unresolved_ids": index["unresolved_ids"][: args.max_items],
            "deferred_change_count": index["summary"]["deferred_change_count"],
        },
        "protected_baseline": index["protected_baseline"],
        "tasks": task_status_summary(root),
        "diagnostics": diagnostics,
        "truncated": truncated or len(index["unresolved_ids"]) > args.max_items,
    }


def coverage_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    inbound = index["reverse_references"]
    unreferenced = sorted(
        section["id"]
        for section in index["sections"]
        if not inbound.get(section["id"])
        and section_prefix(section["id"]) not in {"SOL", "DEC", "DCR"}
    )
    unreferenced_limited, unreferenced_truncated = limit_items(unreferenced, args.max_items)
    unresolved_limited, unresolved_truncated = limit_items(index["unresolved_ids"], args.max_items)
    return {
        "ok": True,
        "command": "coverage",
        "counts": index["summary"],
        "protected_baseline": index["protected_baseline"],
        "unresolved_ids": unresolved_limited,
        "unreferenced_upstream_ids": unreferenced_limited,
        "truncated": unreferenced_truncated or unresolved_truncated,
        "note": "a reference is traceability data, not proof of semantic coverage",
    }


def unique_section(index: dict[str, Any], section_id: str) -> dict[str, Any]:
    matches = [section for section in index["sections"] if section["id"] == section_id]
    if not matches:
        raise WorkctlError(
            f"unknown semantic id: {section_id}",
            gate_id="WORK-AMBIGUOUS-TARGET",
            risk="the exact query has no uniquely identified target",
            recovery="choose an ID present in the current Markdown documents",
        )
    if len(matches) > 1:
        raise WorkctlError(
            f"ambiguous semantic id: {section_id}",
            gate_id="WORK-AMBIGUOUS-TARGET",
            risk="the exact query could return or mutate the wrong semantic object",
            recovery="disambiguate duplicate IDs in the documents, then retry this exact query",
        )
    return matches[0]


def fit_context(payload: dict[str, Any], budget: int) -> dict[str, Any]:
    payload["truncated"] = bool(payload.get("truncated"))
    sections = payload["sections"]
    if sections:
        per_body = max(160, budget // max(4, len(sections) * 2))
        for section in sections:
            body = section.get("body", "")
            if len(body) > per_body:
                section["body"] = body[:per_body] + "…"
                payload["truncated"] = True
    while len(compact_json(payload)) > budget and len(sections) > 1:
        sections.pop()
        payload["truncated"] = True
    while len(compact_json(payload)) > budget and sections and len(sections[0].get("body", "")) > 80:
        body = sections[0]["body"]
        sections[0]["body"] = body[: max(80, len(body) // 2)] + "…"
        payload["truncated"] = True
    if len(compact_json(payload)) > budget:
        payload = {
            "ok": True,
            "command": "context",
            "id": payload["id"],
            "sections": [
                {
                    "id": sections[0]["id"],
                    "title": sections[0]["title"],
                    "stage": sections[0]["stage"],
                    "document": sections[0]["document"],
                    "line": sections[0]["line"],
                }
            ]
            if sections
            else [],
            "truncated": True,
            "hint": "increase --budget or read the returned document and line",
        }
    return payload


def context_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    unique_section(index, args.id)
    duplicates = set(index["duplicates"])
    by_id = {
        section["id"]: section
        for section in index["sections"]
        if section["id"] not in duplicates
    }
    selected: list[str] = []
    seen = {args.id}
    queue: deque[tuple[str, int]] = deque([(args.id, 0)])
    while queue:
        current, depth = queue.popleft()
        selected.append(current)
        if depth >= args.depth:
            continue
        section = by_id[current]
        neighbors = list(section["references"]) + list(index["reverse_references"].get(current, []))
        for neighbor in neighbors:
            if neighbor in duplicates:
                raise WorkctlError(
                    f"ambiguous related semantic id: {neighbor}",
                    gate_id="WORK-AMBIGUOUS-TARGET",
                    risk="the exact context query could traverse the wrong semantic object",
                    recovery="disambiguate the duplicate ID, then retry this exact query",
                )
            if neighbor in by_id and neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, depth + 1))
    selected = selected[: args.max_items]
    sections = [
        {
            "id": by_id[section_id]["id"],
            "title": by_id[section_id]["title"],
            "stage": by_id[section_id]["stage"],
            "document": by_id[section_id]["document"],
            "line": by_id[section_id]["line"],
            "status": by_id[section_id]["status"],
            "references": by_id[section_id]["references"],
            "body": by_id[section_id]["body"],
        }
        for section_id in selected
    ]
    payload = {
        "ok": True,
        "command": "context",
        "id": args.id,
        "sections": sections,
        "truncated": len(seen) > args.max_items,
    }
    return fit_context(payload, args.budget) if args.view == "machine" else payload


def impact_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    unique_section(index, args.id)
    duplicates = set(index["duplicates"])
    affected: list[str] = []
    seen = {args.id}
    queue = deque([args.id])
    paths: dict[str, list[str]] = {args.id: [args.id]}
    while queue:
        current = queue.popleft()
        for dependent in index["reverse_references"].get(current, []):
            if dependent in duplicates:
                raise WorkctlError(
                    f"ambiguous related semantic id: {dependent}",
                    gate_id="WORK-AMBIGUOUS-TARGET",
                    risk="the exact impact query could traverse the wrong semantic object",
                    recovery="disambiguate the duplicate ID, then retry this exact query",
                )
            if dependent not in seen:
                seen.add(dependent)
                affected.append(dependent)
                paths[dependent] = [*paths[current], dependent]
                queue.append(dependent)
    limited, truncated = limit_items(affected, args.max_items)
    by_id = {section["id"]: section for section in index["sections"]}
    return {
        "ok": True,
        "command": "impact",
        "id": args.id,
        "affected": [
            {
                "id": section_id,
                "stage": by_id[section_id]["stage"],
                "document": by_id[section_id]["document"],
                "line": by_id[section_id]["line"],
                "depth": len(paths[section_id]) - 1,
                "via": paths[section_id][-2],
                "path": paths[section_id],
            }
            for section_id in limited
        ],
        "affected_count": len(affected),
        "truncated": truncated,
        "note": "affected entries require model review; they are not automatically invalid",
    }


def markdown_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    manifest = load_manifest(root)
    index = build_index(root, manifest)
    task_summary = task_status_summary(root)
    output_path = resolve_inside(root, str(manifest.get("status_view", "WORK_STATUS.md")))
    lines = [
        f"# {manifest.get('title') or manifest.get('id') or 'Delivery'} 状态",
        "",
        "> 本文件由 workctl 生成，只是可重建的复核导航；其中计数不定义语义、READY 或最终完成状态。",
        "",
        "## 用户确认快照",
        "",
        f"- 状态：{index['protected_baseline']['status']}",
        f"- 受保护 ID：{index['protected_baseline']['protected_ids']}",
        f"- 确认者：{index['protected_baseline'].get('confirmed_by') or '未记录'}",
        "",
        "## 可修订语义闭合",
        "",
        "| 类型 | 数量 |",
        "| --- | ---: |",
    ]
    for prefix, count in sorted(index["summary"]["prefix_counts"].items()):
        lines.append(f"| {markdown_escape(prefix)} | {count} |")
    for label, key in (
        ("未决条目", "unresolved_count"),
        ("未解析引用", "unknown_reference_count"),
        ("延后讨论项", "deferred_change_count"),
    ):
        if index["summary"][key]:
            lines.append(f"| {label} | {index['summary'][key]} |")
    lines.extend(["", "## 任务执行状态", ""])
    if task_summary["status"] in {"available", "partial"}:
        nonzero_statuses = [
            (status, count)
            for status, count in task_summary["counts"].items()
            if count
        ]
        if nonzero_statuses:
            lines.extend(["| 状态 | 数量 |", "| --- | ---: |"])
            lines.extend(
                f"| {status} | {count} |" for status, count in nonzero_statuses
            )
        else:
            lines.append("- 无任务")
        if task_summary["status"] == "partial":
            lines.append("- 任务读取状态：partial")
    else:
        lines.append("- 任务状态不可用")
    lines.extend(["", "## 任务结果证据", ""])
    if task_summary["result_count"] is None:
        lines.append("- 结果摘要未知")
    elif task_summary["result_count"] == 0:
        lines.append("- 当前没有结果引用")
    else:
        lines.extend(
            [
                f"- 任务状态引用结果：{task_summary['result_count']}",
                f"- 含验证结果：{task_summary['result_with_verification_count']}",
            ]
        )
        for label, key in (
            ("含未决结果", "result_with_unresolved_count"),
            ("含结果诊断", "result_with_diagnostics_count"),
            ("任务合同 revision 陈旧结果", "task_revision_stale_result_count"),
            ("含来源快照问题结果", "source_snapshot_issue_result_count"),
            ("结果诊断条目", "result_diagnostic_count"),
        ):
            if task_summary[key]:
                lines.append(f"- {label}：{task_summary[key]}")
        if task_summary["invalidated_source_ids"]:
            lines.append(
                f"- 使上游失效的 ID：{len(task_summary['invalidated_source_ids'])}"
            )
    if task_summary.get("diagnostics"):
        lines.extend(["", "## 任务读取诊断", ""])
        lines.extend(
            f"- {markdown_escape(item.get('kind'))}: {markdown_escape(item.get('message', ''))}"
            for item in task_summary["diagnostics"][: args.max_items]
        )
    lines.extend(["", "## 未决 ID", ""])
    if index["unresolved_ids"]:
        lines.extend(f"- {markdown_escape(section_id)}" for section_id in index["unresolved_ids"])
    else:
        lines.append("- 无")
    atomic_write_text(output_path, "\n".join(lines) + "\n")
    return {
        "ok": True,
        "command": "render",
        "output": str(output_path),
        "semantic": index["summary"],
        "tasks": task_summary,
    }


def add_common(subparser: argparse.ArgumentParser, *, include_work_dir: bool = True) -> None:
    if include_work_dir:
        subparser.add_argument("--work-dir", required=True)
    subparser.add_argument("--view", choices=("model", "machine"), default="model")
    subparser.add_argument("--pretty", action="store_true")
    subparser.add_argument(
        "--model-token-budget", type=int, default=DEFAULT_MODEL_TOKEN_BUDGET
    )
    subparser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"workctl {WORKFLOW_CLI_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a delivery workspace")
    add_common(init_parser)
    init_parser.add_argument("--id", required=True)
    init_parser.add_argument("--title", required=True)
    init_parser.set_defaults(handler=init_workspace)

    outline_parser = subparsers.add_parser("outline", help="show one stage's compact contract")
    add_common(outline_parser)
    outline_parser.add_argument("--stage", choices=tuple(PUBLIC_STAGES), required=True)
    outline_parser.set_defaults(handler=outline_stage)

    protect_parser = subparsers.add_parser(
        "protect", help="protect user-confirmed requirements and user design"
    )
    add_common(protect_parser)
    protect_parser.add_argument("--confirmed-by", default="")
    protect_parser.add_argument("--confirmation-ref", default="")
    protect_parser.add_argument("--new-cycle", action="store_true")
    protect_parser.set_defaults(handler=protect_workspace)

    index_parser = subparsers.add_parser("index", help="rebuild the semantic index")
    add_common(index_parser)
    index_parser.set_defaults(handler=index_workspace)

    status_parser = subparsers.add_parser("status", help="summarize workflow and task state")
    add_common(status_parser)
    status_parser.set_defaults(handler=status_workspace)

    coverage_parser = subparsers.add_parser("coverage", help="show traceability diagnostics")
    add_common(coverage_parser)
    coverage_parser.set_defaults(handler=coverage_workspace)

    context_parser = subparsers.add_parser("context", help="return bounded context for one id")
    add_common(context_parser)
    context_parser.add_argument("--id", required=True)
    context_parser.add_argument("--depth", type=int, choices=range(0, 5), default=1)
    context_parser.add_argument("--budget", type=int, default=8_000)
    context_parser.set_defaults(handler=context_workspace)

    impact_parser = subparsers.add_parser("impact", help="show downstream references")
    add_common(impact_parser)
    impact_parser.add_argument("--id", required=True)
    impact_parser.set_defaults(handler=impact_workspace)

    render_parser = subparsers.add_parser("render", help="write a read-only workflow view")
    add_common(render_parser)
    render_parser.set_defaults(handler=render_workspace)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "max_items") and not 1 <= args.max_items <= 1_000:
        raise WorkctlError("--max-items must be between 1 and 1000")
    if hasattr(args, "budget") and not 1_000 <= args.budget <= 100_000:
        raise WorkctlError("--budget must be between 1000 and 100000")
    if not 256 <= args.model_token_budget <= 100_000:
        raise WorkctlError("--model-token-budget must be between 256 and 100000")
    if args.pretty and args.view != "machine":
        raise WorkctlError("--pretty requires --view machine")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
        result = args.handler(args)
        emit(
            result,
            pretty=args.pretty,
            view=args.view,
            model_token_budget=args.model_token_budget,
        )
        return 0
    except WorkctlError as exc:
        emit(
            exc.payload(),
            view=getattr(args, "view", "model"),
            model_token_budget=getattr(
                args, "model_token_budget", DEFAULT_MODEL_TOKEN_BUDGET
            ),
            stream=sys.stderr,
        )
        return 2
    except OSError as exc:
        error = WorkctlError(
            f"filesystem operation failed: {exc}",
            risk="the current filesystem operation could not complete safely",
            recovery="resolve the reported filesystem condition and retry",
            retryable=True,
        )
        emit(
            error.payload(),
            view=getattr(args, "view", "model"),
            model_token_budget=getattr(
                args, "model_token_budget", DEFAULT_MODEL_TOKEN_BUDGET
            ),
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
