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


EXPERIMENT_SCHEMA = "agentbase.source-query-experiment/v1"
RESULT_SCHEMA = "agentbase.source-query-results/v1"
CAPSULE_SCHEMA = "agentbase.source-query-audit-capsule/v1"
CORPUS_SCHEMA = "agentbase.source-query-corpus/v1"
CAPSULE_HASH_SCHEME = "sha256-canonical-json-without-capsule_sha256"
SECRET_OR_STATE_NAMES = {
    "auth.json", "cap_sid", "installation_id", "history.jsonl", "models_cache.json",
}
STATE_SUFFIXES = {".sqlite", ".sqlite-shm", ".sqlite-wal"}
STATE_DIRECTORIES = {"cache", "logs", "tmp", ".tmp", ".sandbox", ".sandbox-bin", "sessions", "archived_sessions", "thread-writer-locks"}
MAX_ENV_FILES = 50_000
READ_ONLY_PREFIX = (
    "这是只读源码查找基准。不得修改文件、配置、进程或外部状态；"
    "不得访问其他测试环境、历史答案、聚合结果或隐藏 oracle。请根据当前环境自主完成下列任务。\n\n"
)


class ExperimentError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def capsule_sha256(capsule: dict[str, Any]) -> str:
    payload = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
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


def git_identity(root: Path) -> dict[str, Any]:
    head = run_capture(["git", "rev-parse", "HEAD"], root).decode().strip()
    tree = run_capture(["git", "rev-parse", "HEAD^{tree}"], root).decode().strip()
    tracked_patch = run_capture(["git", "diff", "--binary", "HEAD", "--", "."], root)
    untracked = run_capture(["git", "ls-files", "--others", "--exclude-standard", "-z"], root)
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


def validate_corpus_snapshot(corpus: dict[str, Any], workspaces: dict[str, dict[str, Any]]) -> None:
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
        oracle = case.get("oracle", {})
        sources = [oracle["source"]] if "source" in oracle else list(oracle.get("sources", []))
        if oracle.get("kind") == "unique-path":
            sources.append({"path": oracle["path"], "sha256": oracle["sha256"]})
        for source in sources:
            root = Path(workspaces[role]["path"])
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


