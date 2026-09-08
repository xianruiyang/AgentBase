from __future__ import annotations

import math
import statistics
from typing import Any, Callable

from .spec import EvoError


UNKNOWN = object()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return UNKNOWN  # type: ignore[return-value]
    if not 0 <= percentile <= 100:
        raise EvoError("percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def matches(row: dict[str, Any], selector: dict[str, Any]) -> bool:
    dimensions = row.get("dimensions", {})
    for name, expected in selector.items():
        actual = dimensions.get(name)
        allowed = expected if isinstance(expected, list) else [expected]
        if actual not in allowed:
            return False
    return True


def evaluate_predicate(expression: dict[str, Any], row: dict[str, Any]) -> bool:
    value = evaluate(expression, [row], {}, "unknown")
    return value is not UNKNOWN and bool(value)


def _field_values(expression: dict[str, Any], rows: list[dict[str, Any]]) -> list[Any]:
    field = expression.get("field")
    if not isinstance(field, str):
        raise EvoError("aggregate.field must be a string")
    selector = expression.get("select", {})
    if not isinstance(selector, dict):
        raise EvoError("aggregate.select must be an object")
    where = expression.get("where")
    values: list[Any] = []
    for row in rows:
        if not matches(row, selector):
            continue
        if field not in row.get("values", {}):
            continue
        if where is not None and not evaluate_predicate(where, row):
            continue
        if row.get("completeness") != "complete":
            values.append(UNKNOWN)
        else:
            values.append(row.get("values", {}).get(field, UNKNOWN))
    return values


def _apply_missing(values: list[Any], policy: str) -> tuple[list[Any], int]:
    missing = sum(value is UNKNOWN or value is None for value in values)
    if missing and policy == "error":
        raise EvoError("selected data contains missing or incomplete values")
    if missing and policy == "unknown":
        return [UNKNOWN], missing
    if policy == "zero":
        return [0 if value is UNKNOWN or value is None else value for value in values], missing
    return [value for value in values if value is not UNKNOWN and value is not None], missing


def evaluate(
    expression: dict[str, Any],
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    missing_policy: str,
) -> Any:
    if "literal" in expression:
        return expression["literal"]
    if "metric" in expression:
        return metrics.get(expression["metric"], UNKNOWN)
    if "field" in expression and "aggregate" not in expression:
        values = _field_values({"field": expression["field"], "select": expression.get("select", {})}, rows)
        values, _ = _apply_missing(values, missing_policy)
        return values[0] if len(values) == 1 else UNKNOWN
    if "aggregate" in expression:
        operation = expression["aggregate"]
        values, _ = _apply_missing(_field_values(expression, rows), missing_policy)
        if values == [UNKNOWN]:
            return UNKNOWN
        if operation == "count":
            return len(values)
        if operation == "distinct":
            return len({json_key(value) for value in values})
        if not values:
            return UNKNOWN
        if not all(_is_number(value) for value in values):
            raise EvoError(f"aggregate {operation} requires numeric values")
        numeric = [float(value) for value in values]
        functions: dict[str, Callable[[list[float]], Any]] = {
            "sum": sum,
            "mean": statistics.fmean,
            "median": statistics.median,
            "min": min,
            "max": max,
        }
        if operation == "percentile":
            return _percentile(numeric, float(expression.get("percentile", 50)))
        if operation not in functions:
            raise EvoError(f"unsupported aggregate: {operation}")
        return functions[operation](numeric)

    operation = expression.get("op")
    if operation == "if":
        condition = evaluate(expression.get("condition", {}), rows, metrics, missing_policy)
        branch = "then" if condition is not UNKNOWN and bool(condition) else "else"
        return evaluate(expression.get(branch, {}), rows, metrics, missing_policy)
    args = expression.get("args")
    if not isinstance(args, list) or not args:
        raise EvoError("expression operation requires non-empty args")
    values = [evaluate(arg, rows, metrics, missing_policy) for arg in args]
    if any(value is UNKNOWN for value in values):
        return UNKNOWN
    if operation in {"eq", "ne", "lt", "lte", "gt", "gte"}:
        if len(values) != 2:
            raise EvoError(f"comparison {operation} requires two args")
        compare = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a < b,
                   "lte": lambda a, b: a <= b, "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b}
        return compare[operation](values[0], values[1])
    if operation in {"and", "or"}:
        return all(map(bool, values)) if operation == "and" else any(map(bool, values))
    if not all(_is_number(value) for value in values):
        raise EvoError(f"operation {operation} requires numeric args")
    if operation == "add":
        return sum(values)
    if operation == "subtract" and len(values) == 2:
        return values[0] - values[1]
    if operation == "multiply":
        return math.prod(values)
    if operation == "divide" and len(values) == 2:
        if values[1] == 0:
            handling = expression.get("zero_division", "unknown")
            if handling == "zero":
                return 0
            if handling == "error":
                raise EvoError("division by zero")
            return UNKNOWN
        return values[0] / values[1]
    raise EvoError(f"unsupported or malformed operation: {operation}")


def json_key(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
