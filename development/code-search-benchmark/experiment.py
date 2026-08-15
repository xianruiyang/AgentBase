#!/usr/bin/env python3
"""Build, run, summarize, and capsule monitored Codex source-query experiments."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPERIMENT_SCHEMA = "agentbase.source-query-experiment/v2"
RESULT_SCHEMA = "agentbase.source-query-results/v2"
CAPSULE_SCHEMA = "agentbase.source-query-audit-capsule/v2"
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
    "as_of": "2026-08-16",
    "model_family": "gpt-5.6",
    "source": "https://developers.openai.com/api/docs/pricing",
    "model_source": "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
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
SECRET_OR_STATE_NAMES = {
    ".sandbox_migration", "auth.json", "cap_sid", "installation_id", "history.jsonl", "models_cache.json",
}
STATE_SUFFIXES = {".sqlite", ".sqlite-shm", ".sqlite-wal"}
STATE_DIRECTORIES = {"cache", "logs", "tmp", ".tmp", ".sandbox", ".sandbox-bin", "sessions", "archived_sessions", "thread-writer-locks"}
MAX_ENV_FILES = 50_000
READ_ONLY_PREFIX = (
    "这是只读源码查找基准。不得修改文件、配置、进程或外部状态；"
    "不得访问其他测试环境、历史答案、聚合结果或隐藏 oracle。请根据当前环境自主完成下列任务。\n\n"
)
PREFLIGHT_PROMPT = (
    "这是独立基准运行能力预检。必须运行 PATH 中的 {command}，"
    "只返回该命令输出；不得修改文件、配置、其他进程或外部状态。"
)


class ExperimentError(ValueError):
    pass


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


def environment_tree(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.name in SECRET_OR_STATE_NAMES or path.name.endswith(tuple(STATE_SUFFIXES)):
            continue
        if any(part in STATE_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        entries[relative] = sha256_file(path)
        if len(entries) > MAX_ENV_FILES:
            raise ExperimentError(f"environment tree exceeds {MAX_ENV_FILES} files: {root}")
    return entries


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
    return {
        **TOKEN_PRICING,
        "experiment_model": model,
        "requested_service_tier": str(codex.get("service_tier", "")),
        "applicable": model == "gpt-5.6" or model.startswith("gpt-5.6-"),
    }


def validate_benchmark_codex(codex: dict[str, Any]) -> None:
    if codex.get("service_tier") != "default":
        raise ExperimentError("independent benchmark requires service_tier=default")
    if codex.get("sandbox") != "danger-full-access":
        raise ExperimentError("independent benchmark requires sandbox=danger-full-access")
    protected = {
        "approval_policy", "model", "model_reasoning_effort", "sandbox_mode", "service_tier",
    }
    for override in codex.get("extra_config", []):
        key = str(override).split("=", 1)[0].strip()
        if key in protected:
            raise ExperimentError(f"extra_config must not override benchmark execution identity: {key}")


def resolve_codex_identity(raw: dict[str, Any]) -> dict[str, Any]:
    codex = dict(raw)
    validate_benchmark_codex(codex)
    executable = Path(str(codex.get("executable", ""))).resolve()
    if not executable.is_file():
        raise ExperimentError(f"Codex executable does not exist: {executable}")
    observed_version = run_capture([str(executable), "--version"], Path.cwd()).decode(
        "utf-8", errors="replace"
    ).strip()
    observed_sha256 = sha256_file(executable)
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
        role = case.get("workspace_role")
        if role not in workspaces:
            raise ExperimentError(f"corpus role has no workspace: {role!r}")
        if selected is not None and case_id not in selected:
            continue
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


def codex_environment(environment: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
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
    argv = [
        codex["executable"], "exec", "--json", "--ephemeral", "--sandbox", codex["sandbox"],
        "-c", 'approval_policy="never"', "-m", codex["model"],
        "-c", f'model_reasoning_effort="{codex["reasoning_effort"]}"',
        "-c", f'service_tier="{codex["service_tier"]}"',
    ]
    for override in codex.get("extra_config", []):
        argv.extend(["-c", str(override)])
    if "project_doc_max_bytes" in codex:
        argv.extend(["-c", f'project_doc_max_bytes={int(codex["project_doc_max_bytes"])}'])
    if skip_git_repo_check:
        argv.append("--skip-git-repo-check")
    argv.extend(["--cd", str(workspace), "--color", "never", prompt])
    return argv


def preflight_command(environment: dict[str, Any]) -> tuple[str, str]:
    home = Path(environment["codex_home"])
    srcq = home / "bin" / "srcq.exe"
    if srcq.is_file():
        return "srcq.exe --version", "srcq "
    return "rg.exe --version", "ripgrep "


def validate_preflight_record(record: dict[str, Any], command: str, expected_output: str) -> None:
    if record["exit_code"] != 0 or record["timed_out"]:
        raise ExperimentError(f"Codex preflight process failed: {record['environment']}")
    if not record["usage_complete"]:
        raise ExperimentError(f"Codex preflight usage is incomplete: {record['environment']}")
    command_name = command.split()[0].lower()
    successful = False
    for item in record["tool_items"]:
        if item.get("type") != "command_execution":
            continue
        invoked = str(item.get("command", "")).lower()
        output = str(item.get("aggregated_output", item.get("output", "")))
        if (
            command_name in invoked
            and item.get("status") in {None, "completed"}
            and item.get("exit_code") in {None, 0}
            and expected_output.lower() in (output + record["final_answer"]).lower()
        ):
            successful = True
            break
    if not successful:
        raise ExperimentError(
            f"Codex preflight did not execute the required command successfully: {record['environment']}/{command}"
        )


def run_preflights(
    codex: dict[str, Any],
    environments: dict[str, dict[str, Any]],
    output: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    root = output / "preflight"
    fixture = root / "workspace"
    fixture.mkdir(parents=True)
    records = []
    for name in ("control", "candidate"):
        environment = environments[name]
        command, expected_output = preflight_command(environment)
        stdout_path = root / f"{name}.jsonl"
        stderr_path = root / f"{name}.stderr.txt"
        argv = codex_exec_argv(
            codex,
            fixture,
            PREFLIGHT_PROMPT.format(command=command),
            skip_git_repo_check=True,
        )
        monitored = monitor_command(
            argv,
            fixture,
            codex_environment(environment),
            stdout_path,
            stderr_path,
            timeout_seconds,
        )
        parsed = parse_events(stdout_path)
        record = {
            "run_id": f"preflight__{name}",
            "environment": name,
            "command": command,
            **monitored,
            **parsed,
            "actual_total_tokens": parsed["usage_breakdown"]["actual_total_tokens"],
            "price_equivalent": price_equivalent(parsed["usage_breakdown"], token_pricing_contract(codex)),
            "stdout": str(stdout_path.relative_to(output)),
            "stderr": str(stderr_path.relative_to(output)),
        }
        validate_preflight_record(record, command, expected_output)
        records.append(record)
    return {
        "prompt_contract": "execute the environment's installed query executable and return its version",
        "timeout_seconds": timeout_seconds,
        "usage_report": aggregate_usage(records, token_pricing_contract(codex)),
        "records": records,
    }


def build_experiment(config_path: Path, output: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    corpus_path = Path(config["corpus"]).resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    case_ids = selected_case_ids(corpus, config.get("case_ids"))
    workspaces = {}
    for role, raw in config["workspaces"].items():
        root = Path(raw["path"]).resolve()
        identity_paths = normalize_identity_paths(root, raw.get("identity_paths"))
        workspaces[role] = {"path": str(root), "identity_paths": identity_paths}
    validate_corpus_snapshot(corpus, workspaces, set(case_ids))
    environments = {}
    for name in ("control", "candidate"):
        raw_environment = config["environments"][name]
        home = Path(raw_environment["codex_home"]).resolve()
        environments[name] = {
            "codex_home": str(home),
            "auth_mode": "inherited-secure-environment",
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
    preflight = run_preflights(
        codex,
        environments,
        output,
        int(config.get("preflight_timeout_seconds", 180)),
    )
    for role, workspace in workspaces.items():
        workspace["identity"] = git_identity(Path(workspace["path"]), workspace["identity_paths"])
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
        "corpus": {"path": str(corpus_path), "sha256": sha256_file(corpus_path), "version": corpus["version"]},
        "workspaces": workspaces,
        "codex": codex,
        "preflight": preflight,
        "tool_versions": tool_versions,
        "environments": environments,
        "allowed_differences": config["allowed_differences"],
        "selected_case_ids": case_ids,
        "environment_diff_sha256": sha256_file(output / "environment-diff.json"),
        "environment_trees_sha256": sha256_file(output / "environment-trees.json"),
        "schedule": selected_schedule(
            case_ids,
            int(config["repetitions"]),
            int(config["seed"]),
            list(config.get("run_environments", ["control", "candidate"])),
        ),
        "timeout_seconds": int(config["timeout_seconds"]),
        "network_policy": config["network_policy"],
        "token_pricing": token_pricing_contract(codex),
        "runner": {"schema": EXPERIMENT_SCHEMA, "source_sha256": sha256_file(Path(__file__)), "python": sys.version},
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
    turns = [event for event in events if event.get("type") == "turn.completed"]
    messages = [
        event.get("item", {}).get("text", "")
        for event in events
        if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"
    ]
    completed_items = [event.get("item", {}) for event in events if event.get("type") == "item.completed"]
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
    usage = turns[-1].get("usage", {}) if turns else {}
    usage_breakdown = normalize_usage(usage)
    complete = not invalid_lines and bool(turns) and usage_breakdown["complete"]
    return {
        "event_count": len(events), "invalid_json_lines": invalid_lines, "usage_complete": complete,
        "usage": usage, "usage_breakdown": usage_breakdown,
        "final_answer": messages[-1] if messages else "", "tool_items": tools,
        "completed_item_type_counts": item_type_counts,
    }


def verify_experiment_identity(experiment: dict[str, Any]) -> list[str]:
    failures = []
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
    return failures


def run_experiment(experiment_path: Path) -> dict[str, Any]:
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    validate_benchmark_codex(experiment["codex"])
    failures = verify_experiment_identity(experiment)
    if failures:
        raise ExperimentError(f"preflight identity mismatch: {failures}")
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
        argv = codex_exec_argv(codex, workspace, READ_ONLY_PREFIX + case["prompt"])
        env = codex_environment(environment)
        monitored = monitor_command(argv, workspace, env, stdout_path, stderr_path, experiment["timeout_seconds"])
        parsed = parse_events(stdout_path)
        pricing = experiment.get("token_pricing", TOKEN_PRICING)
        records.append({
            "run_id": run_id, **scheduled, "workspace_role": case["workspace_role"], **monitored,
            **parsed,
            "actual_total_tokens": parsed["usage_breakdown"]["actual_total_tokens"],
            "price_equivalent": price_equivalent(parsed["usage_breakdown"], pricing),
            "stdout": str(stdout_path.relative_to(root)), "stderr": str(stderr_path.relative_to(root)),
        })
    postflight = verify_experiment_identity(experiment)
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_identity": experiment["experiment_identity"],
        "postflight_failures": postflight,
        "usage_report": aggregate_usage(records, experiment.get("token_pricing", TOKEN_PRICING)),
        "setup_usage_report": experiment["preflight"]["usage_report"],
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
    if capsule.get("schema") != CAPSULE_SCHEMA:
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
