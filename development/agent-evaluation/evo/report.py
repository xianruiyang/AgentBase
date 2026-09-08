from __future__ import annotations

from typing import Any

from .spec import RESULT_SCHEMA, EvoError


def build_report(results: dict[str, Any]) -> str:
    if results.get("schema") != RESULT_SCHEMA:
        raise EvoError(f"result schema must be {RESULT_SCHEMA}")
    research = results.get("research", {})
    lines = [f"# Evo offline score report: {research.get('id', 'unknown')}", "", f"Research version: `{research.get('version', 'unknown')}`", f"Artifact rows: {results.get('source_row_count', 0)}", ""]
    for score in results.get("scores", []):
        lines.extend([f"## {score['id']} ({score['version']})", ""])
        if not score.get("groups"):
            lines.extend(["No selected samples.", ""])
            continue
        for group in score["groups"]:
            label = ", ".join(f"{key}={value}" for key, value in group["dimensions"].items()) or "all"
            lines.extend([f"### {label}", "", "| Metric | Value | Unit | Samples | Incomplete |", "| --- | ---: | --- | ---: | ---: |"])
            for metric in group["metrics"]:
                value = "unknown" if metric["status"] == "unknown" else str(metric["value"])
                lines.append(f"| {metric['id']} | {value} | {metric['unit']} | {metric['sample_count']} | {metric['incomplete_sample_count']} |")
            lines.append("")
    return "\n".join(lines)
