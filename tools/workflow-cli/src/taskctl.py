#!/usr/bin/env python3
"""管理任务合同、依赖查询、执行状态和有界上下文。"""

from __future__ import annotations

import argparse
import copy
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_RESULT_RECORDS = 100_000
MAX_LIST_ITEMS = 200
MAX_STRING = 8_000
DEFAULT_LIMIT = 50
DEFAULT_BUDGET = 16_000
DEFAULT_MODEL_TOKEN_BUDGET = 2_048
WORKFLOW_CLI_VERSION = (
    Path(__file__).resolve().parents[1] / "VERSION"
).read_text(encoding="utf-8").strip()
TASK_ID_RE = re.compile(r"^T[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_ID_RE = re.compile(
    r"^(?:REQ|AC|CON|UDES|DEC|DES|OBS|GAP|SOL|DCR)-[A-Za-z0-9][A-Za-z0-9._-]*$"
)
SOURCE_SNAPSHOT_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_RECEIPT_RE = re.compile(r"^source-(T[A-Za-z0-9][A-Za-z0-9._-]*)-([1-9][0-9]*)$")
REVIEW_RECEIPT_RE = re.compile(r"^review-([1-9][0-9]*)$")
MAX_REVIEW_RECEIPTS = 32
STATE_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
STATUSES = ("todo", "claimed", "in_progress", "review", "blocked", "done", "retired")
ACTIVE_STATUSES = {"claimed", "in_progress", "review", "blocked"}
TERMINAL_STATUSES = {"done", "retired"}
EXECUTION_CHECKPOINT_TEXT_FIELDS = (
    "evidence_frontier",
    "active_consumer",
    "latest_evidence",
)
EXECUTION_CHECKPOINT_LIST_FIELDS = (
    "validation_case",
    "validated_coverage",
    "uncovered_dimensions",
    "invalidated_source_ids",
)
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


class TaskctlError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        gate_id: str = "TASK-INPUT-UNREADABLE",
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
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault(
            "formatter_class", argparse.ArgumentDefaultsHelpFormatter
        )
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        error = TaskctlError(
            f"argument error: {message}",
            recovery="correct the command arguments and retry",
            retryable=True,
        )
        emit(error.payload(), view=requested_view(), stream=sys.stderr)
        raise SystemExit(2)


def normalize_manifest_text(value: Any, field: str, *, writing: bool = False) -> str:
    if not isinstance(value, str):
        raise TaskctlError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise TaskctlError(f"{field} must not be empty")
    if len(cleaned) > MAX_STRING:
        raise TaskctlError(
            f"{field} exceeds {MAX_STRING} characters",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep manifest input bounded",
            recovery="shorten the manifest identity before retrying",
        )
    if not writing and value != cleaned:
        raise TaskctlError(f"{field} must not contain surrounding whitespace")
    return cleaned


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


def nonzero_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): count
        for key, count in value.items()
        if isinstance(count, int) and count != 0
    }


def task_status_model(payload: dict[str, Any]) -> dict[str, Any]:
    tasks: dict[str, Any] = {"total": payload.get("task_count", 0)}
    states = nonzero_counts(payload.get("status_counts"))
    if states:
        tasks["states"] = states
    if payload.get("dependency_attention_count"):
        tasks["dependency_attention"] = payload["dependency_attention_count"]
    upstream_source = payload.get("upstream", {})
    upstream: dict[str, Any] = {}
    for source_key, target_key in (
        ("unresolved_count", "unresolved"),
        ("deferred_change_count", "deferred_changes"),
        ("invalidated_source_ids", "invalidated"),
    ):
        value = upstream_source.get(source_key) if isinstance(upstream_source, dict) else None
        if value not in (None, 0, [], {}):
            upstream[target_key] = value
    result_source = payload.get("results", {})
    results: dict[str, Any] = {}
    for source_key, target_key in (
        ("referenced_result_count", "referenced"),
        ("result_with_verification_count", "verified"),
        ("result_with_unresolved_count", "unresolved"),
        ("result_with_diagnostics_count", "diagnosed"),
        ("task_revision_stale_result_count", "task_revision_stale"),
        ("source_snapshot_issue_result_count", "source_snapshot_issues"),
        ("result_diagnostic_count", "diagnostic_items"),
    ):
        value = result_source.get(source_key) if isinstance(result_source, dict) else None
        if value not in (None, 0):
            results[target_key] = value
    kind_counts = nonzero_counts(
        result_source.get("result_diagnostic_kind_counts", {})
        if isinstance(result_source, dict)
        else {}
    )
    if kind_counts:
        results["issues"] = kind_counts
    projected: dict[str, Any] = {"tasks": tasks}
    if payload.get("generated_at"):
        projected["generated_at"] = payload["generated_at"]
    if payload.get("active_frontiers"):
        projected["active_frontiers"] = copy.deepcopy(payload["active_frontiers"])
        active_frontier_count = payload.get("active_frontier_count", 0)
        if active_frontier_count > len(payload["active_frontiers"]):
            projected["active_frontiers_more"] = {
                "total": active_frontier_count,
                "returned": len(payload["active_frontiers"]),
                "recovery": "rerun status with a larger --limit or query one task with context",
            }
    if payload.get("state_writeback_drift_count"):
        projected["state_writeback_drift_count"] = payload[
            "state_writeback_drift_count"
        ]
    if upstream:
        projected["upstream"] = upstream
    if results:
        projected["results"] = results
    for key in ("index_diagnostics", "storage_diagnostics"):
        if payload.get(key):
            projected[key] = model_task_diagnostics(payload[key])
    return projected


