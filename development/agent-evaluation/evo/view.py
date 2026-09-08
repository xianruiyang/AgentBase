"""Bounded model-facing projections for existing Evo machine results."""
from __future__ import annotations

import json
from typing import Any, Callable

from .spec import EvoError


RECOVERY = "Full machine data is unchanged; rerun with --view machine or write it with --output <path>."
MIN_MODEL_TOKENS = 128
MAX_MODEL_TOKENS = 20_000


def model_text_cost(text: str) -> int:
    """The repository's conservative ASCII-word/CJK model-text cost contract."""
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


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower()):
        return "machine-id-hidden"
    return value


def _take(values: list[Any], count: int) -> tuple[list[Any], int]:
    return values[:count], max(0, len(values) - count)


def _base(schema: str) -> dict[str, Any]:
    return {"schema": "agentbase-evo-model-view/v1", "source_schema": schema, "recovery": RECOVERY}


def _plan(value: dict[str, Any], count: int) -> dict[str, Any]:
    jobs, omitted = _take(value.get("jobs", []), count)
    selection = value.get("selection", {})
    result = {
        **_base(value["schema"]), "study": value.get("source", {}), "job_count": value.get("job_count", len(value.get("jobs", []))),
        "selection": {"combinations": selection.get("combinations", [])[:count], "groups": selection.get("groups", [])[:count], "replicates": selection.get("replicates")},
        "jobs": [{key: job.get(key) for key in ("id", "combination", "item", "replicate", "groups", "observations")} for job in jobs],
    }
    if omitted:
        result["omitted"] = {"jobs": omitted}
    return result


def _status(value: dict[str, Any], count: int) -> dict[str, Any]:
    jobs, omitted = _take(value.get("jobs", []), count)
    result = {
        **_base(value["schema"]), "study": value.get("study"), "counts": value.get("counts", {}),
        "total_jobs": value.get("total_jobs"), "tokens_observed": value.get("tokens_observed"),
        "tokens_reserved": value.get("tokens_reserved"), "usage_unsettled": value.get("usage_unsettled"),
        "resources": value.get("resources"),
        "jobs": [{key: job.get(key) for key in ("job", "study", "item", "combination", "state", "reason", "error", "reused_from", "usage", "usage_complete")} for job in jobs],
    }
    if omitted or value.get("truncated"):
        result["omitted"] = {"jobs_in_value": omitted, "source_was_truncated": bool(value.get("truncated")), "next_offset": value.get("next_offset")}
    return result


def _resources(value: dict[str, Any], count: int) -> dict[str, Any]:
    storage = value.get("managed_storage", {})
    volumes, omitted = _take(value.get("volumes", []), count)
    result = {**_base(value["schema"]), "study": value.get("study"),
              "managed_storage": {key: storage.get(key) for key in
                                  ("used_bytes", "reserved_bytes", "used_plus_reserved_bytes", "max_bytes",
                                   "min_free_bytes", "complete", "error")},
              "volumes": volumes, "capacity": value.get("capacity"), "reuse": value.get("reuse")}
    if omitted:
        result["omitted"] = {"volumes": omitted}
    return result


def _scores(value: dict[str, Any], count: int) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    unknown = incomplete = 0
    for score in value.get("scores", []):
        for group in score.get("groups", []):
            for metric in group.get("metrics", []):
                unknown += metric.get("status") == "unknown"
                incomplete += int(metric.get("incomplete_sample_count", 0) or 0)
                lines.append({
                    "score": score.get("id"), "version": score.get("version"), "group": group.get("dimensions", {}),
                    "metric": metric.get("id"), "value": metric.get("value"), "status": metric.get("status"),
                    "unit": metric.get("unit"), "samples": metric.get("sample_count"),
                    "incomplete": metric.get("incomplete_sample_count"),
                })
    selected, omitted = _take(lines, count)
    result = {
        **_base(value["schema"]), "research": value.get("research"),
        "artifacts": {"id": value.get("artifacts", {}).get("id"), "version": _short(value.get("artifacts", {}).get("version"))},
        "source_row_count": value.get("source_row_count"), "metric_count": len(lines),
        "unknown_metric_count": unknown, "incomplete_source_count": incomplete, "score_lines": selected,
    }
    if omitted:
        result["omitted"] = {"score_lines": omitted}
    return result


