#!/usr/bin/env python3
"""Single-variable sensitivity sweep for the 40/400/24 KiB Token-Safe baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import tiktoken
import tokenizers
import yaml
from tokenizers import Tokenizer

import benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--sgy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def run(argv: list[str], cwd: Path, environment: dict[str, str]) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError(
            f"command failed: exit={completed.returncode}, stderr={completed.stderr.decode('utf-8', errors='replace')[-2000:]}"
        )
    return completed.stdout


def text_retention(document: dict[str, Any], truth: list[dict[str, Any]]) -> dict[str, Any]:
    truth_by_identity = {benchmark.record_identity(record): record for record in truth}
    previews = []
    full = 0
    disclosed = 0
    for record in document.get("results", []):
        native = truth_by_identity.get(benchmark.record_identity(record))
        if native is None or len(str(native.get("text", ""))) <= 400:
            continue
        text = str(record.get("text", ""))
        previews.append(len(text))
        if text == str(native.get("text", "")):
            full += 1
        if record.get("_sgy_text_truncated") is True:
            disclosed += 1
    return {
        "long_records_shown": len(previews),
        "preview_chars_min": min(previews) if previews else None,
        "preview_chars_max": max(previews) if previews else None,
        "full_long_records": full,
        "truncation_disclosed_records": disclosed,
    }


def main() -> int:
    if os.name != "nt":
        raise SystemExit("sgy benchmarks are maintained only on Windows")
    args = parse_args()
    engine = args.engine.resolve(strict=True)
    sgy = args.sgy.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = output / "generated-budget-fixture"
    workloads = benchmark.load_workloads()
    sweep_sizes = {key: workloads["sizes"][key] for key in ["small", "large"]}
    fixture_hash = benchmark.generate_repository(fixture, sweep_sizes)

    environment = os.environ.copy()
    isolated = output / "isolated-budget-environment"
    isolated.mkdir(exist_ok=True)
    environment["APPDATA"] = str(isolated / "appdata")
    environment["LOCALAPPDATA"] = str(isolated / "localappdata")

    qwen = Tokenizer.from_pretrained(benchmark.QWEN_REPO, revision=benchmark.QWEN_REVISION)
    cl100k = tiktoken.get_encoding("cl100k_base")
    o200k = tiktoken.get_encoding("o200k_base")
    tokenizers_by_name: dict[str, Callable[[str], int]] = {
        "cl100k_base": lambda text: len(cl100k.encode(text)),
        "o200k_base": lambda text: len(o200k.encode(text)),
        "qwen2.5_coder": lambda text: len(qwen.encode(text).ids),
    }
    configurations = {
        "default_40_400_24576": [],
        "detail_20": ["--max-detail-results", "20"],
        "detail_80": ["--max-detail-results", "80"],
        "text_200": ["--max-text-chars", "200"],
        "text_800": ["--max-text-chars", "800"],
        "context_12288": ["--max-context-bytes", "12288"],
        "context_49152": ["--max-context-bytes", "49152"],
    }

    results: dict[str, Any] = {}
    for size_name in sweep_sizes:
        size_results: dict[str, Any] = {}
        for kind in workloads["commands"]:
            native_args = benchmark.ast_grep_args(
                kind, fixture / size_name, fixture / "scan-rule.yml"
            )
            truth_bytes = run([str(engine), *native_args], fixture, environment)
            truth = benchmark.parse_compact(truth_bytes)
            kind_results: dict[str, Any] = {}
            for name, wrapper_args in configurations.items():
                data = run(
                    [
                        str(sgy),
                        "exec",
                        "--engine",
                        str(engine),
                        "--cache",
                        "off",
                        *wrapper_args,
                        "--",
                        *native_args,
                    ],
                    fixture,
                    environment,
                )
                document = benchmark.parse_token_safe(data)
                text = data.decode("utf-8")
                kind_results[name] = {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "tokens": {key: count(text) for key, count in tokenizers_by_name.items()},
                    "shown": document["_sgy"]["shown"],
                    "omitted": document["_sgy"]["omitted"],
                    "task_correctness": benchmark.score_tasks(
                        kind, truth, "token_safe_yaml", document
                    ),
                    "text_retention": text_retention(document, truth),
                }
            kind_results["_truth_records"] = len(truth)
            size_results[kind] = kind_results
        results[size_name] = size_results

    result = {
        "schema": "sgy.budget-sweep/v1",
        "engine_version": benchmark.version_output([str(engine), "--version"], fixture, environment),
        "sgy_version": benchmark.version_output([str(sgy), "--version"], fixture, environment),
        "fixture_sha256": fixture_hash,
        "records_per_command": sweep_sizes,
        "variables": {
            "max_detail_results": [20, 40, 80],
            "max_text_chars": [200, 400, 800],
            "max_context_bytes": [12288, 24576, 49152],
            "all_other_values": "builtin defaults",
            "cache": "off to remove random cache-id from token comparison",
        },
        "tokenizers": {
            "cl100k_base": tiktoken.__version__,
            "o200k_base": tiktoken.__version__,
            "qwen2.5_coder": {
                "tokenizers_package": tokenizers.__version__,
                "repository": benchmark.QWEN_REPO,
                "revision": benchmark.QWEN_REVISION,
            },
        },
        "results": results,
    }
    result_path = output / "budget-sweep.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(fixture)
    print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