def model_task_diagnostics(value: Any) -> Any:
    if isinstance(value, list):
        return [model_task_diagnostics(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    return {
        key: model_task_diagnostics(item)
        for key, item in value.items()
        if key not in {"snapshot_id", "source_snapshot_ref"}
    }


def task_context_model(payload: dict[str, Any]) -> dict[str, Any]:
    task = copy.deepcopy(payload.get("task", {}))
    if isinstance(task, dict):
        task.pop("schema", None)
    state = copy.deepcopy(payload.get("state", {}))
    if isinstance(state, dict):
        state.pop("schema", None)
        state.pop("task_id", None)
    projected: dict[str, Any] = {
        "task": sparse_model_value(task),
        "state": sparse_model_value(state),
    }
    for key in ("diagnostics", "upstream", "deferred_changes", "source_snapshot"):
        if payload.get(key):
            value = copy.deepcopy(payload[key])
            if key == "diagnostics":
                value = model_task_diagnostics(value)
            projected[key] = sparse_model_value(value)
    dependencies: list[dict[str, Any]] = []
    for dependency in payload.get("dependencies", []):
        row = {
            key: (
                model_task_diagnostics(dependency.get(key))
                if key == "diagnostics"
                else copy.deepcopy(dependency.get(key))
            )
            for key in ("id", "type", "status", "consumes", "diagnostics")
        }
        result = dependency.get("result")
        if isinstance(result, dict):
            row["result"] = {
                key: copy.deepcopy(result.get(key))
                for key in (
                    "outcome",
                    "outputs",
                    "verification",
                    "validation_coverage",
                    "unresolved",
                    "invalidated_source_ids",
                    "evidence_for",
                    "evidence_refs",
                )
            }
        dependencies.append(sparse_model_value(row))
    if dependencies:
        projected["dependencies"] = dependencies
    projected["source_snapshot_complete"] = bool(
        payload.get("source_snapshot_complete")
    )
    if payload.get("dependents"):
        projected["dependents"] = sparse_model_value(copy.deepcopy(payload["dependents"]))
    more = {
        key: value
        for key, value in payload.get("truncation", {}).items()
        if value
    }
    if payload.get("truncated") or more:
        projected["more"] = {
            "truncated": True,
            **more,
            "recovery": "narrow with show/deps/context or raise --model-token-budget",
        }
    return sparse_model_value(projected)


def task_completion_model(payload: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    if payload.get("review_receipt"):
        projected["review_receipt"] = payload["review_receipt"]
    counts = {
        "targets": payload.get("target_count", 0),
        "returned_targets": payload.get("returned_target_count", 0),
        "constraints": payload.get("constraint_count", 0),
        "returned_constraints": payload.get("returned_constraint_count", 0),
        "deferred_changes": payload.get("deferred_change_count", 0),
        "returned_deferred_changes": payload.get("returned_deferred_change_count", 0),
    }
    projected["review"] = {key: value for key, value in counts.items() if value}
    if payload.get("diagnostic_summary"):
        summary = sparse_model_value(copy.deepcopy(payload["diagnostic_summary"]))
        if isinstance(summary, dict):
            summary = {
                key: value
                for key, value in summary.items()
                if value not in (0, {}, [])
            }
        if summary:
            projected["diagnostics"] = summary
    if payload.get("query_diagnostics"):
        projected["query_diagnostics"] = model_task_diagnostics(
            payload["query_diagnostics"]
        )
    if payload.get("targets"):
        projected["targets"] = sparse_model_value(copy.deepcopy(payload["targets"]))
    candidates: dict[str, Any] = {}
    for task_id, candidate in payload.get("candidate_tasks", {}).items():
        row = {
            key: copy.deepcopy(candidate.get(key))
            for key in (
                "status",
                "result_ref",
                "result_outcome",
                "outputs",
                "verification",
                "validation_coverage",
                "unresolved",
                "invalidated_source_ids",
                "evidence_refs",
                "result_diagnostics",
            )
        }
        compacted = sparse_model_value(row)
        if isinstance(compacted, dict) and compacted.get("result_diagnostics"):
            compacted["result_diagnostics"] = model_task_diagnostics(
                compacted["result_diagnostics"]
            )
        if compacted:
            candidates[task_id] = compacted
    if candidates:
        projected["candidates"] = candidates
    for source_key, target_key in (
        ("constraints", "constraints"),
        ("deferred_changes", "deferred_changes"),
    ):
        if payload.get(source_key):
            projected[target_key] = sparse_model_value(copy.deepcopy(payload[source_key]))
    pagination = sparse_model_value(copy.deepcopy(payload.get("pagination", {})))
    if isinstance(pagination, dict):
        pagination = {
            key: value
            for key, value in pagination.items()
            if value not in (None, {}, [])
        }
    if pagination:
        projected["more"] = {
            "review_receipt": payload.get("review_receipt"),
            **pagination,
        }
    return sparse_model_value(projected)


def add_bounded_issues(
    projected: dict[str, Any],
    payload: dict[str, Any],
    items_key: str,
    count_key: str,
) -> None:
    items = model_task_diagnostics(payload.get(items_key))
    if items:
        projected[items_key] = sparse_model_value(copy.deepcopy(items))
    visible_count = len(items) if isinstance(items, list) else 0
    total_count = payload.get(count_key)
    if isinstance(total_count, int) and total_count > visible_count:
        projected[count_key] = total_count


def task_contract_write_model(payload: dict[str, Any]) -> dict[str, Any]:
    projected = {
        key: copy.deepcopy(payload.get(key))
        for key in ("task_id", "task_revision", "state_revision")
    }
    if payload.get("recovered_partial_write") is True:
        projected["recovered_partial_write"] = True
    table_view = payload.get("table_view")
    if isinstance(table_view, dict) and table_view.get("status") == "stale":
        projected["table_view"] = sparse_model_value(copy.deepcopy(table_view))
    add_bounded_issues(projected, payload, "diagnostics", "diagnostic_count")
    return sparse_model_value(projected)


def task_state_write_model(payload: dict[str, Any]) -> dict[str, Any]:
    command = payload.get("command")
    source_state = payload.get("state", {})
    state = {
        key: copy.deepcopy(source_state.get(key))
        for key in (
            "status",
            "owner",
            "note",
            "blocked_reason",
            "next_action",
            "evidence_frontier",
            "active_consumer",
            "validation_case",
            "validated_coverage",
            "uncovered_dimensions",
            "latest_evidence",
            "invalidated_source_ids",
            "result_ref",
            "started_at",
            "ended_at",
            "revision",
        )
        if isinstance(source_state, dict)
    }
    if command == "complete":
        state.pop("result_ref", None)
    projected: dict[str, Any] = {
        "id": payload.get("id"),
        "state": sparse_model_value(state),
    }
    if command == "complete":
        projected["result_ref"] = payload.get("result_ref")
        if payload.get("recovered_partial_write") is True:
            projected["recovered_partial_write"] = True
    table_view = payload.get("table_view")
    if isinstance(table_view, dict) and table_view.get("status") == "stale":
        projected["table_view"] = sparse_model_value(copy.deepcopy(table_view))
    add_bounded_issues(projected, payload, "warnings", "warning_count")
    add_bounded_issues(projected, payload, "diagnostics", "diagnostic_count")
    return sparse_model_value(projected)


def task_render_model(payload: dict[str, Any]) -> dict[str, Any]:
    summary = task_status_model(payload)
    tasks = summary.get("tasks")
    if isinstance(tasks, dict) and payload.get("needs_review_count"):
        tasks["needs_review"] = payload["needs_review_count"]
    return sparse_model_value(
        {
            "output": payload.get("output"),
            **summary,
        }
    )


def task_show_model(payload: dict[str, Any]) -> dict[str, Any]:
    task = copy.deepcopy(payload.get("task", {}))
    if isinstance(task, dict):
        task.pop("schema", None)
        task.pop("id", None)
    state = copy.deepcopy(payload.get("state", {}))
    if isinstance(state, dict):
        state.pop("schema", None)
        state.pop("task_id", None)
    result = copy.deepcopy(payload.get("result"))
    if isinstance(result, dict):
        result.pop("schema", None)
        result.pop("task_id", None)
        if result.get("current_for_task_revision") is True:
            result.pop("current_for_task_revision", None)
        if result.get("source_snapshot"):
            result["source_snapshot_count"] = len(result["source_snapshot"])
            result.pop("source_snapshot", None)
        if result.pop("source_snapshot_ref", None):
            result["source_snapshot"] = "captured"
    return sparse_model_value(
        {
            "id": payload.get("id"),
            "task": task,
            "state": state,
            "result": result,
            "diagnostics": model_task_diagnostics(payload.get("diagnostics", [])),
        }
    )


def task_page_more(
    payload: dict[str, Any], total_key: str, *, total_label: str = "total"
) -> dict[str, Any]:
    if not payload.get("truncated"):
        return {}
    return sparse_model_value(
        {
            total_label: payload.get(total_key),
            "after_id": payload.get("next_after_id"),
        }
    )


def task_list_model(payload: dict[str, Any]) -> dict[str, Any]:
    items = copy.deepcopy(payload.get("items", []))
    projected: dict[str, Any] = {
        "counts": nonzero_counts(payload.get("counts")),
        "items": items,
    }
    if not items:
        projected["matched_count"] = payload.get("matched_count", 0)
    more = task_page_more(payload, "matched_count")
    if more:
        projected["more"] = more
    add_bounded_issues(projected, payload, "diagnostics", "diagnostic_count")
    return sparse_model_value(projected)


def task_relation_model(payload: dict[str, Any], count_key: str) -> dict[str, Any]:
    items = copy.deepcopy(payload.get("items", []))
    projected: dict[str, Any] = {
        "id": payload.get("id"),
        "items": items,
    }
    if not items:
        projected[count_key] = payload.get(count_key, 0)
    more = task_page_more(payload, count_key)
    if more:
        projected["more"] = more
    add_bounded_issues(projected, payload, "diagnostics", "diagnostic_count")
    return sparse_model_value(projected)


def task_next_model(payload: dict[str, Any]) -> dict[str, Any]:
    items = copy.deepcopy(payload.get("items", []))
    for item in items:
        if isinstance(item, dict) and item.get("recommended") is True:
            item.pop("recommended", None)
    projected: dict[str, Any] = {"items": items}
    if not items:
        projected["candidate_count"] = payload.get("candidate_count", 0)
    more = task_page_more(payload, "candidate_count", total_label="candidate_count")
    if more:
        recommended_count = payload.get("recommended_count")
        if recommended_count != payload.get("candidate_count"):
            more["recommended_count"] = recommended_count
        projected["more"] = more
    add_bounded_issues(projected, payload, "diagnostics", "diagnostic_count")
    return sparse_model_value(projected)


def task_model_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        return sparse_model_value(payload, root=True)
    if payload.get("schema") == "task.record":
        candidate = copy.deepcopy(payload)
        candidate.pop("schema", None)
        candidate.pop("revision", None)
        return sparse_model_value(candidate, root=True)
    command = payload.get("command")
    if command == "status":
        return task_status_model(payload)
    if command == "context":
        return task_context_model(payload)
    if command == "completion-context":
        return task_completion_model(payload)
    if command in {"add", "update"}:
        return task_contract_write_model(payload)
    if command in {"claim", "start", "note", "complete", "reopen", "release"}:
        return task_state_write_model(payload)
    if command == "render":
        return task_render_model(payload)
    if command == "show":
        return task_show_model(payload)
    if command == "list":
        return task_list_model(payload)
    if command == "deps":
        return task_relation_model(payload, "dependency_count")
    if command in {"dependents", "impact"}:
        return task_relation_model(payload, "dependent_count")
    if command == "next":
        return task_next_model(payload)
    return sparse_model_value(copy.deepcopy(payload), root=True)


def bounded_frontier_text(
    value: Any,
    maximum: int,
    field: str,
    omitted_fields: list[str],
) -> Any:
    if not isinstance(value, str) or len(value) <= maximum:
        return value
    omitted_fields.append(field)
    return value[: maximum - 1] + "…"


def bounded_frontier_list(
    value: Any,
    maximum_items: int,
    maximum_item_chars: int,
    field: str,
    omitted_fields: list[str],
) -> Any:
    if not isinstance(value, list):
        return value
    projected = []
    for item in value[:maximum_items]:
        projected.append(
            bounded_frontier_text(
                item,
                maximum_item_chars,
                field,
                omitted_fields,
            )
        )
    if len(value) > maximum_items:
        omitted_fields.append(field)
    return projected


def compact_active_frontier(
    frontier: dict[str, Any], *, minimal: bool = False
) -> dict[str, Any]:
    projected: dict[str, Any] = {
        key: copy.deepcopy(frontier[key])
        for key in ("id", "status", "source")
        if frontier.get(key) not in (None, "", [], {})
    }
    omitted_fields: list[str] = []
    text_limits = (
        {
            "title": 64,
            "outcome": 96,
            "evidence_frontier": 120,
            "active_consumer": 80,
            "latest_evidence": 120,
            "next_action": 120,
        }
        if minimal
        else {
            "title": 120,
            "outcome": 160,
            "evidence_frontier": 240,
            "active_consumer": 160,
            "latest_evidence": 240,
            "next_action": 240,
        }
    )
    for field, maximum in text_limits.items():
        value = frontier.get(field)
        if value not in (None, ""):
            projected[field] = bounded_frontier_text(
                value, maximum, field, omitted_fields
            )
    if not minimal:
        for field, maximum_items, maximum_item_chars in (
            ("source_ids", 8, 80),
            ("mutation_scope", 4, 120),
            ("validation_dimensions", 4, 120),
            ("validation_case", 4, 120),
            ("validated_coverage", 4, 120),
            ("uncovered_dimensions", 4, 120),
            ("invalidated_source_ids", 8, 80),
        ):
            value = frontier.get(field)
            if value:
                projected[field] = bounded_frontier_list(
                    value,
                    maximum_items,
                    maximum_item_chars,
                    field,
                    omitted_fields,
                )
    drifts = frontier.get("state_writeback_drifts")
    if isinstance(drifts, list) and drifts:
        drift = drifts[0]
        if isinstance(drift, dict):
            projected["state_writeback_drift"] = {
                key: bounded_frontier_text(
                    drift[key],
                    160,
                    f"state_writeback_drifts.{key}",
                    omitted_fields,
                )
                for key in (
                    "kind",
                    "path",
                    "result_task_revision",
                    "current_task_revision",
                    "recovery",
                )
                if drift.get(key) not in (None, "")
            }
        if len(drifts) > 1:
            omitted_fields.append("state_writeback_drifts")
    retained_fields = set(projected)
    for field, value in frontier.items():
        if field not in retained_fields and value not in (None, "", [], {}):
            omitted_fields.append(field)
    if omitted_fields:
        projected["more"] = {
            "omitted_or_shortened": sorted(set(omitted_fields)),
            "recovery": "query this task with context",
        }
    return projected


def task_model_variants(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    projected = task_model_projection(payload)
    yield projected
    command = payload.get("command")
    if command == "context":
        candidate = copy.deepcopy(projected)
        candidate.pop("dependents", None)
        yield candidate
        upstream = candidate.get("upstream")
        omitted: list[str] = []
        if isinstance(upstream, list):
            while len(upstream) > 1:
                row = upstream.pop()
                if isinstance(row, dict) and row.get("id"):
                    omitted.append(str(row["id"]))
                candidate["more"] = {
                    **candidate.get("more", {}),
                    "upstream_ids": list(reversed(omitted)),
                    "recovery": "query an omitted upstream ID or raise --model-token-budget",
                }
                yield copy.deepcopy(candidate)
    elif command == "completion-context":
        candidate = copy.deepcopy(projected)
        for row in candidate.get("candidates", {}).values():
            for evidence in row.get("evidence_refs", []):
                if isinstance(evidence, dict):
                    evidence.pop("note", None)
        yield candidate
        targets = candidate.get("targets")
        while isinstance(targets, list) and len(targets) > 1:
            targets.pop()
            referenced = {
                task_id
                for target in targets
                for task_id in target.get("candidate_task_ids", [])
            }
            candidate["candidates"] = {
                task_id: row
                for task_id, row in candidate.get("candidates", {}).items()
                if task_id in referenced
            }
            last_id = targets[-1].get("id") if targets else None
            candidate["more"] = {
                **candidate.get("more", {}),
                "target_next_after_id": last_id,
                "review_receipt": payload.get("review_receipt"),
            }
            yield copy.deepcopy(candidate)
    elif command in {"status", "render"}:
        candidate = copy.deepcopy(projected)
        frontiers = candidate.get("active_frontiers")
        if isinstance(frontiers, list) and frontiers:
            for frontier in frontiers:
                body_omitted = False
                for deferred_change in frontier.get("deferred_changes", []):
                    if isinstance(deferred_change, dict):
                        body_omitted = (
                            deferred_change.pop("body", None) is not None
                            or body_omitted
                        )
                if body_omitted:
                    frontier["deferred_change_bodies"] = {
                        "omitted": True,
                        "recovery": "query this task with context",
                    }
            yield copy.deepcopy(candidate)
            while len(frontiers) > 1:
                frontiers.pop()
                candidate["active_frontiers_more"] = {
                    "total": payload.get("active_frontier_count", len(frontiers)),
                    "returned": len(frontiers),
                    "recovery": "rerun status with a larger model budget or query one task with context",
                }
                yield copy.deepcopy(candidate)
            compact = copy.deepcopy(candidate)
            compact["active_frontiers"] = [
                compact_active_frontier(frontier)
                for frontier in compact.get("active_frontiers", [])
            ]
            yield compact
            minimal = copy.deepcopy(candidate)
            minimal["active_frontiers"] = [
                compact_active_frontier(frontier, minimal=True)
                for frontier in minimal.get("active_frontiers", [])
            ]
            yield minimal


def context_model_receipt_candidate(
    candidate: dict[str, Any], *, capture: bool
) -> tuple[dict[str, Any], dict[str, str]]:
    projected = copy.deepcopy(candidate)
    original_snapshot = source_snapshot_map(
        projected.pop("source_snapshot", {}), "context.source_snapshot"
    )
    originally_complete = bool(projected.pop("source_snapshot_complete", False))
    visible_ids = {
        row.get("id")
        for section_name in ("upstream", "deferred_changes")
        for row in projected.get(section_name, [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    visible_snapshot = {
        source_id: fingerprint
        for source_id, fingerprint in original_snapshot.items()
        if source_id in visible_ids
    }
    complete = originally_complete and len(visible_snapshot) == len(original_snapshot)
    receipt: dict[str, Any] = {
        "count": len(visible_snapshot),
        "complete": complete,
    }
    if capture:
        receipt["ref"] = f"source-{candidate.get('id', 'T001')}-1"
    else:
        receipt["capture"] = "context --capture"
    projected["source_snapshot"] = receipt
    return projected, visible_snapshot


def fit_task_model_with_snapshot(
    payload: dict[str, Any], budget: int, *, capture: bool = False
) -> tuple[str, dict[str, str] | None, dict[str, Any] | None]:
    for candidate in task_model_variants(payload):
        snapshot = None
        rendered_candidate = candidate
        if payload.get("command") == "context":
            rendered_candidate, snapshot = context_model_receipt_candidate(
                candidate, capture=capture
            )
        text = render_model(rendered_candidate)
        if model_text_cost(text) <= budget:
            return text, snapshot if capture else None, rendered_candidate
    core: dict[str, Any] = {}
    for key in ("id", "task_id", "review_receipt", "error", "gate"):
        if payload.get(key) not in (None, "", [], {}):
            core[key] = payload[key]
    task = payload.get("task")
    if isinstance(task, dict):
        core["task"] = {
            key: task[key]
            for key in ("id", "title", "outcome", "source_ids")
            if task.get(key) not in (None, "", [], {})
        }
    state = payload.get("state")
    if isinstance(state, dict):
        core["state"] = {
            key: state[key]
            for key in (
                "status",
                "owner",
                "blocked_reason",
                "next_action",
                "evidence_frontier",
                "active_consumer",
                "validation_case",
                "validated_coverage",
                "uncovered_dimensions",
                "latest_evidence",
                "invalidated_source_ids",
                "revision",
            )
            if state.get(key) not in (None, "", [], {})
        }
    core["more"] = {
        "reason": "model_token_budget",
        "recovery": "narrow the query or continue with returned cursors",
    }
    text = render_model(sparse_model_value(core))
    if model_text_cost(text) <= budget:
        return text, None, None
    minimal = {
        "id": payload.get("id") or payload.get("task_id"),
        "more": {"reason": "model_token_budget", "recovery": "narrow the query"},
    }
    text = render_model(sparse_model_value(minimal))
    if model_text_cost(text) > budget:
        raise TaskctlError("--model-token-budget is too small for a recoverable response")
    return text, None, None


def fit_task_model(payload: dict[str, Any], budget: int) -> str:
    return fit_task_model_with_snapshot(payload, budget)[0]


def emit(
    value: Any,
    *,
    pretty: bool = False,
    view: str = "model",
    model_token_budget: int = DEFAULT_MODEL_TOKEN_BUDGET,
    capture_snapshot: Callable[[dict[str, str]], str] | None = None,
    stream: Any = sys.stdout,
) -> None:
    if view == "machine":
        if pretty:
            text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            text = compact_json(value)
    else:
        text, snapshot, rendered_candidate = fit_task_model_with_snapshot(
            value,
            model_token_budget,
            capture=capture_snapshot is not None,
        )
        if snapshot is not None and capture_snapshot is not None:
            actual_ref = capture_snapshot(snapshot)
            if rendered_candidate is None:
                raise TaskctlError("captured model response has no receipt projection")
            rendered_candidate["source_snapshot"]["ref"] = actual_ref
            text = render_model(rendered_candidate)
            if model_text_cost(text) > model_token_budget:
                raise TaskctlError("--model-token-budget is too small for a recoverable capture receipt")
    stream.write(text + "\n")


def read_text_bounded(path: Path, limit: int) -> str:
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise TaskctlError(f"missing file: {path}") from exc
    if size > limit:
        raise TaskctlError(
            f"file exceeds {limit} bytes: {path}",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep input and output resource use bounded",
            recovery="narrow or split the input before retrying",
        )
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
        raise TaskctlError(
            f"manifest path must be relative: {relative}",
            gate_id="TASK-PATH",
            risk="the command could read or write outside the selected task workspace",
            recovery="use the fixed task-workspace-relative path",
        )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise TaskctlError(
            f"path escapes task directory: {relative}",
            gate_id="TASK-PATH",
            risk="the command could read or write outside the selected task workspace",
            recovery="use a path contained by the task directory",
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
            raise TaskctlError(
                "task workspace is being updated by another process",
                gate_id="TASK-LOCK",
                risk="concurrent writes could overwrite task data",
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


def load_table(root: Path) -> dict[str, Any]:
    path = root / "task-table.json"
    table = read_json(path)
    if not isinstance(table, dict) or table.get("schema") != "task.table":
        raise TaskctlError(f"unsupported task table manifest: {path}")
    table_id = normalize_manifest_text(table.get("id"), "task-table.json id")
    table_title = semantic_string(table.get("title"), "task-table.json title")
    table_diagnostics = semantic_text_diagnostics(table_title, "task_table.title")
    resolved_paths: dict[str, Path] = {}
    for field, default in (
        ("task_dir", "tasks"),
        ("state_dir", "state"),
        ("result_dir", "results"),
        ("snapshot_dir", "snapshots"),
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
        resolved_paths["snapshot_dir"],
    ]
    if any(path == root for path in storage_paths):
        raise TaskctlError(
            "task, state, result, and snapshot storage must not use the workspace root"
        )
    if len(set(storage_paths)) != len(storage_paths):
        raise TaskctlError(
            "task, state, result, and snapshot storage must use distinct directories"
        )
    for index, left in enumerate(storage_paths):
        for right in storage_paths[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise TaskctlError(
                    "task, state, result, and snapshot storage directories must not overlap"
                )
    reserved_files = {(root / "task-table.json").resolve(), (root / "workflow.json").resolve()}
    workflow = load_workflow(root)
    if workflow is not None:
        if table_id != workflow.get("id"):
            raise TaskctlError("task table belongs to a different workflow")
        table_diagnostics.extend(workflow.get("_diagnostics", []))
        if table_title != workflow.get("title"):
            table_diagnostics.append(
                {
                    "kind": "task_table_title_differs_from_workflow",
                    "workflow_title": workflow.get("title"),
                    "task_table_title": table_title,
                }
            )
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
    table["_diagnostics"] = table_diagnostics
    return table


def table_paths(root: Path, table: dict[str, Any]) -> tuple[Path, Path, Path]:
    return (
        resolve_inside(root, str(table.get("task_dir", "tasks"))),
        resolve_inside(root, str(table.get("state_dir", "state"))),
        resolve_inside(root, str(table.get("result_dir", "results"))),
    )


def snapshot_directory(root: Path, table: dict[str, Any]) -> Path:
    return resolve_inside(root, str(table.get("snapshot_dir", "snapshots")))


def normalize_source_snapshot_ref(value: Any, field: str) -> str:
    reference = require_identity_string(value, field)
    if not SOURCE_SNAPSHOT_REF_RE.fullmatch(reference):
        raise TaskctlError(
            f"{field} must be a sha256 source snapshot reference",
            gate_id="TASK-INPUT-UNREADABLE",
            risk="the command cannot locate the exact immutable source snapshot",
            recovery="use the exact source snapshot reference returned by context --capture",
        )
    return reference


def source_snapshot_record(sources: dict[str, str]) -> dict[str, Any]:
    normalized = source_snapshot_map(sources, "source_snapshot.sources")
    body = {"schema": "task.source-snapshot", "sources": normalized}
    reference = "sha256:" + hashlib.sha256(compact_json(body).encode("utf-8")).hexdigest()
    return {**body, "ref": reference}


def source_snapshot_path(root: Path, table: dict[str, Any], reference: str) -> Path:
    normalized = normalize_source_snapshot_ref(reference, "source_snapshot_ref")
    digest = normalized.removeprefix("sha256:")
    return snapshot_directory(root, table) / f"{digest}.json"


def store_source_snapshot(
    root: Path, table: dict[str, Any], sources: dict[str, str]
) -> str:
    record = source_snapshot_record(sources)
    reference = record["ref"]
    path = source_snapshot_path(root, table, reference)
    if path.exists():
        existing = read_json(path)
        if existing != record:
            raise TaskctlError(
                "conflicting immutable source snapshot asset",
                gate_id="TASK-OVERWRITE",
                risk="the same content identity would resolve to different snapshot evidence",
                recovery="inspect the existing snapshot asset before retrying",
            )
    else:
        atomic_write_json(path, record)
    return reference


def source_receipt_index_path(root: Path, table: dict[str, Any]) -> Path:
    return snapshot_directory(root, table) / "source-receipts.json"


def load_source_receipt_index(root: Path, table: dict[str, Any]) -> dict[str, Any]:
    path = source_receipt_index_path(root, table)
    if not path.exists():
        return {"schema": "task.source-receipts", "handles": {}, "next_by_task": {}}
    raw = read_json(path)
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != "task.source-receipts"
        or not isinstance(raw.get("handles"), dict)
        or not isinstance(raw.get("next_by_task"), dict)
    ):
        raise TaskctlError(
            "source receipt index is invalid",
            gate_id="TASK-SNAPSHOT-CONFLICT",
            risk="a readable receipt could resolve to missing or competing provenance",
            recovery="inspect and repair the persistent source receipt index before retrying",
        )
    seen: dict[tuple[str, str], str] = {}
    maximum_by_task: dict[str, int] = {}
    if len(raw["handles"]) > MAX_RECORDS or len(raw["next_by_task"]) > MAX_RECORDS:
        raise TaskctlError("source receipt index exceeds the supported record limit", gate_id="TASK-LIMIT")
    for handle, reference in raw["handles"].items():
        match = SOURCE_RECEIPT_RE.fullmatch(str(handle))
        if match is None:
            raise TaskctlError("source receipt index contains an invalid handle", gate_id="TASK-SNAPSHOT-CONFLICT")
        normalized = normalize_source_snapshot_ref(reference, "source receipt reference")
        key = (match.group(1), normalized)
        if key in seen and seen[key] != handle:
            raise TaskctlError("source receipt index contains competing handles", gate_id="TASK-SNAPSHOT-CONFLICT")
        seen[key] = str(handle)
        maximum_by_task[match.group(1)] = max(
            maximum_by_task.get(match.group(1), 0), int(match.group(2))
        )
    for task_id, next_value in raw["next_by_task"].items():
        if (
            TASK_ID_RE.fullmatch(str(task_id)) is None
            or not isinstance(next_value, int)
            or isinstance(next_value, bool)
            or next_value < 1
            or next_value != maximum_by_task.get(str(task_id), 0) + 1
        ):
            raise TaskctlError(
                "source receipt index contains an invalid task sequence",
                gate_id="TASK-SNAPSHOT-CONFLICT",
                risk="a new readable receipt could reuse or skip a persistent identity",
                recovery="inspect and repair the persistent source receipt index before retrying",
            )
    if set(maximum_by_task) != set(raw["next_by_task"]):
        raise TaskctlError("source receipt index is missing a task sequence", gate_id="TASK-SNAPSHOT-CONFLICT")
    return raw


def store_source_receipt(
    root: Path, table: dict[str, Any], task_id: str, sources: dict[str, str]
) -> str:
    reference = store_source_snapshot(root, table, sources)
    index = load_source_receipt_index(root, table)
    for handle, existing_ref in index["handles"].items():
        match = SOURCE_RECEIPT_RE.fullmatch(handle)
        if match is not None and match.group(1) == task_id and existing_ref == reference:
            return handle
    next_value = index["next_by_task"].get(task_id, 1)
    if not isinstance(next_value, int) or next_value < 1:
        raise TaskctlError("source receipt sequence is invalid", gate_id="TASK-SNAPSHOT-CONFLICT")
    handle = f"source-{task_id}-{next_value}"
    if handle in index["handles"]:
        raise TaskctlError(
            "source receipt sequence conflicts with an existing handle",
            gate_id="TASK-SNAPSHOT-CONFLICT",
            risk="the new receipt would silently change an existing provenance identity",
            recovery="inspect and repair the persistent source receipt index before retrying",
        )
    index["handles"][handle] = reference
    index["next_by_task"][task_id] = next_value + 1
    atomic_write_json(source_receipt_index_path(root, table), index)
    return handle


def resolve_source_receipt(
    root: Path, table: dict[str, Any], handle: str, task_id: str
) -> str:
    match = SOURCE_RECEIPT_RE.fullmatch(require_identity_string(handle, "--source-receipt"))
    if match is None or match.group(1) != task_id:
        raise TaskctlError(
            "source receipt does not identify the completion task",
            gate_id="TASK-INPUT-UNREADABLE",
            risk="the completion could bind evidence captured for another task",
            recovery="use the source receipt returned by context --capture for this task",
        )
    index = load_source_receipt_index(root, table)
    reference = index["handles"].get(handle)
    if reference is None:
        raise TaskctlError(
            f"source receipt is unavailable: {handle}",
            gate_id="TASK-INPUT-UNREADABLE",
            risk="the completion provenance cannot be resolved",
            recovery="recapture this task context and retry with the returned source receipt",
            retryable=True,
        )
    return normalize_source_snapshot_ref(reference, "source receipt reference")


def review_receipt_path(root: Path) -> Path:
    return resolve_inside(root, ".work-cache/taskctl-review-receipts.json")


def load_review_receipts(root: Path) -> dict[str, Any]:
    path = review_receipt_path(root)
    if not path.exists():
        return {"schema": "task.review-receipts", "next": 1, "handles": {}}
    raw = read_json(path)
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != "task.review-receipts"
        or not isinstance(raw.get("next"), int)
        or raw["next"] < 1
        or not isinstance(raw.get("handles"), dict)
    ):
        raise TaskctlError(
            "review receipt cache is invalid",
            gate_id="TASK-SNAPSHOT-CONFLICT",
            risk="a review continuation could resolve to competing snapshots",
            recovery="remove the rebuildable review receipt cache and restart from the first page",
        )
    if len(raw["handles"]) > MAX_REVIEW_RECEIPTS:
        raise TaskctlError("review receipt cache exceeds its retention bound", gate_id="TASK-LIMIT")
    maximum = 0
    for handle, reference in raw["handles"].items():
        match = REVIEW_RECEIPT_RE.fullmatch(str(handle))
        if match is None:
            raise TaskctlError("review receipt cache contains an invalid handle", gate_id="TASK-SNAPSHOT-CONFLICT")
        maximum = max(maximum, int(match.group(1)))
        normalize_source_snapshot_ref(reference, "review receipt snapshot")
    if raw["next"] != maximum + 1:
        raise TaskctlError("review receipt cache sequence is invalid", gate_id="TASK-SNAPSHOT-CONFLICT")
    return raw


def store_review_receipt(root: Path, snapshot_id: str) -> str:
    cache = load_review_receipts(root)
    for handle, existing in cache["handles"].items():
        if existing == snapshot_id:
            return handle
    handle = f"review-{cache['next']}"
    if handle in cache["handles"]:
        raise TaskctlError("review receipt sequence conflicts with an existing handle", gate_id="TASK-SNAPSHOT-CONFLICT")
    cache["handles"][handle] = snapshot_id
    cache["next"] += 1
    ordered = sorted(
        cache["handles"].items(),
        key=lambda item: int(REVIEW_RECEIPT_RE.fullmatch(item[0]).group(1)),
    )
    cache["handles"] = dict(ordered[-MAX_REVIEW_RECEIPTS:])
    atomic_write_json(review_receipt_path(root), cache)
    return handle


def resolve_review_receipt(root: Path, handle: str) -> str:
    normalized = require_identity_string(handle, "--review-receipt")
    if REVIEW_RECEIPT_RE.fullmatch(normalized) is None:
        raise TaskctlError("--review-receipt must be a readable review sequence")
    reference = load_review_receipts(root)["handles"].get(normalized)
    if reference is None:
        raise TaskctlError(
            f"review receipt is unavailable: {normalized}",
            gate_id="TASK-PAGINATION-SNAPSHOT",
            risk="the continuation cannot prove that its cursors belong to the current review snapshot",
            recovery="restart completion-context from the first page without old cursors",
            retryable=True,
        )
    return normalize_source_snapshot_ref(reference, "review receipt snapshot")


def read_source_snapshot(
    root: Path, table: dict[str, Any], reference: str, task_id: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    path = source_snapshot_path(root, table, reference)
    if not path.is_file():
        return {}, [
            {
                "kind": "result_source_snapshot_asset_missing",
                "task_id": task_id,
                "source_snapshot_ref": reference,
            }
        ]
    try:
        raw = read_json(path)
        if not isinstance(raw, dict) or raw.get("schema") != "task.source-snapshot":
            raise TaskctlError("source snapshot asset has an unsupported schema")
        sources = source_snapshot_map(raw.get("sources"), "source_snapshot.sources")
        expected = source_snapshot_record(sources)
        if raw.get("ref") != reference or expected != raw:
            return {}, [
                {
                    "kind": "result_source_snapshot_asset_identity_mismatch",
                    "task_id": task_id,
                    "source_snapshot_ref": reference,
                }
            ]
        return sources, []
    except (OSError, TaskctlError) as exc:
        return {}, [
            {
                "kind": "result_source_snapshot_asset_invalid",
                "task_id": task_id,
                "source_snapshot_ref": reference,
                "message": "source snapshot asset is unreadable or invalid",
            }
        ]


def require_completion_source_snapshot(
    root: Path, table: dict[str, Any], reference: str, task_id: str
) -> None:
    _, diagnostics = read_source_snapshot(root, table, reference, task_id)
    if not diagnostics:
        return
    issue = diagnostics[0]
    raise TaskctlError(
        f"completion source snapshot cannot be resolved: {issue['kind']}",
        gate_id="TASK-INPUT-UNREADABLE",
        risk="the completion would persist a result with a missing, unreadable, or identity-mismatched provenance asset",
        scope="current completion write",
        recovery="restore the referenced immutable snapshot or recapture the execution context and retry with the returned reference",
        retryable=True,
    )


def require_identity_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise TaskctlError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise TaskctlError(f"{field} must not be empty")
    if len(cleaned) > MAX_STRING:
        raise TaskctlError(
            f"{field} exceeds {MAX_STRING} characters",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep structured input and output bounded",
            recovery="shorten the identity value before retrying",
        )
    return cleaned


def semantic_string(value: Any, field: str) -> str:
    """Preserve parseable semantic text; only type and resource bounds are gates."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TaskctlError(f"{field} must be a string")
    if len(value) > MAX_STRING:
        raise TaskctlError(
            f"{field} exceeds {MAX_STRING} characters",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep structured input and output bounded",
            recovery="shorten or split the semantic value before retrying",
        )
    return value


def string_list(value: Any, field: str, *, maximum: int = MAX_LIST_ITEMS) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskctlError(f"{field} must be an array")
    if len(value) > maximum:
        raise TaskctlError(
            f"{field} contains more than {maximum} items",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep structured input and output bounded",
            recovery="split or reduce the list before retrying",
        )
    return [semantic_string(item, f"{field}[]") for item in value]


def evidence_ref_list(value: Any, field: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskctlError(f"{field} must be an array")
    if len(value) > MAX_LIST_ITEMS:
        raise TaskctlError(
            f"{field} must contain at most {MAX_LIST_ITEMS} objects",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep structured evidence input bounded",
            recovery="split or reduce the evidence references before retrying",
        )
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskctlError(f"{field}[{index}] must be an object")
        row = {"ref": semantic_string(item.get("ref"), f"{field}[{index}].ref")}
        for key in ("kind", "note"):
            if item.get(key) is not None:
                row[key] = semantic_string(item.get(key), f"{field}[{index}].{key}")
        normalized.append(row)
    return normalized


def source_snapshot_map(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TaskctlError(f"{field} must be an object")
    if len(value) > MAX_LIST_ITEMS:
        raise TaskctlError(
            f"{field} must contain at most {MAX_LIST_ITEMS} entries",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep source snapshot input bounded",
            recovery="split or reduce the source snapshot before retrying",
        )
    normalized: dict[str, str] = {}
    for source_id, fingerprint in value.items():
        source_id = semantic_string(source_id, f"{field} key")
        normalized[source_id] = semantic_string(fingerprint, f"{field}[{source_id}]")
    return dict(sorted(normalized.items()))


def validate_relative(
    value: str,
    field: str,
    *,
    allow_glob: bool = True,
    storage_path: bool = False,
) -> str:
    if not storage_path:
        return semantic_string(value, field)
    cleaned = require_identity_string(value, field).replace("\\", "/")
    if Path(cleaned).is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
        raise TaskctlError(
            f"{field} must be project-relative: {value}",
            gate_id="TASK-PATH",
            risk="a storage pointer could resolve outside the selected task workspace",
            recovery="use a task-workspace-relative result path",
        )
    pieces = [piece for piece in cleaned.split("/") if piece not in ("", ".")]
    if ".." in pieces:
        raise TaskctlError(
            f"{field} escapes the project: {value}",
            gate_id="TASK-PATH",
            risk="a storage pointer could resolve outside the selected task workspace",
            recovery="remove parent traversal from the result path",
        )
    if not allow_glob and any(token in cleaned for token in ("*", "?", "[", "]")):
        raise TaskctlError(
            f"{field} must not contain glob syntax: {value}",
            gate_id="TASK-PATH",
            risk="a storage pointer containing glob syntax would not identify one file",
            recovery="use one literal task-workspace-relative result path",
        )
    return cleaned


def is_project_relative_reference(value: str, *, allow_glob: bool = True) -> bool:
    cleaned = value.replace("\\", "/")
    if Path(cleaned).is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
        return False
    pieces = [piece for piece in cleaned.split("/") if piece not in ("", ".")]
    if ".." in pieces:
        return False
    return allow_glob or not any(token in cleaned for token in ("*", "?", "[", "]"))


def semantic_text_diagnostics(
    value: str, field: str, *, task_id: str | None = None
) -> list[dict[str, Any]]:
    diagnostic: dict[str, Any] = {"field": field}
    if task_id is not None:
        diagnostic["task_id"] = task_id
    if not value.strip():
        return [{"kind": "semantic_text_empty", **diagnostic}]
    if value != value.strip():
        return [{"kind": "semantic_text_surrounding_whitespace", **diagnostic}]
    return []


def normalize_task_body(
    raw: Any, task_id: str, revision: int
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskctlError("task input must be an object")
    source_ids = string_list(raw.get("source_ids"), "task.source_ids")

    raw_dependencies = raw.get("dependencies", [])
    if not isinstance(raw_dependencies, list):
        raise TaskctlError("task.dependencies must be an array")
    if len(raw_dependencies) > MAX_LIST_ITEMS:
        raise TaskctlError(
            f"task.dependencies must contain at most {MAX_LIST_ITEMS} items",
            gate_id="TASK-LIMIT",
            risk="the command cannot keep task dependency input bounded",
            recovery="split or reduce the dependency list before retrying",
        )
    dependencies: list[dict[str, Any]] = []
    for index, dependency in enumerate(raw_dependencies):
        if not isinstance(dependency, dict):
            raise TaskctlError(f"task.dependencies[{index}] must be an object")
        dependency_id = semantic_string(dependency.get("id"), f"task.dependencies[{index}].id")
        dependency_type = semantic_string(
            dependency.get("type"), f"task.dependencies[{index}].type"
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

    mutation_scope = [
        validate_relative(value, "task.mutation_scope[]")
        for value in string_list(raw.get("mutation_scope"), "task.mutation_scope")
    ]
    reasoning_hint = raw.get("reasoning_hint")
    if reasoning_hint is not None:
        reasoning_hint = semantic_string(reasoning_hint, "task.reasoning_hint")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TaskctlError("task.metadata must be an object")
    normalized = {
        "schema": "task.record",
        "id": task_id,
        "title": semantic_string(raw.get("title"), "task.title"),
        "outcome": semantic_string(raw.get("outcome"), "task.outcome"),
        "source_ids": source_ids,
        "dependencies": dependencies,
        "mutation_scope": mutation_scope,
        "outputs": string_list(raw.get("outputs"), "task.outputs"),
        "verification": string_list(raw.get("verification"), "task.verification"),
        "validation_dimensions": string_list(
            raw.get("validation_dimensions"), "task.validation_dimensions"
        ),
        "suggested_skills": string_list(
            raw.get("suggested_skills"), "task.suggested_skills"
        ),
        "reasoning_hint": reasoning_hint,
        "revision": revision,
    }
    if metadata:
        normalized["metadata"] = metadata
    return normalized


def validate_task(raw: Any, *, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "task.record":
        raise TaskctlError("task file must use schema task.record")
    task_id = require_identity_string(raw.get("id"), "task.id")
    if not TASK_ID_RE.fullmatch(task_id):
        raise TaskctlError(f"invalid task id: {task_id}")
    if expected_id is not None and task_id != expected_id:
        raise TaskctlError(f"task id mismatch: expected {expected_id}, got {task_id}")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise TaskctlError("task.revision must be a positive integer")
    return normalize_task_body(raw, task_id, revision)


def normalize_task_authoring_input(raw: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, dict):
        raise TaskctlError("task authoring input must be an object")
    if raw.get("schema") == "task.record":
        return validate_task(raw), True
    machine_fields = sorted(
        field for field in ("schema", "revision") if field in raw
    )
    if machine_fields:
        raise TaskctlError(
            "semantic task input contains machine-owned fields: "
            + ", ".join(machine_fields),
            risk="the model task body would duplicate schema or revision lifecycle owned by the task write command",
            recovery="remove the reported fields and use --expected-task-revision when updating an existing task",
            retryable=True,
        )
    task_id = require_identity_string(raw.get("id"), "task.id")
    if not TASK_ID_RE.fullmatch(task_id):
        raise TaskctlError(f"invalid task id: {task_id}")
    return normalize_task_body(raw, task_id, 1), False


def utc_now_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def optional_state_timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not STATE_TIMESTAMP_RE.fullmatch(value):
        raise TaskctlError(f"{field} must be a UTC RFC3339 timestamp or null")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise TaskctlError(f"{field} must be a valid UTC RFC3339 timestamp") from exc
    return value


def validate_state(raw: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != "task.state":
        raise TaskctlError(f"state for {task_id} must use schema task.state")
    if raw.get("task_id") != task_id:
        raise TaskctlError(f"state identity mismatch for {task_id}")
    status = raw.get("status")
    status = semantic_string(status, f"state.status[{task_id}]")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise TaskctlError(f"state revision for {task_id} must be a positive integer")
    owner = raw.get("owner")
    if owner is not None:
        owner = semantic_string(owner, f"state.owner[{task_id}]")
    result_ref = raw.get("result_ref")
    if result_ref is not None:
        result_ref = validate_relative(
            require_identity_string(result_ref, f"state.result_ref[{task_id}]"),
            f"state.result_ref[{task_id}]",
            allow_glob=False,
            storage_path=True,
        )
    blocked_reason = semantic_string(
        raw.get("blocked_reason", ""), f"state.blocked_reason[{task_id}]"
    )
    return {
        "schema": "task.state",
        "task_id": task_id,
        "status": status,
        "owner": owner,
        "revision": revision,
        "started_at": optional_state_timestamp(
            raw.get("started_at"), f"state.started_at[{task_id}]"
        ),
        "ended_at": optional_state_timestamp(
            raw.get("ended_at"), f"state.ended_at[{task_id}]"
        ),
        "note": semantic_string(raw.get("note", ""), f"state.note[{task_id}]"),
        "blocked_reason": blocked_reason,
        "next_action": semantic_string(
            raw.get("next_action", ""), f"state.next_action[{task_id}]"
        ),
        "evidence_frontier": semantic_string(
            raw.get("evidence_frontier", ""),
            f"state.evidence_frontier[{task_id}]",
        ),
        "active_consumer": semantic_string(
            raw.get("active_consumer", ""), f"state.active_consumer[{task_id}]"
        ),
        "validation_case": string_list(
            raw.get("validation_case"), f"state.validation_case[{task_id}]"
        ),
        "validated_coverage": string_list(
            raw.get("validated_coverage"),
            f"state.validated_coverage[{task_id}]",
        ),
        "uncovered_dimensions": string_list(
            raw.get("uncovered_dimensions"),
            f"state.uncovered_dimensions[{task_id}]",
        ),
        "latest_evidence": semantic_string(
            raw.get("latest_evidence", ""), f"state.latest_evidence[{task_id}]"
        ),
        "invalidated_source_ids": string_list(
            raw.get("invalidated_source_ids"),
            f"state.invalidated_source_ids[{task_id}]",
        ),
        "result_ref": result_ref,
    }


def clear_execution_checkpoint(state: dict[str, Any]) -> None:
    for field in EXECUTION_CHECKPOINT_TEXT_FIELDS:
        state[field] = ""
    for field in EXECUTION_CHECKPOINT_LIST_FIELDS:
        state[field] = []


def normalize_result_body(
    raw: Any, task: dict[str, Any], task_revision: int
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskctlError("result input must be an object")
    changed_files = [
        validate_relative(value, "result.changed_files[]", allow_glob=False)
        for value in string_list(raw.get("changed_files"), "result.changed_files")
    ]
    invalidated_ids = string_list(
        raw.get("invalidated_source_ids"), "result.invalidated_source_ids"
    )
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TaskctlError("result.metadata must be an object")
    result = {
        "schema": "task.result",
        "task_id": task["id"],
        "task_revision": task_revision,
        "outcome": semantic_string(raw.get("outcome"), "result.outcome"),
        "outputs": string_list(raw.get("outputs"), "result.outputs"),
        "changed_files": changed_files,
        "verification": string_list(raw.get("verification"), "result.verification"),
        "validation_coverage": string_list(
            raw.get("validation_coverage"), "result.validation_coverage"
        ),
        "unresolved": string_list(raw.get("unresolved"), "result.unresolved"),
        "invalidated_source_ids": invalidated_ids,
        "evidence_for": string_list(raw.get("evidence_for"), "result.evidence_for"),
        "evidence_refs": evidence_ref_list(raw.get("evidence_refs"), "result.evidence_refs"),
    }
    if metadata:
        result["metadata"] = metadata
    return result


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
    result = normalize_result_body(raw, task, result_revision)
    inline_snapshot = source_snapshot_map(
        raw.get("source_snapshot"), "result.source_snapshot"
    )
    snapshot_ref = None
    if raw.get("source_snapshot_ref") not in (None, ""):
        snapshot_ref = normalize_source_snapshot_ref(
            raw.get("source_snapshot_ref"), "result.source_snapshot_ref"
        )
    if inline_snapshot and snapshot_ref is not None:
        raise TaskctlError(
            "result must not contain both source_snapshot and source_snapshot_ref",
            gate_id="TASK-SNAPSHOT-CONFLICT",
            risk="the completion would create two competing sources for execution provenance",
            recovery="use the captured reference or the legacy inline map, not both",
        )
    if inline_snapshot:
        result["source_snapshot"] = inline_snapshot
    if snapshot_ref is not None:
        result["source_snapshot_ref"] = snapshot_ref
    return result


def normalize_completion_result(
    raw: Any, task: dict[str, Any], task_revision: int
) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, dict):
        raise TaskctlError("completion result input must be an object")
    if raw.get("schema") == "task.result":
        return (
            validate_result_for_task(raw, task, require_current_revision=True),
            True,
        )
    machine_fields = sorted(
        field
        for field in (
            "schema",
            "task_id",
            "task_revision",
            "source_snapshot",
            "source_snapshot_ref",
        )
        if field in raw
    )
    if machine_fields:
        raise TaskctlError(
            "semantic completion input contains machine-owned fields: "
            + ", ".join(machine_fields),
            risk="the model result would duplicate task identity, revision, or provenance owned by the completion command",
            recovery="remove the reported fields; pass task identity, expected revisions, and the snapshot receipt as command arguments",
            retryable=True,
        )
    return normalize_result_body(raw, task, task_revision), False


def hydrate_result_source_snapshot(
    root: Path, table: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    hydrated = copy.deepcopy(result)
    reference = hydrated.get("source_snapshot_ref")
    if reference:
        sources, diagnostics = read_source_snapshot(
            root, table, reference, hydrated["task_id"]
        )
        hydrated["source_snapshot"] = sources
        hydrated["_source_snapshot_diagnostics"] = diagnostics
    return hydrated


def public_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }


def load_state(root: Path, table: dict[str, Any], task_id: str) -> dict[str, Any]:
    _, state_dir, _ = table_paths(root, table)
    path = (state_dir / f"{task_id}.json").resolve()
    if path.parent != state_dir:
        raise TaskctlError(f"task state escapes state storage: {path}")
    return validate_state(read_json(path), task_id)


def load_query_storage(
    root: Path, table: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    task_dir, state_dir, _ = table_paths(root, table)
    diagnostics: list[dict[str, Any]] = list(table.get("_diagnostics", []))
    if not task_dir.exists():
        return {}, {}, [
            *diagnostics,
            {"kind": "task_directory_missing", "path": str(task_dir)},
        ]
    task_paths = sorted(task_dir.glob("*.json"))
    if len(task_paths) > MAX_RECORDS:
        raise TaskctlError(
            f"task directory contains more than {MAX_RECORDS} records",
            gate_id="TASK-LIMIT",
            risk="the query cannot keep record processing bounded",
            recovery="split or archive the task workspace before retrying",
        )
    tasks: dict[str, dict[str, Any]] = {}
    for path in task_paths:
        resolved = path.resolve()
        if resolved.parent != task_dir:
            diagnostics.append(
                {"kind": "task_record_outside_storage", "path": str(path)}
            )
            continue
        try:
            task = validate_task(read_json(resolved), expected_id=resolved.stem)
        except (OSError, TaskctlError) as exc:
            diagnostics.append(
                {
                    "kind": "task_record_unreadable",
                    "id": resolved.stem,
                    "message": str(exc),
                }
            )
            continue
        tasks[task["id"]] = task
    known_task_ids = set(tasks)
    state_paths = sorted(state_dir.glob("*.json")) if state_dir.exists() else []
    if len(state_paths) > MAX_RECORDS:
        raise TaskctlError(
            f"state directory contains more than {MAX_RECORDS} records",
            gate_id="TASK-LIMIT",
            risk="the query cannot keep record processing bounded",
            recovery="split or archive the task workspace before retrying",
        )
    state_ids = {path.stem for path in state_paths}
    states: dict[str, dict[str, Any]] = {}
    for task_id in sorted(tasks):
        if task_id not in state_ids:
            diagnostics.append({"kind": "task_state_missing", "id": task_id})
            continue
        try:
            states[task_id] = load_state(root, table, task_id)
        except (OSError, TaskctlError) as exc:
            diagnostics.append(
                {"kind": "task_state_unreadable", "id": task_id, "message": str(exc)}
            )
    usable_ids = set(states)
    tasks = {task_id: task for task_id, task in tasks.items() if task_id in usable_ids}
    for extra_id in sorted(state_ids - known_task_ids):
        diagnostics.append({"kind": "orphan_task_state", "id": extra_id})
    cycle_ids = ensure_acyclic(tasks)
    if cycle_ids:
        diagnostics.append({"kind": "dependency_cycle", "task_ids": cycle_ids[:20]})
    return tasks, states, diagnostics


def result_history_diagnostics(
    root: Path,
    table: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    _, _, result_dir = table_paths(root, table)
    paths = sorted(result_dir.glob(f"{task['id']}.r*.json"))
    if len(paths) > MAX_RESULT_RECORDS:
        raise TaskctlError(
            f"task {task['id']} has more than {MAX_RESULT_RECORDS} result records",
            gate_id="TASK-LIMIT",
            risk="the query cannot keep result-history processing bounded",
            recovery="archive or split the task result history before retrying",
        )
    diagnostics: list[dict[str, Any]] = []
    invalid_count = 0
    returned_invalid_count = 0
    for path in paths:
        try:
            path = path.resolve()
            if path.parent != result_dir:
                raise TaskctlError(f"task result history escapes result storage: {path}")
            match = re.fullmatch(
                rf"{re.escape(task['id'])}\.r(?P<revision>[1-9][0-9]*)\.json",
                path.name,
            )
            if match is None:
                raise TaskctlError(f"invalid task result history name: {path}")
            storage_revision = int(match.group("revision"))
            maximum_revision = state["revision"] + 1
            if storage_revision > maximum_revision:
                raise TaskctlError(
                    f"task result history revision is ahead of task state: {path}"
                )
            historical = validate_result_for_task(
                read_json(path), task, require_current_revision=False
            )
            if historical["task_id"] != task["id"]:
                raise TaskctlError(f"task result history identity mismatch: {path}")
            relative_ref = path.relative_to(root).as_posix()
            if (
                storage_revision == maximum_revision
                and state.get("result_ref") != relative_ref
            ):
                same_task_revision = historical["task_revision"] == task["revision"]
                diagnostics.append(
                    {
                        "kind": "result_history_state_write_drift",
                        "task_id": task["id"],
                        "path": relative_ref,
                        "state_revision": state["revision"],
                        "result_revision": storage_revision,
                        "result_task_revision": historical["task_revision"],
                        "current_task_revision": task["revision"],
                        "message": (
                            "a structurally valid, identity-matching next-revision "
                            "result exists but the current task state does not reference it"
                        ),
                        "recovery": (
                            "inspect the existing result, then retry complete with the same "
                            "expected state revision and a reconciled identical result; a "
                            "superseded attempt must first be recorded with a CAS state note, "
                            "and a conflicting overwrite remains TASK-OVERWRITE"
                            if same_task_revision
                            else "inspect the result from the earlier task revision, then use "
                            "a CAS state note to record that the stale attempt was superseded "
                            "before completing against the current task contract; do not "
                            "overwrite the occupied result path"
                        ),
                    }
                )
        except (OSError, TaskctlError) as exc:
            invalid_count += 1
            if returned_invalid_count < DEFAULT_LIMIT:
                diagnostics.append(
                    {
                        "kind": "result_history_record_unreadable",
                        "task_id": task["id"],
                        "path": str(path),
                        "message": str(exc),
                    }
                )
                returned_invalid_count += 1
    if invalid_count > returned_invalid_count:
        diagnostics.append(
            {
                "kind": "result_history_diagnostics_truncated",
                "task_id": task["id"],
                "invalid_count": invalid_count,
                "returned_count": returned_invalid_count,
            }
        )
    return diagnostics


def load_workflow(root: Path) -> dict[str, Any] | None:
    path = root / "workflow.json"
    if not path.exists():
        return None
    workflow = read_json(path)
    if not isinstance(workflow, dict) or workflow.get("schema") != "delivery.workflow":
        raise TaskctlError(f"unsupported workflow manifest: {path}")
    workflow_id = workflow.get("id")
    normalize_manifest_text(workflow_id, "workflow.json id")
    workflow_title = semantic_string(workflow.get("title"), "workflow.json title")
    workflow["_diagnostics"] = semantic_text_diagnostics(
        workflow_title, "workflow.title"
    )
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


def ensure_acyclic(tasks: dict[str, dict[str, Any]]) -> list[str]:
    graph: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    reverse: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task_id, task in tasks.items():
        for dependency in task["dependencies"]:
            dependency_id = dependency["id"]
            if dependency_id not in tasks:
                continue
            graph[task_id].append(dependency_id)
            reverse[dependency_id].append(task_id)
    for values in graph.values():
        values[:] = sorted(set(values))
    for values in reverse.values():
        values[:] = sorted(set(values))

    visited: set[str] = set()
    finish_order: list[str] = []
    for start in sorted(graph):
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                finish_order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for neighbor in reversed(graph[node]):
                if neighbor not in visited:
                    stack.append((neighbor, False))

    assigned: set[str] = set()
    cycle_ids: set[str] = set()
    for start in reversed(finish_order):
        if start in assigned:
            continue
        component: list[str] = []
        stack = [start]
        assigned.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in reverse[node]:
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    stack.append(neighbor)
        if len(component) > 1 or start in graph[start]:
            cycle_ids.update(component)
    return sorted(cycle_ids)


def rebuild_delivery_index(root: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    script_path = Path(__file__).resolve().with_name("workctl.py")
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
    workflow = load_workflow(root)
    if workflow is None:
        return None, [{"kind": "upstream_workflow_missing"}]
    rebuilt, rebuild_diagnostic = rebuild_delivery_index(root)
    if rebuilt is None:
        diagnostics = [rebuild_diagnostic or {"kind": "delivery_index_rebuild_failed"}]
        if not path.exists():
            diagnostics.append({"kind": "upstream_index_missing", "path": str(source_index)})
        return None, diagnostics
    diagnostics: list[dict[str, Any]] = list(rebuilt.get("diagnostics", []))
    if not path.exists():
        diagnostics.append({"kind": "upstream_index_missing", "path": str(source_index)})
        return rebuilt, diagnostics
    try:
        index = read_json(path, MAX_INDEX_BYTES)
    except TaskctlError as exc:
        diagnostics.append({"kind": "upstream_index_unreadable", "message": str(exc)})
        return rebuilt, diagnostics
    if not isinstance(index, dict) or index.get("schema") != "delivery.index":
        diagnostics.append({"kind": "upstream_index_unsupported", "path": str(source_index)})
        return rebuilt, diagnostics
    if index.get("workflow_id") != workflow.get("id"):
        diagnostics.append({"kind": "upstream_index_workflow_mismatch"})
    if index.get("documents") != workflow.get("documents"):
        diagnostics.append({"kind": "upstream_index_document_map_stale"})
    hashes = index.get("document_hashes")
    if not isinstance(hashes, dict):
        diagnostics.append({"kind": "upstream_index_hashes_missing"})
    else:
        for stage in WORKFLOW_STAGES:
            relative = workflow["documents"][stage]
            if hashes.get(stage) != rebuilt.get("document_hashes", {}).get(stage):
                diagnostics.append(
                    {
                        "kind": "upstream_index_stale",
                        "stage": stage,
                        "path": relative,
                    }
                )
    if compact_json(index) != compact_json(rebuilt):
        diagnostics.append({"kind": "upstream_index_derived_content_mismatch"})
    return rebuilt, diagnostics


def current_result(
    root: Path,
    table: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    result_ref = state.get("result_ref")
    if not result_ref:
        return None
    path = resolve_inside(root, result_ref)
    _, _, result_dir = table_paths(root, table)
    if path.parent != result_dir:
        raise TaskctlError(f"current task result must be stored in {result_dir}: {path}")
    match = re.fullmatch(
        rf"{re.escape(task['id'])}\.r(?P<revision>[1-9][0-9]*)\.json", path.name
    )
    if match is None:
        raise TaskctlError(f"current task result has an invalid name: {path}")
    result_state_revision = int(match.group("revision"))
    if result_state_revision > state["revision"]:
        raise TaskctlError(
            f"current task result points beyond the current state revision: {path}"
        )
    result = validate_result_for_task(
        read_json(path), task, require_current_revision=False
    )
    result["current_for_task_revision"] = result["task_revision"] == task["revision"]
    return hydrate_result_source_snapshot(root, table, result)


def safe_current_result(
    root: Path,
    table: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    diagnostics = result_history_diagnostics(root, table, task, state)
    try:
        return current_result(root, table, task, state), diagnostics
    except (OSError, TaskctlError) as exc:
        diagnostics.append(
            {
                "kind": "current_result_unreadable",
                "task_id": task["id"],
                "message": str(exc),
            }
        )
        return None, diagnostics


def state_diagnostics(task_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    status = state["status"]
    owner = state.get("owner")
    result_ref = state.get("result_ref")
    blocked_reason = state.get("blocked_reason", "")
    diagnostics.extend(
        semantic_text_diagnostics(status, "state.status", task_id=task_id)
    )
    if owner is not None:
        diagnostics.extend(
            semantic_text_diagnostics(owner, "state.owner", task_id=task_id)
        )
    if status not in STATUSES:
        diagnostics.append(
            {
                "kind": "non_standard_status",
                "task_id": task_id,
                "status": status,
                "recommended_statuses": list(STATUSES),
            }
        )
    if status == "todo" and owner is not None:
        diagnostics.append({"kind": "todo_has_owner", "task_id": task_id, "owner": owner})
    if status in ACTIVE_STATUSES | {"done"} and owner is None:
        diagnostics.append({"kind": "owner_missing", "task_id": task_id, "status": status})
    if status == "done" and result_ref is None:
        diagnostics.append({"kind": "done_without_result", "task_id": task_id})
    if status not in {"done", "retired"} and result_ref is not None:
        diagnostics.append(
            {"kind": "result_link_on_non_done_state", "task_id": task_id, "status": status}
        )
    if status == "blocked" and not blocked_reason:
        diagnostics.append({"kind": "blocked_reason_missing", "task_id": task_id})
    if status != "blocked" and blocked_reason:
        diagnostics.append(
            {"kind": "blocked_reason_on_other_state", "task_id": task_id, "status": status}
        )
    if status == "retired" and not state.get("note"):
        diagnostics.append({"kind": "retired_reason_missing", "task_id": task_id})
    for field in EXECUTION_CHECKPOINT_TEXT_FIELDS:
        value = state.get(field, "")
        if value:
            diagnostics.extend(
                semantic_text_diagnostics(value, f"state.{field}", task_id=task_id)
            )
    for field in EXECUTION_CHECKPOINT_LIST_FIELDS:
        values = state.get(field, [])
        for value_index, value in enumerate(values):
            diagnostics.extend(
                semantic_text_diagnostics(
                    value, f"state.{field}[{value_index}]", task_id=task_id
                )
            )
        if len(values) != len(set(values)):
            diagnostics.append(
                {"kind": "duplicate_state_values", "task_id": task_id, "field": field}
            )
    return diagnostics


def result_diagnostics(
    result: dict[str, Any] | None,
    task: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if result is None:
        return []
    diagnostics: list[dict[str, Any]] = list(
        result.get("_source_snapshot_diagnostics", [])
    )
    diagnostics.extend(
        semantic_text_diagnostics(
            result["outcome"], "result.outcome", task_id=task["id"]
        )
    )
    for field in (
        "outputs",
        "changed_files",
        "verification",
        "validation_coverage",
        "unresolved",
        "invalidated_source_ids",
        "evidence_for",
    ):
        values = result.get(field, [])
        for value_index, value in enumerate(values):
            diagnostics.extend(
                semantic_text_diagnostics(
                    value, f"result.{field}[{value_index}]", task_id=task["id"]
                )
            )
        if len(values) != len(set(values)):
            diagnostics.append(
                {"kind": "duplicate_result_values", "task_id": task["id"], "field": field}
            )
    for ref_index, evidence_ref in enumerate(result.get("evidence_refs", [])):
        diagnostics.extend(
            semantic_text_diagnostics(
                evidence_ref["ref"],
                f"result.evidence_refs[{ref_index}].ref",
                task_id=task["id"],
            )
        )
        for key in ("kind", "note"):
            if key in evidence_ref:
                diagnostics.extend(
                    semantic_text_diagnostics(
                        evidence_ref[key],
                        f"result.evidence_refs[{ref_index}].{key}",
                        task_id=task["id"],
                    )
                )
    for source_id, fingerprint in result.get("source_snapshot", {}).items():
        diagnostics.extend(
            semantic_text_diagnostics(
                source_id, "result.source_snapshot key", task_id=task["id"]
            )
        )
        diagnostics.extend(
            semantic_text_diagnostics(
                fingerprint,
                f"result.source_snapshot[{source_id}]",
                task_id=task["id"],
            )
        )
    for source_id in [
        *result.get("invalidated_source_ids", []),
        *result.get("evidence_for", []),
        *result.get("source_snapshot", {}).keys(),
    ]:
        if not SOURCE_ID_RE.fullmatch(source_id):
            diagnostics.append(
                {
                    "kind": "non_standard_result_source_id",
                    "task_id": task["id"],
                    "source_id": source_id,
                }
            )
    for changed_file in result.get("changed_files", []):
        if not is_project_relative_reference(changed_file, allow_glob=False):
            diagnostics.append(
                {
                    "kind": "non_project_relative_changed_file",
                    "task_id": task["id"],
                    "path": changed_file,
                }
            )
    if result["task_revision"] != task["revision"]:
        diagnostics.append(
            {
                "kind": "result_task_revision_stale",
                "task_id": task["id"],
                "result_task_revision": result["task_revision"],
                "current_task_revision": task["revision"],
            }
        )
    source_basis = sorted(set([*task["source_ids"], *result.get("evidence_for", [])]))
    recorded_snapshot = result.get("source_snapshot", {})
    if (
        source_basis
        and not recorded_snapshot
        and not result.get("source_snapshot_ref")
    ):
        diagnostics.append(
            {
                "kind": "result_source_snapshot_missing",
                "task_id": task["id"],
                "source_ids": source_basis[:DEFAULT_LIMIT],
                "source_count": len(source_basis),
            }
        )
    if index is not None and recorded_snapshot:
        expected_source_ids = semantic_source_closure(index, source_basis)
        missing_source_ids = sorted(expected_source_ids - set(recorded_snapshot))
        if missing_source_ids:
            diagnostics.append(
                {
                    "kind": "result_source_snapshot_incomplete",
                    "task_id": task["id"],
                    "missing_source_ids": missing_source_ids[:DEFAULT_LIMIT],
                    "missing_count": len(missing_source_ids),
                }
            )
        fingerprints = {
            section.get("id"): section.get("fingerprint")
            for section in index.get("sections", [])
            if isinstance(section, dict) and isinstance(section.get("id"), str)
        }
        for source_id, recorded in recorded_snapshot.items():
            current = fingerprints.get(source_id)
            if current != recorded:
                diagnostics.append(
                    {
                        "kind": "result_source_snapshot_stale",
                        "task_id": task["id"],
                        "source_id": source_id,
                        "recorded": recorded,
                        "current": current,
                    }
                )
    return diagnostics


RESULT_SOURCE_SNAPSHOT_DIAGNOSTIC_KINDS = {
    "result_source_snapshot_missing",
    "result_source_snapshot_incomplete",
    "result_source_snapshot_stale",
    "result_source_snapshot_asset_missing",
    "result_source_snapshot_asset_invalid",
    "result_source_snapshot_asset_identity_mismatch",
}


def summarize_result_diagnostics(
    diagnostics_by_task: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    kind_counts: Counter[str] = Counter()
    result_with_diagnostics_count = 0
    task_revision_stale_result_count = 0
    source_snapshot_issue_result_count = 0
    for diagnostics in diagnostics_by_task.values():
        if diagnostics:
            result_with_diagnostics_count += 1
        kinds = {item.get("kind") for item in diagnostics}
        kind_counts.update(
            item["kind"] for item in diagnostics if isinstance(item.get("kind"), str)
        )
        if "result_task_revision_stale" in kinds:
            task_revision_stale_result_count += 1
        if kinds.intersection(RESULT_SOURCE_SNAPSHOT_DIAGNOSTIC_KINDS):
            source_snapshot_issue_result_count += 1
    return {
        "result_with_diagnostics_count": result_with_diagnostics_count,
        "task_revision_stale_result_count": task_revision_stale_result_count,
        "source_snapshot_issue_result_count": source_snapshot_issue_result_count,
        "result_diagnostic_count": sum(kind_counts.values()),
        "result_diagnostic_kind_counts": dict(sorted(kind_counts.items())),
    }


def summarize_loaded_task_storage(
    root: Path,
    table: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_count = 0
    result_with_verification_count = 0
    result_with_unresolved_count = 0
    invalidated_source_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    diagnostics_by_task: dict[str, list[dict[str, Any]]] = {}
    state_writeback_drifts: list[dict[str, Any]] = []
    for task_id, task in tasks.items():
        state = states[task_id]
        diagnostics.extend(state_diagnostics(task_id, state))
        result, result_read_diagnostics = safe_current_result(root, table, task, state)
        diagnostics.extend(result_read_diagnostics)
        state_writeback_drifts.extend(
            item
            for item in result_read_diagnostics
            if item.get("kind") == "result_history_state_write_drift"
        )
        if result is None:
            continue
        result_count += 1
        diagnostics_by_task[task_id] = result_diagnostics(result, task, index)
        if result["verification"]:
            result_with_verification_count += 1
        if result["unresolved"]:
            result_with_unresolved_count += 1
        invalidated_source_ids.update(result["invalidated_source_ids"])
    return {
        "counts": counts_for(states),
        "task_count": len(tasks),
        "result_count": result_count,
        "result_with_verification_count": result_with_verification_count,
        "result_with_unresolved_count": result_with_unresolved_count,
        "invalidated_source_ids": sorted(invalidated_source_ids),
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
        "state_writeback_drifts": state_writeback_drifts,
        "state_writeback_drift_count": len(state_writeback_drifts),
        **summarize_result_diagnostics(diagnostics_by_task),
    }


def task_storage_summary(root: Path) -> dict[str, Any]:
    root = root.resolve()
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    index, index_diagnostics = maybe_load_index(root, table)
    summary = summarize_loaded_task_storage(root, table, tasks, states, index)
    summary.pop("state_writeback_drifts", None)
    all_diagnostics = [
        *storage_diagnostics,
        *index_diagnostics,
        *summary.get("diagnostics", []),
    ]
    summary["status"] = "partial" if all_diagnostics else "available"
    summary["diagnostics"] = all_diagnostics[:DEFAULT_LIMIT]
    summary["diagnostic_count"] = (
        len(all_diagnostics) + summary["result_diagnostic_count"]
    )
    return summary


def task_diagnostics(
    task: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    index: dict[str, Any] | None,
    cycle_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for field in ("title", "outcome"):
        diagnostics.extend(
            semantic_text_diagnostics(task[field], f"task.{field}", task_id=task["id"])
        )
    if not task["source_ids"]:
        diagnostics.append({"kind": "source_ids_empty"})
    if not task["outputs"]:
        diagnostics.append({"kind": "outputs_empty"})
    if not task["verification"]:
        diagnostics.append({"kind": "verification_empty"})
    for field in (
        "source_ids",
        "mutation_scope",
        "outputs",
        "verification",
        "validation_dimensions",
        "suggested_skills",
    ):
        values = task.get(field, [])
        for value_index, value in enumerate(values):
            diagnostics.extend(
                semantic_text_diagnostics(
                    value, f"task.{field}[{value_index}]", task_id=task["id"]
                )
            )
        if len(values) != len(set(values)):
            diagnostics.append({"kind": "duplicate_task_values", "field": field})
    for source_id in task["source_ids"]:
        if not SOURCE_ID_RE.fullmatch(source_id):
            diagnostics.append(
                {"kind": "non_standard_source_id", "source_id": source_id}
            )
    for scope in task["mutation_scope"]:
        if not is_project_relative_reference(scope):
            diagnostics.append(
                {"kind": "non_project_relative_mutation_scope", "scope": scope}
            )
    if task.get("reasoning_hint") is not None:
        diagnostics.extend(
            semantic_text_diagnostics(
                task["reasoning_hint"], "task.reasoning_hint", task_id=task["id"]
            )
        )
    if task.get("reasoning_hint") not in (None, *REASONING_HINTS):
        diagnostics.append(
            {
                "kind": "non_standard_reasoning_hint",
                "reasoning_hint": task["reasoning_hint"],
            }
        )
    seen_dependencies: set[str] = set()
    for dependency_index, dependency in enumerate(task["dependencies"]):
        dependency_id = dependency["id"]
        diagnostics.extend(
            semantic_text_diagnostics(
                dependency_id,
                f"task.dependencies[{dependency_index}].id",
                task_id=task["id"],
            )
        )
        diagnostics.extend(
            semantic_text_diagnostics(
                dependency["type"],
                f"task.dependencies[{dependency_index}].type",
                task_id=task["id"],
            )
        )
        for consumes_index, value in enumerate(dependency.get("consumes", [])):
            diagnostics.extend(
                semantic_text_diagnostics(
                    value,
                    f"task.dependencies[{dependency_index}].consumes[{consumes_index}]",
                    task_id=task["id"],
                )
            )
        if not TASK_ID_RE.fullmatch(dependency_id):
            diagnostics.append(
                {"kind": "non_standard_dependency_id", "dependency_id": dependency_id}
            )
        if dependency["type"] not in DEPENDENCY_TYPES:
            diagnostics.append(
                {
                    "kind": "non_standard_dependency_type",
                    "dependency_id": dependency_id,
                    "dependency_type": dependency["type"],
                }
            )
        if dependency_id == task["id"]:
            diagnostics.append({"kind": "self_dependency", "dependency_id": dependency_id})
        if dependency_id in seen_dependencies:
            diagnostics.append({"kind": "duplicate_dependency", "dependency_id": dependency_id})
        seen_dependencies.add(dependency_id)
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
            diagnostic_kind = (
                f"{dependency['type']}_dependency_incomplete"
                if dependency["type"] in DEPENDENCY_TYPES
                else "dependency_incomplete"
            )
            diagnostics.append(
                {
                    "kind": diagnostic_kind,
                    "dependency_id": dependency_id,
                    "dependency_type": dependency["type"],
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
    if cycle_ids is None:
        cycle_ids = set(ensure_acyclic(tasks))
    if task["id"] in cycle_ids:
        diagnostics.append({"kind": "dependency_cycle", "task_id": task["id"]})
    if task["id"] in states:
        diagnostics.extend(state_diagnostics(task["id"], states[task["id"]]))
    return diagnostics


def counts_for(states: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for state in states.values():
        status = state["status"]
        counts[status] = counts.get(status, 0) + 1
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
    with workspace_lock(root):
        return command_init_locked(args, root)


def command_init_locked(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    table_id = normalize_manifest_text(args.id, "--id", writing=True)
    title = semantic_string(args.title, "--title")
    workflow = load_workflow(root)
    if workflow is not None:
        if table_id != workflow["id"]:
            raise TaskctlError("--id must match the existing workflow id")
    conflicts = [
        relative
        for relative in ("task-table.json", "TASK_TABLE.md")
        if (root / relative).exists()
    ]
    conflicts.extend(
        directory
        for directory in ("tasks", "state", "results", "snapshots")
        if (root / directory).is_dir() and any((root / directory).iterdir())
    )
    if conflicts:
        raise TaskctlError(
            f"refusing to overwrite existing task workspace: {', '.join(conflicts)}",
            gate_id="TASK-OVERWRITE",
            risk="initialization would overwrite existing task data",
            recovery="choose an empty directory or preserve and inspect the existing workspace",
        )
    for directory in ("tasks", "state", "results", "snapshots"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    table = {
        "schema": "task.table",
        "id": table_id,
        "title": title,
        "task_dir": "tasks",
        "state_dir": "state",
        "result_dir": "results",
        "snapshot_dir": "snapshots",
        "source_index": ".work-cache/index.json",
        "table_view": "TASK_TABLE.md",
    }
    atomic_write_json(root / "task-table.json", table)
    diagnostics = semantic_text_diagnostics(title, "task_table.title")
    if workflow is not None:
        diagnostics.extend(workflow.get("_diagnostics", []))
        if title != workflow.get("title"):
            diagnostics.append(
                {
                    "kind": "task_table_title_differs_from_workflow",
                    "workflow_title": workflow.get("title"),
                    "task_table_title": title,
                }
            )
    return {
        "ok": True,
        "command": "init",
        "task_dir": str(root),
        "diagnostics": diagnostics,
    }


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
        "validation_dimensions": args.validation_dimension,
        "suggested_skills": args.suggested_skill,
        "reasoning_hint": args.reasoning_hint,
        "revision": 1,
    }
    normalized = validate_task(task)
    return normalized


def command_add(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    candidate, legacy_task_envelope = normalize_task_authoring_input(
        read_json(Path(args.file).expanduser().resolve())
    )
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
                "started_at": None,
                "ended_at": None,
                "note": "",
                "blocked_reason": "",
                "next_action": "",
                "evidence_frontier": "",
                "active_consumer": "",
                "validation_case": [],
                "validated_coverage": [],
                "uncovered_dimensions": [],
                "latest_evidence": "",
                "invalidated_source_ids": [],
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
            raise TaskctlError(
                f"task already exists: {candidate['id']}",
                gate_id="TASK-OVERWRITE",
                risk="adding the task would overwrite an existing contract and state",
                recovery="use update for the existing task or choose a new task ID",
            )
        if existing_task is not None and existing_task != candidate:
            raise TaskctlError(f"conflicting partial task record: {candidate['id']}")
        if existing_state is not None and existing_state != initial_state:
            raise TaskctlError(f"conflicting partial task state: {candidate['id']}")
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        proposed = dict(tasks)
        proposed[candidate["id"]] = candidate
        proposed_states = dict(states)
        proposed_states[candidate["id"]] = initial_state
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *(
                [{"kind": "legacy_task_envelope_normalized"}]
                if legacy_task_envelope
                else []
            ),
            *(
                [{"kind": "non_initial_task_revision", "revision": candidate["revision"]}]
                if candidate["revision"] != 1
                else []
            ),
            *task_diagnostics(candidate, proposed, proposed_states, index),
        ]
        if existing_task is None:
            atomic_write_json(task_path, candidate)
        if existing_state is None:
            atomic_write_json(state_path, initial_state)
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            proposed,
            proposed_states,
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "add",
        "task_id": candidate["id"],
        "task_revision": candidate["revision"],
        "state_revision": 1,
        "table_view": table_view,
        "recovered_partial_write": existing_task is not None or existing_state is not None,
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
        "note": "diagnostics are advisory and do not accept or reject task semantics",
    }


def command_update(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    candidate, legacy_task_envelope = normalize_task_authoring_input(
        read_json(Path(args.file).expanduser().resolve())
    )
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        task_id = candidate["id"]
        if task_id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {task_id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the exact update has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        current = tasks[task_id]
        if args.expected_task_revision is None:
            raise TaskctlError(
                "update requires --expected-task-revision",
                gate_id="TASK-REVISION",
                risk="the update has no caller-observed task revision and could overwrite a newer contract",
                recovery="read the current task revision, merge the intended change, and retry with --expected-task-revision",
                retryable=True,
            )
        if current["revision"] != args.expected_task_revision:
            raise TaskctlError(
                f"task revision conflict: expected {args.expected_task_revision}, "
                f"current {current['revision']}",
                gate_id="TASK-REVISION",
                risk="the update would overwrite a newer task contract",
                recovery="reload the current task revision, merge the intended change, and retry",
                retryable=True,
            )
        state = states[task_id]
        transition_diagnostics: list[dict[str, Any]] = []
        if state["status"] == "done" or state["result_ref"] is not None:
            transition_diagnostics.append(
                {
                    "kind": "completed_task_contract_updated",
                    "result_ref": state.get("result_ref"),
                }
            )
        if state["owner"] is not None and args.owner != state["owner"]:
            transition_diagnostics.append(
                {
                    "kind": "owner_mismatch",
                    "recorded_owner": state["owner"],
                    "requested_owner": args.owner,
                }
            )
        candidate["revision"] = current["revision"] + 1
        proposed = dict(tasks)
        proposed[task_id] = candidate
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *transition_diagnostics,
            *index_diagnostics,
            *(
                [{"kind": "legacy_task_envelope_normalized"}]
                if legacy_task_envelope
                else []
            ),
            *task_diagnostics(candidate, proposed, states, index),
        ]
        task_dir, _, _ = table_paths(root, table)
        atomic_write_json(task_dir / f"{task_id}.json", candidate)
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            proposed,
            states,
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "update",
        "task_id": task_id,
        "task_revision": candidate["revision"],
        "table_view": table_view,
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
        "note": "diagnostics are advisory and do not accept or reject task semantics",
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
    for maximum in (2_000, 1_000, 500, 240, 120, 80):
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
        "source_snapshot_ref": payload.get("source_snapshot_ref"),
        "pagination": payload.get("pagination"),
        "truncated": True,
        "hint": "increase --budget or use show/deps/context with a narrower target",
    }
    if len(compact_json(minimal)) > budget:
        raise TaskctlError("--budget is too small for a minimal response")
    return minimal


def page_after_id(
    items: list[dict[str, Any]], after_id: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None, bool]:
    remaining = items
    cursor_reset = False
    if after_id is not None:
        cursor_index = next(
            (index for index, item in enumerate(items) if item.get("id") == after_id),
            None,
        )
        if cursor_index is None:
            cursor_reset = True
        else:
            remaining = items[cursor_index + 1 :]
    page = remaining[:limit]
    next_after_id = page[-1]["id"] if len(remaining) > len(page) and page else None
    return page, next_after_id, cursor_reset


def completion_ids_after(
    item_ids: list[str], after_id: str | None, stream: str
) -> list[str]:
    if after_id is None:
        return item_ids
    try:
        cursor_index = item_ids.index(after_id)
    except ValueError as exc:
        raise TaskctlError(
            f"unknown completion {stream} cursor: {after_id}",
            gate_id="TASK-INPUT-UNREADABLE",
            risk="the final-review continuation point is not identifiable and could omit review items",
            scope="current completion-context continuation",
            recovery=(
                "use the exact cursor returned for this stream and snapshot, "
                "or restart completion-context from the first page"
            ),
            retryable=True,
        ) from exc
    return item_ids[cursor_index + 1 :]


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    if args.id not in tasks:
        raise TaskctlError(
            f"task is unavailable or unknown: {args.id}",
            gate_id="TASK-AMBIGUOUS-TARGET",
            risk="the exact query has no readable uniquely identified task",
            recovery="inspect the matching storage diagnostic or choose a current task ID",
        )
    state = states[args.id]
    result, result_read_diagnostics = safe_current_result(
        root, table, tasks[args.id], state
    )
    payload = {
        "ok": True,
        "command": "show",
        "id": args.id,
        "task": tasks[args.id],
        "state": state,
        "result": public_result(result),
        "diagnostics": [
            *storage_diagnostics,
            *state_diagnostics(args.id, state),
            *result_read_diagnostics,
            *result_diagnostics(result, tasks[args.id], None),
        ],
    }
    return fit_payload(payload, args.budget) if args.view == "machine" else payload


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
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
    page, next_after_id, cursor_reset = page_after_id(rows, args.after_id, args.limit)
    if cursor_reset:
        storage_diagnostics.append(
            {"kind": "pagination_cursor_reset", "after_id": args.after_id}
        )
    page_state_diagnostics = [
        diagnostic
        for row in page
        for diagnostic in state_diagnostics(row["id"], states[row["id"]])
    ]
    return {
        "ok": True,
        "command": "list",
        "counts": counts_for(states),
        "items": page,
        "matched_count": len(rows),
        "next_after_id": next_after_id,
        "truncated": next_after_id is not None,
        "diagnostics": [*storage_diagnostics, *page_state_diagnostics][: args.limit],
        "diagnostic_count": len(storage_diagnostics) + len(page_state_diagnostics),
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
    return [path[-1] for path in dependent_paths(tasks, task_id, recursive)]


def dependent_paths(
    tasks: dict[str, dict[str, Any]], task_id: str, recursive: bool
) -> list[list[str]]:
    reverse = reverse_graph(tasks)
    result: list[list[str]] = []
    seen: set[str] = {task_id}
    queue = deque([task_id, dependent] for dependent in reverse[task_id])
    while queue:
        path = queue.popleft()
        current = path[-1]
        if current in seen:
            continue
        seen.add(current)
        result.append(path)
        if recursive:
            queue.extend([*path, dependent] for dependent in reverse[current])
    return result


def command_deps(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    if args.id not in tasks:
        raise TaskctlError(
            f"task is unavailable or unknown: {args.id}",
            gate_id="TASK-AMBIGUOUS-TARGET",
            risk="the exact dependency query has no readable uniquely identified task",
            recovery="inspect storage diagnostics or choose a current task ID",
        )
    ids = dependency_ids(tasks, args.id, args.recursive)
    items = []
    direct_types = {
        dependency["id"]: dependency["type"] for dependency in tasks[args.id]["dependencies"]
    }
    for dependency_id in ids:
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
    page, next_after_id, cursor_reset = page_after_id(items, args.after_id, args.limit)
    if cursor_reset:
        storage_diagnostics.append(
            {"kind": "pagination_cursor_reset", "after_id": args.after_id}
        )
    return {
        "ok": True,
        "command": "deps",
        "id": args.id,
        "items": page,
        "dependency_count": len(ids),
        "next_after_id": next_after_id,
        "truncated": next_after_id is not None,
        "diagnostics": storage_diagnostics[: args.limit],
        "diagnostic_count": len(storage_diagnostics),
    }


def command_dependents(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    if args.id not in tasks:
        raise TaskctlError(
            f"task is unavailable or unknown: {args.id}",
            gate_id="TASK-AMBIGUOUS-TARGET",
            risk="the exact dependent query has no readable uniquely identified task",
            recovery="inspect storage diagnostics or choose a current task ID",
        )
    paths = dependent_paths(tasks, args.id, args.recursive)
    items = []
    for path in paths:
        dependent_id = path[-1]
        via = path[-2]
        edge = next(
            dependency
            for dependency in tasks[dependent_id]["dependencies"]
            if dependency["id"] == via
        )
        items.append(
            {
                "id": dependent_id,
                "title": tasks[dependent_id]["title"],
                "status": states[dependent_id]["status"],
                "depth": len(path) - 1,
                "via": via,
                "type": edge["type"],
                "consumes": edge["consumes"],
                "path": path,
            }
        )
    page, next_after_id, cursor_reset = page_after_id(items, args.after_id, args.limit)
    if cursor_reset:
        storage_diagnostics.append(
            {"kind": "pagination_cursor_reset", "after_id": args.after_id}
        )
    return {
        "ok": True,
        "command": "dependents",
        "id": args.id,
        "items": page,
        "dependent_count": len(paths),
        "next_after_id": next_after_id,
        "truncated": next_after_id is not None,
        "diagnostics": storage_diagnostics[: args.limit],
        "diagnostic_count": len(storage_diagnostics),
    }


def command_next(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    index, index_diagnostics = maybe_load_index(root, table)
    cycle_ids = set(ensure_acyclic(tasks))
    rows = []
    for task_id, task in tasks.items():
        state = states[task_id]
        if state["status"] in {"done", "retired"}:
            continue
        diagnostics = task_diagnostics(task, tasks, states, index, cycle_ids)
        if state["owner"] and state["owner"] != args.owner:
            diagnostics.append({"kind": "owned_by_other", "owner": state["owner"]})
        hard_blocked = any(
            item["kind"] in {"hard_dependency_incomplete", "unknown_dependency"}
            and item.get("dependency_type", "hard") == "hard"
            for item in diagnostics
        )
        owned_by_other = any(item["kind"] == "owned_by_other" for item in diagnostics)
        status_blocked = state["status"] == "blocked"
        non_standard_status = state["status"] not in STATUSES
        recommended = (
            not hard_blocked
            and not owned_by_other
            and not status_blocked
            and not non_standard_status
        )
        if not recommended and not args.include_blocked:
            continue
        status_rank = {
            "in_progress": 0,
            "review": 1,
            "claimed": 2,
            "todo": 3,
            "blocked": 4,
        }.get(state["status"], 5)
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
    ordered_items = [row[1] for row in rows]
    items, next_after_id, cursor_reset = page_after_id(
        ordered_items, args.after_id, args.limit
    )
    if cursor_reset:
        storage_diagnostics.append(
            {"kind": "pagination_cursor_reset", "after_id": args.after_id}
        )
    return {
        "ok": True,
        "command": "next",
        "items": items,
        "candidate_count": len(rows),
        "recommended_count": sum(row[1]["recommended"] for row in rows),
        "next_after_id": next_after_id,
        "truncated": next_after_id is not None,
        "diagnostics": [*storage_diagnostics, *index_diagnostics][
            : args.diagnostic_limit
        ],
        "diagnostic_count": len(storage_diagnostics) + len(index_diagnostics),
        "note": "recommendation is advisory and does not grant or deny execution",
    }


def select_upstream_context(
    index: dict[str, Any] | None, source_ids: list[str], maximum: int
) -> tuple[list[dict[str, Any]], dict[str, str], bool, bool]:
    if index is None:
        return [], {}, False, False
    rows_by_id: dict[str, list[dict[str, Any]]] = {}
    for section in index.get("sections", []):
        if isinstance(section, dict) and isinstance(section.get("id"), str):
            rows_by_id.setdefault(section["id"], []).append(section)
    by_id = {
        section_id: rows[0]
        for section_id, rows in rows_by_id.items()
        if len(rows) == 1
    }
    selected: list[str] = []
    seen: set[str] = set()
    unresolved = False
    queue = deque(source_ids)
    while queue and len(selected) < maximum:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        if current not in by_id:
            unresolved = True
            continue
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
    source_snapshot: dict[str, str] = {}
    for section_id in selected:
        fingerprint = by_id[section_id].get("fingerprint")
        if isinstance(fingerprint, str):
            source_snapshot[section_id] = fingerprint
        else:
            unresolved = True
    truncated = bool(queue)
    return rows, source_snapshot, truncated, not truncated and not unresolved


def select_related_deferred_changes(
    index: dict[str, Any] | None,
    source_ids: list[str],
    excluded_ids: set[str],
    maximum: int,
) -> tuple[list[dict[str, Any]], dict[str, str], bool, bool]:
    if index is None:
        return [], {}, False, False
    source_closure = semantic_source_closure(index, source_ids)
    candidates = [
        section
        for section in index.get("sections", [])
        if isinstance(section, dict)
        and isinstance(section.get("id"), str)
        and section["id"].startswith("DCR-")
        and section["id"] not in excluded_ids
        and source_closure.intersection(section.get("references", []))
    ]
    selected = candidates[:maximum]
    rows = [
        {
            "id": section.get("id"),
            "title": section.get("title"),
            "stage": section.get("stage"),
            "document": section.get("document"),
            "line": section.get("line"),
            "status": section.get("status"),
            "references": section.get("references", []),
            "body": section.get("body", ""),
        }
        for section in selected
    ]
    source_snapshot: dict[str, str] = {}
    unresolved = False
    for section in selected:
        fingerprint = section.get("fingerprint")
        if isinstance(fingerprint, str):
            source_snapshot[section["id"]] = fingerprint
        else:
            unresolved = True
    truncated = len(candidates) > len(selected)
    return rows, source_snapshot, truncated, not truncated and not unresolved


def semantic_source_closure(index: dict[str, Any], source_ids: list[str]) -> set[str]:
    by_id: dict[str, dict[str, Any]] = {}
    for section in index.get("sections", []):
        if isinstance(section, dict) and isinstance(section.get("id"), str):
            by_id.setdefault(section["id"], section)
    selected: set[str] = set()
    queue = deque(source_ids)
    while queue:
        current = queue.popleft()
        if current in selected:
            continue
        selected.add(current)
        section = by_id.get(current)
        if section is not None:
            queue.extend(section.get("references", []))
    return selected


def active_execution_frontiers(
    root: Path,
    table: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    index: dict[str, Any] | None,
    state_writeback_drifts: list[dict[str, Any]],
    maximum: int,
) -> tuple[list[dict[str, Any]], int]:
    task_dir, state_dir, _ = table_paths(root, table)
    drifts_by_task: dict[str, list[dict[str, Any]]] = {}
    for diagnostic in state_writeback_drifts:
        task_id = diagnostic.get("task_id")
        if isinstance(task_id, str):
            drifts_by_task.setdefault(task_id, []).append(diagnostic)
    rows: list[dict[str, Any]] = []
    for task_id in sorted(tasks):
        task = tasks[task_id]
        state = states[task_id]
        if state["status"] not in ACTIVE_STATUSES:
            continue
        deferred_changes, _, deferred_truncated, _ = select_related_deferred_changes(
            index, task["source_ids"], set(), 5
        )
        checkpoint_present = any(
            state.get(field) for field in EXECUTION_CHECKPOINT_TEXT_FIELDS
        ) or any(state.get(field) for field in EXECUTION_CHECKPOINT_LIST_FIELDS)
        task_drifts = drifts_by_task.get(task_id, [])
        if not checkpoint_present and not deferred_changes and not task_drifts:
            continue
        row: dict[str, Any] = {
            "id": task_id,
            "title": task["title"],
            "outcome": task["outcome"],
            "status": state["status"],
            "owner": state["owner"],
            "source_ids": task["source_ids"],
            "mutation_scope": task["mutation_scope"],
            "validation_dimensions": task["validation_dimensions"],
            "source": {
                "task": (
                    (task_dir / f"{task_id}.json").relative_to(root).as_posix()
                ),
                "task_revision": task["revision"],
                "state": (
                    (state_dir / f"{task_id}.json").relative_to(root).as_posix()
                ),
                "state_revision": state["revision"],
            },
        }
        for field in (
            *EXECUTION_CHECKPOINT_TEXT_FIELDS,
            *EXECUTION_CHECKPOINT_LIST_FIELDS,
        ):
            value = state.get(field)
            if value not in (None, "", []):
                row[field] = copy.deepcopy(value)
        if state.get("next_action"):
            row["next_action"] = state["next_action"]
        if deferred_changes:
            row["deferred_changes"] = deferred_changes
        if deferred_truncated:
            row["deferred_changes_truncated"] = True
        if task_drifts:
            row["state_writeback_drifts"] = copy.deepcopy(task_drifts)
        rows.append(row)
    return rows[:maximum], len(rows)


def command_context(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    if args.id not in tasks:
        raise TaskctlError(
            f"task is unavailable or unknown: {args.id}",
            gate_id="TASK-AMBIGUOUS-TARGET",
            risk="the exact context query has no readable uniquely identified task",
            recovery="inspect storage diagnostics or choose a current task ID",
        )
    index, index_diagnostics = maybe_load_index(root, table)
    task = tasks[args.id]
    _, current_result_diagnostics = safe_current_result(
        root, table, task, states[args.id]
    )
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
        dependency_result, dependency_result_diagnostics = safe_current_result(
            root, table, tasks[dependency_id], dependency_state
        )
        dependency_context.append(
            {
                "id": dependency_id,
                "type": dependency["type"],
                "status": dependency_state["status"],
                "consumes": dependency["consumes"],
                "result": public_result(dependency_result),
                "diagnostics": [
                    *dependency_result_diagnostics,
                    *(
                        dependency_result.get("_source_snapshot_diagnostics", [])
                        if dependency_result
                        else []
                    ),
                ],
            }
        )
    reverse = reverse_graph(tasks)
    all_dependents = reverse[args.id]
    dependents = [
        {
            "id": dependent_id,
            "title": tasks[dependent_id]["title"],
            "status": states[dependent_id]["status"],
            "consumes": next(
                dependency["consumes"]
                for dependency in tasks[dependent_id]["dependencies"]
                if dependency["id"] == args.id
            ),
        }
        for dependent_id in all_dependents[: args.max_items]
    ]
    all_diagnostics = [
        *storage_diagnostics,
        *index_diagnostics,
        *current_result_diagnostics,
        *task_diagnostics(task, tasks, states, index),
    ]
    upstream, source_snapshot, upstream_truncated, source_snapshot_complete = select_upstream_context(
        index, task["source_ids"], args.max_items
    )
    deferred_changes, deferred_snapshot, deferred_truncated, deferred_complete = (
        select_related_deferred_changes(
            index,
            task["source_ids"],
            {row["id"] for row in upstream},
            args.max_items,
        )
    )
    source_snapshot.update(deferred_snapshot)
    source_snapshot_complete = source_snapshot_complete and deferred_complete
    truncation = {
        "diagnostics": len(all_diagnostics) > args.max_items,
        "upstream": upstream_truncated,
        "deferred_changes": deferred_truncated,
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
        "deferred_changes": deferred_changes,
        "source_snapshot": source_snapshot,
        "source_snapshot_complete": source_snapshot_complete,
        "dependencies": dependency_context,
        "dependents": dependents,
        "truncation": truncation,
        "truncated": any(truncation.values()),
    }
    if args.capture and args.view == "machine":
        with workspace_lock(root):
            payload["source_snapshot_ref"] = store_source_snapshot(
                root, load_table(root), source_snapshot
            )
    return fit_payload(payload, args.budget) if args.view == "machine" else payload


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
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    index, index_diagnostics = maybe_load_index(root, table)
    if index is None:
        diagnostics = [*storage_diagnostics, *index_diagnostics]
        if args.snapshot_id is not None or args.review_receipt is not None:
            rebuild_message = next(
                (
                    diagnostic.get("message")
                    for diagnostic in index_diagnostics
                    if isinstance(diagnostic, dict)
                    and isinstance(diagnostic.get("message"), str)
                ),
                None,
            )
            detail = f": {rebuild_message}" if rebuild_message else ""
            raise TaskctlError(
                "completion snapshot cannot be verified because current Markdown "
                f"could not be indexed{detail}",
                gate_id="TASK-INPUT-UNREADABLE",
                risk=(
                    "the current final-review snapshot is not identifiable and "
                    "continuing could omit or mix review items"
                ),
                scope="current completion-context continuation",
                recovery=(
                    "repair the reported current Markdown input, then restart "
                    "completion-context from the first page without old cursors"
                ),
                retryable=True,
            )
        return {
            "ok": True,
            "command": "completion-context",
            "protected_baseline": None,
            "targets": [],
            "returned_streams": [],
            "query_diagnostics": diagnostics[: args.max_items],
            "diagnostic_summary": {
                "query_diagnostic_count": len(diagnostics),
                "candidate_result_with_diagnostics_count": 0,
                "candidate_task_revision_stale_result_count": 0,
                "candidate_source_snapshot_issue_result_count": 0,
                "candidate_result_diagnostic_count": 0,
                "candidate_result_diagnostic_kind_counts": {},
                "total_diagnostic_count": len(diagnostics),
            },
            "note": "current Markdown could not be indexed by the helper; review the documents directly",
        }
    current_results: dict[str, dict[str, Any] | None] = {}
    result_read_diagnostics: list[dict[str, Any]] = []
    for task_id in sorted(tasks):
        result, diagnostics = safe_current_result(
            root, table, tasks[task_id], states[task_id]
        )
        current_results[task_id] = result
        result_read_diagnostics.extend(diagnostics)
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
    expected_snapshot_id = args.snapshot_id
    if args.review_receipt is not None:
        expected_snapshot_id = resolve_review_receipt(root, args.review_receipt)
    if expected_snapshot_id is not None and expected_snapshot_id != snapshot_id:
        raise TaskctlError(
            "completion snapshot changed; restart final review from the first page",
            gate_id="TASK-PAGINATION-SNAPSHOT",
            risk="continuing would mix evidence from different task or document snapshots",
            recovery="restart completion-context from the first page without old cursors",
            retryable=True,
        )
    sections = [section for section in index.get("sections", []) if isinstance(section, dict)]
    section_rows: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        section_id = section.get("id")
        if isinstance(section_id, str):
            section_rows.setdefault(section_id, []).append(section)
    baseline_requirement_ids = sorted(
        {
            section["id"]
            for section in sections
            if section.get("stage") == "requirements"
            and str(section.get("id", "")).split("-", 1)[0] in {"REQ", "AC", "CON"}
        }
    )
    baseline_user_design_ids = sorted(
        {
            section["id"]
            for section in sections
            if section.get("stage") == "user_design"
            and str(section.get("id", "")).split("-", 1)[0] == "UDES"
        }
    )
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
    target_stream_continuation = bool(
        args.after_id is not None
        or args.candidate_after_id is not None
        or (args.target_id is not None and args.snapshot_id)
    )
    constraint_stream_continuation = args.constraint_after_id is not None
    deferred_stream_continuation = args.deferred_after_id is not None
    has_stream_continuation = any(
        (
            target_stream_continuation,
            constraint_stream_continuation,
            deferred_stream_continuation,
        )
    )
    include_targets = not has_stream_continuation or target_stream_continuation
    include_constraints = not has_stream_continuation or constraint_stream_continuation
    include_deferred = not has_stream_continuation or deferred_stream_continuation

    if not include_targets:
        filtered_target_ids = []
    elif args.target_id is not None:
        if args.target_id not in all_target_ids:
            raise TaskctlError(
                f"unknown current completion target: {args.target_id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the exact completion query has no uniquely identified current target",
                recovery="choose a REQ, AC, or UDES ID present in the current Markdown documents",
            )
        filtered_target_ids = [args.target_id]
    else:
        filtered_target_ids = completion_ids_after(
            all_target_ids, args.after_id, "target"
        )
    page_ids = filtered_target_ids[: args.limit]
    diagnostics = [
        *storage_diagnostics,
        *index_diagnostics,
        *result_read_diagnostics,
    ]
    candidate_task_rows: dict[str, dict[str, Any]] = {}
    for task_id in sorted(tasks):
        task = tasks[task_id]
        state = states[task_id]
        result = current_results[task_id]
        candidate_task_rows[task_id] = {
            "status": state["status"],
            "task_revision": task["revision"],
            "result_ref": state["result_ref"],
            "result_outcome": result.get("outcome") if result else None,
            "outputs": result.get("outputs", []) if result else [],
            "verification": result.get("verification", []) if result else [],
            "validation_coverage": (
                result.get("validation_coverage", []) if result else []
            ),
            "unresolved": result.get("unresolved", []) if result else [],
            "invalidated_source_ids": (
                result.get("invalidated_source_ids", []) if result else []
            ),
            "evidence_for": result.get("evidence_for", []) if result else [],
            "evidence_refs": result.get("evidence_refs", []) if result else [],
            "source_snapshot_ref": (
                result.get("source_snapshot_ref") if result else None
            ),
            "source_snapshot": result.get("source_snapshot", {}) if result else {},
            "result_diagnostics": result_diagnostics(result, task, index),
        }
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
        all_linked_task_ids = []
        for task_id in sorted(tasks):
            task = tasks[task_id]
            result = current_results[task_id]
            evidence_for = result.get("evidence_for", []) if result else []
            if not semantic_ids.intersection([*task["source_ids"], *evidence_for]):
                continue
            all_linked_task_ids.append(task_id)
        remaining_candidate_ids = completion_ids_after(
            all_linked_task_ids, args.candidate_after_id, "candidate"
        )
        linked_task_ids = remaining_candidate_ids[: args.max_items]
        candidate_more = len(remaining_candidate_ids) > len(linked_task_ids)
        candidate_next_after_ids[target_id] = (
            linked_task_ids[-1] if candidate_more and linked_task_ids else None
        )
        target_rows.append(
            {
                "id": target_id,
                "title": section.get("title"),
                "document": section.get("document"),
                "line": section.get("line"),
                "status": section.get("status"),
                "body": section.get("body", ""),
                "candidate_task_ids": linked_task_ids,
                "candidate_task_count": len(all_linked_task_ids),
                "returned_candidate_task_count": len(linked_task_ids),
                "candidate_tasks_truncated": candidate_more,
                "candidate_next_after_id": candidate_next_after_ids[target_id],
                "candidate_result_count": sum(
                    candidate_task_rows[task_id]["result_ref"] is not None
                    for task_id in all_linked_task_ids
                ),
                "candidate_result_with_verification_count": sum(
                    bool(candidate_task_rows[task_id]["verification"])
                    for task_id in all_linked_task_ids
                ),
            }
        )
    deferred_ids = sorted(
        value
        for value in index.get("deferred_change_ids", [])
        if isinstance(value, str)
    )
    constraint_remaining = (
        completion_ids_after(
            constraint_ids, args.constraint_after_id, "constraint"
        )
        if include_constraints
        else []
    )
    constraint_page_ids = constraint_remaining[: args.max_items]
    deferred_remaining = (
        completion_ids_after(
            deferred_ids, args.deferred_after_id, "deferred-change"
        )
        if include_deferred
        else []
    )
    deferred_page_ids = deferred_remaining[: args.max_items]

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
            "status": section.get("status"),
            "body": section.get("body", ""),
        }

    def candidate_catalog(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        task_ids = sorted(
            {
                task_id
                for row in rows
                for task_id in row["candidate_task_ids"]
            }
        )
        return {task_id: candidate_task_rows[task_id] for task_id in task_ids}

    def page_diagnostic_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        catalog = candidate_catalog(rows)
        result_summary = summarize_result_diagnostics(
            {
                task_id: candidate["result_diagnostics"]
                for task_id, candidate in catalog.items()
                if candidate["result_ref"] is not None
            }
        )
        return {
            "query_diagnostic_count": len(diagnostics),
            "candidate_result_with_diagnostics_count": result_summary[
                "result_with_diagnostics_count"
            ],
            "candidate_task_revision_stale_result_count": result_summary[
                "task_revision_stale_result_count"
            ],
            "candidate_source_snapshot_issue_result_count": result_summary[
                "source_snapshot_issue_result_count"
            ],
            "candidate_result_diagnostic_count": result_summary[
                "result_diagnostic_count"
            ],
            "candidate_result_diagnostic_kind_counts": result_summary[
                "result_diagnostic_kind_counts"
            ],
            "total_diagnostic_count": (
                len(diagnostics) + result_summary["result_diagnostic_count"]
            ),
        }

    target_more = len(filtered_target_ids) > len(target_rows)
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
        "target_source": "current_markdown_documents",
        "target_count": len(all_target_ids),
        "returned_target_count": len(target_rows),
        "targets": target_rows,
        "candidate_tasks": candidate_catalog(target_rows),
        "constraint_count": len(constraint_ids),
        "returned_constraint_count": len(constraint_page_ids),
        "constraints": [section_summary(value) for value in constraint_page_ids],
        "deferred_change_count": len(deferred_ids),
        "returned_deferred_change_count": len(deferred_page_ids),
        "deferred_changes": [section_summary(value) for value in deferred_page_ids],
        "returned_streams": [
            stream
            for stream, included in (
                ("targets", include_targets),
                ("constraints", include_constraints),
                ("deferred_changes", include_deferred),
            )
            if included
        ],
        "pagination": pagination,
        "query_diagnostics": diagnostics[: args.max_items],
        "diagnostic_summary": page_diagnostic_summary(target_rows),
        "note": (
            "current Markdown targets and candidate evidence are inputs to model review; no final pass or fail is produced"
        ),
    }
    if args.view == "model":
        payload["review_receipt"] = (
            args.review_receipt or store_review_receipt(root, snapshot_id)
        )
    if args.view == "machine":
        while (
            len(compact_json(shrink_value(payload, 500))) > args.budget
            and len(target_rows) > 1
        ):
            target_rows.pop()
            payload["returned_target_count"] = len(target_rows)
            payload["pagination"]["target_next_after_id"] = (
                target_rows[-1]["id"] if target_rows else args.after_id
            )
            payload["pagination"]["candidate_next_after_ids"] = {
                row["id"]: row["candidate_next_after_id"] for row in target_rows
            }
            payload["candidate_tasks"] = candidate_catalog(target_rows)
            payload["diagnostic_summary"] = page_diagnostic_summary(target_rows)
        return fit_payload(payload, args.budget)
    return payload


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    table = load_table(root)
    tasks, states, storage_diagnostics = load_query_storage(root, table)
    index, index_diagnostics = maybe_load_index(root, table)
    storage = summarize_loaded_task_storage(root, table, tasks, states, index)
    dependency_blocked_count = 0
    cycle_ids = set(ensure_acyclic(tasks))
    diagnostic_count = (
        len(storage_diagnostics)
        + len(index_diagnostics)
        + storage.get("diagnostic_count", 0)
        + storage["result_diagnostic_count"]
    )
    for task_id, task in tasks.items():
        diagnostics = task_diagnostics(task, tasks, states, index, cycle_ids)
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
    semantic_summary = index.get("summary", {}) if index else {}
    active_frontiers, active_frontier_count = active_execution_frontiers(
        root,
        table,
        tasks,
        states,
        index,
        storage["state_writeback_drifts"],
        args.limit,
    )
    return {
        "ok": True,
        "command": "status",
        "generated_at": utc_now_timestamp(),
        "task_count": storage["task_count"],
        "status_counts": storage["counts"],
        "needs_review_count": storage["counts"]["review"],
        "dependency_attention_count": dependency_blocked_count,
        "upstream": {
            "protected_baseline": index.get("protected_baseline") if index else None,
            "unresolved_count": semantic_summary.get("unresolved_count"),
            "deferred_change_count": semantic_summary.get("deferred_change_count", 0),
            "invalidated_source_ids": storage["invalidated_source_ids"][: args.limit],
        },
        "results": {
            "referenced_result_count": storage["result_count"],
            "result_with_verification_count": storage["result_with_verification_count"],
            "result_with_unresolved_count": storage["result_with_unresolved_count"],
            "result_with_diagnostics_count": storage[
                "result_with_diagnostics_count"
            ],
            "task_revision_stale_result_count": storage[
                "task_revision_stale_result_count"
            ],
            "source_snapshot_issue_result_count": storage[
                "source_snapshot_issue_result_count"
            ],
            "result_diagnostic_count": storage["result_diagnostic_count"],
            "result_diagnostic_kind_counts": storage[
                "result_diagnostic_kind_counts"
            ],
        },
        "active_frontier_count": active_frontier_count,
        "active_frontiers": active_frontiers,
        "state_writeback_drift_count": storage["state_writeback_drift_count"],
        "diagnostic_count": diagnostic_count,
        "index_diagnostics": index_diagnostics[: args.limit],
        "storage_diagnostics": [
            *storage_diagnostics,
            *storage.get("diagnostics", []),
        ][: args.limit],
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
        if other_id == task_id or other_state["status"] in {"todo", "done", "retired"}:
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
    if expected is None:
        raise TaskctlError(
            "state write requires --expected-state-revision",
            gate_id="TASK-REVISION",
            risk="the write has no caller-observed state revision and could overwrite newer task state",
            recovery="read the current state revision, reconcile the intended change, and retry with --expected-state-revision",
            retryable=True,
        )
    if state["revision"] != expected:
        raise TaskctlError(
            f"state revision conflict: expected {expected}, current {state['revision']}",
            gate_id="TASK-REVISION",
            risk="the update would overwrite newer task state",
            recovery="reload the current state revision, reconcile the intended change, and retry",
            retryable=True,
        )


def owner_diagnostics(state: dict[str, Any], owner: str) -> list[dict[str, Any]]:
    if state["owner"] is not None and state["owner"] != owner:
        return [
            {
                "kind": "owner_mismatch",
                "recorded_owner": state["owner"],
                "requested_owner": owner,
            }
        ]
    return []


def apply_state_timestamps(
    previous_state: dict[str, Any],
    next_state: dict[str, Any],
    *,
    start_event: bool = False,
    end_event: bool = False,
) -> dict[str, Any]:
    previous_status = previous_state["status"]
    next_status = next_state["status"]
    transition_timestamp: str | None = None

    def timestamp() -> str:
        nonlocal transition_timestamp
        if transition_timestamp is None:
            transition_timestamp = utc_now_timestamp()
        return transition_timestamp

    if next_state.get("started_at") is None and (
        start_event
        or (next_status == "in_progress" and previous_status != "in_progress")
    ):
        next_state["started_at"] = timestamp()

    if next_status not in TERMINAL_STATUSES and previous_status in TERMINAL_STATUSES:
        next_state["ended_at"] = None
    elif next_state.get("ended_at") is None and (
        end_event
        or (
            next_status in TERMINAL_STATUSES
            and previous_status not in TERMINAL_STATUSES
        )
    ):
        next_state["ended_at"] = timestamp()
    return next_state


def write_state(
    root: Path,
    table: dict[str, Any],
    state: dict[str, Any],
    previous_state: dict[str, Any],
    *,
    start_event: bool = False,
) -> dict[str, Any]:
    _, state_dir, _ = table_paths(root, table)
    state["revision"] += 1
    state = apply_state_timestamps(
        previous_state, state, start_event=start_event
    )
    normalized = validate_state(state, state["task_id"])
    atomic_write_json(state_dir / f"{state['task_id']}.json", normalized)
    return normalized


def command_claim(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the claim has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        previous_state = dict(state)
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if state["status"] in {"done", "retired"}:
            diagnostics.append(
                {"kind": "non_typical_claim_state", "from_status": state["status"]}
            )
        state["owner"] = args.owner
        if state["status"] in {"todo", "done", "retired"}:
            state["status"] = "claimed"
        state = write_state(root, table, state, previous_state)
        warnings = mutation_overlap_warnings(args.id, tasks, {**states, args.id: state})
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            {**states, args.id: state},
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "claim",
        "id": args.id,
        "state": state,
        "table_view": table_view,
        "warnings": warnings[:DEFAULT_LIMIT],
        "warning_count": len(warnings),
        "diagnostics": (diagnostics + state_diagnostics(args.id, state))[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics) + len(state_diagnostics(args.id, state)),
    }


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the start command has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        previous_state = dict(state)
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if state["status"] not in {"todo", "claimed", "in_progress", "blocked"}:
            diagnostics.append(
                {"kind": "non_typical_start_state", "from_status": state["status"]}
            )
        state["owner"] = args.owner
        state["status"] = "in_progress"
        state = write_state(
            root, table, state, previous_state, start_event=True
        )
        warnings = mutation_overlap_warnings(args.id, tasks, {**states, args.id: state})
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            {**states, args.id: state},
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "start",
        "id": args.id,
        "state": state,
        "table_view": table_view,
        "warnings": warnings[:DEFAULT_LIMIT],
        "warning_count": len(warnings),
        "diagnostics": (diagnostics + state_diagnostics(args.id, state))[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics) + len(state_diagnostics(args.id, state)),
    }


def command_note(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint_values = (
        args.evidence_frontier,
        args.active_consumer,
        args.validation_case,
        args.validated_coverage,
        args.uncovered_dimension,
        args.latest_evidence,
        args.invalidated_source_id,
    )
    if all(
        value is None
        for value in (
            args.message,
            args.status,
            args.blocked_reason,
            args.next_action,
            *checkpoint_values,
        )
    ) and not args.clear_execution_checkpoint:
        raise TaskctlError(
            "note requires progress, status, a next action, or an execution checkpoint"
        )
    if args.clear_execution_checkpoint and any(
        value is not None for value in checkpoint_values
    ):
        raise TaskctlError(
            "--clear-execution-checkpoint cannot be combined with checkpoint values"
        )
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the note command has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        previous_state = dict(state)
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if state["status"] == "done":
            diagnostics.append({"kind": "note_added_to_completed_task"})
        if state["owner"] is None:
            state["owner"] = args.owner
        if state["status"] == "todo" and args.status is None:
            state["status"] = "claimed"
        if args.status is not None:
            state["status"] = args.status
            if args.status != "blocked" and args.blocked_reason is None:
                state["blocked_reason"] = ""
        if args.message is not None:
            state["note"] = semantic_string(args.message, "note.message")
        if args.blocked_reason is not None:
            state["blocked_reason"] = semantic_string(
                args.blocked_reason, "note.blocked_reason"
            )
            if state["blocked_reason"] and args.status is None:
                state["status"] = "blocked"
            if not state["blocked_reason"] and state["status"] == "blocked":
                diagnostics.append(
                    {"kind": "blocked_reason_cleared_while_status_remains_blocked"}
                )
        if args.next_action is not None:
            state["next_action"] = semantic_string(args.next_action, "note.next_action")
        if args.clear_execution_checkpoint:
            clear_execution_checkpoint(state)
        else:
            if args.evidence_frontier is not None:
                state["evidence_frontier"] = semantic_string(
                    args.evidence_frontier, "note.evidence_frontier"
                )
            if args.active_consumer is not None:
                state["active_consumer"] = semantic_string(
                    args.active_consumer, "note.active_consumer"
                )
            if args.validation_case is not None:
                state["validation_case"] = string_list(
                    args.validation_case, "note.validation_case"
                )
            if args.validated_coverage is not None:
                state["validated_coverage"] = string_list(
                    args.validated_coverage, "note.validated_coverage"
                )
            if args.uncovered_dimension is not None:
                state["uncovered_dimensions"] = string_list(
                    args.uncovered_dimension, "note.uncovered_dimensions"
                )
            if args.latest_evidence is not None:
                state["latest_evidence"] = semantic_string(
                    args.latest_evidence, "note.latest_evidence"
                )
            if args.invalidated_source_id is not None:
                state["invalidated_source_ids"] = string_list(
                    args.invalidated_source_id, "note.invalidated_source_ids"
                )
        state = write_state(root, table, state, previous_state)
        diagnostics.extend(state_diagnostics(args.id, state))
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            {**states, args.id: state},
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "note",
        "id": args.id,
        "state": state,
        "table_view": table_view,
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
    }


def command_complete(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    raw_result = read_json(Path(args.result_file).expanduser().resolve())
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the completion has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        task = tasks[args.id]
        if args.expected_task_revision is None:
            raise TaskctlError(
                "complete requires --expected-task-revision",
                gate_id="TASK-REVISION",
                risk="the completion has no caller-observed task contract revision and could bind an older execution to a newer contract",
                recovery="read the task revision used for execution and retry with --expected-task-revision",
                retryable=True,
            )
        if task["revision"] != args.expected_task_revision:
            raise TaskctlError(
                f"task revision conflict: expected {args.expected_task_revision}, current {task['revision']}",
                gate_id="TASK-REVISION",
                risk="the completion result was produced against a different task contract revision",
                recovery="reload the current task contract, reconcile or redo the result, and retry with its revision",
                retryable=True,
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        result, legacy_result_envelope = normalize_completion_result(
            raw_result, task, args.expected_task_revision
        )
        inline_snapshot = result.pop("source_snapshot", None)
        result_file_snapshot_ref = result.get("source_snapshot_ref")
        argument_snapshot_ref = None
        if args.source_snapshot_ref is not None:
            argument_snapshot_ref = normalize_source_snapshot_ref(
                args.source_snapshot_ref, "--source-snapshot-ref"
            )
        receipt_snapshot_ref = None
        if args.source_receipt is not None:
            receipt_snapshot_ref = resolve_source_receipt(
                root, table, args.source_receipt, args.id
            )
        if (
            argument_snapshot_ref is not None
            and receipt_snapshot_ref is not None
            and argument_snapshot_ref != receipt_snapshot_ref
        ):
            raise TaskctlError(
                "--source-receipt and --source-snapshot-ref resolve to different snapshots",
                gate_id="TASK-SNAPSHOT-CONFLICT",
                risk="the completion would mix two competing execution snapshots",
                recovery="pass one captured source receipt or the matching machine snapshot reference",
            )
        argument_snapshot_ref = argument_snapshot_ref or receipt_snapshot_ref
        if inline_snapshot is not None and argument_snapshot_ref is not None:
            raise TaskctlError(
                "legacy inline source_snapshot cannot be combined with --source-snapshot-ref",
                gate_id="TASK-SNAPSHOT-CONFLICT",
                risk="the completion would mix two competing execution snapshots",
                recovery="use the captured reference or the legacy inline map, not both",
            )
        if (
            result_file_snapshot_ref is not None
            and argument_snapshot_ref is not None
            and result_file_snapshot_ref != argument_snapshot_ref
        ):
            raise TaskctlError(
                "result source_snapshot_ref differs from --source-snapshot-ref",
                gate_id="TASK-SNAPSHOT-CONFLICT",
                risk="the completion would mix two competing execution snapshots",
                recovery="pass the same captured reference through one completion input",
            )
        legacy_snapshot_externalized = inline_snapshot is not None
        if inline_snapshot is not None:
            result["source_snapshot_ref"] = store_source_snapshot(
                root, table, inline_snapshot
            )
        elif argument_snapshot_ref is not None:
            result["source_snapshot_ref"] = argument_snapshot_ref
        if result.get("source_snapshot_ref") is not None:
            require_completion_source_snapshot(
                root, table, result["source_snapshot_ref"], args.id
            )
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if legacy_result_envelope:
            diagnostics.append({"kind": "legacy_result_envelope_normalized"})
        if legacy_snapshot_externalized:
            diagnostics.append(
                {
                    "kind": "legacy_inline_source_snapshot_externalized",
                    "source_snapshot_ref": result["source_snapshot_ref"],
                }
            )
        if state["status"] == "done":
            diagnostics.append({"kind": "task_already_done"})
        if state["status"] not in {"in_progress", "review"}:
            diagnostics.append(
                {
                    "kind": "non_typical_completion_state",
                    "from_status": state["status"],
                }
            )
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
        clear_execution_checkpoint(next_state)
        next_state = apply_state_timestamps(state, next_state, end_event=True)
        next_state = validate_state(next_state, args.id)
        recovered_partial_write = result_path.exists()
        if recovered_partial_write:
            existing_result = validate_result_for_task(
                read_json(result_path), task, require_current_revision=True
            )
            if existing_result != result:
                raise TaskctlError(
                    f"conflicting partial result: {result_path}",
                    gate_id="TASK-OVERWRITE",
                    risk="completion would overwrite a different existing result record",
                    recovery="inspect the existing result and retry with a reconciled state revision",
                )
            result = existing_result
        else:
            atomic_write_json(result_path, result)
        _, state_dir, _ = table_paths(root, table)
        atomic_write_json(state_dir / f"{args.id}.json", next_state)
        state = next_state
        states = {**states, args.id: state}
        diagnostics.extend(task_diagnostics(task, tasks, states, index))
        diagnostic_result = hydrate_result_source_snapshot(root, table, result)
        diagnostics.extend(result_diagnostics(diagnostic_result, task, index))
        if not result["verification"]:
            diagnostics.append({"kind": "result_verification_empty"})
        if result["unresolved"]:
            diagnostics.append(
                {"kind": "result_has_unresolved", "count": len(result["unresolved"])}
            )
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            states,
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "complete",
        "id": args.id,
        "state": state,
        "result_ref": relative_ref,
        "table_view": table_view,
        "recovered_partial_write": recovered_partial_write,
        "diagnostics": diagnostics[: args.diagnostic_limit],
        "diagnostic_count": len(diagnostics),
        "note": "completion records the model-provided result; it is not a product audit",
    }


def command_reopen(args: argparse.Namespace) -> dict[str, Any]:
    reason = semantic_string(args.reason, "reopen.reason")
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the reopen command has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        previous_state = dict(state)
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if state["status"] != "done":
            diagnostics.append(
                {"kind": "non_typical_reopen_state", "from_status": state["status"]}
            )
        state["status"] = "todo"
        state["owner"] = None
        state["note"] = f"reopened: {reason}"
        state["blocked_reason"] = ""
        state["next_action"] = ""
        clear_execution_checkpoint(state)
        state["result_ref"] = None
        state = write_state(root, table, state, previous_state)
        diagnostics.extend(state_diagnostics(args.id, state))
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            {**states, args.id: state},
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "reopen",
        "id": args.id,
        "state": state,
        "table_view": table_view,
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
    }


def command_release(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        if args.id not in tasks:
            raise TaskctlError(
                f"task is unavailable or unknown: {args.id}",
                gate_id="TASK-AMBIGUOUS-TARGET",
                risk="the release command has no readable uniquely identified task",
                recovery="repair the matching task/state record or choose a current task ID",
            )
        state = states[args.id]
        check_expected_state(state, args.expected_state_revision)
        previous_state = dict(state)
        index, index_diagnostics = maybe_load_index(root, table)
        diagnostics = [
            *storage_diagnostics,
            *index_diagnostics,
            *owner_diagnostics(state, args.owner),
        ]
        if state["status"] == "done":
            diagnostics.append({"kind": "completed_task_released"})
        if state["owner"] is None:
            diagnostics.append({"kind": "unowned_task_released"})
        state["status"] = "todo"
        state["owner"] = None
        state["blocked_reason"] = ""
        state["next_action"] = ""
        clear_execution_checkpoint(state)
        state["result_ref"] = None
        state = write_state(root, table, state, previous_state)
        diagnostics.extend(state_diagnostics(args.id, state))
        table_view, table_view_diagnostic = refresh_task_table_after_mutation(
            root,
            table,
            tasks,
            {**states, args.id: state},
            storage_diagnostics,
            index,
            index_diagnostics,
        )
        if table_view_diagnostic is not None:
            diagnostics.append(table_view_diagnostic)
    return {
        "ok": True,
        "command": "release",
        "id": args.id,
        "state": state,
        "table_view": table_view,
        "diagnostics": diagnostics[:DEFAULT_LIMIT],
        "diagnostic_count": len(diagnostics),
    }


def command_impact(args: argparse.Namespace) -> dict[str, Any]:
    args.recursive = True
    result = command_dependents(args)
    result["command"] = "impact"
    result["note"] = "dependents require model review and are not automatically invalid"
    return result


def markdown_cell(value: Any, maximum: int = 120) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= maximum else text[:maximum] + "…"


def markdown_table_cell(value: Any, maximum: int = 120) -> str:
    if value is None:
        return "—"
    text = markdown_cell(value, maximum)
    return text if text.strip() else "—"


def render_task_table_locked(
    root: Path,
    table: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    storage_diagnostics: list[dict[str, Any]],
    index: dict[str, Any] | None,
    index_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    storage = summarize_loaded_task_storage(root, table, tasks, states, index)
    generated_at = utc_now_timestamp()
    active_frontiers, active_frontier_count = active_execution_frontiers(
        root,
        table,
        tasks,
        states,
        index,
        storage["state_writeback_drifts"],
        DEFAULT_LIMIT,
    )
    output_path = resolve_inside(root, str(table.get("table_view", "TASK_TABLE.md")))
    counts = storage["counts"]
    lines = [
        f"# {table.get('title') or table.get('id') or 'Tasks'}",
        "",
        "> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。",
        f"> 视图刷新时间：{generated_at}；真源仍为 tasks/、state/ 与 results/。",
        "",
        "## 状态统计",
        "",
    ]
    nonzero_statuses = [(status, count) for status, count in counts.items() if count]
    if nonzero_statuses:
        lines.extend(["| 状态 | 数量 |", "| --- | ---: |"])
        lines.extend(f"| {status} | {count} |" for status, count in nonzero_statuses)
    else:
        lines.append("- 无任务")
    if active_frontiers:
        lines.extend(["", "## 当前执行前沿", ""])
        for frontier in active_frontiers:
            lines.extend(
                [
                    f"### {markdown_cell(frontier['id'])} · {markdown_cell(frontier['status'])}",
                    "",
                    f"- 标题：{markdown_cell(frontier['title'], 240)}",
                    f"- 当前任务结果：{markdown_cell(frontier['outcome'], 320)}",
                    "- 真源："
                    + markdown_cell(
                        f"{frontier['source']['task']}@r{frontier['source']['task_revision']}; "
                        f"{frontier['source']['state']}@r{frontier['source']['state_revision']}",
                        240,
                    ),
                    "- 修改范围："
                    + markdown_cell(
                        ", ".join(frontier.get("mutation_scope", [])) or "—", 320
                    ),
                ]
            )
            for field, label in (
                ("source_ids", "目标来源"),
                ("evidence_frontier", "证据前沿"),
                ("active_consumer", "当前消费者"),
                ("validation_dimensions", "可能改变结论的维度"),
                ("validation_case", "当前验证 case"),
                ("validated_coverage", "已验证覆盖"),
                ("uncovered_dimensions", "仍未覆盖"),
                ("latest_evidence", "最近有效证据/反例"),
                ("invalidated_source_ids", "已失效来源"),
                ("next_action", "下一项有界动作"),
            ):
                value = frontier.get(field)
                if value in (None, "", []):
                    continue
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                lines.append(f"- {label}：{markdown_cell(value, 320)}")
            for deferred_change in frontier.get("deferred_changes", []):
                location = ":".join(
                    str(value)
                    for value in (
                        deferred_change.get("document"),
                        deferred_change.get("line"),
                    )
                    if value not in (None, "")
                )
                lines.append(
                    "- 关联 DCR："
                    + markdown_cell(
                        f"{deferred_change.get('id')} [{deferred_change.get('status')}] "
                        f"{deferred_change.get('title')} — {deferred_change.get('body', '')}"
                        + (f" ({location})" if location else ""),
                        360,
                    )
                )
            if frontier.get("deferred_changes_truncated"):
                lines.append("- 关联 DCR：已截断；用 context 读取本任务完整关联项")
            for drift in frontier.get("state_writeback_drifts", []):
                lines.append(
                    "- 状态漂移："
                    + markdown_cell(
                        f"{drift.get('path')} 未被 state r{drift.get('state_revision')} 引用；"
                        f"result task r{drift.get('result_task_revision')} / "
                        f"current task r{drift.get('current_task_revision')}；"
                        f"{drift.get('recovery')}",
                        360,
                    )
                )
            lines.append("")
        if active_frontier_count > len(active_frontiers):
            lines.append(
                f"- 仅展示前 {len(active_frontiers)} 项，共 {active_frontier_count} 项；"
                "使用 status --limit 或 context 渐进读取。"
            )
    lines.extend(["", "## 复核与结果", ""])
    if counts["review"]:
        lines.append(f"- 需复核任务：{counts['review']}")
    if storage["state_writeback_drift_count"]:
        lines.append(
            f"- 结果/state 结构写回漂移：{storage['state_writeback_drift_count']}"
        )
    if storage["result_count"]:
        lines.extend(
            [
                f"- 当前状态引用结果：{storage['result_count']}",
                f"- 含验证结果：{storage['result_with_verification_count']}",
            ]
        )
        for label, key in (
            ("含未决结果", "result_with_unresolved_count"),
            ("含结果诊断", "result_with_diagnostics_count"),
            ("任务合同 revision 陈旧结果", "task_revision_stale_result_count"),
            ("含来源快照问题结果", "source_snapshot_issue_result_count"),
            ("结果诊断条目", "result_diagnostic_count"),
        ):
            if storage[key]:
                lines.append(f"- {label}：{storage[key]}")
    else:
        lines.append("- 当前没有结果引用")
    if index is not None:
        summary = index.get("summary", {})
        lines.extend(
            [
                "",
                "## 上游状态",
                "",
                f"- 用户确认快照：{index.get('protected_baseline', {}).get('status')}",
            ]
        )
        if summary.get("unresolved_count"):
            lines.append(f"- 可修订上游未决：{summary['unresolved_count']}")
        if summary.get("deferred_change_count"):
            lines.append(f"- 延后讨论项：{summary['deferred_change_count']}")
    all_storage_diagnostics = [
        *storage_diagnostics,
        *storage.get("diagnostics", []),
    ]
    if all_storage_diagnostics:
        lines.extend(["", "## 存储诊断", ""])
        lines.extend(
            f"- {markdown_cell(item.get('kind'))}: "
            + markdown_cell(item.get("message", ""), 320)
            + (
                f"；恢复：{markdown_cell(item.get('recovery'), 320)}"
                if item.get("recovery")
                else ""
            )
            for item in all_storage_diagnostics[:DEFAULT_LIMIT]
        )
    lines.extend(["", "## 任务", ""])
    if tasks:
        lines.extend(
            [
                "| ID | 状态 | Owner | 开始时间 | 结束时间 | 标题 | 依赖 | 结果 | 合同修订 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
            ]
        )
        task_ids_for_display = sorted(
            tasks,
            key=lambda task_id: (states[task_id]["status"] == "retired", task_id),
        )
        for task_id in task_ids_for_display:
            task = tasks[task_id]
            state = states[task_id]
            dependencies = ", ".join(
                f"{dependency['id']}:{dependency['type']}"
                for dependency in task["dependencies"]
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_table_cell(task_id),
                        markdown_table_cell(state["status"]),
                        markdown_table_cell(state["owner"]),
                        markdown_table_cell(state["started_at"]),
                        markdown_table_cell(state["ended_at"]),
                        markdown_table_cell(task["title"]),
                        markdown_table_cell(dependencies),
                        markdown_table_cell(state["result_ref"]),
                        str(task["revision"]),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- 无任务")
    atomic_write_text(output_path, "\n".join(lines) + "\n")
    return {
        "ok": True,
        "command": "render",
        "generated_at": generated_at,
        "output": str(output_path),
        "task_count": len(tasks),
        "status_counts": counts,
        "needs_review_count": counts["review"],
        "active_frontier_count": active_frontier_count,
        "active_frontiers": active_frontiers,
        "state_writeback_drift_count": storage["state_writeback_drift_count"],
        "results": {
            "referenced_result_count": storage["result_count"],
            "result_with_verification_count": storage[
                "result_with_verification_count"
            ],
            "result_with_unresolved_count": storage["result_with_unresolved_count"],
            "result_with_diagnostics_count": storage[
                "result_with_diagnostics_count"
            ],
            "task_revision_stale_result_count": storage[
                "task_revision_stale_result_count"
            ],
            "source_snapshot_issue_result_count": storage[
                "source_snapshot_issue_result_count"
            ],
            "result_diagnostic_count": storage["result_diagnostic_count"],
            "result_diagnostic_kind_counts": storage[
                "result_diagnostic_kind_counts"
            ],
        },
        "index_diagnostics": index_diagnostics[:DEFAULT_LIMIT],
        "index_diagnostic_count": len(index_diagnostics),
        "storage_diagnostics": all_storage_diagnostics[:DEFAULT_LIMIT],
        "storage_diagnostic_count": len(all_storage_diagnostics),
    }


def refresh_task_table_after_mutation(
    root: Path,
    table: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
    storage_diagnostics: list[dict[str, Any]],
    index: dict[str, Any] | None,
    index_diagnostics: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        rendered = render_task_table_locked(
            root,
            table,
            tasks,
            states,
            storage_diagnostics,
            index,
            index_diagnostics,
        )
    except Exception as exc:
        table_view = {
            "status": "stale",
            "output": str(root / str(table.get("table_view", "TASK_TABLE.md"))),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "recovery": "run taskctl render for the same absolute --task-dir after repairing the generated-view path or filesystem",
        }
        return table_view, {
            "kind": "task_table_refresh_failed",
            "error_type": table_view["error_type"],
            "error": table_view["error"],
            "recovery": table_view["recovery"],
        }
    return {
        "status": "refreshed",
        "output": rendered["output"],
    }, None


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.task_dir)
    with workspace_lock(root):
        table = load_table(root)
        tasks, states, storage_diagnostics = load_query_storage(root, table)
        index, index_diagnostics = maybe_load_index(root, table)
        return render_task_table_locked(
            root,
            table,
            tasks,
            states,
            storage_diagnostics,
            index,
            index_diagnostics,
        )


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--task-dir",
        required=True,
        help="任务表工作目录，其中必须包含 task-table.json",
    )
    parser.add_argument(
        "--view",
        choices=("model", "machine"),
        default="model",
        help="输出视图：model 为当前动作稀疏证据，machine 为完整稳定结构",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="仅在 machine 视图缩进 JSON 输出",
    )
    parser.add_argument(
        "--model-token-budget",
        type=int,
        default=DEFAULT_MODEL_TOKEN_BUDGET,
        help="model 视图的保守 Token 上限；超限时裁剪完整低优先级单元",
    )


def add_limit(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help="单页最多返回的记录数（1—1000）"
    )


def add_state_revision(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expected-state-revision",
        type=int,
        help="预期 state revision；不匹配时拒绝并发覆盖",
    )


def add_command_parser(
    subparsers: Any, name: str, summary: str, *, epilog: str | None = None
) -> argparse.ArgumentParser:
    return subparsers.add_parser(
        name, help=summary, description=summary, epilog=epilog
    )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"taskctl {WORKFLOW_CLI_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = add_command_parser(subparsers, "init", "初始化任务表固定目录和登记文件")
    add_common(init_parser)
    init_parser.add_argument("--id", required=True, help="工作流稳定 ID，必须与 Delivery Workflow 一致")
    init_parser.add_argument("--title", required=True, help="任务表的人类可读标题")
    init_parser.set_defaults(handler=command_init)

    draft_parser = add_command_parser(subparsers, "draft", "生成不落盘的最小候选任务")
    add_common(draft_parser)
    draft_parser.add_argument("--id", required=True, help="候选任务稳定 ID")
    draft_parser.add_argument("--title", required=True, help="候选任务标题")
    draft_parser.add_argument("--outcome", required=True, help="任务完成后必须成立的可验收结果")
    draft_parser.add_argument("--source-id", action="append", default=[], help="关联的上游方案或目标 ID；可重复")
    draft_parser.add_argument(
        "--dependency",
        action="append",
        default=[],
        help="依赖，格式 TASK_ID:type[:consumed-output]；可重复",
    )
    draft_parser.add_argument("--mutation-scope", action="append", default=[], help="允许修改的路径或职责范围；可重复")
    draft_parser.add_argument("--output", action="append", default=[], help="必须交付的产物；可重复")
    draft_parser.add_argument("--verification", action="append", default=[], help="直接验收方式；可重复")
    draft_parser.add_argument(
        "--validation-dimension",
        action="append",
        default=[],
        help="可能改变行为或 oracle 的验证维度；可重复",
    )
    draft_parser.add_argument("--suggested-skill", action="append", default=[], help="执行时建议选择的 skill；可重复且不构成许可")
    draft_parser.add_argument("--reasoning-hint", help="执行阶段的非约束推理深度提示")
    draft_parser.set_defaults(handler=command_draft)

    add_parser = add_command_parser(subparsers, "add", "写入新的任务合同并注入机器字段")
    add_common(add_parser)
    add_parser.add_argument("--file", required=True, help="只含任务语义的 JSON 输入文件")
    add_parser.set_defaults(handler=command_add)

    update_parser = add_command_parser(subparsers, "update", "按任务 revision 更新任务合同")
    add_common(update_parser)
    update_parser.add_argument("--file", required=True, help="完整替换任务语义的 JSON 输入文件")
    update_parser.add_argument("--owner", help="当前执行 owner；用于所有权诊断，不创建授权")
    update_parser.add_argument("--expected-task-revision", type=int, help="预期 task revision；不匹配时拒绝并发覆盖")
    update_parser.set_defaults(handler=command_update)

    show_parser = add_command_parser(subparsers, "show", "有界读取一个任务及其状态和结果")
    add_common(show_parser)
    show_parser.add_argument("--id", required=True, help="要读取的任务 ID")
    show_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="machine JSON 最大字符数（1000—100000）")
    show_parser.set_defaults(handler=command_show)

    list_parser = add_command_parser(subparsers, "list", "分页列出任务及局部诊断")
    add_common(list_parser)
    add_limit(list_parser)
    list_parser.add_argument("--after-id", help="从该任务 ID 之后继续分页")
    list_parser.add_argument("--status", action="append", help="只返回指定状态；可重复")
    list_parser.set_defaults(handler=command_list)

    deps_parser = add_command_parser(subparsers, "deps", "查询任务依赖")
    add_common(deps_parser)
    add_limit(deps_parser)
    deps_parser.add_argument("--id", required=True, help="作为查询起点的任务 ID")
    deps_parser.add_argument("--recursive", action="store_true", help="递归返回传递依赖")
    deps_parser.add_argument("--after-id", help="从该依赖任务 ID 之后继续分页")
    deps_parser.set_defaults(handler=command_deps)

    dependents_parser = add_command_parser(subparsers, "dependents", "查询消费当前任务的后继")
    add_common(dependents_parser)
    add_limit(dependents_parser)
    dependents_parser.add_argument("--id", required=True, help="作为查询起点的任务 ID")
    dependents_parser.add_argument("--recursive", action="store_true", help="递归返回传递后继")
    dependents_parser.add_argument("--after-id", help="从该后继任务 ID 之后继续分页")
    dependents_parser.set_defaults(handler=command_dependents)

    next_parser = add_command_parser(subparsers, "next", "返回建议候选，不签发执行许可")
    add_common(next_parser)
    add_limit(next_parser)
    next_parser.add_argument("--owner", help="按当前领取 owner 过滤或解释候选")
    next_parser.add_argument("--include-blocked", action="store_true", help="把被阻塞任务也纳入建议结果")
    next_parser.add_argument("--diagnostic-limit", type=int, default=10, help="最多返回的诊断条数（1—1000）")
    next_parser.add_argument("--after-id", help="从该候选任务 ID 之后继续分页")
    next_parser.set_defaults(handler=command_next)

    context_parser = add_command_parser(
        subparsers,
        "context",
        "取得执行上下文并可捕获来源收据",
        epilog="示例：taskctl context --task-dir <工作目录> --id T001 --capture",
    )
    add_common(context_parser)
    context_parser.add_argument("--id", required=True, help="要执行的任务 ID")
    context_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="machine JSON 最大字符数（1000—100000）")
    context_parser.add_argument("--max-items", type=int, default=DEFAULT_LIMIT, help="每类上游上下文最多包含的完整条目数（1—1000）")
    context_parser.add_argument("--capture", action="store_true", help="按最终可见上下文写入内容寻址来源快照并返回收据")
    context_parser.set_defaults(
        handler=command_context, model_token_budget=6_144
    )

    completion_parser = add_command_parser(
        subparsers,
        "completion-context",
        "分页取得最终复核证据，不裁决整体完成",
        epilog="示例：taskctl completion-context --task-dir <工作目录> --target-id T001",
    )
    add_common(completion_parser)
    add_limit(completion_parser)
    completion_parser.add_argument("--after-id", help="从该目标任务 ID 之后继续目标目录分页")
    completion_parser.add_argument("--target-id", help="只展开一个目标任务的完整复核证据")
    completion_parser.add_argument("--candidate-after-id", help="继续指定 target 的候选证据分页；要求 --target-id")
    completion_parser.add_argument("--constraint-after-id", help="继续约束目录分页")
    completion_parser.add_argument("--deferred-after-id", help="继续延后项目录分页")
    completion_parser.add_argument("--snapshot-id", help="首屏返回的复核快照 ID；后续页必须原样传回")
    completion_parser.add_argument("--review-receipt", help="model 首屏返回的短复核收据；model 续页必须原样传回")
    completion_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="machine JSON 最大字符数（1000—100000）")
    completion_parser.add_argument("--max-items", type=int, default=DEFAULT_LIMIT, help="每类证据最多返回的完整条目数（1—1000）")
    completion_parser.set_defaults(
        handler=command_completion_context, model_token_budget=4_096
    )

    status_parser = add_command_parser(subparsers, "status", "汇总任务状态、结果和实际诊断")
    add_common(status_parser)
    add_limit(status_parser)
    status_parser.set_defaults(handler=command_status)

    claim_parser = add_command_parser(subparsers, "claim", "按 state revision 记录领取意图")
    add_common(claim_parser)
    claim_parser.add_argument("--id", required=True, help="要领取的任务 ID")
    claim_parser.add_argument("--owner", required=True, help="领取者稳定身份")
    add_state_revision(claim_parser)
    claim_parser.set_defaults(handler=command_claim)

    start_parser = add_command_parser(subparsers, "start", "按 state revision 记录开始执行")
    add_common(start_parser)
    start_parser.add_argument("--id", required=True, help="要开始执行的任务 ID")
    start_parser.add_argument("--owner", required=True, help="必须与当前领取者一致的稳定身份")
    add_state_revision(start_parser)
    start_parser.set_defaults(handler=command_start)

    note_parser = add_command_parser(subparsers, "note", "按 state revision 写入有界执行说明")
    add_common(note_parser)
    note_parser.add_argument("--id", required=True, help="要更新执行说明的任务 ID")
    note_parser.add_argument("--owner", required=True, help="当前执行 owner 的稳定身份")
    note_parser.add_argument("--message", help="替换当前有界执行说明；传空字符串可清除")
    note_parser.add_argument("--status", help="新的执行状态；非标准值只形成诊断")
    note_parser.add_argument("--blocked-reason", help="阻塞原因；仅 blocked 状态应保留")
    note_parser.add_argument("--next-action", help="恢复执行所需的下一动作")
    note_parser.add_argument("--evidence-frontier", help="当前最早会支配后续动作的未证判断")
    note_parser.add_argument("--active-consumer", help="当前用于闭合前沿的真实消费者")
    note_parser.add_argument(
        "--validation-case",
        action="append",
        default=None,
        help="当前消费者实际选择的维度值或等价类；可重复并整体替换",
    )
    note_parser.add_argument(
        "--validated-coverage",
        action="append",
        default=None,
        help="当前检查点已有直接证据覆盖的维度值或等价类；可重复并整体替换",
    )
    note_parser.add_argument(
        "--uncovered-dimension",
        action="append",
        default=None,
        help="当前已知仍未覆盖的维度、值或 case；可重复并整体替换",
    )
    note_parser.add_argument("--latest-evidence", help="最近有效结果或关键反例的有界摘要")
    note_parser.add_argument(
        "--invalidated-source-id",
        action="append",
        default=None,
        help="被当前反例推翻的上游 ID；可重复并整体替换",
    )
    note_parser.add_argument(
        "--clear-execution-checkpoint",
        action="store_true",
        help="清除当前前沿、消费者、验证 case、覆盖边界、最近证据和失效 ID",
    )
    add_state_revision(note_parser)
    note_parser.set_defaults(handler=command_note)

    complete_parser = add_command_parser(
        subparsers,
        "complete",
        "用 task/state CAS 和来源收据提交结果",
        epilog="示例：taskctl complete --task-dir <工作目录> --id T001 --owner agent-a --result-file result.json --expected-task-revision 3 --expected-state-revision 5",
    )
    add_common(complete_parser)
    complete_parser.add_argument("--id", required=True, help="要提交结果的任务 ID")
    complete_parser.add_argument("--owner", required=True, help="必须与当前执行 owner 一致的稳定身份")
    complete_parser.add_argument("--result-file", required=True, help="只含结果语义的 JSON 输入文件；机器身份由 CLI 注入")
    complete_parser.add_argument("--expected-task-revision", type=int, help="执行所依据的 task revision；不匹配时拒绝提交")
    complete_parser.add_argument("--source-snapshot-ref", help="machine context --capture 返回的完整内容寻址引用；与结果文件内收据不可并用")
    complete_parser.add_argument("--source-receipt", help="model context --capture 返回的可读来源收据")
    complete_parser.add_argument("--diagnostic-limit", type=int, default=20, help="最多返回的结果诊断条数（1—1000）")
    add_state_revision(complete_parser)
    complete_parser.set_defaults(handler=command_complete)

    reopen_parser = add_command_parser(subparsers, "reopen", "记录现有完成结论或合同已经失效")
    add_common(reopen_parser)
    reopen_parser.add_argument("--id", required=True, help="要重开的任务 ID")
    reopen_parser.add_argument("--owner", required=True, help="执行重开的稳定身份")
    reopen_parser.add_argument("--reason", required=True, help="现有完成结论或合同失效的直接原因")
    add_state_revision(reopen_parser)
    reopen_parser.set_defaults(handler=command_reopen)

    release_parser = add_command_parser(subparsers, "release", "清除领取意图并返回待办状态")
    add_common(release_parser)
    release_parser.add_argument("--id", required=True, help="要释放的任务 ID")
    release_parser.add_argument("--owner", required=True, help="必须与当前领取者一致的稳定身份")
    add_state_revision(release_parser)
    release_parser.set_defaults(handler=command_release)

    impact_parser = add_command_parser(subparsers, "impact", "递归查询受当前任务影响的后继")
    add_common(impact_parser)
    add_limit(impact_parser)
    impact_parser.add_argument("--id", required=True, help="发生变化的起点任务 ID")
    impact_parser.add_argument("--after-id", help="从该受影响任务 ID 之后继续分页")
    impact_parser.set_defaults(handler=command_impact)

    render_parser = add_command_parser(subparsers, "render", "重建只读 TASK_TABLE.md 导航视图")
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
    if not 256 <= args.model_token_budget <= 100_000:
        raise TaskctlError("--model-token-budget must be between 256 and 100000")
    if args.pretty and args.view != "machine":
        raise TaskctlError("--pretty requires --view machine")
    if hasattr(args, "expected_state_revision"):
        value = args.expected_state_revision
        if value is not None and value < 1:
            raise TaskctlError("--expected-state-revision must be positive")
    if (
        getattr(args, "command", None) == "completion-context"
        and args.target_id is not None
        and args.after_id is not None
    ):
        raise TaskctlError("--target-id and --after-id cannot be combined")
    if (
        getattr(args, "command", None) == "completion-context"
        and args.candidate_after_id is not None
        and args.target_id is None
    ):
        raise TaskctlError("--candidate-after-id requires --target-id")
    if getattr(args, "command", None) == "completion-context":
        has_cursor = any(
            value is not None
            for value in (
                args.after_id,
                args.candidate_after_id,
                args.constraint_after_id,
                args.deferred_after_id,
            )
        )
        continuation_receipt = (
            args.review_receipt if args.view == "model" else args.snapshot_id
        )
        if has_cursor and not continuation_receipt:
            required = "--review-receipt" if args.view == "model" else "--snapshot-id"
            raise TaskctlError(f"completion pagination requires {required}")
        if args.review_receipt is not None and args.snapshot_id is not None:
            raise TaskctlError("--review-receipt and --snapshot-id cannot be combined")
        target_stream = bool(
            args.after_id is not None
            or args.candidate_after_id is not None
            or (
                args.target_id is not None
                and (args.snapshot_id or args.review_receipt)
            )
        )
        continued_streams = sum(
            (
                target_stream,
                args.constraint_after_id is not None,
                args.deferred_after_id is not None,
            )
        )
        if continued_streams > 1:
            raise TaskctlError(
                "completion pagination accepts one result stream at a time"
            )
    if (
        hasattr(args, "expected_task_revision")
        and args.expected_task_revision is not None
        and args.expected_task_revision < 1
    ):
        raise TaskctlError("--expected-task-revision must be positive")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
        result = args.handler(args)
        capture_snapshot = None
        if (
            args.command == "context"
            and args.view == "model"
            and getattr(args, "capture", False)
        ):
            root = resolve_root(args.task_dir)

            def capture_snapshot(sources: dict[str, str]) -> str:
                with workspace_lock(root):
                    return store_source_receipt(
                        root, load_table(root), args.id, sources
                    )

        emit(
            result,
            pretty=args.pretty,
            view=args.view,
            model_token_budget=args.model_token_budget,
            capture_snapshot=capture_snapshot,
        )
        return 0
    except TaskctlError as exc:
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
        error = TaskctlError(
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
