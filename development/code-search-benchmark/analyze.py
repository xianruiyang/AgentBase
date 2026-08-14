#!/usr/bin/env python3
"""Validate and summarize recorded code-search benchmark runs."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

SCHEMA = "agentbase.code-search-benchmark/v1"
MAX_FILE_BYTES = 1_048_576


class BenchmarkError(ValueError):
    pass


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise BenchmarkError(f"{label} must be a non-negative number")
    return float(value)


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BenchmarkError(f"{label} must be a positive integer")
    return value


def _paths(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be an array")
    return [_string(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _read_bounded(root: Path, relative: str) -> str:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise BenchmarkError(f"benchmark file escapes manifest directory: {relative}") from error
    size = candidate.stat().st_size
    if size > MAX_FILE_BYTES:
        raise BenchmarkError(f"benchmark file exceeds {MAX_FILE_BYTES} bytes: {relative}")
    return candidate.read_text(encoding="utf-8")


def analyze(manifest_path: Path) -> dict[str, Any]:
    try:
        import tiktoken
    except ImportError as error:
        raise BenchmarkError("tiktoken is required for exact o200k_base counts") from error

    root = manifest_path.resolve().parent
    document = _record(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    if document.get("schema") != SCHEMA:
        raise BenchmarkError(f"manifest.schema must equal {SCHEMA}")
    if set(document) != {"schema", "runs"}:
        raise BenchmarkError("manifest contains unknown fields")
    raw_runs = document.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise BenchmarkError("manifest.runs must be a non-empty array")

    encoding = tiktoken.get_encoding("o200k_base")
    runs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_runs):
        run = _record(raw, f"runs[{index}]")
        allowed = {
            "caseId", "route", "language", "temperature", "elapsedMs", "evidenceComplete",
            "targetCount", "resultFiles", "skillFiles", "command", "notes",
        }
        unknown = set(run) - allowed
        if unknown:
            raise BenchmarkError(f"runs[{index}] contains unknown fields: {sorted(unknown)}")
        case_id = _string(run.get("caseId"), f"runs[{index}].caseId")
        route = _string(run.get("route"), f"runs[{index}].route")
        language = _string(run.get("language"), f"runs[{index}].language")
        temperature = run.get("temperature")
        if temperature not in {"cold", "warm"}:
            raise BenchmarkError(f"runs[{index}].temperature must be cold or warm")
        key = (case_id, route, temperature)
        if key in seen:
            raise BenchmarkError(f"duplicate case/route/temperature: {key}")
        seen.add(key)
        if run.get("evidenceComplete") is not True:
            raise BenchmarkError(f"runs[{index}] is not quality-complete")
        result_files = _paths(run.get("resultFiles"), f"runs[{index}].resultFiles")
        skill_files = _paths(run.get("skillFiles"), f"runs[{index}].skillFiles")
        command = _string(run.get("command"), f"runs[{index}].command")
        visible_texts = [_read_bounded(root, path) for path in [*result_files, *skill_files]]
        visible_tokens = len(encoding.encode(command)) + sum(
            len(encoding.encode(text)) for text in visible_texts
        )
        target_count = _positive_integer(run.get("targetCount"), f"runs[{index}].targetCount")
        runs.append({
            "case_id": case_id,
            "route": route,
            "language": language,
            "temperature": temperature,
            "elapsed_ms": _number(run.get("elapsedMs"), f"runs[{index}].elapsedMs"),
            "visible_tokens": visible_tokens,
            "target_count": target_count,
            "tokens_per_target": round(visible_tokens / target_count, 2),
            "notes": run.get("notes", ""),
        })

    route_groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        route_groups.setdefault(run["route"], []).append(run)
    routes = []
    for route, members in sorted(route_groups.items()):
        routes.append({
            "route": route,
            "runs": len(members),
            "median_visible_tokens": statistics.median(item["visible_tokens"] for item in members),
            "median_tokens_per_target": statistics.median(item["tokens_per_target"] for item in members),
            "median_elapsed_ms": statistics.median(item["elapsed_ms"] for item in members),
        })
    return {"schema": "agentbase.code-search-benchmark-result/v1", "runs": runs, "routes": routes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(analyze(args.manifest), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (BenchmarkError, OSError, json.JSONDecodeError) as error:
        print(f"benchmark error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
