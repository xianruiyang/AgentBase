#!/usr/bin/env python3
"""Index and query delivery workflow artifacts without judging their semantics."""

from __future__ import annotations

import argparse
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
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 20_000
DEFAULT_MAX_ITEMS = 50
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
DEFERRED_CHANGE_STATUSES = {"open", "unknown", "unresolved", "deferred", "待决", "未知", "延后"}
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
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        emit({"ok": False, "error": f"argument error: {message}"}, stream=sys.stderr)
        raise SystemExit(2)


def normalize_manifest_text(value: Any, field: str, *, writing: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkctlError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise WorkctlError(f"{field} must not be empty")
    if len(cleaned) > MAX_MANIFEST_TEXT:
        raise WorkctlError(f"{field} exceeds {MAX_MANIFEST_TEXT} characters")
    if not writing and value != cleaned:
        raise WorkctlError(f"{field} must not contain surrounding whitespace")
    return cleaned


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
        raise WorkctlError(f"missing file: {path}") from exc
    if size > limit:
        raise WorkctlError(f"file exceeds {limit} bytes: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkctlError(f"file is not UTF-8: {path}") from exc


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> Any:
    text = read_text_bounded(path, limit)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkctlError(f"invalid JSON in {path}: {exc}") from exc


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
        raise WorkctlError(f"refusing to overwrite protected baseline: {path}") from exc
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
        raise WorkctlError(f"manifest path must be relative: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkctlError(f"path escapes work directory: {relative}") from exc
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
            raise WorkctlError("delivery workspace is being updated by another process") from exc
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
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "delivery.workflow":
        raise WorkctlError(f"unsupported workflow manifest: {manifest_path}")
    normalize_manifest_text(manifest.get("id"), "workflow.json id")
    normalize_manifest_text(manifest.get("title"), "workflow.json title")
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
        raise WorkctlError("protected baseline must use a dedicated path")
    if task_table_path.exists():
        task_table = read_json(task_table_path)
        if not isinstance(task_table, dict) or task_table.get("schema") != "task.table":
            raise WorkctlError(f"unsupported task table manifest: {task_table_path}")
        if task_table.get("id") != manifest.get("id"):
            raise WorkctlError("task table belongs to a different workflow")
        storage_paths = []
        for field, default in (
            ("task_dir", "tasks"),
            ("state_dir", "state"),
            ("result_dir", "results"),
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
    return manifest


def file_fingerprint(path: Path) -> str:
    text = read_text_bounded(path, MAX_DOCUMENT_BYTES)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def verify_protected_baseline(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    baseline_path = resolve_inside(
        root, str(manifest.get("protected_baseline", "protected-baseline.json"))
    )
    if not baseline_path.exists():
        return {"status": "unprotected", "path": baseline_path.name, "protected_ids": 0}
    baseline = read_json(baseline_path)
    if not isinstance(baseline, dict) or baseline.get("schema") != "delivery.protected-baseline":
        raise WorkctlError(f"unsupported protected baseline: {baseline_path}")
    if baseline.get("workflow_id") != manifest.get("id"):
        raise WorkctlError("protected baseline belongs to a different workflow")
    if baseline.get("confirmed_by") != "user":
        raise WorkctlError("protected baseline must be confirmed by the user")
    confirmation_ref = normalize_manifest_text(
        baseline.get("confirmation_ref"), "protected baseline confirmation_ref"
    )
    documents = baseline.get("documents")
    if not isinstance(documents, dict):
        raise WorkctlError("protected baseline documents must be an object")
    protected_ids = 0
    for stage in PROTECTED_STAGES:
        record = documents.get(stage)
        if not isinstance(record, dict):
            raise WorkctlError(f"protected baseline is missing {stage}")
        expected_path = str(manifest["documents"][stage])
        if record.get("path") != expected_path:
            raise WorkctlError(f"protected baseline path mismatch for {stage}")
        current_fingerprint = file_fingerprint(resolve_inside(root, expected_path))
        if record.get("fingerprint") != current_fingerprint:
            raise WorkctlError(
                f"protected source changed: {expected_path}; restore it and record a deferred change"
            )
        ids = record.get("ids")
        if (
            not isinstance(ids, list)
            or any(not isinstance(value, str) for value in ids)
            or len(ids) != len(set(ids))
        ):
            raise WorkctlError(f"protected baseline ids are invalid for {stage}")
        actual_sections, _ = parse_document(resolve_inside(root, expected_path), stage)
        actual_ids = sorted(section["id"] for section in actual_sections)
        if sorted(ids) != actual_ids:
            raise WorkctlError(f"protected baseline ids do not match {expected_path}")
        if any(section_prefix(value) not in STAGE_PREFIXES[stage] for value in ids):
            raise WorkctlError(f"protected baseline contains an invalid {stage} id")
        protected_ids += len(ids)
    return {
        "status": "protected",
        "path": baseline_path.name,
        "confirmed_by": baseline.get("confirmed_by"),
        "confirmation_ref": confirmation_ref,
        "protected_ids": protected_ids,
    }


def section_prefix(section_id: str) -> str:
    return section_id.split("-", 1)[0]


def parse_document(path: Path, stage: str) -> tuple[list[dict[str, Any]], str]:
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
        sections.append(
            {
                "id": section_id,
                "title": title,
                "stage": stage,
                "document": path.name,
                "line": line_index + 1,
                "status": status,
                "references": refs,
                "body": body,
            }
        )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return sections, f"sha256:{digest}"


def build_index(root: Path) -> dict[str, Any]:
    manifest = load_manifest(root)
    baseline = verify_protected_baseline(root, manifest)
    all_sections: list[dict[str, Any]] = []
    document_hashes: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    for stage in STAGE_PREFIXES:
        path = resolve_inside(root, str(manifest["documents"][stage]))
        sections, digest = parse_document(path, stage)
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
    if len(all_sections) > MAX_RECORDS:
        raise WorkctlError(f"workflow contains more than {MAX_RECORDS} semantic sections")

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
    deferred_change_ids = sorted(
        section["id"]
        for section in all_sections
        if section_prefix(section["id"]) == "DCR"
        and section["status"].casefold() in DEFERRED_CHANGE_STATUSES
    )
    summary = {
        "section_count": len(all_sections),
        "stage_counts": dict(sorted(stage_counts.items())),
        "prefix_counts": dict(sorted(prefix_counts.items())),
        "unresolved_count": len(unresolved_ids),
        "deferred_change_count": len(deferred_change_ids),
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
    script_path = (
        Path(__file__).resolve().parents[2]
        / "task-table-manager"
        / "scripts"
        / "taskctl.py"
    )
    if not script_path.is_file():
        raise WorkctlError(f"task table manager is unavailable: {script_path}")
    spec = importlib.util.spec_from_file_location("_agentbase_taskctl", script_path)
    if spec is None or spec.loader is None:
        raise WorkctlError(f"task table manager is unreadable: {script_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        summary = module.task_storage_summary(root)
    except Exception as exc:
        taskctl_error = getattr(module, "TaskctlError", None)
        if taskctl_error is not None and isinstance(exc, taskctl_error):
            raise WorkctlError(f"task storage is invalid: {exc}") from exc
        raise WorkctlError(f"task table manager failed: {exc}") from exc
    if not isinstance(summary, dict):
        raise WorkctlError("task table manager returned an invalid storage summary")
    return summary


def init_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    workflow_id = normalize_manifest_text(args.id, "--id", writing=True)
    title = normalize_manifest_text(args.title, "--title", writing=True)
    root.mkdir(parents=True, exist_ok=True)
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
        for directory in ("tasks", "state", "results")
        if (root / directory).is_dir() and any((root / directory).iterdir())
    )
    if conflicts:
        raise WorkctlError(f"refusing to overwrite existing workspace files: {', '.join(conflicts)}")

    for directory in ("tasks", "state", "results"):
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
        "source_index": ".work-cache/index.json",
        "table_view": "TASK_TABLE.md",
    }
    atomic_write_json(root / "workflow.json", manifest)
    atomic_write_json(root / "task-table.json", table)
    return {
        "ok": True,
        "command": "init",
        "work_dir": str(root),
        "created": created_files + ["tasks/", "state/", "results/"],
        "pending": pending_files,
    }


def protect_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    with workspace_lock(root):
        return protect_workspace_locked(args, root)


def protect_workspace_locked(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    confirmation_ref = normalize_manifest_text(
        args.confirmation_ref, "--confirmation-ref", writing=True
    )
    manifest = load_manifest(root)
    baseline_path = resolve_inside(
        root, str(manifest.get("protected_baseline", "protected-baseline.json"))
    )
    if baseline_path.exists():
        raise WorkctlError(f"refusing to overwrite protected baseline: {baseline_path}")
    index = build_index(root)
    if index["duplicates"]:
        raise WorkctlError("cannot protect an ambiguous workflow with duplicate ids")
    protected_documents: dict[str, Any] = {}
    for stage in PROTECTED_STAGES:
        sections = [section for section in index["sections"] if section["stage"] == stage]
        misplaced = [
            section["id"]
            for section in sections
            if section_prefix(section["id"]) not in STAGE_PREFIXES[stage]
        ]
        if misplaced:
            raise WorkctlError(
                f"cannot protect {stage} with misplaced ids: {', '.join(misplaced[:10])}"
            )
        unconfirmed = [
            section["id"]
            for section in sections
            if section["status"].casefold() != "confirmed"
        ]
        if unconfirmed:
            raise WorkctlError(
                f"cannot protect {stage} with entries not marked confirmed: "
                f"{', '.join(unconfirmed[:10])}"
            )
        relative_path = str(manifest["documents"][stage])
        protected_documents[stage] = {
            "path": relative_path,
            "fingerprint": index["document_hashes"][stage],
            "ids": sorted(section["id"] for section in sections),
        }
    final_target_ids = [
        value
        for stage in PROTECTED_STAGES
        for value in protected_documents[stage]["ids"]
        if section_prefix(value) in {"REQ", "AC", "UDES"}
    ]
    if not final_target_ids:
        raise WorkctlError("cannot protect a workflow without a REQ, AC, or UDES target")
    for stage in PROTECTED_STAGES:
        relative_path = str(manifest["documents"][stage])
        if file_fingerprint(resolve_inside(root, relative_path)) != index["document_hashes"][stage]:
            raise WorkctlError(
                f"protected source changed while creating baseline: {relative_path}; retry"
            )
    baseline = {
        "schema": "delivery.protected-baseline",
        "workflow_id": manifest.get("id"),
        "confirmed_by": args.confirmed_by,
        "confirmation_ref": confirmation_ref,
        "documents": protected_documents,
    }
    written_text = exclusive_write_json(baseline_path, baseline)
    try:
        summary = verify_protected_baseline(root, manifest)
    except WorkctlError:
        try:
            if read_text_bounded(baseline_path, MAX_JSON_BYTES) == written_text:
                baseline_path.unlink()
        except (OSError, WorkctlError):
            pass
        raise
    return {
        "ok": True,
        "command": "protect",
        "baseline": summary,
        "note": "requirements and user design are protected for this execution closure",
    }


def outline_stage(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
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
        "document": DEFAULT_DOCUMENTS[stage],
        "heading": "## <ID> <title>",
        **outlines[stage],
    }


def index_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    manifest = load_manifest(root)
    cache_path = resolve_inside(root, str(manifest.get("semantic_index", ".work-cache/index.json")))
    atomic_write_json(cache_path, index)
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
        raise WorkctlError(f"unknown semantic id: {section_id}")
    if len(matches) > 1:
        raise WorkctlError(f"ambiguous semantic id: {section_id}")
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
                raise WorkctlError(f"ambiguous related semantic id: {neighbor}")
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
    return fit_context(payload, args.budget)


def impact_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.work_dir)
    index = build_index(root)
    unique_section(index, args.id)
    duplicates = set(index["duplicates"])
    affected: list[str] = []
    seen = {args.id}
    queue = deque([args.id])
    while queue:
        current = queue.popleft()
        for dependent in index["reverse_references"].get(current, []):
            if dependent in duplicates:
                raise WorkctlError(f"ambiguous related semantic id: {dependent}")
            if dependent not in seen:
                seen.add(dependent)
                affected.append(dependent)
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
    index = build_index(root)
    task_summary = task_status_summary(root)
    output_path = resolve_inside(root, str(manifest.get("status_view", "WORK_STATUS.md")))
    lines = [
        f"# {manifest.get('title') or manifest.get('id') or 'Delivery'} 状态",
        "",
        "> 本文件由 workctl 生成，只是可重建的复核导航；其中计数不定义语义、READY 或最终完成状态。",
        "",
        "## 受保护基线",
        "",
        f"- 状态：{index['protected_baseline']['status']}",
        f"- 受保护 ID：{index['protected_baseline']['protected_ids']}",
        f"- 确认者：{index['protected_baseline'].get('confirmed_by') or '未记录'}",
        f"- 确认引用：{index['protected_baseline'].get('confirmation_ref') or '未记录'}",
        "",
        "## 可修订语义闭合",
        "",
        "| 类型 | 数量 |",
        "| --- | ---: |",
    ]
    for prefix, count in sorted(index["summary"]["prefix_counts"].items()):
        lines.append(f"| {markdown_escape(prefix)} | {count} |")
    lines.extend(
        [
            f"| 未决条目 | {index['summary']['unresolved_count']} |",
            f"| 未解析引用 | {index['summary']['unknown_reference_count']} |",
            f"| 未解决延后讨论项 | {index['summary']['deferred_change_count']} |",
            "",
            "## 任务执行状态",
            "",
            "| 状态 | 数量 |",
            "| --- | ---: |",
        ]
    )
    for status, count in task_summary["counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            f"- 任务总数：{task_summary['task_count']}",
            f"- 需复核任务：{task_summary['counts']['review']}",
            "",
            "## 任务结果证据",
            "",
            f"- 当前有效结果：{task_summary['result_count']}",
            f"- 含验证结果：{task_summary['result_with_verification_count']}",
            f"- 含未决结果：{task_summary['result_with_unresolved_count']}",
            f"- 使上游失效的 ID：{len(task_summary['invalidated_source_ids'])}",
        ]
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
    subparser.add_argument("--pretty", action="store_true")
    subparser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
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
    protect_parser.add_argument("--confirmed-by", choices=("user",), required=True)
    protect_parser.add_argument("--confirmation-ref", required=True)
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
        result = args.handler(args)
        emit(result, pretty=args.pretty)
        return 0
    except WorkctlError as exc:
        emit({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2
    except OSError as exc:
        emit(
            {"ok": False, "error": f"filesystem operation failed: {exc}"},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