def _artifacts(value: dict[str, Any], count: int) -> dict[str, Any]:
    rows = value.get("rows", [])
    completeness: dict[str, int] = {}
    fields: set[str] = set()
    for row in rows:
        state = str(row.get("completeness", "unknown"))
        completeness[state] = completeness.get(state, 0) + 1
        fields.update(row.get("values", {}))
    result = {
        **_base(value["schema"]), "artifacts": {"id": value.get("id"), "version": _short(value.get("version"))},
        "row_count": len(rows), "completeness": completeness, "fields": sorted(fields)[:count],
    }
    if value.get("calculator"):
        calculator = value["calculator"]
        result["calculator"] = {"id": calculator.get("id"), "version": calculator.get("version"), "code_source": calculator.get("code", {}).get("path")}
    if len(fields) > count:
        result["omitted"] = {"fields": len(fields) - count}
    return result


def _review(value: dict[str, Any], count: int) -> dict[str, Any]:
    if value["schema"] == "agentbase-evo-review-projection/v1":
        heads = list(value.get("heads", {}).values())
        return {**_base(value["schema"]), "record_count": value.get("record_count"), "current_assessment_count": len(heads),
                "current": [{key: item.get(key) for key in ("review_key", "field", "value", "reviewer")} for item in heads[:count]],
                "omitted": {"current_assessments": max(0, len(heads) - count)}}
    items = value.get("items", [])
    assessments = value.get("assessments", [])
    missing = value.get("missing", [])
    result = {**_base(value["schema"]), "package": value.get("alias") or "review-package", "complete": value.get("complete"),
              "item_count": len(items), "assessment_count": len(assessments), "missing_count": len(missing),
              "missing": missing[:count], "blind": value.get("blind"), "blind_scope": value.get("blind_scope")}
    if value["schema"] == "agentbase-evo-review-import/v1":
        result.update(imported_count=len(value.get("imported", [])), skipped_blank=value.get("skipped_blank"))
    omitted = max(0, len(missing) - count)
    if omitted:
        result["omitted"] = {"missing": omitted}
    return result


def _evaluation(value: dict[str, Any], count: int) -> dict[str, Any]:
    reviews = _runtime_reviews(value.get("reviews", []), count, "evaluation-reviews")
    return {**_base(value["schema"]), "operation": "evaluate", "study": value.get("study"),
            "status": _status(value.get("status", {"schema": "agentbase-evo-status/v1"}), count),
            "reviews": reviews,
            "scores": _scores(value.get("scores", {"schema": "agentbase-evo-scores/v1"}), count)}


def _trace(value: dict[str, Any], count: int) -> dict[str, Any]:
    events, omitted = _take(value.get("events", []), count)
    projected_events = []
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        projected = {key: event.get(key) for key in ("seq", "time", "job", "agent", "role", "kind", "server", "tool", "status", "seconds", "action", "path", "error") if event.get(key) is not None}
        if isinstance(event.get("excerpt"), str):
            projected["excerpt"] = event["excerpt"][:400]
            projected["excerpt_truncated"] = len(event["excerpt"]) > 400
        for key, maximum in (("arguments", 400), ("result_excerpt", 600)):
            if key not in event:
                continue
            raw = event[key]
            encoded = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            projected[key] = encoded[:maximum]
            projected[f"{key}_truncated"] = len(encoded) > maximum
        for key in ("action", "state", "reason", "source_job", "error"):
            if key in payload and key not in projected:
                projected[key] = payload[key]
        projected_events.append(projected)
    coverage = []
    for record in value.get("coverage", []):
        issues = record.get("issues", {}) if isinstance(record.get("issues"), dict) else {}
        coverage.append({
            "job": record.get("job"), "agent": record.get("agent"),
            "lines": record.get("lines", record.get("records")),
            "complete_scan": record.get("complete_scan"),
            "issue_counts": {key: len(item) if isinstance(item, (list, dict)) else item for key, item in issues.items()},
        })
    snapshot = value.get("snapshot")
    result = {
        **_base(value["schema"]), "study": value.get("study"), "source": value.get("source"),
        "summary": value.get("summary", {}), "coverage": coverage[:count],
        "snapshot": f"snapshot-{snapshot[:8]}" if isinstance(snapshot, str) and snapshot else None,
        "events": projected_events, "page": value.get("page", {}),
    }
    coverage_omitted = max(0, len(coverage) - count)
    if omitted or coverage_omitted:
        result["omitted"] = {"events_in_value": omitted, "coverage_rows": coverage_omitted}
    return result


