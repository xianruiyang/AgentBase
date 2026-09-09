from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


SPEC_SCHEMA = "agentbase-evo-research/v1"
ARTIFACT_SCHEMA = "agentbase-evo-artifacts/v1"
RESULT_SCHEMA = "agentbase-evo-scores/v1"
COMPONENT_KINDS = (
    "agents_md",
    "skills",
    "hooks",
    "mcp",
    "tools",
    "agents",
    "codex_settings",
)
FIELD_TYPES = {"number", "integer", "boolean", "string"}
GRAINS = {"research", "job", "attempt", "request", "agent", "event", "assessment"}
COMPLETENESS = {"complete", "partial", "missing", "redacted", "truncated"}
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_ARTIFACT_ROWS = 100_000
MAX_REPLICATES = 100
MAX_PLAN_JOBS = 100_000


class EvoError(ValueError):
    """A deterministic Evo contract error suitable for CLI display."""


def _reject_nonfinite(value: Any, where: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise EvoError(f"{where} contains a non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{where}[{index}]")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvoError(f"{where} must be an object")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvoError(f"{where} must be an array")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvoError(f"{where} must be a non-empty string")
    return value


def _unique(items: list[dict[str, Any]], where: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        entry = _object(item, f"{where}[{index}]")
        identity = _text(entry.get("id"), f"{where}[{index}].id")
        if identity in result:
            raise EvoError(f"duplicate {where} id: {identity}")
        result[identity] = entry
    return result


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise EvoError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(EvoError(f"non-finite JSON number: {value}")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoError(f"cannot read JSON {path}: {exc}") from exc
    return _object(value, str(path))


def load_spec(path: Path) -> dict[str, Any]:
    spec = read_json(path)
    from .swe_catalog import resolve_catalog
    spec = resolve_catalog(spec, path)
    from .code_reading_catalog import resolve_catalog as resolve_code_reading_catalog
    spec = resolve_code_reading_catalog(spec, path)
    validate_spec(spec)
    return spec


def validate_spec(spec: dict[str, Any]) -> None:
    _reject_nonfinite(spec, "spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise EvoError(f"schema must be {SPEC_SCHEMA}")
    _text(spec.get("id"), "id")
    _text(spec.get("version"), "version")

    components = _object(spec.get("components"), "components")
    if set(components) != set(COMPONENT_KINDS):
        missing = sorted(set(COMPONENT_KINDS) - set(components))
        extra = sorted(set(components) - set(COMPONENT_KINDS))
        raise EvoError(f"components must define the seven kinds; missing={missing}, extra={extra}")
    component_ids: dict[str, set[str]] = {}
    for kind in COMPONENT_KINDS:
        entries = _unique(_list(components[kind], f"components.{kind}"), f"components.{kind}")
        for identity, entry in entries.items():
            _text(entry.get("source"), f"components.{kind}.{identity}.source")
        component_ids[kind] = set(entries)

    combinations = _unique(_list(spec.get("combinations"), "combinations"), "combinations")
    for combo_id, combo in combinations.items():
        members = _object(combo.get("members"), f"combinations.{combo_id}.members")
        unknown_kinds = set(members) - set(COMPONENT_KINDS)
        if unknown_kinds:
            raise EvoError(f"combination {combo_id} has unknown component kinds: {sorted(unknown_kinds)}")
        for kind, selected in members.items():
            for member in _list(selected, f"combinations.{combo_id}.members.{kind}"):
                if member not in component_ids[kind]:
                    raise EvoError(f"combination {combo_id} references unknown {kind}: {member}")

    evaluations = _object(spec.get("evaluations"), "evaluations")
    items = _unique(_list(evaluations.get("items"), "evaluations.items"), "evaluations.items")
    for item_id, item in items.items():
        _text(item.get("input_version"), f"evaluations.items.{item_id}.input_version")
        _text(item.get("protocol"), f"evaluations.items.{item_id}.protocol")
        observations = _list(item.get("observations", []), f"evaluations.items.{item_id}.observations")
        if any(not isinstance(value, str) or not value for value in observations):
            raise EvoError(f"evaluations.items.{item_id}.observations must contain strings")
    groups = _unique(_list(evaluations.get("groups"), "evaluations.groups"), "evaluations.groups")
    for group_id, group in groups.items():
        for item_id in _list(group.get("items"), f"evaluations.groups.{group_id}.items"):
            if item_id not in items:
                raise EvoError(f"group {group_id} references unknown evaluation item: {item_id}")
        if "active" in group and not isinstance(group["active"], bool):
            raise EvoError(f"evaluations.groups.{group_id}.active must be boolean")

    fields = _unique(_list(spec.get("fields"), "fields"), "fields")
    for field_id, field in fields.items():
        if field.get("type") not in FIELD_TYPES:
            raise EvoError(f"field {field_id} has unsupported type")
        if field.get("grain") not in GRAINS:
            raise EvoError(f"field {field_id} has unsupported grain")
        _text(field.get("unit"), f"fields.{field_id}.unit")
        _text(field.get("source"), f"fields.{field_id}.source")
        if "extract" in field:
            extract = _object(field["extract"], f"fields.{field_id}.extract")
            if set(extract) != {"from", "path"}:
                raise EvoError(f"field {field_id}.extract requires exactly from and path")
            if (not isinstance(extract["from"], str) or
                    extract["from"] not in {"attempt", "agent", "request", "event"} or extract["from"] != field["grain"]):
                raise EvoError(f"field {field_id}.extract.from must match its supported runtime grain")
            raw_path = extract["path"]
            parts = raw_path.split(".") if isinstance(raw_path, str) else raw_path
            if (not isinstance(parts, list) or not 1 <= len(parts) <= 16 or
                    any(not isinstance(part, str) or not 1 <= len(part) <= 128 or "\x00" in part for part in parts)):
                raise EvoError(f"field {field_id}.extract.path must contain 1..16 bounded object keys")

    scoring = _unique(_list(spec.get("scoring"), "scoring"), "scoring")
    for scoring_id, config in scoring.items():
        _text(config.get("version"), f"scoring.{scoring_id}.version")
        metrics = _unique(_list(config.get("metrics"), f"scoring.{scoring_id}.metrics"), f"scoring.{scoring_id}.metrics")
        for metric_id, metric in metrics.items():
            expression = _object(metric.get("expression"), f"scoring.{scoring_id}.metrics.{metric_id}.expression")
            unknown_fields = _field_references(expression) - set(fields)
            if unknown_fields:
                raise EvoError(f"metric {metric_id} references unknown fields: {sorted(unknown_fields)}")
            _text(metric.get("unit"), f"scoring.{scoring_id}.metrics.{metric_id}.unit")
            if metric.get("missing", "unknown") not in {"unknown", "zero", "exclude", "error"}:
                raise EvoError(f"metric {metric_id} has unsupported missing policy")

    selection = _object(spec.get("selection", {}), "selection")
    selected_combinations = _list(selection.get("combinations", list(combinations)), "selection.combinations")
    if len(selected_combinations) != len(set(selected_combinations)):
        raise EvoError("selection.combinations contains duplicates")
    for combo_id in selected_combinations:
        if combo_id not in combinations:
            raise EvoError(f"selection references unknown combination: {combo_id}")
    default_groups = [identity for identity, group in groups.items() if group.get("active", False)]
    selected_groups = _list(selection.get("groups", default_groups), "selection.groups")
    if len(selected_groups) != len(set(selected_groups)):
        raise EvoError("selection.groups contains duplicates")
    for group_id in selected_groups:
        if group_id not in groups:
            raise EvoError(f"selection references unknown group: {group_id}")
    replicates = selection.get("replicates", 1)
    if not isinstance(replicates, int) or isinstance(replicates, bool) or not 1 <= replicates <= MAX_REPLICATES:
        raise EvoError(f"selection.replicates must be an integer from 1 to {MAX_REPLICATES}")
    selected_item_count = len({item_id for group_id in selected_groups for item_id in groups[group_id]["items"]})
    if len(selected_combinations) * selected_item_count * replicates > MAX_PLAN_JOBS:
        raise EvoError(f"selection expands beyond {MAX_PLAN_JOBS} plan jobs")


def _field_references(expression: dict[str, Any]) -> set[str]:
    result = {expression["field"]} if isinstance(expression.get("field"), str) else set()
    for value in expression.values():
        if isinstance(value, dict):
            result.update(_field_references(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.update(_field_references(item))
    return result


def load_artifacts(path: Path) -> dict[str, Any]:
    artifacts = read_json(path)
    validate_artifacts(artifacts)
    return artifacts


def validate_artifacts(artifacts: dict[str, Any]) -> None:
    _reject_nonfinite(artifacts, "artifacts")
    if artifacts.get("schema") != ARTIFACT_SCHEMA:
        raise EvoError(f"artifact schema must be {ARTIFACT_SCHEMA}")
    _text(artifacts.get("id"), "artifacts.id")
    _text(artifacts.get("version"), "artifacts.version")
    rows = _list(artifacts.get("rows"), "artifacts.rows")
    if len(rows) > MAX_ARTIFACT_ROWS:
        raise EvoError(f"artifacts.rows exceeds {MAX_ARTIFACT_ROWS} rows")
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        row = _object(raw, f"artifacts.rows[{index}]")
        row_id = _text(row.get("id"), f"artifacts.rows[{index}].id")
        if row_id in seen:
            raise EvoError(f"duplicate artifact row id: {row_id}")
        seen.add(row_id)
        if row.get("grain") not in GRAINS:
            raise EvoError(f"artifact row {row_id} has unsupported grain")
        _object(row.get("dimensions", {}), f"artifact row {row_id}.dimensions")
        _object(row.get("values"), f"artifact row {row_id}.values")
        source = _object(row.get("source"), f"artifact row {row_id}.source")
        _text(source.get("kind"), f"artifact row {row_id}.source.kind")
        _text(source.get("location"), f"artifact row {row_id}.source.location")
        if row.get("completeness") not in COMPLETENESS:
            raise EvoError(f"artifact row {row_id} has unsupported completeness")