def build_experiment(config_path: Path, output: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    corpus_path = Path(config["corpus"]).resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    workspaces = {}
    for role, raw in config["workspaces"].items():
        root = Path(raw["path"]).resolve()
        workspaces[role] = {"path": str(root), "identity": git_identity(root)}
    validate_corpus_snapshot(corpus, workspaces)
    environments = {}
    trees = {}
    for name in ("control", "candidate"):
        raw_environment = config["environments"][name]
        home = Path(raw_environment["codex_home"]).resolve()
        tree = environment_tree(home)
        trees[name] = tree
        environments[name] = {
            "codex_home": str(home),
            "tree_sha256": sha256_bytes(canonical_bytes(tree)),
            "auth_mode": "inherited-secure-environment",
        }
        if raw_environment.get("path_prepend"):
            path_prepend = resolve_path_prepend(home, str(raw_environment["path_prepend"]), name)
            environments[name]["path_prepend"] = str(path_prepend)
    diff = environment_diff(trees["control"], trees["candidate"], config["allowed_differences"])
    if not diff["ok"]:
        raise ExperimentError(f"environment difference outside allowlist: {diff['unexpected']}")
    output.mkdir(parents=True, exist_ok=False)
    (output / "environment-diff.json").write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "environment-trees.json").write_text(json.dumps(trees, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    case_ids = selected_case_ids(corpus, config.get("case_ids"))
    codex = dict(config["codex"])
    codex["observed_version"] = run_capture([codex["executable"], "--version"], Path.cwd()).decode("utf-8", errors="replace").strip()
    tool_versions = {}
    for probe in config.get("tool_probes", []):
        tool_versions[probe["id"]] = run_capture(list(probe["argv"]), Path.cwd()).decode("utf-8", errors="replace").strip()
    document = {
        "schema": EXPERIMENT_SCHEMA,
        "corpus": {"path": str(corpus_path), "sha256": sha256_file(corpus_path), "version": corpus["version"]},
        "workspaces": workspaces,
        "codex": codex,
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
        "runner": {"schema": EXPERIMENT_SCHEMA, "source_sha256": sha256_file(Path(__file__)), "python": sys.version},
    }
    document["experiment_identity"] = sha256_bytes(canonical_bytes(document))
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
    tools = [
        event.get("item", {})
        for event in events
        if event.get("type") == "item.completed" and event.get("item", {}).get("type") in {"command_execution", "mcp_tool_call"}
    ]
    usage = turns[-1].get("usage", {}) if turns else {}
    required = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"}
    complete = not invalid_lines and bool(turns) and required.issubset(usage)
    return {
        "event_count": len(events), "invalid_json_lines": invalid_lines, "usage_complete": complete,
        "usage": usage, "final_answer": messages[-1] if messages else "", "tool_items": tools,
    }


def verify_experiment_identity(experiment: dict[str, Any]) -> list[str]:
    failures = []
    corpus_path = Path(experiment["corpus"]["path"])
    if not corpus_path.is_file() or sha256_file(corpus_path) != experiment["corpus"]["sha256"]:
        failures.append("corpus changed")
    for role, workspace in experiment["workspaces"].items():
        if git_identity(Path(workspace["path"])) != workspace["identity"]:
            failures.append(f"workspace changed: {role}")
    for name, environment in experiment["environments"].items():
        tree = environment_tree(Path(environment["codex_home"]))
        if sha256_bytes(canonical_bytes(tree)) != environment["tree_sha256"]:
            failures.append(f"environment changed: {name}")
    return failures


def run_experiment(experiment_path: Path) -> dict[str, Any]:
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
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
        argv = [
            codex["executable"], "exec", "--json", "--ephemeral", "--sandbox", codex.get("sandbox", "read-only"),
            "-c", 'approval_policy="never"', "-m", codex["model"],
            "-c", f'model_reasoning_effort="{codex["reasoning_effort"]}"',
            "-c", f'service_tier="{codex["service_tier"]}"',
        ]
        for override in codex.get("extra_config", []):
            argv.extend(["-c", str(override)])
        if "project_doc_max_bytes" in codex:
            argv.extend(["-c", f'project_doc_max_bytes={int(codex["project_doc_max_bytes"])}'])
        argv.extend(["--cd", str(workspace), "--color", "never", READ_ONLY_PREFIX + case["prompt"]])
        env = os.environ.copy()
        env["CODEX_HOME"] = environment["codex_home"]
        if environment.get("path_prepend"):
            env["PATH"] = environment["path_prepend"] + os.pathsep + env.get("PATH", "")
        monitored = monitor_command(argv, workspace, env, stdout_path, stderr_path, experiment["timeout_seconds"])
        parsed = parse_events(stdout_path)
        usage = parsed["usage"]
        records.append({
            "run_id": run_id, **scheduled, "workspace_role": case["workspace_role"], **monitored,
            **parsed, "actual_total_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
            "stdout": str(stdout_path.relative_to(root)), "stderr": str(stderr_path.relative_to(root)),
        })
    postflight = verify_experiment_identity(experiment)
    result = {"schema": RESULT_SCHEMA, "experiment_identity": experiment["experiment_identity"], "postflight_failures": postflight, "records": records}
    (root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def build_capsule(experiment_path: Path) -> dict[str, Any]:
    root = experiment_path.resolve().parent
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    corpus_path = Path(experiment["corpus"]["path"])
    raw_files = {}
    for record in summary["records"]:
        for field in ("stdout", "stderr"):
            relative = record[field]
            raw_files[relative] = sha256_file(root / relative)
    capsule = {
        "schema": CAPSULE_SCHEMA,
        "isolation": "detached-capsule",
        "input_declaration": "auditor may read only this capsule and its designated output path",
        "capsule_hash_scheme": CAPSULE_HASH_SCHEME,
        "experiment": experiment,
        "corpus": json.loads(corpus_path.read_text(encoding="utf-8")),
        "environment_diff": json.loads((root / "environment-diff.json").read_text(encoding="utf-8")),
        "summary": summary,
        "raw_file_sha256": raw_files,
    }
    capsule["capsule_sha256"] = capsule_sha256(capsule)
    (root / "audit-capsule.json").write_text(json.dumps(capsule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return capsule


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
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = build_experiment(args.config, args.output)
        elif args.command == "run":
            value = run_experiment(args.experiment)
        else:
            value = build_capsule(args.experiment)
        print(json.dumps({"ok": True, "schema": value["schema"]}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ExperimentError, OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
