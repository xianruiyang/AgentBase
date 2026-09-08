from __future__ import annotations

import hashlib
import json
from typing import Any

from .expression import UNKNOWN, evaluate, matches
from .spec import RESULT_SCHEMA, EvoError


MAX_SCORE_CELLS = 100_000


def _group_rows(rows: list[dict[str, Any]], group_by: list[str]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    if not group_by:
        return [({}, rows)]
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        dimensions = row.get("dimensions", {})
        key = tuple(dimensions.get(name) for name in group_by)
        grouped.setdefault(key, []).append(row)
    return [({name: key[index] for index, name in enumerate(group_by)}, selected) for key, selected in grouped.items()]


def _validate_row_fields(spec: dict[str, Any], artifacts: dict[str, Any]) -> None:
    fields = {field["id"]: field for field in spec["fields"]}
    for row in artifacts["rows"]:
        for field_id, value in row["values"].items():
            if field_id not in fields:
                raise EvoError(f"artifact row {row['id']} uses undeclared field: {field_id}")
            declared = fields[field_id]
            if row["grain"] != declared["grain"]:
                raise EvoError(f"artifact row {row['id']} field {field_id} has grain {row['grain']}, expected {declared['grain']}")
            expected = declared["type"]
            valid = ((expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)) or
                     (expected == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
                     (expected == "boolean" and isinstance(value, bool)) or
                     (expected == "string" and isinstance(value, str)))
            if value is not None and not valid:
                raise EvoError(f"artifact row {row['id']} field {field_id} does not match type {expected}")


def _metric_dependencies(expression: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    if isinstance(expression.get("metric"), str):
        result.add(expression["metric"])
    for value in expression.values():
        if isinstance(value, dict):
            result.update(_metric_dependencies(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.update(_metric_dependencies(item))
    return result


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


def _identity(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unit(value: str) -> dict[str, int]:
    if value in {"ratio", "score", "dimensionless", "1"}:
        return {}
    result: dict[str, int] = {}
    numerator, separator, denominator = value.partition("/")
    for token in filter(None, numerator.split("*")):
        result[token] = result.get(token, 0) + 1
    if separator:
        for token in filter(None, denominator.split("*")):
            result[token] = result.get(token, 0) - 1
    return {key: power for key, power in result.items() if power}


def _combine_units(left: dict[str, int], right: dict[str, int], sign: int) -> dict[str, int]:
    result = dict(left)
    for key, power in right.items():
        result[key] = result.get(key, 0) + sign * power
    return {key: power for key, power in result.items() if power}


def _expression_unit(
    expression: dict[str, Any], field_units: dict[str, str], metric_units: dict[str, str]
) -> dict[str, int] | None:
    if "literal" in expression:
        return _unit(expression.get("unit", "dimensionless"))
    if "field" in expression and "aggregate" not in expression:
        return _unit(field_units[expression["field"]])
    if "metric" in expression:
        return _unit(metric_units[expression["metric"]])
    if "aggregate" in expression:
        if expression["aggregate"] in {"count", "distinct"}:
            return None
        return _unit(field_units[expression["field"]])
    operation = expression.get("op")
    if operation in {"eq", "ne", "lt", "lte", "gt", "gte"}:
        args = expression.get("args", [])
        units = [_expression_unit(arg, field_units, metric_units) for arg in args]
        if len(units) != 2 or units[0] != units[1]:
            raise EvoError(f"comparison {operation} requires matching units")
        return _unit("boolean")
    if operation in {"and", "or"}:
        args = expression.get("args", [])
        units = [_expression_unit(arg, field_units, metric_units) for arg in args]
        if not units or any(value != _unit("boolean") for value in units):
            raise EvoError(f"operation {operation} requires boolean args")
        return _unit("boolean")
    if operation == "if":
        condition = _expression_unit(expression["condition"], field_units, metric_units)
        if condition != _unit("boolean"):
            raise EvoError("if condition must be boolean")
        left = _expression_unit(expression["then"], field_units, metric_units)
        right = _expression_unit(expression["else"], field_units, metric_units)
        if left != right:
            raise EvoError("if branches must have matching units")
        return left
    args = expression.get("args", [])
    units = [_expression_unit(arg, field_units, metric_units) for arg in args]
    if any(value is None for value in units):
        raise EvoError(f"operation {operation} requires metrics with declared units")
    concrete = [value for value in units if value is not None]
    if operation in {"add", "subtract"}:
        if any(value != concrete[0] for value in concrete[1:]):
            raise EvoError(f"operation {operation} requires matching units")
        return concrete[0]
    if operation == "multiply":
        result: dict[str, int] = {}
        for value in concrete:
            result = _combine_units(result, value, 1)
        return result
    if operation == "divide" and len(concrete) == 2:
        return _combine_units(concrete[0], concrete[1], -1)
    return None


def _validate_metric_units(spec: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    field_units = {field["id"]: field["unit"] for field in spec["fields"]}
    metric_units: dict[str, str] = {}
    for metric in _metric_order(metrics):
        inferred = _expression_unit(metric["expression"], field_units, metric_units)
        if inferred is not None and inferred != _unit(metric["unit"]):
            raise EvoError(f"metric {metric['id']} declares unit {metric['unit']} incompatible with its expression")
        metric_units[metric["id"]] = metric["unit"]


def _metric_order(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {metric["id"]: metric for metric in metrics}
    pending = dict(by_id)
    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set()
    while pending:
        ready = [identity for identity, metric in pending.items() if _metric_dependencies(metric["expression"]) <= resolved]
        if not ready:
            unknown = set().union(*(_metric_dependencies(metric["expression"]) for metric in pending.values())) - set(by_id)
            if unknown:
                raise EvoError(f"metrics reference unknown dependencies: {sorted(unknown)}")
            raise EvoError(f"metric dependency cycle: {sorted(pending)}")
        for identity in ready:
            ordered.append(pending.pop(identity))
            resolved.add(identity)
    return ordered


def score_artifacts(spec: dict[str, Any], artifacts: dict[str, Any], scoring_ids: list[str] | None = None) -> dict[str, Any]:
    _validate_row_fields(spec, artifacts)
    selection = spec.get("selection", {})
    allowed_combinations = set(selection.get("combinations", [entry["id"] for entry in spec["combinations"]]))
    groups = {entry["id"]: entry for entry in spec["evaluations"]["groups"]}
    selected_groups = selection.get("groups", [identity for identity, group in groups.items() if group.get("active", False)])
    allowed_items = {item for group_id in selected_groups for item in groups[group_id]["items"]}
    families = {item["id"]: item["family"] for item in spec["evaluations"]["items"] if item.get("family")}
    selected_rows = [
        row for row in artifacts["rows"]
        if ("combination" not in row.get("dimensions", {}) or row["dimensions"]["combination"] in allowed_combinations)
        and ("item" not in row.get("dimensions", {}) or row["dimensions"]["item"] in allowed_items)
    ]
    # Family belongs to the frozen evaluation item, including older receipts
    # that predate its projection into row dimensions. Do not rewrite facts.
    selected_rows = [
        {**row, "dimensions": {**row.get("dimensions", {}), "family": families[row["dimensions"]["item"]]}}
        if row.get("dimensions", {}).get("item") in families and "family" not in row.get("dimensions", {}) else row
        for row in selected_rows
    ]
    configs = {config["id"]: config for config in spec["scoring"]}
    selected = scoring_ids or list(configs)
    unknown = set(selected) - set(configs)
    if unknown:
        raise EvoError(f"unknown scoring configurations: {sorted(unknown)}")
    outputs: list[dict[str, Any]] = []
    used_fields: set[str] = set()
    score_cells = 0
    for config_id in selected:
        config = configs[config_id]
        _validate_metric_units(spec, config["metrics"])
        config_rows = [row for row in selected_rows if matches(row, config.get("select", {}))]
        group_by = config.get("group_by", [])
        if not isinstance(group_by, list) or any(not isinstance(value, str) for value in group_by):
            raise EvoError(f"scoring {config_id}.group_by must be an array of strings")
        groups: list[dict[str, Any]] = []
        grouped_rows = _group_rows(config_rows, group_by)
        score_cells += len(grouped_rows) * len(config["metrics"])
        if score_cells > MAX_SCORE_CELLS:
            raise EvoError(f"score output exceeds {MAX_SCORE_CELLS} metric cells")
        for dimensions, rows in grouped_rows:
            values: dict[str, Any] = {}
            metric_sources: dict[str, set[str]] = {}
            metric_results: list[dict[str, Any]] = []
            for metric in _metric_order(config["metrics"]):
                value = evaluate(metric["expression"], rows, values, metric.get("missing", "unknown"))
                values[metric["id"]] = value
                direct_fields = _field_references(metric["expression"])
                used_fields.update(direct_fields)
                source_ids = {
                    row["id"]
                    for row in rows
                    if direct_fields & set(row.get("values", {}))
                }
                for dependency in _metric_dependencies(metric["expression"]):
                    source_ids.update(metric_sources[dependency])
                metric_sources[metric["id"]] = source_ids
                source_rows = sorted(source_ids)
                incomplete = sum(row["completeness"] != "complete" for row in rows if row["id"] in source_ids)
                metric_results.append({
                    "id": metric["id"],
                    "value": None if value is UNKNOWN else value,
                    "status": "unknown" if value is UNKNOWN else "computed",
                    "unit": metric["unit"],
                    "expression": metric["expression"],
                    "sample_count": len(source_rows),
                    "incomplete_sample_count": incomplete,
                    "source_rows": source_rows,
                })
            groups.append({"dimensions": dimensions, "sample_count": len(rows), "metrics": metric_results})
        outputs.append({"id": config_id, "version": config["version"], "identity_sha256": _identity(config), "group_by": group_by, "groups": groups})
    field_catalog = {field["id"]: field for field in spec["fields"] if field["id"] in used_fields}
    return {
        "schema": RESULT_SCHEMA,
        "research": {"id": spec["id"], "version": spec["version"]},
        "artifacts": {"id": artifacts["id"], "version": artifacts["version"]},
        "source_snapshot": {
            "spec_sha256": _identity(spec),
            "artifacts_sha256": _identity(artifacts),
            "field_catalog": field_catalog,
            "source_rows": {row["id"]: {"source": row["source"], "completeness": row["completeness"]} for row in artifacts["rows"]},
        },
        "source_row_count": len(artifacts["rows"]),
        "scores": outputs,
    }