def _candidate(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("candidate-") and len(value) <= 32:
        return value
    if isinstance(value, str) and len(value) >= 8:
        return f"candidate-{value[:8]}"
    return value


def _runtime_reviews(values: list[Any], count: int, operation: str) -> dict[str, Any]:
    rows = [value for value in values if isinstance(value, dict)]
    selected, omitted = _take(rows, count)
    complete = sum(value.get("complete") is True for value in rows)
    changed = sum(value.get("state_changed") is True for value in rows)
    result = {
        "operation": operation, "review_count": len(rows), "complete_count": complete,
        "pending_count": sum(value.get("complete") is False for value in rows), "state_changed_count": changed,
        "reviews": [{key: value.get(key) for key in ("job", "alias", "path", "complete", "missing", "state_changed") if key in value}
                    for value in selected],
    }
    if omitted:
        result["omitted"] = {"reviews": omitted}
    return result


def _grading_facts(value: dict[str, Any], count: int) -> dict[str, Any]:
    rows, omitted = _take(value.get("rows", []), count)
    result = {
        **_base(value["schema"]), "subject_study": value.get("subject_study"), "grader_study": value.get("grader_study"),
        "grading": value.get("grading"), "usage": value.get("usage"), "usage_complete": value.get("usage_complete"),
        "fact_count": len(value.get("rows", [])),
        "facts": [{"id": row.get("id"), "dimensions": row.get("dimensions"), "values": row.get("values"),
                   "completeness": row.get("completeness")} for row in rows],
    }
    if omitted:
        result["omitted"] = {"facts": omitted}
    return result


def _grading_run(value: dict[str, Any], count: int) -> dict[str, Any]:
    return {**_base("grade-run"), "operation": "grade-run", "status": _status(value["status"], count),
            "facts": _grading_facts(value["facts"], count), "grader_usage": value.get("grader_usage"),
            "research_usage": value.get("research_usage")}


def _optimization(value: dict[str, Any], _count: int) -> dict[str, Any]:
    result = {
        **_base(value["schema"]), "operation": "optimization", "optimization": value.get("alias") or (f"opt-{value['id'][:8]}" if isinstance(value.get("id"), str) else None),
        "state": value.get("state"), "round": value.get("round"), "baseline": _candidate(value.get("baseline")),
        "champion": _candidate(value.get("champion")), "controller_tokens": value.get("controller_tokens"),
        "subject_tokens": value.get("subject_tokens"), "grader_tokens": value.get("grader_tokens"), "stop_reason": value.get("stop_reason"),
        "awaiting": value.get("awaiting"), "final_study": value.get("final_study"),
        "final_acceptance": value.get("final_acceptance"),
    }
    return result


def _optimization_export(value: dict[str, Any], _count: int) -> dict[str, Any]:
    identity = value.get("optimization")
    return {
        **_base(value["schema"]), "operation": "optimize-export",
        "optimization": f"opt-{identity[:8]}" if isinstance(identity, str) else identity,
        "state": value.get("state"), "baseline": _candidate(value.get("baseline")), "champion": _candidate(value.get("champion")),
        "candidate_root": value.get("candidate_root"), "controller_tokens": value.get("controller_tokens"),
        "subject_tokens": value.get("subject_tokens"), "grader_tokens": value.get("grader_tokens"),
        "final_study": value.get("final_study"), "final_acceptance": value.get("final_acceptance"), "note": value.get("note"),
    }


def _small_result(value: dict[str, Any], kind: str) -> dict[str, Any]:
    result = {**_base(kind), "operation": kind}
    for key in ("valid", "study", "id", "version", "output", "rows", "limits"):
        if key in value:
            result[key] = _short(value[key]) if key in {"id", "version"} else value[key]
    if "schema" in value:
        result["result_schema"] = value["schema"]
    if isinstance(value.get("calculator"), dict):
        calculator = value["calculator"]
        result["calculator"] = {"id": calculator.get("id"), "version": calculator.get("version"), "code_source": calculator.get("code", {}).get("path")}
    return result


PROJECTORS: dict[str, Callable[[dict[str, Any], int], dict[str, Any]]] = {
    "agentbase-evo-resources/v1": _resources,
    "agentbase-evo-plan/v1": _plan,
    "agentbase-evo-status/v1": _status,
    "agentbase-evo-scores/v1": _scores,
    "agentbase-evo-artifacts/v1": _artifacts,
    "agentbase-evo-review-package/v1": _review,
    "agentbase-evo-review-projection/v1": _review,
    "agentbase-evo-review-status/v1": _review,
    "agentbase-evo-review-import/v1": _review,
    "agentbase-evo-evaluation/v1": _evaluation,
    "agentbase-evo-trace/v1": _trace,
    "agentbase-evo-model-grading-facts/v1": _grading_facts,
    "agentbase-evo-optimization/v1": _optimization,
    "agentbase-evo-optimization-export/v1": _optimization_export,
}


def project_model(value: dict[str, Any], *, items: int = 20) -> dict[str, Any]:
    if isinstance(value, dict) and set(value) == {"limits"}:
        return _small_result(value, "init")
    if isinstance(value, dict) and set(value) == {"study"}:
        return _small_result(value, "submit")
    if isinstance(value, dict) and {"subject_study", "grader_study", "grading", "identity"} <= set(value):
        return {**_base("grade-start"), "operation": "grade-start", "subject_study": value.get("subject_study"),
                "grader_study": value.get("grader_study"), "grading": value.get("grading")}
    if isinstance(value, dict) and {"status", "facts", "grader_usage", "research_usage"} <= set(value):
        return _grading_run(value, items)
    if isinstance(value, dict) and set(value) == {"study", "reviews"}:
        operation = "review-sync" if any(isinstance(row, dict) and "state_changed" in row for row in value["reviews"]) else "review-prepare"
        return {**_base(operation), "operation": operation, "study": value["study"],
                "reviews": _runtime_reviews(value["reviews"], items, operation)}
    if isinstance(value, dict) and value.get("valid") is True and {"schema", "id", "version"} <= set(value):
        return _small_result(value, "validate")
    if isinstance(value, dict) and "output" in value and isinstance(value.get("rows"), int) and isinstance(value.get("calculator"), dict):
        return _small_result(value, "calculate")
    if isinstance(value, dict) and "output" in value and "schema" in value and set(value) <= {"output", "schema", "id"}:
        return _small_result(value, "save")
    if isinstance(value, dict) and "schema" not in value and {"package_id", "imported", "skipped_blank"} <= set(value):
        value = {"schema": "agentbase-evo-review-import/v1", **value}
    elif isinstance(value, dict) and "schema" not in value and {"alias", "complete", "missing"} <= set(value):
        value = {"schema": "agentbase-evo-review-status/v1", **value}
    if not isinstance(value, dict) or value.get("schema") not in PROJECTORS:
        raise EvoError(f"no model projection for schema: {value.get('schema') if isinstance(value, dict) else type(value).__name__}")
    if type(items) is not int or not 1 <= items <= 500:
        raise EvoError("model projection items must be an integer from 1 to 500")
    return PROJECTORS[value["schema"]](value, items)


def render_model(value: dict[str, Any], limit: int = 1200) -> str:
    """Render a bounded projection; reduction is explicit through omitted counts and recovery."""
    if type(limit) is not int or not MIN_MODEL_TOKENS <= limit <= MAX_MODEL_TOKENS:
        raise EvoError(f"model view limit must be an integer from {MIN_MODEL_TOKENS} to {MAX_MODEL_TOKENS}")
    count = 100
    while count >= 1:
        projection = project_model(value, items=count)
        rendered = json.dumps(projection, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if model_text_cost(rendered) <= limit:
            return rendered
        count //= 2
    projection = project_model(value, items=1)
    if projection.get("operation") in {"init", "submit", "validate", "save", "calculate", "grade-start", "grade-run",
                                        "review-prepare", "review-sync", "evaluate", "optimization", "optimize-export"}:
        minimal = {"schema": projection["schema"], "operation": projection["operation"], "success": True, "recovery": RECOVERY}
        for key in ("study", "output", "valid"):
            if key in projection:
                minimal[key] = projection[key]
        return json.dumps(minimal, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    raise EvoError("decision summary exceeds the selected model-view limit; increase it, use --view machine, or use --output")
