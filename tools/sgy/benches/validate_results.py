#!/usr/bin/env python3
"""Validate benchmark result completeness and frozen comparison invariants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("sweep", type=Path)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    sweep = json.loads(args.sweep.read_text(encoding="utf-8"))

    require(results.get("schema") == "sgy.benchmark-results/v1", "result schema")
    require(sweep.get("schema") == "sgy.budget-sweep/v1", "sweep schema")
    require(len(results.get("workloads", {})) == 9, "nine run/scan/rewrite size workloads")
    tokenizer_names = {"cl100k_base", "o200k_base", "qwen2.5_coder"}
    for label, workload in results["workloads"].items():
        require(workload["expected_records"] in {8, 80, 800}, f"{label}: record scale")
        for format_name in ["compact_json", "lossless_yaml", "token_safe_yaml"]:
            format_result = workload["formats"][format_name]
            require(format_result["bytes"] > 0, f"{label}/{format_name}: bytes")
            require(set(format_result["tokens"]) == tokenizer_names, f"{label}/{format_name}: tokenizers")
        require(workload["formats"]["compact_json"]["task_correctness"]["rate"] == 1, f"{label}: compact correctness")
        require(workload["formats"]["lossless_yaml"]["task_correctness"]["rate"] == 1, f"{label}: lossless correctness")
        require(workload["formats"]["token_safe_yaml"]["bytes"] <= 24_576, f"{label}: context budget")
        require(workload["timing"]["engine_compact_json"]["samples"] >= 3, f"{label}: engine samples")
        require(workload["timing"]["sgy_lossless_e2e"]["samples"] >= 3, f"{label}: lossless samples")
        require(workload["timing"]["sgy_token_safe_e2e"]["samples"] >= 3, f"{label}: token-safe samples")

    require(results["task_success_summary"]["compact_json"]["rate"] == 1, "compact task summary")
    require(results["task_success_summary"]["lossless_yaml"]["rate"] == 1, "lossless task summary")
    require(0 < results["task_success_summary"]["token_safe_yaml"]["rate"] <= 1, "token-safe task summary")
    require(results["metadata"]["fixture_unchanged_after_rewrite_preview"] is True, "rewrite preview mutation")
    for label in ["sort_single_run", "sort_multi_run", "count_multi_run_input"]:
        require(results["process_benchmarks"][label]["correct"] is True, f"{label}: correctness")
    require(results["process_benchmarks"]["sort_multi_run"]["records"] == 20_050, "external sort record count")
    require(results["process_benchmarks"]["sort_multi_run"]["timing"]["peak_temp_bytes"]["max"] > 0, "external sort temp peak")

    require(set(sweep["results"]) == {"small", "large"}, "sweep sizes")
    expected_configs = {
        "default_40_400_24576",
        "detail_20",
        "detail_80",
        "text_200",
        "text_800",
        "context_12288",
        "context_49152",
    }
    for size in ["small", "large"]:
        for command in ["run", "scan", "rewrite"]:
            values = sweep["results"][size][command]
            require(expected_configs.issubset(values), f"{size}/{command}: sweep configs")
            require(values["default_40_400_24576"]["bytes"] <= 24_576, f"{size}/{command}: default budget")
    print("benchmark validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
