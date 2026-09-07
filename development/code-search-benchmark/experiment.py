#!/usr/bin/env python3
"""Build, run, summarize, and capsule monitored Codex source-query experiments."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any


COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from codex_runtime import (  # noqa: E402
    CodexRuntimeError as ExperimentError,
    NETWORK_ENVIRONMENT_KEYS,
    RUNTIME_ENVIRONMENT_SCHEMA,
    apply_runtime_environment_options,
    codex_shell_environment_overrides,
    materialize_runtime_environment,
    parse_dotenv_projection,
    resolve_runtime_environment,
    resolve_shell_environment_policy,
    sanitized_process_environment,
)


EXPERIMENT_SCHEMA = "agentbase.source-query-experiment/v3"
RESULT_SCHEMA = "agentbase.source-query-results/v3"
CAPSULE_SCHEMA = "agentbase.source-query-audit-capsule/v3"
LEGACY_CAPSULE_SCHEMAS = {"agentbase.source-query-audit-capsule/v2"}
CAPSULE_VERIFICATION_SCHEMA = "agentbase.source-query-capsule-verification/v1"
CORPUS_SCHEMA = "agentbase.source-query-corpus/v1"
CAPSULE_HASH_SCHEME = "sha256-canonical-json-without-capsule_sha256"
EXPERIMENT_IDENTITY_SCHEME = "sha256-canonical-json-without-experiment_identity"
CANONICALIZATION = {
    "encoding": "utf-8",
    "ensure_ascii": False,
    "object_keys": "recursive lexicographic order",
    "separators": [",", ":"],
}
TOKEN_PRICING = {
    "schema": "agentbase.gpt-5.6-token-price-coefficients/v1",
    "as_of": "2026-09-01",
    "model_family": "gpt-5.6",
    "source": "https://help.openai.com/en/articles/20001415",
    "model_source": "https://developers.openai.com/api/docs/models/compare",
    "basis": "short_context_uncached_input_token",
    "long_context_threshold_input_tokens_exclusive": 272_000,
    "short_context": {
        "ordinary_input": 1.0,
        "cached_input": 0.1,
        "cache_write_input": 1.25,
        "output_including_reasoning": 6.0,
    },
    "long_context": {
        "ordinary_input": 2.0,
        "cached_input": 0.2,
        "cache_write_input": 2.5,
        "output_including_reasoning": 9.0,
    },
    "long_context_relative_to_its_uncached_input": {
        "ordinary_input": 1.0,
        "cached_input": 0.1,
        "cache_write_input": 1.25,
        "output_including_reasoning": 4.5,
    },
    "notes": [
        "reasoning_output_tokens is a subset of output_tokens and is not charged twice",
        "independent benchmarks use standard processing; Fast mode is excluded from the experiment contract",
    ],
}
GPT_56_STANDARD_INPUT_USD_PER_MILLION = {
    "gpt-5.6": 4.0,
    "gpt-5.6-sol": 4.0,
    "gpt-5.6-terra": 2.0,
    "gpt-5.6-luna": 0.20,
}
SECRET_OR_STATE_NAMES = {
    ".env", ".sandbox_migration", "auth.json", "cap_sid", "installation_id", "history.jsonl", "models_cache.json",
}
STATE_SUFFIXES = {".sqlite", ".sqlite-shm", ".sqlite-wal"}
STATE_DIRECTORIES = {"cache", "logs", "tmp", ".tmp", ".sandbox", ".sandbox-bin", "sessions", "archived_sessions", "thread-writer-locks"}
MAX_ENV_FILES = 50_000
NETWORK_TRANSPORT_PATTERNS = {
    "websocket_connect_failures": ("failed to connect to websocket", "websocket connect failed"),
    "sampling_retries": ("stream disconnected - retrying sampling request", "reconnecting..."),
    "http_fallbacks": (
        "falling back to http",
        "falling back from websockets to https",
        "falling back to https transport",
    ),
}
READ_ONLY_PREFIX = (
    "这是只读源码查找基准。不得修改文件、配置、进程或外部状态；"
    "不得创建子代理；"
    "不得访问其他测试环境、历史答案、聚合结果或隐藏 oracle。请根据当前环境自主完成下列任务。\n\n"
)
PREFLIGHT_PROMPT = (
    "这是独立基准运行能力预检。必须按顺序分别运行 PATH 中的以下命令，"
    "并只返回各命令输出；不得修改文件、配置、其他进程或外部状态。\n\n{commands}"
)
def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def capsule_sha256(capsule: dict[str, Any]) -> str:
    payload = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
    return sha256_bytes(canonical_bytes(payload))


def experiment_identity_sha256(experiment: dict[str, Any]) -> str:
    payload = {key: value for key, value in experiment.items() if key != "experiment_identity"}
    return sha256_bytes(canonical_bytes(payload))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_capture(argv: list[str], cwd: Path) -> bytes:
    completed = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ExperimentError(f"command failed ({completed.returncode}): {argv!r}: {detail}")
    return completed.stdout


def normalize_identity_paths(root: Path, requested: Any) -> list[str]:
    if requested is None:
        return ["."]
    if not isinstance(requested, list) or not requested:
        raise ExperimentError("workspace identity_paths must be a non-empty list")
    normalized: list[str] = []
    for raw in requested:
        if not isinstance(raw, str) or not raw.strip():
            raise ExperimentError("workspace identity_paths must contain non-empty strings")
        relative = Path(raw)
        if relative.is_absolute():
            raise ExperimentError(f"workspace identity path must be relative: {raw}")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as error:
            raise ExperimentError(f"workspace identity path escapes root: {raw}") from error
        value = relative.as_posix().rstrip("/") or "."
        if value not in normalized:
            normalized.append(value)
    return normalized


def path_in_identity_scope(relative: str, identity_paths: list[str]) -> bool:
    candidate = Path(relative)
    for scope in identity_paths:
        if scope == ".":
            return True
        root = Path(scope)
        if candidate == root or root in candidate.parents:
            return True
    return False


def git_identity(root: Path, identity_paths: list[str] | None = None) -> dict[str, Any]:
    paths = identity_paths or ["."]
    head = run_capture(["git", "rev-parse", "HEAD"], root).decode().strip()
    tree = run_capture(["git", "rev-parse", "HEAD^{tree}"], root).decode().strip()
    tracked_patch = run_capture(["git", "diff", "--binary", "HEAD", "--", *paths], root)
    untracked = run_capture(["git", "ls-files", "--others", "--exclude-standard", "-z", "--", *paths], root)
    untracked_entries = []
    for raw in untracked.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = root / relative
        untracked_entries.append({"path": relative.replace("\\", "/"), "sha256": sha256_file(path) if path.is_file() else None})
    identity = {
        "head": head,
        "tree": tree,
        "identity_paths": paths,
        "tracked_patch_sha256": sha256_bytes(tracked_patch),
        "untracked_manifest_sha256": sha256_bytes(canonical_bytes(untracked_entries)),
        "untracked_files": len(untracked_entries),
    }
    identity["snapshot_sha256"] = sha256_bytes(canonical_bytes(identity))
    return identity


def _directory_tree(root: Path, prefix: str = "") -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        relative = prefix + relative_path.as_posix()
        if path.name in SECRET_OR_STATE_NAMES or path.name.endswith(tuple(STATE_SUFFIXES)):
            continue
        plugin_install_cache = len(relative_path.parts) >= 2 and relative_path.parts[:2] == ("plugins", "cache")
        if any(part in STATE_DIRECTORIES for part in relative_path.parts) and not plugin_install_cache:
            continue
        entries[relative] = sha256_file(path)
    return entries


def environment_tree(root: Path) -> dict[str, str]:
    entries = _directory_tree(root)
    dependencies_path = root / "environment-dependencies.json"
    if dependencies_path.is_file():
        try:
            dependencies = json.loads(dependencies_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentError(f"environment dependency receipt is invalid: {dependencies_path}: {exc}") from exc
        if dependencies.get("schema") != "agentbase.benchmark-environment-dependencies/v1":
            raise ExperimentError(f"unsupported environment dependency receipt: {dependencies_path}")
        seen_ids: set[str] = set()
        for dependency in dependencies.get("directories", []):
            identity = str(dependency.get("id", ""))
            directory = Path(str(dependency.get("path", ""))).resolve()
            if not identity or identity in seen_ids or not directory.is_dir():
                raise ExperimentError(f"invalid environment directory dependency: {dependency}")
            seen_ids.add(identity)
            entries.update(_directory_tree(directory, f"@external/{identity}/"))
    if len(entries) > MAX_ENV_FILES:
        raise ExperimentError(f"environment tree exceeds {MAX_ENV_FILES} files: {root}")
    return entries


def validate_shared_shell_policy_owner(home: Path) -> None:
    config_path = home.resolve() / "config.toml"
    if not config_path.is_file():
        return
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExperimentError(f"benchmark Codex config is invalid: {config_path}: {exc}") from exc
    if "shell_environment_policy" in config:
        raise ExperimentError(
            "benchmark Codex homes must not define shell_environment_policy; "
            "the shared repository policy is the only owner"
        )


def benchmark_home_execution_contract(home: Path) -> dict[str, Any]:
    config_path = home.resolve() / "config.toml"
    if not config_path.is_file():
        raise ExperimentError(f"benchmark Codex config is missing: {config_path}")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExperimentError(f"benchmark Codex config is invalid: {config_path}: {exc}") from exc
    if config.get("features", {}).get("multi_agent") is not False:
        raise ExperimentError("benchmark Codex homes must set features.multi_agent=false")
    return {"read_only_prompt": True, "multi_agent": False}


def allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def environment_diff(control: dict[str, str], candidate: dict[str, str], patterns: list[str]) -> dict[str, Any]:
    changed = []
    unexpected = []
    for path in sorted(set(control) | set(candidate)):
        if control.get(path) == candidate.get(path):
            continue
        item = {"path": path, "control": control.get(path), "candidate": candidate.get(path)}
        changed.append(item)
        if not allowed(path, patterns):
            unexpected.append(path)
    return {"changed": changed, "unexpected": unexpected, "ok": not unexpected}


def balanced_schedule(case_ids: list[str], repetitions: int, seed: int) -> list[dict[str, Any]]:
    if repetitions < 1:
        raise ExperimentError("repetitions must be positive")
    rng = random.Random(seed)
    schedule: list[dict[str, Any]] = []
    for case_index, case_id in enumerate(case_ids):
        if repetitions == 2:
            order = ["control", "candidate", "candidate", "control"]
            if (case_index + rng.randrange(2)) % 2:
                order = ["candidate", "control", "control", "candidate"]
        else:
            blocks = []
            for ordinal in range(repetitions):
                pair = ["control", "candidate"] if ordinal % 2 == 0 else ["candidate", "control"]
                blocks.append(pair)
            rng.shuffle(blocks)
            order = [environment for block in blocks for environment in block]
        counts = {"control": 0, "candidate": 0}
        for environment in order:
            counts[environment] += 1
            schedule.append({"case_id": case_id, "environment": environment, "ordinal": counts[environment]})
    return schedule


def selected_schedule(case_ids: list[str], repetitions: int, seed: int, environments: list[str]) -> list[dict[str, Any]]:
    if not environments or any(name not in {"control", "candidate"} for name in environments):
        raise ExperimentError("run_environments must contain control and/or candidate")
    if len(set(environments)) != len(environments):
        raise ExperimentError("run_environments contains duplicates")
    if set(environments) == {"control", "candidate"}:
        return balanced_schedule(case_ids, repetitions, seed)
    if repetitions < 1:
        raise ExperimentError("repetitions must be positive")
    environment = environments[0]
    return [
        {"case_id": case_id, "environment": environment, "ordinal": ordinal}
        for case_id in case_ids
        for ordinal in range(1, repetitions + 1)
    ]


def selected_case_ids(corpus: dict[str, Any], requested: Any) -> list[str]:
    available = [str(case["id"]) for case in corpus["cases"]]
    if requested is None:
        return available
    if not isinstance(requested, list) or not requested or any(not isinstance(case_id, str) or not case_id for case_id in requested):
        raise ExperimentError("case_ids must be a non-empty list of strings")
    if len(set(requested)) != len(requested):
        raise ExperimentError("case_ids contains duplicates")
    unknown = [case_id for case_id in requested if case_id not in available]
    if unknown:
        raise ExperimentError(f"case_ids contains unknown cases: {unknown}")
    return list(requested)


def _usage_integer(usage: dict[str, Any], name: str, diagnostics: list[str]) -> int | None:
    value = usage.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        diagnostics.append(f"missing or invalid non-negative integer: {name}")
        return None
    return value


def normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[str] = []
    input_tokens = _usage_integer(usage, "input_tokens", diagnostics)
    cached_tokens = _usage_integer(usage, "cached_input_tokens", diagnostics)
    output_tokens = _usage_integer(usage, "output_tokens", diagnostics)
    reasoning_tokens = _usage_integer(usage, "reasoning_output_tokens", diagnostics)

    cache_write_tokens = None
    cache_write_fields = [name for name in ("cache_write_input_tokens", "cache_write_tokens") if name in usage]
    if cache_write_fields:
        values = [_usage_integer(usage, name, diagnostics) for name in cache_write_fields]
        if len(values) == 2 and values[0] != values[1]:
            diagnostics.append("conflicting cache write token fields")
        elif values:
            cache_write_tokens = values[0]

    if input_tokens is not None and cached_tokens is not None and cached_tokens > input_tokens:
        diagnostics.append("cached_input_tokens exceeds input_tokens")
    if output_tokens is not None and reasoning_tokens is not None and reasoning_tokens > output_tokens:
        diagnostics.append("reasoning_output_tokens exceeds output_tokens")
    if (
        input_tokens is not None
        and cached_tokens is not None
        and cache_write_tokens is not None
        and cached_tokens + cache_write_tokens > input_tokens
    ):
        diagnostics.append("cached and cache write input exceeds input_tokens")

    complete = not diagnostics
    if not complete:
        return {
            "complete": False,
            "pricing_exact": False,
            "diagnostics": diagnostics,
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cached_tokens,
            "cache_write_input_tokens": cache_write_tokens,
            "ordinary_input_tokens": None,
            "non_cached_input_tokens": None,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_tokens,
            "visible_output_tokens": None,
            "actual_total_tokens": None,
        }

    assert input_tokens is not None and cached_tokens is not None
    assert output_tokens is not None and reasoning_tokens is not None
    non_cached_tokens = input_tokens - cached_tokens
    ordinary_tokens = non_cached_tokens - cache_write_tokens if cache_write_tokens is not None else None
    return {
        "complete": True,
        "pricing_exact": cache_write_tokens is not None,
        "diagnostics": [],
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cached_tokens,
        "cache_write_input_tokens": cache_write_tokens,
        "ordinary_input_tokens": ordinary_tokens,
        "non_cached_input_tokens": non_cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "visible_output_tokens": output_tokens - reasoning_tokens,
        "actual_total_tokens": input_tokens + output_tokens,
        "cache_read_ratio": cached_tokens / input_tokens if input_tokens else 0.0,
        "reasoning_output_ratio": reasoning_tokens / output_tokens if output_tokens else 0.0,
    }


def token_pricing_contract(codex: dict[str, Any]) -> dict[str, Any]:
    model = str(codex.get("model", ""))
    input_price = GPT_56_STANDARD_INPUT_USD_PER_MILLION.get(model)
    return {
        **TOKEN_PRICING,
        "experiment_model": model,
        "requested_service_tier": str(codex.get("service_tier", "")),
        "short_context_uncached_input_usd_per_million": input_price,
        "applicable": input_price is not None,
    }


def validate_benchmark_codex(codex: dict[str, Any]) -> None:
    if codex.get("service_tier") != "default":
        raise ExperimentError("independent benchmark requires service_tier=default")
    if codex.get("sandbox") != "danger-full-access":
        raise ExperimentError("independent benchmark requires sandbox=danger-full-access")
    if codex.get("transport") not in {"websocket", "http-only"}:
        raise ExperimentError("independent benchmark requires an explicit websocket or http-only transport")
    if codex.get("client_protocol") not in {"exec-json", "app-server-v2"}:
        raise ExperimentError("independent benchmark requires client_protocol=exec-json or app-server-v2")
    protected = {
        "approval_policy", "model", "model_provider", "model_reasoning_effort", "sandbox_mode",
        "service_tier", "shell_environment_policy", "features", "features.multi_agent",
    }
    for override in codex.get("extra_config", []):
        key = str(override).split("=", 1)[0].strip()
        if (
            key in protected
            or key.startswith("model_providers.")
            or key.startswith("shell_environment_policy.")
            or key.startswith("features.multi_agent.")
        ):
            raise ExperimentError(f"extra_config must not override benchmark execution identity: {key}")


def resolve_codex_identity(raw: dict[str, Any]) -> dict[str, Any]:
    codex = dict(raw)
    validate_benchmark_codex(codex)
    if codex["client_protocol"] != "app-server-v2":
        raise ExperimentError("new benchmark preparation requires client_protocol=app-server-v2")
    executable = Path(str(codex.get("executable", ""))).resolve()
    if not executable.is_file():
        raise ExperimentError(f"Codex executable does not exist: {executable}")
    observed_version = run_capture([str(executable), "--version"], Path.cwd()).decode(
        "utf-8", errors="replace"
    ).strip()
    observed_sha256 = sha256_file(executable)
    shell_policy_descriptor, _ = resolve_shell_environment_policy()
    configured_version = codex.get("observed_version")
    configured_sha256 = codex.get("executable_sha256")
    if configured_version is not None and configured_version != observed_version:
        raise ExperimentError("configured Codex version does not match executable")
    if configured_sha256 is not None and str(configured_sha256).lower() != observed_sha256:
        raise ExperimentError("configured Codex sha256 does not match executable")
    codex.update({
        "executable": str(executable),
        "observed_version": observed_version,
        "executable_sha256": observed_sha256,
        "executable_size_bytes": executable.stat().st_size,
        "shell_environment_policy": shell_policy_descriptor,
    })
    return codex


def price_equivalent(breakdown: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    if not breakdown.get("complete"):
        return {"available": False, "reason": "usage_incomplete"}
    if pricing.get("applicable") is False:
        return {"available": False, "reason": "pricing_not_applicable_to_experiment_model"}
    cached = breakdown["cache_read_input_tokens"]
    non_cached = breakdown["non_cached_input_tokens"]
    cache_write = breakdown["cache_write_input_tokens"]
    output = breakdown["output_tokens"]
    scenarios = {}
    for name in ("short_context", "long_context"):
        coefficients = pricing[name]
        fixed = cached * coefficients["cached_input"] + output * coefficients["output_including_reasoning"]
        lower = fixed + non_cached * coefficients["ordinary_input"]
        upper = fixed + non_cached * coefficients["cache_write_input"]
        exact = None
        if cache_write is not None:
            ordinary = breakdown["ordinary_input_tokens"]
            exact = (
                fixed
                + ordinary * coefficients["ordinary_input"]
                + cache_write * coefficients["cache_write_input"]
            )
            lower = exact
            upper = exact
        scenarios[name] = {"lower": lower, "upper": upper, "exact": exact}
    return {
        "available": True,
        "basis": pricing["basis"],
        "context_classification": "scenario_only",
        "cache_write_classification": "exact" if cache_write is not None else "bounded",
        "short_context": scenarios["short_context"],
        "long_context": scenarios["long_context"],
        "overall": {
            "lower": scenarios["short_context"]["lower"],
            "upper": scenarios["long_context"]["upper"],
            "exact": None,
        },
    }


def ideal_cache_projection(
    request_usages: list[dict[str, Any]],
    aggregate_usage_value: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema": "agentbase.ideal-cache-projection/v2",
        "scope": "observed-subject-start-no-future-prefix-eviction",
        "evidence": "app-server-v2 thread/tokenUsage/updated last/total",
    }
    if not request_usages:
        return {**base, "status": "unavailable", "reason": "per_request_usage_unavailable"}

    aggregate = normalize_usage(aggregate_usage_value)
    if not aggregate.get("complete") or not aggregate.get("pricing_exact"):
        return {**base, "status": "unavailable", "reason": "aggregate_usage_incomplete"}

    normalized_requests: list[dict[str, Any]] = []
    for index, raw in enumerate(request_usages, 1):
        breakdown = normalize_usage(raw)
        if not breakdown.get("complete") or not breakdown.get("pricing_exact"):
            return {
                **base,
                "status": "unavailable",
                "reason": "request_usage_incomplete",
                "request_index": index,
            }
        normalized_requests.append({**raw, "breakdown": breakdown})

    comparable_fields = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    request_totals = {
        field: sum(item["breakdown"][field] for item in normalized_requests)
        for field in comparable_fields
    }
    aggregate_totals = {field: aggregate[field] for field in comparable_fields}
    if request_totals != aggregate_totals:
        return {
            **base,
            "status": "unavailable",
            "reason": "request_usage_does_not_reconcile_with_total",
            "request_totals": request_totals,
            "aggregate_totals": aggregate_totals,
        }

    retained_by_epoch: dict[int, int] = {}
    last_eligible_by_epoch: dict[int, int] = {}
    projected: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_requests, 1):
        breakdown = item["breakdown"]
        epoch = int(item.get("prefix_epoch", 0))
        eligible = breakdown["cache_read_input_tokens"] + breakdown["cache_write_input_tokens"]
        previous_eligible = last_eligible_by_epoch.get(epoch)
        if previous_eligible is not None and eligible < previous_eligible:
            return {
                **base,
                "status": "unavailable",
                "reason": "eligible_prefix_regressed_without_compaction",
                "request_index": index,
                "prefix_epoch": epoch,
                "previous_eligible_prefix_tokens": previous_eligible,
                "eligible_prefix_tokens": eligible,
            }
        retained = retained_by_epoch.get(epoch)
        if retained is None:
            ideal_read = breakdown["cache_read_input_tokens"]
            ideal_write = breakdown["cache_write_input_tokens"]
        else:
            if breakdown["cache_read_input_tokens"] > retained:
                return {
                    **base,
                    "status": "unavailable",
                    "reason": "cache_write_accounting_inconsistent_with_later_hits",
                    "request_index": index,
                    "prefix_epoch": epoch,
                    "previous_observed_retained_prefix_tokens": retained,
                    "observed_cache_read_input_tokens": breakdown["cache_read_input_tokens"],
                }
            ideal_read = min(retained, eligible)
            ideal_write = eligible - ideal_read
        ideal_ordinary = breakdown["input_tokens"] - eligible
        projected.append({
            "request_index": index,
            "prefix_epoch": epoch,
            "input_tokens": breakdown["input_tokens"],
            "observed_cache_read_input_tokens": breakdown["cache_read_input_tokens"],
            "observed_cache_write_input_tokens": breakdown["cache_write_input_tokens"],
            "eligible_prefix_tokens": eligible,
            "ideal_cache_read_input_tokens": ideal_read,
            "ideal_cache_write_input_tokens": ideal_write,
            "ideal_ordinary_input_tokens": ideal_ordinary,
            "output_tokens": breakdown["output_tokens"],
            "reasoning_output_tokens": breakdown["reasoning_output_tokens"],
        })
        retained_by_epoch[epoch] = max(retained or 0, eligible)
        last_eligible_by_epoch[epoch] = eligible

    totals = {
        "input_tokens": sum(item["input_tokens"] for item in projected),
        "observed_cache_read_input_tokens": sum(item["observed_cache_read_input_tokens"] for item in projected),
        "observed_cache_write_input_tokens": sum(item["observed_cache_write_input_tokens"] for item in projected),
        "ideal_cache_read_input_tokens": sum(item["ideal_cache_read_input_tokens"] for item in projected),
        "ideal_cache_write_input_tokens": sum(item["ideal_cache_write_input_tokens"] for item in projected),
        "ideal_ordinary_input_tokens": sum(item["ideal_ordinary_input_tokens"] for item in projected),
        "output_tokens": sum(item["output_tokens"] for item in projected),
        "reasoning_output_tokens": sum(item["reasoning_output_tokens"] for item in projected),
    }
    return {
        **base,
        "status": "available",
        "request_count": len(projected),
        "prefix_epoch_count": len(retained_by_epoch),
        "requests": projected,
        "totals": totals,
    }


def ideal_cache_price(projection: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    if projection.get("status") != "available":
        return {"available": False, "reason": projection.get("reason", "projection_unavailable")}
    input_price = pricing.get("short_context_uncached_input_usd_per_million")
    if pricing.get("applicable") is False or not isinstance(input_price, (int, float)):
        return {"available": False, "reason": "pricing_not_applicable_to_experiment_model"}
    threshold = int(pricing["long_context_threshold_input_tokens_exclusive"])
    equivalent_units = 0.0
    context_counts = {"short_context": 0, "long_context": 0}
    for request in projection["requests"]:
        context = "long_context" if request["input_tokens"] > threshold else "short_context"
        context_counts[context] += 1
        coefficients = pricing[context]
        equivalent_units += (
            request["ideal_ordinary_input_tokens"] * coefficients["ordinary_input"]
            + request["ideal_cache_read_input_tokens"] * coefficients["cached_input"]
            + request["ideal_cache_write_input_tokens"] * coefficients["cache_write_input"]
            + request["output_tokens"] * coefficients["output_including_reasoning"]
        )
    return {
        "available": True,
        "context_classification": "exact_per_request",
        "short_context_request_count": context_counts["short_context"],
        "long_context_request_count": context_counts["long_context"],
        "short_context_uncached_input_equivalent_tokens": equivalent_units,
        "usd": equivalent_units * float(input_price) / 1_000_000,
    }


def observed_request_price(request_usages: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    if not request_usages:
        return {"available": False, "reason": "per_request_usage_unavailable"}
    input_price = pricing.get("short_context_uncached_input_usd_per_million")
    if pricing.get("applicable") is False or not isinstance(input_price, (int, float)):
        return {"available": False, "reason": "pricing_not_applicable_to_experiment_model"}
    threshold = int(pricing["long_context_threshold_input_tokens_exclusive"])
    equivalent_units = 0.0
    context_counts = {"short_context": 0, "long_context": 0}
    for index, usage in enumerate(request_usages, 1):
        breakdown = normalize_usage(usage)
        if not breakdown.get("complete") or not breakdown.get("pricing_exact"):
            return {"available": False, "reason": "request_usage_incomplete", "request_index": index}
        context = "long_context" if breakdown["input_tokens"] > threshold else "short_context"
        context_counts[context] += 1
        coefficients = pricing[context]
        equivalent_units += (
            breakdown["ordinary_input_tokens"] * coefficients["ordinary_input"]
            + breakdown["cache_read_input_tokens"] * coefficients["cached_input"]
            + breakdown["cache_write_input_tokens"] * coefficients["cache_write_input"]
            + breakdown["output_tokens"] * coefficients["output_including_reasoning"]
        )
    return {
        "available": True,
        "context_classification": "exact_per_request",
        "short_context_request_count": context_counts["short_context"],
        "long_context_request_count": context_counts["long_context"],
        "short_context_uncached_input_equivalent_tokens": equivalent_units,
        "usd": equivalent_units * float(input_price) / 1_000_000,
    }


def aggregate_observed_request_price(records: list[dict[str, Any]]) -> dict[str, Any]:
    environments = sorted({str(record.get("environment", "unknown")) for record in records})

    def aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
        unavailable = [record for record in selected if not record.get("observed_request_price", {}).get("available")]
        if unavailable:
            return {
                "status": "unavailable",
                "run_count": len(selected),
                "unavailable_run_ids": [record["run_id"] for record in unavailable],
                "reasons": {
                    record["run_id"]: record.get("observed_request_price", {}).get("reason", "missing")
                    for record in unavailable
                },
            }
        return {
            "status": "available",
            "run_count": len(selected),
            "request_count": sum(len(record.get("request_usages", [])) for record in selected),
            "context_classification": "exact_per_request",
            "short_context_uncached_input_equivalent_tokens": sum(
                record["observed_request_price"]["short_context_uncached_input_equivalent_tokens"]
                for record in selected
            ),
            "usd": sum(record["observed_request_price"]["usd"] for record in selected),
        }

    return {
        "schema": "agentbase.observed-request-price-report/v1",
        "all": aggregate(records),
        "by_environment": {
            name: aggregate([record for record in records if str(record.get("environment", "unknown")) == name])
            for name in environments
        },
    }


def aggregate_ideal_cache(records: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    environments = sorted({str(record.get("environment", "unknown")) for record in records})

    def aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
        unavailable = [
            record for record in selected
            if record.get("ideal_cache_projection", {}).get("status") != "available"
        ]
        if unavailable:
            return {
                "status": "unavailable",
                "run_count": len(selected),
                "unavailable_run_ids": [record["run_id"] for record in unavailable],
                "reasons": {
                    record["run_id"]: record.get("ideal_cache_projection", {}).get("reason", "missing")
                    for record in unavailable
                },
            }
        token_fields = (
            "input_tokens",
            "observed_cache_read_input_tokens",
            "observed_cache_write_input_tokens",
            "ideal_cache_read_input_tokens",
            "ideal_cache_write_input_tokens",
            "ideal_ordinary_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
        prices = [record["ideal_cache_price"] for record in selected]
        price_available = all(price.get("available") for price in prices)
        return {
            "status": "available",
            "run_count": len(selected),
            "request_count": sum(record["ideal_cache_projection"]["request_count"] for record in selected),
            "totals": {
                field: sum(record["ideal_cache_projection"]["totals"][field] for record in selected)
                for field in token_fields
            },
            "price": (
                {
                    "available": True,
                    "context_classification": "exact_per_request",
                    "short_context_uncached_input_equivalent_tokens": sum(
                        price["short_context_uncached_input_equivalent_tokens"] for price in prices
                    ),
                    "usd": sum(price["usd"] for price in prices),
                }
                if price_available
                else {"available": False, "reason": "pricing_unavailable_for_one_or_more_runs"}
            ),
        }

    return {
        "schema": "agentbase.ideal-cache-report/v2",
        "semantics": {
            "scope": "preserve the observed cache state at subject start; no observed retained prefix is evicted within an epoch",
            "source": "distinct app-server-v2 per-request last usage reconciled with cumulative total",
            "compaction": "contextCompaction starts a new cold prefix epoch",
            "legacy": "aggregate exec-json usage is unavailable and is never retroactively inferred",
            "missing_write_accounting": "later hits exceeding observed retained prefixes make the projection unavailable",
        },
        "all": aggregate(records),
        "by_environment": {
            name: aggregate([record for record in records if str(record.get("environment", "unknown")) == name])
            for name in environments
        },
    }


def aggregate_usage(records: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    environments = sorted({str(record.get("environment", "unknown")) for record in records})

    def aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
        complete = [record for record in selected if record["usage_breakdown"].get("complete")]
        exact = [record for record in complete if record["usage_breakdown"].get("pricing_exact")]
        token_fields = (
            "input_tokens", "cache_read_input_tokens", "output_tokens", "reasoning_output_tokens",
            "visible_output_tokens", "actual_total_tokens",
        )
        totals = {field: sum(record["usage_breakdown"][field] for record in complete) for field in token_fields}
        optional_fields = ("cache_write_input_tokens", "ordinary_input_tokens")
        for field in optional_fields:
            totals[field] = sum(record["usage_breakdown"][field] for record in exact) if len(exact) == len(complete) else None
        price_estimates = [record["price_equivalent"] for record in complete]
        price = None
        if len(complete) == len(selected) and pricing.get("applicable") is not False:
            price = {
                scenario: {
                    bound: sum(item[scenario][bound] for item in price_estimates)
                    for bound in ("lower", "upper")
                }
                for scenario in ("short_context", "long_context", "overall")
            }
            if len(exact) == len(complete):
                price["short_context"]["exact"] = sum(item["short_context"]["exact"] for item in price_estimates)
                price["long_context"]["exact"] = sum(item["long_context"]["exact"] for item in price_estimates)
            else:
                price["short_context"]["exact"] = None
                price["long_context"]["exact"] = None
            price["overall"]["exact"] = None
        return {
            "run_count": len(selected),
            "usage_complete_runs": len(complete),
            "pricing_exact_runs": len(exact),
            "usage_complete_for_all_runs": len(complete) == len(selected),
            "totals": totals,
            "price_equivalent": price,
            "price_equivalent_status": (
                "pricing_not_applicable_to_experiment_model"
                if pricing.get("applicable") is False
                else "usage_incomplete"
                if len(complete) != len(selected)
                else "scenario_bounds"
            ),
            "incomplete_run_ids": [record["run_id"] for record in selected if not record["usage_breakdown"].get("complete")],
            "cache_write_unreported_run_ids": [
                record["run_id"] for record in complete if not record["usage_breakdown"].get("pricing_exact")
            ],
        }

    return {
        "pricing": pricing,
        "semantics": {
            "actual_total_tokens": "input_tokens + output_tokens",
            "cached_input": "subset of input_tokens",
            "reasoning_output": "subset of output_tokens; never add again to cost or total",
            "visible_output_tokens": "output_tokens - reasoning_output_tokens",
            "price_equivalent": "relative cost units, not USD; unknown cache writes and request context are bounded",
        },
        "all": aggregate(records),
        "by_environment": {
            name: aggregate([record for record in records if str(record.get("environment", "unknown")) == name])
            for name in environments
        },
    }


def validate_corpus_snapshot(
    corpus: dict[str, Any],
    workspaces: dict[str, dict[str, Any]],
    selected: set[str] | None = None,
) -> None:
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise ExperimentError("unsupported corpus schema")
    seen = set()
    for case in corpus.get("cases", []):
        case_id = case.get("id")
        if not case_id or case_id in seen:
            raise ExperimentError(f"invalid or duplicate corpus case: {case_id!r}")
        seen.add(case_id)
        contract = case.get("answer_contract")
        if not isinstance(contract, dict):
            raise ExperimentError(f"case has no answer_contract: {case_id}")
        required = contract.get("required")
        supporting = contract.get("supporting", [])
        if not isinstance(required, list) or not required or not all(isinstance(item, str) and item for item in required):
            raise ExperimentError(f"invalid answer_contract.required: {case_id}")
        if not isinstance(supporting, list) or not all(isinstance(item, str) and item for item in supporting):
            raise ExperimentError(f"invalid answer_contract.supporting: {case_id}")
        if len(set(required)) != len(required) or len(set(supporting)) != len(supporting) or set(required) & set(supporting):
            raise ExperimentError(f"ambiguous answer_contract: {case_id}")
        if not isinstance(case.get("answer_max_lines"), int) or case["answer_max_lines"] <= 0:
            raise ExperimentError(f"invalid answer_max_lines: {case_id}")
        if selected is not None and case_id not in selected:
            continue
        role = case.get("workspace_role")
        if role not in workspaces:
            raise ExperimentError(f"corpus role has no workspace: {role!r}")
        oracle = case.get("oracle", {})
        sources = [oracle["source"]] if "source" in oracle else list(oracle.get("sources", []))
        if oracle.get("kind") == "unique-path":
            sources.append({"path": oracle["path"], "sha256": oracle["sha256"]})
        for source in sources:
            root = Path(workspaces[role]["path"])
            identity_paths = workspaces[role].get("identity_paths", ["."])
            if not path_in_identity_scope(source["path"], identity_paths):
                raise ExperimentError(f"corpus source is outside workspace identity scope: {case_id}/{source['path']}")
            path = (root / source["path"]).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError as error:
                raise ExperimentError(f"corpus source escapes workspace: {case_id}") from error
            if not path.is_file() or sha256_file(path) != source["sha256"]:
                raise ExperimentError(f"corpus source is stale: {case_id}/{source['path']}")


def resolve_path_prepend(home: Path, value: str, name: str) -> Path:
    path_prepend = (home / value).resolve()
    try:
        path_prepend.relative_to(home)
    except ValueError as error:
        raise ExperimentError(f"path_prepend escapes codex home: {name}") from error
    if not path_prepend.is_dir():
        raise ExperimentError(f"path_prepend is not a directory: {name}")
    return path_prepend


def network_transport_observation(jsonl_path: Path, stderr_path: Path) -> dict[str, Any]:
    diagnostic_text = [stderr_path.read_text(encoding="utf-8", errors="replace")]
    for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        params = event.get("params", {})
        app_item = params.get("item", {}) if isinstance(params, dict) else {}
        if (
            event.get("type") in {"error", "turn.failed"}
            or item.get("type") == "error"
            or event.get("method") in {"error", "turn/failed"}
            or "error" in event
            or app_item.get("type") == "error"
        ):
            diagnostic_text.append(json.dumps(event, ensure_ascii=False))
    text = "\n".join(diagnostic_text).lower()
    counts = {
        name: sum(text.count(pattern) for pattern in patterns)
        for name, patterns in NETWORK_TRANSPORT_PATTERNS.items()
    }
    return {"clean": not any(counts.values()), **counts}


def codex_environment(
    environment: dict[str, Any],
    runtime_environment: dict[str, str],
) -> dict[str, str]:
    env = sanitized_process_environment(runtime_environment)
    env["CODEX_HOME"] = environment["codex_home"]
    if environment.get("path_prepend"):
        env["PATH"] = environment["path_prepend"] + os.pathsep + env.get("PATH", "")
    return env


def codex_exec_argv(
    codex: dict[str, Any],
    workspace: Path,
    prompt: str,
    *,
    skip_git_repo_check: bool = False,
) -> list[str]:
    validate_benchmark_codex(codex)
    argv = [
        codex["executable"], "exec", "--json", "--ephemeral", "--sandbox", codex["sandbox"],
        "-c", 'approval_policy="never"', "-m", codex["model"],
        "-c", f'model_reasoning_effort="{codex["reasoning_effort"]}"',
        "-c", f'service_tier="{codex["service_tier"]}"',
        "-c", "features.multi_agent=false",
    ]
    shell_policy_identity = codex.get("shell_environment_policy")
    if not isinstance(shell_policy_identity, dict) or not isinstance(
        shell_policy_identity.get("sha256"), str
    ):
        raise ExperimentError("Codex shell environment policy identity is missing")
    for override in codex_shell_environment_overrides(
        expected_sha256=str(shell_policy_identity["sha256"])
    ):
        argv.extend(["-c", override])
    if codex["transport"] == "http-only":
        argv.extend([
            "-c", 'model_provider="agentbase_eval_http"',
            "-c", 'model_providers.agentbase_eval_http.name="AgentBase ChatGPT HTTP"',
            "-c", 'model_providers.agentbase_eval_http.base_url="https://chatgpt.com/backend-api/codex"',
            "-c", 'model_providers.agentbase_eval_http.wire_api="responses"',
            "-c", "model_providers.agentbase_eval_http.requires_openai_auth=true",
            "-c", "model_providers.agentbase_eval_http.supports_websockets=false",
        ])
    for override in codex.get("extra_config", []):
        argv.extend(["-c", str(override)])
    if "project_doc_max_bytes" in codex:
        argv.extend(["-c", f'project_doc_max_bytes={int(codex["project_doc_max_bytes"])}'])
    if skip_git_repo_check:
        argv.append("--skip-git-repo-check")
    argv.extend(["--cd", str(workspace), "--color", "never", prompt])
    return argv


def codex_app_server_argv(codex: dict[str, Any]) -> list[str]:
    validate_benchmark_codex(codex)
    argv = [
        codex["executable"], "app-server", "--listen", "stdio://",
        "-c", 'approval_policy="never"',
        "-c", f'model="{codex["model"]}"',
        "-c", f'model_reasoning_effort="{codex["reasoning_effort"]}"',
        "-c", f'service_tier="{codex["service_tier"]}"',
        "-c", f'sandbox_mode="{codex["sandbox"]}"',
        "-c", "features.multi_agent=false",
    ]
    shell_policy_identity = codex.get("shell_environment_policy")
    if not isinstance(shell_policy_identity, dict) or not isinstance(
        shell_policy_identity.get("sha256"), str
    ):
        raise ExperimentError("Codex shell environment policy identity is missing")
    for override in codex_shell_environment_overrides(
        expected_sha256=str(shell_policy_identity["sha256"])
    ):
        argv.extend(["-c", override])
    if codex["transport"] == "http-only":
        argv.extend([
            "-c", 'model_provider="agentbase_eval_http"',
            "-c", 'model_providers.agentbase_eval_http.name="AgentBase ChatGPT HTTP"',
            "-c", 'model_providers.agentbase_eval_http.base_url="https://chatgpt.com/backend-api/codex"',
            "-c", 'model_providers.agentbase_eval_http.wire_api="responses"',
            "-c", "model_providers.agentbase_eval_http.requires_openai_auth=true",
            "-c", "model_providers.agentbase_eval_http.supports_websockets=false",
        ])
    for override in codex.get("extra_config", []):
        argv.extend(["-c", str(override)])
    if "project_doc_max_bytes" in codex:
        argv.extend(["-c", f'project_doc_max_bytes={int(codex["project_doc_max_bytes"])}'])
    return argv


def preflight_requirements(environment: dict[str, Any]) -> list[dict[str, str]]:
    home = Path(environment["codex_home"])
    srcq = home / "bin" / "srcq.exe"
    if srcq.is_file():
        return [
            {"command": "srcq.exe --version", "expected_output": "srcq "},
            {"command": "srcq query scc doctor", "expected_output": "ok", "output_match": "exact-line"},
        ]
    return [{"command": "rg.exe --version", "expected_output": "ripgrep "}]


def validate_preflight_record(record: dict[str, Any], requirements: list[dict[str, str]]) -> None:
    if record.get("execution_contract_failures"):
        raise ExperimentError(f"Codex preflight single-model contract violated: {record['environment']}")
    if record["exit_code"] != 0 or record["timed_out"]:
        raise ExperimentError(f"Codex preflight process failed: {record['environment']}")
    if not record["usage_complete"]:
        raise ExperimentError(f"Codex preflight usage is incomplete: {record['environment']}")
    if not record["network_transport"]["clean"]:
        raise ExperimentError(f"Codex preflight network transport degraded: {record['environment']}")
    for requirement in requirements:
        command = requirement["command"]
        expected_output = requirement["expected_output"]
        successful = False
        for item in record["tool_items"]:
            if item.get("type") != "command_execution":
                continue
            invoked = str(item.get("command", "")).lower()
            output = str(item.get("aggregated_output", item.get("output", "")))
            expected_matches = (
                expected_output.lower() in {line.strip().lower() for line in output.splitlines()}
                if requirement.get("output_match") == "exact-line"
                else expected_output.lower() in output.lower()
            )
            if (
                command.lower() in invoked
                and item.get("status") in {None, "completed"}
                and item.get("exit_code") in {None, 0}
                and expected_matches
            ):
                successful = True
                break
        if not successful:
            raise ExperimentError(
                "Codex preflight did not execute the required command successfully: "
                f"{record['environment']}/{command}"
            )


def run_preflights(
    codex: dict[str, Any],
    environments: dict[str, dict[str, Any]],
    selected_environments: list[str],
    workspace: Path,
    runtime_environment: dict[str, str],
    output: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    root = output / "preflight"
    root.mkdir(parents=True)
    records = []
    for name in selected_environments:
        environment = environments[name]
        requirements = preflight_requirements(environment)
        commands = [requirement["command"] for requirement in requirements]
        stdout_path = root / f"{name}.jsonl"
        stderr_path = root / f"{name}.stderr.txt"
        prompt = PREFLIGHT_PROMPT.format(commands="\n".join(f"- {command}" for command in commands))
        monitored = monitor_subject(
            codex,
            workspace,
            prompt,
            codex_environment(environment, runtime_environment),
            stdout_path,
            stderr_path,
            timeout_seconds,
        )
        parsed = parse_events(stdout_path)
        record = {
            "run_id": f"preflight__{name}",
            "environment": name,
            "commands": commands,
            **monitored,
            **parsed,
            "network_transport": network_transport_observation(stdout_path, stderr_path),
            "actual_total_tokens": parsed["usage_breakdown"]["actual_total_tokens"],
            "price_equivalent": price_equivalent(parsed["usage_breakdown"], token_pricing_contract(codex)),
            "observed_request_price": observed_request_price(parsed["request_usages"], token_pricing_contract(codex)),
            "ideal_cache_price": ideal_cache_price(parsed["ideal_cache_projection"], token_pricing_contract(codex)),
            "stdout": str(stdout_path.relative_to(output)),
            "stderr": str(stderr_path.relative_to(output)),
        }
        validate_preflight_record(record, requirements)
        records.append(record)
    return {
        "prompt_contract": (
            "execute the environment's installed query executable and, when srcq is present, "
            "prove that it can spawn the real scc backend"
        ),
        "timeout_seconds": timeout_seconds,
        "usage_report": aggregate_usage(records, token_pricing_contract(codex)),
        "observed_request_price_report": aggregate_observed_request_price(records),
        "ideal_cache_report": aggregate_ideal_cache(records, token_pricing_contract(codex)),
        "records": records,
    }


def build_experiment(config_path: Path, output: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("network_policy") != "configured":
        raise ExperimentError("independent benchmark requires network_policy=configured")
    runtime_environment, runtime_environment_values = resolve_runtime_environment(
        config.get("runtime_environment")
    )
    raw_corpus_path = config.get("corpus")
    if not isinstance(raw_corpus_path, str) or not raw_corpus_path.strip():
        raise ExperimentError(
            "benchmark config must set corpus to an existing local corpus JSON file; "
            "restore the private corpus on this host or select another locally maintained corpus"
        )
    corpus_path = Path(raw_corpus_path).resolve()
    if not corpus_path.is_file():
        raise ExperimentError(
            f"local corpus is missing: {corpus_path}; restore it on this host and keep the config corpus path explicit"
        )
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus_sha256 = sha256_file(corpus_path)
    runner_sha256 = sha256_file(Path(__file__))
    case_ids = selected_case_ids(corpus, config.get("case_ids"))
    workspaces = {}
    for role, raw in config["workspaces"].items():
        root = Path(raw["path"]).resolve()
        identity_paths = normalize_identity_paths(root, raw.get("identity_paths"))
        workspaces[role] = {"path": str(root), "identity_paths": identity_paths}
    validate_corpus_snapshot(corpus, workspaces, set(case_ids))
    run_environments = list(config.get("run_environments", ["control", "candidate"]))
    schedule = selected_schedule(
        case_ids,
        int(config["repetitions"]),
        int(config["seed"]),
        run_environments,
    )
    preflight_workspace_role = str(config.get("preflight_workspace_role", next(iter(workspaces))))
    if preflight_workspace_role not in workspaces:
        raise ExperimentError(f"unknown preflight_workspace_role: {preflight_workspace_role}")
    preflight_workspace = Path(workspaces[preflight_workspace_role]["path"])
    environments = {}
    for name in ("control", "candidate"):
        raw_environment = config["environments"][name]
        home = Path(raw_environment["codex_home"]).resolve()
        validate_shared_shell_policy_owner(home)
        environments[name] = {
            "codex_home": str(home),
            "auth_mode": "inherited-secure-environment",
            "execution_contract": benchmark_home_execution_contract(home),
        }
        if raw_environment.get("path_prepend"):
            path_prepend = resolve_path_prepend(home, str(raw_environment["path_prepend"]), name)
            environments[name]["path_prepend"] = str(path_prepend)
    codex = resolve_codex_identity(config["codex"])
    tool_versions = {}
    for probe in config.get("tool_probes", []):
        tool_versions[probe["id"]] = run_capture(list(probe["argv"]), Path.cwd()).decode(
            "utf-8", errors="replace"
        ).strip()
    output.mkdir(parents=True, exist_ok=False)
    preflight_workspace_identities = {
        role: git_identity(Path(workspace["path"]), workspace["identity_paths"])
        for role, workspace in workspaces.items()
    }
    preflight = run_preflights(
        codex,
        environments,
        run_environments,
        preflight_workspace,
        runtime_environment_values,
        output,
        int(config.get("preflight_timeout_seconds", 180)),
    )
    if sha256_file(Path(__file__)) != runner_sha256:
        raise ExperimentError("Codex preflight modified runner source")
    if sha256_file(corpus_path) != corpus_sha256:
        raise ExperimentError("Codex preflight modified corpus")
    materialize_runtime_environment(runtime_environment)
    for role, workspace in workspaces.items():
        observed = git_identity(Path(workspace["path"]), workspace["identity_paths"])
        if observed != preflight_workspace_identities[role]:
            raise ExperimentError(f"Codex preflight modified workspace: {role}")
        workspace["identity"] = preflight_workspace_identities[role]
    trees = {}
    for name, environment in environments.items():
        tree = environment_tree(Path(environment["codex_home"]))
        trees[name] = tree
        environment["tree_sha256"] = sha256_bytes(canonical_bytes(tree))
    diff = environment_diff(trees["control"], trees["candidate"], config["allowed_differences"])
    if not diff["ok"]:
        raise ExperimentError(f"environment difference outside allowlist: {diff['unexpected']}")
    (output / "environment-diff.json").write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "environment-trees.json").write_text(json.dumps(trees, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    document = {
        "schema": EXPERIMENT_SCHEMA,
        "corpus": {"path": str(corpus_path), "sha256": corpus_sha256, "version": corpus["version"]},
        "workspaces": workspaces,
        "codex": codex,
        "runtime_environment": runtime_environment,
        "preflight": preflight,
        "tool_versions": tool_versions,
        "environments": environments,
        "allowed_differences": config["allowed_differences"],
        "selected_case_ids": case_ids,
        "environment_diff_sha256": sha256_file(output / "environment-diff.json"),
        "environment_trees_sha256": sha256_file(output / "environment-trees.json"),
        "schedule": schedule,
        "timeout_seconds": int(config["timeout_seconds"]),
        "network_policy": config["network_policy"],
        "token_pricing": token_pricing_contract(codex),
        "runner": {"schema": EXPERIMENT_SCHEMA, "source_sha256": runner_sha256, "python": sys.version},
    }
    document["experiment_identity"] = experiment_identity_sha256(document)
    (output / "experiment.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def monitor_command(argv: list[str], cwd: Path, env: dict[str, str], stdout_path: Path, stderr_path: Path, timeout_seconds: int) -> dict[str, Any]:
    started = time.perf_counter()
    timed_out = False
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, creationflags=creationflags)
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            exit_code = process.returncode if process.returncode is not None else -1
    return {"exit_code": exit_code, "timed_out": timed_out, "elapsed_ms": round((time.perf_counter() - started) * 1000)}


def monitor_app_server(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    codex: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    timed_out = False
    completed = False
    error_text = ""
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with stderr_path.open("w", encoding="utf-8", newline="\n") as stderr:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        assert process.stdin is not None and process.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        def send(payload: dict[str, Any]) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()

        with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout:
            def receive() -> dict[str, Any]:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError("app-server request timed out")
                try:
                    line = lines.get(timeout=remaining)
                except queue.Empty as error:
                    raise TimeoutError("app-server request timed out") from error
                if line is None:
                    raise ExperimentError("app-server stdout closed before turn completion")
                stdout.write(line if line.endswith("\n") else line + "\n")
                stdout.flush()
                try:
                    return json.loads(line)
                except json.JSONDecodeError as error:
                    raise ExperimentError("app-server emitted invalid JSON") from error

            def wait_response(request_id: int) -> dict[str, Any]:
                while True:
                    message = receive()
                    if message.get("id") != request_id:
                        continue
                    if "error" in message:
                        raise ExperimentError(
                            f"app-server request {request_id} failed: "
                            f"{json.dumps(message['error'], ensure_ascii=False)}"
                        )
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise ExperimentError(f"app-server request {request_id} returned no result")
                    return result

            try:
                send({
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "agentbase-code-search-benchmark", "version": "1"}},
                })
                wait_response(1)
                send({"method": "initialized"})
                send({
                    "id": 2,
                    "method": "thread/start",
                    "params": {
                        "cwd": str(cwd),
                        "model": codex["model"],
                        "approvalPolicy": "never",
                        "sandbox": codex["sandbox"],
                        "serviceTier": codex["service_tier"],
                        "ephemeral": True,
                    },
                })
                thread_result = wait_response(2)
                thread = thread_result.get("thread", {})
                thread_id = thread.get("id") if isinstance(thread, dict) else None
                if not isinstance(thread_id, str) or not thread_id:
                    raise ExperimentError("app-server thread/start returned no thread id")
                send({
                    "id": 3,
                    "method": "turn/start",
                    "params": {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": prompt}],
                        "cwd": str(cwd),
                        "model": codex["model"],
                        "effort": codex["reasoning_effort"],
                        "serviceTier": codex["service_tier"],
                        "approvalPolicy": "never",
                        "sandboxPolicy": {"type": "dangerFullAccess"},
                    },
                })
                turn_result = wait_response(3)
                turn = turn_result.get("turn", {})
                turn_id = turn.get("id") if isinstance(turn, dict) else None
                if not isinstance(turn_id, str) or not turn_id:
                    raise ExperimentError("app-server turn/start returned no turn id")
                while True:
                    message = receive()
                    if message.get("method") != "turn/completed":
                        continue
                    params = message.get("params", {})
                    observed_turn = params.get("turn", {}) if isinstance(params, dict) else {}
                    if params.get("threadId") == thread_id and observed_turn.get("id") == turn_id:
                        completed = observed_turn.get("status") == "completed"
                        if not completed:
                            error_text = f"app-server turn ended with status {observed_turn.get('status')}"
                        break
            except TimeoutError as error:
                timed_out = True
                error_text = str(error)
            except (BrokenPipeError, OSError, ExperimentError) as error:
                error_text = str(error)

        terminate_process_tree(process)
        reader.join(timeout=2)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
    if error_text:
        with stderr_path.open("a", encoding="utf-8", newline="\n") as stderr:
            stderr.write(f"\nagentbase app-server runner: {error_text}\n")
    return {
        "exit_code": 0 if completed else (process.returncode if process.returncode not in {None, 0} else 1),
        "timed_out": timed_out,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def monitor_subject(
    codex: dict[str, Any],
    workspace: Path,
    prompt: str,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if codex["client_protocol"] == "app-server-v2":
        return monitor_app_server(
            codex_app_server_argv(codex),
            workspace,
            env,
            stdout_path,
            stderr_path,
            timeout_seconds,
            codex,
            prompt,
        )
    return monitor_command(
        codex_exec_argv(codex, workspace, prompt),
        workspace,
        env,
        stdout_path,
        stderr_path,
        timeout_seconds,
    )


def app_server_usage(usage: dict[str, Any], prefix_epoch: int) -> dict[str, Any]:
    mapping = {
        "inputTokens": "input_tokens",
        "cachedInputTokens": "cached_input_tokens",
        "cacheWriteInputTokens": "cache_write_input_tokens",
        "outputTokens": "output_tokens",
        "reasoningOutputTokens": "reasoning_output_tokens",
    }
    normalized = {target: usage[source] for source, target in mapping.items() if source in usage}
    normalized.setdefault("cache_write_input_tokens", 0)
    normalized["prefix_epoch"] = prefix_epoch
    return normalized


def normalize_app_server_item(item: dict[str, Any]) -> dict[str, Any]:
    type_mapping = {
        "agentMessage": "agent_message",
        "commandExecution": "command_execution",
        "mcpToolCall": "mcp_tool_call",
        "webSearch": "web_search",
        "toolSearch": "tool_search",
        "contextCompaction": "context_compaction",
        "collabAgentToolCall": "collab_agent_tool_call",
    }
    key_mapping = {
        "aggregatedOutput": "aggregated_output",
        "exitCode": "exit_code",
        "server": "server",
        "tool": "tool",
    }
    normalized = dict(item)
    normalized["type"] = type_mapping.get(str(item.get("type", "unknown")), str(item.get("type", "unknown")))
    for source, target in key_mapping.items():
        if source in item:
            normalized[target] = item[source]
    return normalized


def parse_events(path: Path) -> dict[str, Any]:
    events = []
    invalid_lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            invalid_lines.append(number)
    legacy_turns = [event for event in events if event.get("type") == "turn.completed"]
    app_turns = []
    completed_items = [event.get("item", {}) for event in events if event.get("type") == "item.completed"]
    request_usages: list[dict[str, Any]] = []
    latest_app_total: dict[str, Any] = {}
    seen_app_totals: set[tuple[tuple[str, int], ...]] = set()
    prefix_epoch = 0
    execution_contract_failures: list[str] = []
    for event in events:
        method = event.get("method")
        params = event.get("params", {})
        # The App Server ThreadItem schema exposes collab calls at both lifecycle
        # edges. A started call is sufficient even if it fails or never completes.
        if (
            method in {"item/started", "item/completed"}
            and isinstance(params, dict)
            and isinstance(params.get("item"), dict)
            and params["item"].get("type") == "collabAgentToolCall"
            and not execution_contract_failures
        ):
            execution_contract_failures.append("single-model contract violated: collabAgentToolCall observed")
        if method == "item/completed" and isinstance(params, dict) and isinstance(params.get("item"), dict):
            item = normalize_app_server_item(params["item"])
            completed_items.append(item)
            if item.get("type") == "context_compaction":
                prefix_epoch += 1
        elif method == "thread/tokenUsage/updated" and isinstance(params, dict):
            token_usage = params.get("tokenUsage", {})
            if not isinstance(token_usage, dict):
                continue
            last = token_usage.get("last", {})
            total = token_usage.get("total", {})
            if not isinstance(last, dict) or not isinstance(total, dict):
                continue
            normalized_total = app_server_usage(total, prefix_epoch)
            normalized_last = app_server_usage(last, prefix_epoch)
            total_identity = tuple(sorted(
                (key, value) for key, value in normalized_total.items()
                if key != "prefix_epoch" and isinstance(value, int) and not isinstance(value, bool)
            ))
            latest_app_total = normalized_total
            if total_identity not in seen_app_totals and any(
                value for key, value in normalized_last.items()
                if key != "prefix_epoch" and isinstance(value, int) and not isinstance(value, bool)
            ):
                seen_app_totals.add(total_identity)
                request_usages.append(normalized_last)
        elif method == "turn/completed" and isinstance(params, dict):
            app_turns.append(params)
    messages = [item.get("text", "") for item in completed_items if item.get("type") == "agent_message"]
    item_type_counts: dict[str, int] = {}
    for item in completed_items:
        item_type = str(item.get("type", "unknown"))
        item_type_counts[item_type] = item_type_counts.get(item_type, 0) + 1
    tools = [
        item
        for item in completed_items
        if item.get("type") in {"command_execution", "mcp_tool_call", "web_search", "tool_search"}
        or str(item.get("type", "")).endswith("_tool_call")
    ]
    usage = latest_app_total or (legacy_turns[-1].get("usage", {}) if legacy_turns else {})
    usage.pop("prefix_epoch", None)
    usage_breakdown = normalize_usage(usage)
    app_completed = any(
        isinstance(turn.get("turn"), dict) and turn["turn"].get("status") == "completed"
        for turn in app_turns
    )
    complete = not invalid_lines and (bool(legacy_turns) or app_completed) and usage_breakdown["complete"]
    projection = ideal_cache_projection(request_usages, usage)
    return {
        "event_count": len(events), "invalid_json_lines": invalid_lines, "usage_complete": complete,
        "usage": usage, "usage_breakdown": usage_breakdown,
        "request_usages": request_usages,
        "ideal_cache_projection": projection,
        "final_answer": messages[-1] if messages else "", "tool_items": tools,
        "completed_item_type_counts": item_type_counts,
        "execution_contract_failures": execution_contract_failures,
    }


def verify_experiment_identity(experiment: dict[str, Any]) -> list[str]:
    failures = []
    if experiment.get("schema") != EXPERIMENT_SCHEMA:
        failures.append("experiment schema changed")
    runner = experiment.get("runner", {})
    if runner.get("source_sha256") != sha256_file(Path(__file__)):
        failures.append("runner source changed")
    if runner.get("python") != sys.version:
        failures.append("runner Python changed")
    codex = experiment["codex"]
    executable = Path(codex["executable"])
    if not executable.is_file() or sha256_file(executable) != codex["executable_sha256"]:
        failures.append("Codex executable changed")
    corpus_path = Path(experiment["corpus"]["path"])
    if not corpus_path.is_file() or sha256_file(corpus_path) != experiment["corpus"]["sha256"]:
        failures.append("corpus changed")
    for role, workspace in experiment["workspaces"].items():
        if git_identity(Path(workspace["path"]), workspace.get("identity_paths", ["."])) != workspace["identity"]:
            failures.append(f"workspace changed: {role}")
    for name, environment in experiment["environments"].items():
        tree = environment_tree(Path(environment["codex_home"]))
        if sha256_bytes(canonical_bytes(tree)) != environment["tree_sha256"]:
            failures.append(f"environment changed: {name}")
    try:
        materialize_runtime_environment(experiment["runtime_environment"])
    except (ExperimentError, OSError, KeyError, ValueError):
        failures.append("runtime environment changed")
    return failures


def run_experiment(experiment_path: Path) -> dict[str, Any]:
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    validate_benchmark_codex(experiment["codex"])
    failures = verify_experiment_identity(experiment)
    if failures:
        raise ExperimentError(f"preflight identity mismatch: {failures}")
    runtime_environment = materialize_runtime_environment(experiment["runtime_environment"])
    corpus = json.loads(Path(experiment["corpus"]["path"]).read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in corpus["cases"]}
    root = experiment_path.resolve().parent
    runs_root = root / "runs"
    runs_root.mkdir(exist_ok=False)
    records = []
    for scheduled in experiment["schedule"]:
        case = cases[scheduled["case_id"]]
        environment_name = scheduled["environment"]
        environment = experiment["environments"][environment_name]
        workspace = Path(experiment["workspaces"][case["workspace_role"]]["path"])
        run_id = f"{case['id']}__{environment_name}__{scheduled['ordinal']}"
        stdout_path = runs_root / f"{run_id}.jsonl"
        stderr_path = runs_root / f"{run_id}.stderr.txt"
        codex = experiment["codex"]
        env = codex_environment(environment, runtime_environment)
        monitored = monitor_subject(
            codex,
            workspace,
            READ_ONLY_PREFIX + case["prompt"],
            env,
            stdout_path,
            stderr_path,
            experiment["timeout_seconds"],
        )
        parsed = parse_events(stdout_path)
        network_transport = network_transport_observation(stdout_path, stderr_path)
        pricing = experiment.get("token_pricing", TOKEN_PRICING)
        records.append({
            "run_id": run_id, **scheduled, "workspace_role": case["workspace_role"], **monitored,
            **parsed,
            "network_transport": network_transport,
            "actual_total_tokens": parsed["usage_breakdown"]["actual_total_tokens"],
            "price_equivalent": price_equivalent(parsed["usage_breakdown"], pricing),
            "observed_request_price": observed_request_price(parsed["request_usages"], pricing),
            "ideal_cache_price": ideal_cache_price(parsed["ideal_cache_projection"], pricing),
            "stdout": str(stdout_path.relative_to(root)), "stderr": str(stderr_path.relative_to(root)),
        })
    postflight = verify_experiment_identity(experiment)
    postflight.extend(
        f"{failure}: {record['run_id']}"
        for record in records
        for failure in record["execution_contract_failures"]
    )
    postflight.extend(
        f"network transport degraded: {record['run_id']}"
        for record in records
        if not record["network_transport"]["clean"]
    )
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_identity": experiment["experiment_identity"],
        "postflight_failures": postflight,
        "usage_report": aggregate_usage(records, experiment.get("token_pricing", TOKEN_PRICING)),
        "observed_request_price_report": aggregate_observed_request_price(records),
        "setup_observed_request_price_report": experiment["preflight"].get("observed_request_price_report", {
            "schema": "agentbase.observed-request-price-report/v1",
            "all": {"status": "unavailable", "reason": "legacy_preflight_without_per_request_usage"},
        }),
        "observed_request_price_report_including_setup": aggregate_observed_request_price(
            [*experiment["preflight"]["records"], *records]
        ),
        "setup_usage_report": experiment["preflight"]["usage_report"],
        "ideal_cache_report": aggregate_ideal_cache(records, experiment.get("token_pricing", TOKEN_PRICING)),
        "setup_ideal_cache_report": experiment["preflight"].get("ideal_cache_report", {
            "schema": "agentbase.ideal-cache-report/v2",
            "all": {"status": "unavailable", "reason": "legacy_preflight_without_per_request_usage"},
        }),
        "ideal_cache_report_including_setup": aggregate_ideal_cache(
            [*experiment["preflight"]["records"], *records],
            experiment.get("token_pricing", TOKEN_PRICING),
        ),
        "usage_report_including_setup": aggregate_usage(
            [*experiment["preflight"]["records"], *records],
            experiment.get("token_pricing", TOKEN_PRICING),
        ),
        "records": records,
    }
    (root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def build_capsule(experiment_path: Path) -> dict[str, Any]:
    root = experiment_path.resolve().parent
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    corpus_path = Path(experiment["corpus"]["path"])
    raw_files = {}
    for record in [*experiment.get("preflight", {}).get("records", []), *summary["records"]]:
        for field in ("stdout", "stderr"):
            relative = record[field]
            raw_files[relative] = sha256_file(root / relative)
    capsule = {
        "schema": CAPSULE_SCHEMA,
        "isolation": "detached-capsule",
        "input_declaration": "auditor may read only this capsule and its designated output path",
        "capsule_hash_scheme": CAPSULE_HASH_SCHEME,
        "experiment_identity_scheme": EXPERIMENT_IDENTITY_SCHEME,
        "canonicalization": CANONICALIZATION,
        "experiment": experiment,
        "corpus": json.loads(corpus_path.read_text(encoding="utf-8")),
        "environment_diff": json.loads((root / "environment-diff.json").read_text(encoding="utf-8")),
        "summary": summary,
        "raw_file_sha256": raw_files,
    }
    capsule["capsule_sha256"] = capsule_sha256(capsule)
    (root / "audit-capsule.json").write_text(json.dumps(capsule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return capsule


def verify_capsule(capsule_path: Path) -> dict[str, Any]:
    capsule_path = capsule_path.resolve()
    root = capsule_path.parent
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if capsule.get("schema") not in {CAPSULE_SCHEMA, *LEGACY_CAPSULE_SCHEMAS}:
        failures.append("capsule schema mismatch")
    if capsule.get("capsule_hash_scheme") != CAPSULE_HASH_SCHEME:
        failures.append("capsule hash scheme mismatch")
    if capsule.get("experiment_identity_scheme") != EXPERIMENT_IDENTITY_SCHEME:
        failures.append("experiment identity scheme mismatch")
    if capsule.get("canonicalization") != CANONICALIZATION:
        failures.append("canonicalization contract mismatch")

    claimed_capsule_hash = str(capsule.get("capsule_sha256", ""))
    recomputed_capsule_hash = capsule_sha256(capsule)
    if claimed_capsule_hash != recomputed_capsule_hash:
        failures.append("capsule sha256 mismatch")

    experiment = capsule.get("experiment", {})
    claimed_experiment_identity = str(experiment.get("experiment_identity", ""))
    recomputed_experiment_identity = experiment_identity_sha256(experiment)
    if claimed_experiment_identity != recomputed_experiment_identity:
        failures.append("experiment identity mismatch")
    if capsule.get("summary", {}).get("experiment_identity") != claimed_experiment_identity:
        failures.append("summary experiment identity mismatch")

    raw_files = capsule.get("raw_file_sha256", {})
    verified_raw_files = 0
    for relative, expected_hash in raw_files.items():
        raw_path = (root / relative).resolve()
        try:
            raw_path.relative_to(root)
        except ValueError:
            failures.append(f"raw file escapes capsule root: {relative}")
            continue
        if not raw_path.is_file():
            failures.append(f"raw file missing: {relative}")
            continue
        if sha256_file(raw_path) != expected_hash:
            failures.append(f"raw file sha256 mismatch: {relative}")
            continue
        verified_raw_files += 1

    for field, filename in (
        ("environment_diff_sha256", "environment-diff.json"),
        ("environment_trees_sha256", "environment-trees.json"),
    ):
        path = root / filename
        if not path.is_file() or sha256_file(path) != experiment.get(field):
            failures.append(f"{filename} sha256 mismatch")

    if failures:
        raise ExperimentError("capsule verification failed: " + "; ".join(failures))
    return {
        "schema": CAPSULE_VERIFICATION_SCHEMA,
        "capsule_sha256": recomputed_capsule_hash,
        "experiment_identity": recomputed_experiment_identity,
        "verified_raw_files": verified_raw_files,
        "verified_environment_files": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--experiment", type=Path, required=True)
    capsule = sub.add_parser("capsule")
    capsule.add_argument("--experiment", type=Path, required=True)
    verify = sub.add_parser("verify-capsule")
    verify.add_argument("--capsule", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = build_experiment(args.config, args.output)
        elif args.command == "run":
            value = run_experiment(args.experiment)
        elif args.command == "capsule":
            value = build_capsule(args.experiment)
        else:
            value = verify_capsule(args.capsule)
        response = {"ok": True, "schema": value["schema"]}
        if args.command == "verify-capsule":
            response.update({key: value[key] for key in (
                "capsule_sha256", "experiment_identity", "verified_raw_files", "verified_environment_files"
            )})
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ExperimentError, OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
