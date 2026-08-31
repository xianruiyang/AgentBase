"""Deterministic contracts for the AgentBase Windows SWE evaluation set."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CORPUS_SCHEMA = "agentbase.windows-swe-corpus/v4"
CORPUS_ID = "agentbase-windows-swe-v1"
QUALIFICATION_SCHEMA = "agentbase.windows-swe-qualification/v3"
WINDOWS_ADAPTER_ROOT = Path("development/agent-evaluation/windows-adapters")
REQUIRED_ASSETS = (
    "instruction.md",
    "task.toml",
    "solution/solution.patch",
    "tests/test.patch",
    "tests/config.json",
    "tests/grader.py",
)
ALLOWED_PLACEHOLDERS = {
    "python",
    "workspace",
    "npm",
    "pnpm",
    "report",
    "raw_report",
}
FORBIDDEN_RUNTIME_WORDS = ("pier", "docker", "/bin/bash", "bash -c", "linux")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")
TASK_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]+\Z")
MAX_PATCH_BYTES = 8 * 1024 * 1024
MAX_PATCH_FILES = 100
MANAGED_TREE_RETRY_DELAYS_SECONDS = (
    0.05,
    0.1,
    0.2,
    0.4,
    0.8,
    1.6,
    3.2,
    5.0,
    5.0,
    5.0,
    5.0,
)
RECOVERABLE_ATTEMPT_STAGES = frozenset(
    {"candidate-finished", "patch-captured", "verifier-running"}
)
GIT_WINDOWS_PREFIX = (
    "git.exe",
    "-c",
    "core.longpaths=true",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
)
GIT_WINDOWS_ASSET_PREFIX = (
    "git.exe",
    "-c",
    "core.longpaths=true",
    "-c",
    "core.autocrlf=true",
    "-c",
    "core.eol=crlf",
)


class EvaluationError(RuntimeError):
    """The evaluation contract or its current evidence is invalid."""


class PreconditionError(EvaluationError):
    """A caller must establish required evidence before an evaluation can run."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read JSON {path}: {exc}") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_corpus_path(project_root: Path | None = None) -> Path:
    root = (project_root or default_project_root()).resolve()
    return root / "development" / "agent-evaluation" / "corpus" / "final-v1.json"


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise EvaluationError("LOCALAPPDATA is required on the Windows host")
    return Path(value).resolve()


def default_state_root() -> Path:
    return _local_app_data() / "AgentBase" / "agent-evaluation-state"


def default_work_root() -> Path:
    return _local_app_data() / "AgentBase" / "agent-evaluation-workspaces"


def ensure_disjoint_roots(state_root: Path, work_root: Path) -> None:
    state = state_root.resolve()
    work = work_root.resolve()
    if state == work or state in work.parents or work in state.parents:
        raise EvaluationError(
            "state_root and work_root must be disjoint; candidate and verifier state must stay separate"
        )


def ensure_evaluation_roots(
    project_root: Path,
    state_root: Path,
    work_root: Path,
    codex_root: Path | None = None,
) -> None:
    """Keep generated evaluation state away from project and optional runtime assets."""

    ensure_disjoint_roots(state_root, work_root)
    protected = {
        "project_root": project_root.resolve(),
    }
    if codex_root is not None:
        protected["codex_root"] = codex_root.resolve()
    generated = {
        "state_root": state_root.resolve(),
        "work_root": work_root.resolve(),
    }
    for generated_name, generated_path in generated.items():
        for protected_name, protected_path in protected.items():
            if (
                generated_path == protected_path
                or generated_path in protected_path.parents
                or protected_path in generated_path.parents
            ):
                raise EvaluationError(
                    f"{generated_name} must not overlap {protected_name}: {generated_path}"
                )


def require_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if resolved_candidate == resolved_root or resolved_root not in resolved_candidate.parents:
        raise EvaluationError(f"path escapes managed root {resolved_root}: {resolved_candidate}")
    return resolved_candidate


def dependency_runtime_projection(
    task: Mapping[str, Any], values: Mapping[str, str]
) -> dict[str, str | None]:
    """Resolve the task runtime directory that must lead child PATH lookup."""

    toolchain = task.get("toolchain")
    if not isinstance(toolchain, Mapping):
        raise EvaluationError("task toolchain is invalid")
    kind = toolchain.get("kind")
    if kind == "python":
        key = "python"
    elif kind == "node":
        key = str(toolchain.get("package_manager", ""))
        if key not in {"npm", "pnpm"}:
            raise EvaluationError("node task package manager is invalid")
    else:
        raise EvaluationError("task toolchain kind is invalid")
    executable_value = values.get(key)
    if not isinstance(executable_value, str) or not executable_value:
        raise EvaluationError(f"task dependency runtime is missing: {key}")
    executable = Path(executable_value).resolve()
    if not executable.is_file():
        raise EvaluationError(f"task dependency runtime is not a file: {key}")
    bin_directory = executable.parent.resolve()
    virtual_environment: Path | None = None
    if kind == "python":
        workspace_value = values.get("workspace")
        if not isinstance(workspace_value, str) or not workspace_value:
            raise EvaluationError("python task workspace is missing")
        expected = Path(workspace_value).resolve() / ".agentbase-venv"
        virtual_environment = bin_directory.parent.resolve()
        if virtual_environment != expected.resolve():
            raise EvaluationError("python task runtime is outside the managed virtual environment")
    return {
        "kind": str(kind),
        "executable": str(executable),
        "bin_directory": str(bin_directory),
        "virtual_environment": (
            str(virtual_environment) if virtual_environment is not None else None
        ),
    }


def remove_managed_tree(root: Path, candidate: Path) -> None:
    """Remove one verified managed subtree after bounded Windows handle release."""

    resolved = require_within(root, candidate)
    if not resolved.exists():
        return

    def clear_readonly_and_retry(
        function: Any,
        path: str,
        error: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        exception = error[1]
        if not isinstance(exception, PermissionError):
            raise exception
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        function(path)

    for delay in (*MANAGED_TREE_RETRY_DELAYS_SECONDS, None):
        try:
            shutil.rmtree(resolved, onerror=clear_readonly_and_retry)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def _safe_relative_path(value: str, *, field: str) -> bool:
    path = Path(value.replace("/", os.sep))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _validate_object_keys(
    value: Mapping[str, Any],
    *,
    where: str,
    required: set[str],
    optional: set[str] | None,
    errors: list[str],
) -> None:
    actual = set(value)
    missing = required - actual
    extra = actual - required - (optional or set())
    if missing:
        errors.append(f"{where} is missing keys: {sorted(missing)}")
    if extra:
        errors.append(f"{where} contains unknown keys: {sorted(extra)}")


def _validate_command(command: Any, *, where: str, errors: list[str]) -> None:
    if not isinstance(command, dict):
        errors.append(f"{where} must be an object")
        return
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
        errors.append(f"{where}.argv must be a non-empty string array")
        return
    joined = " ".join(argv).lower()
    if any(word in joined for word in FORBIDDEN_RUNTIME_WORDS):
        errors.append(f"{where}.argv contains a non-Windows or retired runtime")
    for argument in argv:
        placeholders = set(PLACEHOLDER_PATTERN.findall(argument))
        unknown = placeholders - ALLOWED_PLACEHOLDERS
        if unknown:
            errors.append(f"{where}.argv contains unknown placeholders: {sorted(unknown)}")
        if any(token in argument for token in ("&&", "||", ";", "`", "$()")):
            errors.append(f"{where}.argv must not contain shell composition")
    timeout = command.get("timeout_seconds")
    if not isinstance(timeout, int) or timeout < 1:
        errors.append(f"{where}.timeout_seconds must be a positive integer")
    environment = command.get("env", {})
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in environment.items()
    ):
        errors.append(f"{where}.env must be a string map")


def validate_corpus(corpus: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(corpus, dict):
        raise EvaluationError("corpus must be an object")
    _validate_object_keys(
        corpus,
        where="corpus",
        required={
            "schema",
            "id",
            "source",
            "adapter",
            "codex",
            "profiles",
            "suites",
            "tasks",
            "assessment",
        },
        optional={"$schema"},
        errors=errors,
    )
    if "$schema" in corpus and (
        not isinstance(corpus["$schema"], str) or not corpus["$schema"].strip()
    ):
        errors.append("$schema must be a non-empty string")
    if corpus.get("schema") != CORPUS_SCHEMA:
        errors.append(f"schema must be {CORPUS_SCHEMA}")
    if corpus.get("id") != CORPUS_ID:
        errors.append(f"id must be {CORPUS_ID}")

    source = corpus.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        _validate_object_keys(
            source,
            where="source",
            required={"name", "version", "repository", "commit", "task_root"},
            optional=None,
            errors=errors,
        )
        if source.get("name") != "DeepSWE" or source.get("version") != "v1.1":
            errors.append("source must identify DeepSWE v1.1")
        if source.get("repository") != "https://github.com/datacurve-ai/deep-swe.git":
            errors.append("source repository mismatch")
        if not GIT_SHA_PATTERN.fullmatch(str(source.get("commit", ""))):
            errors.append("source.commit must be a 40-character lowercase Git SHA")
        if source.get("task_root") != "tasks":
            errors.append("source.task_root must be tasks")

    adapter = corpus.get("adapter")
    if not isinstance(adapter, dict):
        errors.append("adapter must be an object")
    else:
        _validate_object_keys(
            adapter,
            where="adapter",
            required={
                "name",
                "version",
                "platform",
                "workspace_contract",
                "qualification_repetitions",
                "upstream_grader_sha256",
            },
            optional=None,
            errors=errors,
        )
        expected = {
            "name": "agentbase-windows-swe",
            "platform": "windows",
            "workspace_contract": "candidate-patch-verifier",
        }
        for key, value in expected.items():
            if adapter.get(key) != value:
                errors.append(f"adapter.{key} must be {value}")
        if not isinstance(adapter.get("version"), str) or not adapter.get("version", "").strip():
            errors.append("adapter.version must be a non-empty string")
        if not isinstance(adapter.get("qualification_repetitions"), int) or adapter.get(
            "qualification_repetitions", 0
        ) < 2:
            errors.append("adapter.qualification_repetitions must be at least 2")
        if not HASH_PATTERN.fullmatch(str(adapter.get("upstream_grader_sha256", ""))):
            errors.append("adapter.upstream_grader_sha256 must be SHA-256")

    codex = corpus.get("codex")
    if not isinstance(codex, dict):
        errors.append("codex must be an object")
    else:
        _validate_object_keys(
            codex,
            where="codex",
            required={
                "auth_mode",
                "transport_overlay",
            },
            optional=None,
            errors=errors,
        )
        expected_codex = {
            "auth_mode": "existing-codex-auth-json",
            "transport_overlay": "codex-eval-overlay.toml",
        }
        for key, value in expected_codex.items():
            if codex.get(key) != value:
                errors.append(f"codex.{key} must be {value}")

    profiles = corpus.get("profiles")
    expected_profiles = {
        "sol": ("gpt-5.6-sol", "medium"),
        "luna": ("gpt-5.6-luna", "max"),
    }
    if not isinstance(profiles, dict) or set(profiles) != set(expected_profiles):
        errors.append("profiles must contain exactly sol and luna")
    else:
        for name, expected in expected_profiles.items():
            profile = profiles.get(name)
            if not isinstance(profile, dict) or (
                profile.get("model"),
                profile.get("reasoning_effort"),
            ) != expected:
                errors.append(f"profile {name} must be {expected[0]}/{expected[1]}")
            elif set(profile) != {"model", "reasoning_effort"}:
                errors.append(f"profile {name} contains unknown or missing keys")

    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 9:
        errors.append("tasks must contain exactly nine cases")
        tasks = []
    ids: list[str] = []
    difficulties: list[str] = []
    grader_hash = str((adapter or {}).get("upstream_grader_sha256", ""))
    for index, task in enumerate(tasks):
        where = f"tasks[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{where} must be an object")
            continue
        _validate_object_keys(
            task,
            where=where,
            required={
                "id",
                "title",
                "difficulty",
                "difficulty_evidence",
                "language",
                "repository",
                "upstream_base_commit",
                "capabilities",
                "allowed_patch_paths",
                "assets",
                "toolchain",
                "setup",
                "setup_cleanup",
                "checks",
            },
            optional={"windows_adapter", "windows_oracle"},
            errors=errors,
        )
        task_id = str(task.get("id", ""))
        if not TASK_ID_PATTERN.fullmatch(task_id):
            errors.append(f"{where}.id is invalid")
        ids.append(task_id)
        difficulty = str(task.get("difficulty", ""))
        if difficulty not in {"easy", "medium", "hard", "very-hard"}:
            errors.append(f"{where}.difficulty is invalid")
        difficulties.append(difficulty)
        evidence = task.get("difficulty_evidence")
        if not isinstance(evidence, dict) or evidence.get("kind") != "deepswe-v1-successful-rollouts":
            errors.append(f"{where}.difficulty_evidence is invalid")
        else:
            _validate_object_keys(
                evidence,
                where=f"{where}.difficulty_evidence",
                required={"kind", "successful_rollouts", "total_rollouts", "source"},
                optional=None,
                errors=errors,
            )
            if evidence.get("total_rollouts") != 116:
                errors.append(f"{where}.difficulty_evidence total must be 116")
            successful = evidence.get("successful_rollouts")
            if not isinstance(successful, int) or not 0 <= successful <= 116:
                errors.append(f"{where}.difficulty_evidence successful count is invalid")
            expected_url = f"https://deepswe.datacurve.ai/data/v1/tasks/{task_id}"
            if evidence.get("source") != expected_url:
                errors.append(f"{where}.difficulty_evidence source mismatch")
        if task.get("language") not in {"python", "typescript"}:
            errors.append(f"{where}.language must be python or typescript")
        if not isinstance(task.get("title"), str) or not task.get("title", "").strip():
            errors.append(f"{where}.title must be a non-empty string")
        if not str(task.get("repository", "")).startswith("https://github.com/"):
            errors.append(f"{where}.repository must be a GitHub HTTPS URL")
        if not GIT_SHA_PATTERN.fullmatch(str(task.get("upstream_base_commit", ""))):
            errors.append(f"{where}.upstream_base_commit is invalid")
        capabilities = task.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or len(capabilities) < 2
            or any(not isinstance(item, str) or not item.strip() for item in capabilities)
            or len(capabilities) != len(set(capabilities))
        ):
            errors.append(f"{where}.capabilities must contain at least two unique strings")
        allowed = task.get("allowed_patch_paths")
        if not isinstance(allowed, list) or not allowed or any(
            not isinstance(item, str) or not _safe_relative_path(item, field=where)
            for item in allowed
        ) or len(allowed) != len(set(allowed)):
            errors.append(f"{where}.allowed_patch_paths is invalid")
        assets = task.get("assets")
        if not isinstance(assets, dict) or set(assets) != set(REQUIRED_ASSETS):
            errors.append(f"{where}.assets must contain the six pinned task assets")
        else:
            for asset, digest in assets.items():
                if not HASH_PATTERN.fullmatch(str(digest)):
                    errors.append(f"{where}.assets[{asset}] is not SHA-256")
            if assets.get("tests/grader.py") != grader_hash:
                errors.append(f"{where} grader hash differs from adapter owner")
        windows_adapter = task.get("windows_adapter")
        if windows_adapter is not None:
            adapter_where = f"{where}.windows_adapter"
            if not isinstance(windows_adapter, dict):
                errors.append(f"{adapter_where} must be an object")
            else:
                _validate_object_keys(
                    windows_adapter,
                    where=adapter_where,
                    required={"path", "sha256", "patch_paths"},
                    optional=None,
                    errors=errors,
                )
                adapter_path = windows_adapter.get("path")
                if (
                    not isinstance(adapter_path, str)
                    or not _safe_relative_path(adapter_path, field=adapter_where)
                    or not adapter_path.replace("\\", "/").startswith("windows-adapters/")
                    or not adapter_path.lower().endswith(".patch")
                ):
                    errors.append(
                        f"{adapter_where}.path must be a relative windows-adapters/*.patch path"
                    )
                if not HASH_PATTERN.fullmatch(str(windows_adapter.get("sha256", ""))):
                    errors.append(f"{adapter_where}.sha256 is not SHA-256")
                patch_paths = windows_adapter.get("patch_paths")
                if (
                    not isinstance(patch_paths, list)
                    or not patch_paths
                    or any(
                        not isinstance(item, str)
                        or not _safe_relative_path(item, field=f"{adapter_where}.patch_paths")
                        for item in patch_paths
                    )
                    or len(patch_paths) != len(set(patch_paths))
                ):
                    errors.append(f"{adapter_where}.patch_paths is invalid")
        windows_oracle = task.get("windows_oracle")
        if windows_oracle is not None:
            oracle_where = f"{where}.windows_oracle"
            if not isinstance(windows_oracle, dict):
                errors.append(f"{oracle_where} must be an object")
            else:
                _validate_object_keys(
                    windows_oracle,
                    where=oracle_where,
                    required={"p2p_baseline_policy"},
                    optional=None,
                    errors=errors,
                )
                if windows_oracle.get("p2p_baseline_policy") not in {
                    "exclude-stable-skips",
                    "exclude-stable-nonpassing",
                }:
                    errors.append(f"{oracle_where}.p2p_baseline_policy is invalid")
        toolchain = task.get("toolchain")
        if not isinstance(toolchain, dict) or toolchain.get("kind") not in {
            "python",
            "node",
        }:
            errors.append(f"{where}.toolchain is invalid")
        else:
            _validate_object_keys(
                toolchain,
                where=f"{where}.toolchain",
                required={"kind", "minimum_version"},
                optional={"package_manager"},
                errors=errors,
            )
            if not isinstance(toolchain.get("minimum_version"), str) or not toolchain.get(
                "minimum_version", ""
            ).strip():
                errors.append(f"{where}.toolchain.minimum_version is invalid")
            if task.get("language") == "python" and toolchain.get("kind") != "python":
                errors.append(f"{where}.toolchain does not match language")
            elif task.get("language") == "typescript" and toolchain.get("kind") != "node":
                errors.append(f"{where}.toolchain does not match language")
            if toolchain.get("kind") == "node" and toolchain.get("package_manager") not in {
                "npm",
                "pnpm",
            }:
                errors.append(f"{where}.toolchain.package_manager is required for node")
            if toolchain.get("kind") == "python" and "package_manager" in toolchain:
                errors.append(f"{where}.toolchain.package_manager is invalid for python")
        setup = task.get("setup")
        if not isinstance(setup, list) or not setup:
            errors.append(f"{where}.setup must be non-empty")
        else:
            for command_index, command in enumerate(setup):
                if isinstance(command, dict):
                    _validate_object_keys(
                        command,
                        where=f"{where}.setup[{command_index}]",
                        required={"argv", "timeout_seconds"},
                        optional={"env"},
                        errors=errors,
                    )
                _validate_command(command, where=f"{where}.setup[{command_index}]", errors=errors)
        cleanup = task.get("setup_cleanup")
        if not isinstance(cleanup, dict) or set(cleanup) != {
            "restore_tracked",
            "remove_untracked",
        }:
            errors.append(f"{where}.setup_cleanup is invalid")
        else:
            for key in ("restore_tracked", "remove_untracked"):
                values = cleanup[key]
                if (
                    not isinstance(values, list)
                    or any(
                        not isinstance(item, str)
                        or not _safe_relative_path(item, field=f"{where}.setup_cleanup.{key}")
                        for item in values
                    )
                    or len(values) != len(set(values))
                ):
                    errors.append(f"{where}.setup_cleanup.{key} is invalid")
        checks = task.get("checks")
        if not isinstance(checks, list) or len(checks) < 2:
            errors.append(f"{where}.checks must contain at least base and new")
        else:
            check_ids: list[str] = []
            buckets: list[str] = []
            report_paths: list[str] = []
            raw_report_paths: list[str] = []
            for check_index, check in enumerate(checks):
                check_where = f"{where}.checks[{check_index}]"
                if isinstance(check, dict):
                    _validate_object_keys(
                        check,
                        where=check_where,
                        required={"id", "bucket", "argv", "timeout_seconds", "report"},
                        optional={"env", "before"},
                        errors=errors,
                    )
                _validate_command(check, where=check_where, errors=errors)
                if not isinstance(check, dict):
                    continue
                check_id = str(check.get("id", ""))
                check_ids.append(check_id)
                if not re.fullmatch(r"[a-z0-9-]+", check_id):
                    errors.append(f"{check_where}.id is invalid")
                bucket = str(check.get("bucket", ""))
                buckets.append(bucket)
                if bucket not in {"gate", "base", "new"}:
                    errors.append(f"{check_where}.bucket is invalid")
                before_commands = check.get("before", [])
                if not isinstance(before_commands, list):
                    errors.append(f"{check_where}.before must be an array")
                    before_commands = []
                for before_index, before in enumerate(before_commands):
                    if isinstance(before, dict):
                        _validate_object_keys(
                            before,
                            where=f"{check_where}.before[{before_index}]",
                            required={"argv", "timeout_seconds"},
                            optional={"env"},
                            errors=errors,
                        )
                    _validate_command(
                        before,
                        where=f"{check_where}.before[{before_index}]",
                        errors=errors,
                    )
                report = check.get("report")
                if not isinstance(report, dict):
                    errors.append(f"{check_where}.report must be an object")
                    continue
                _validate_object_keys(
                    report,
                    where=f"{check_where}.report",
                    required={"kind", "path"},
                    optional={
                        "raw_path",
                        "name",
                        "tool",
                        "fold_whitespace",
                        "node_identity_normalization",
                    },
                    errors=errors,
                )
                report_path = str(report.get("path", ""))
                if not _safe_relative_path(report_path, field=check_where):
                    errors.append(f"{check_where}.report.path is invalid")
                report_paths.append(report_path)
                kind = report.get("kind")
                if kind not in {
                    "junit",
                    "jest-json-to-ctrf",
                    "junit-to-ctrf",
                    "gate-ctrf",
                }:
                    errors.append(f"{check_where}.report.kind is invalid")
                if kind in {"jest-json-to-ctrf", "junit-to-ctrf"}:
                    raw_path = str(report.get("raw_path", ""))
                    if not _safe_relative_path(raw_path, field=check_where):
                        errors.append(f"{check_where}.report.raw_path is required")
                    elif raw_path == report_path:
                        errors.append(f"{check_where}.report.raw_path must differ from path")
                    raw_report_paths.append(raw_path)
                if kind == "gate-ctrf" and not report.get("name"):
                    errors.append(f"{check_where}.gate report requires a name")
                for optional_string in ("name", "tool"):
                    if optional_string in report and (
                        not isinstance(report[optional_string], str)
                        or not report[optional_string].strip()
                    ):
                        errors.append(
                            f"{check_where}.report.{optional_string} must be a non-empty string"
                        )
                if "fold_whitespace" in report and not isinstance(
                    report["fold_whitespace"], bool
                ):
                    errors.append(f"{check_where}.report.fold_whitespace must be boolean")
                normalization = report.get("node_identity_normalization")
                if normalization not in {None, "nfc-utf16-surrogate-replacement"}:
                    errors.append(
                        f"{check_where}.report.node_identity_normalization is invalid"
                    )
            if len(set(check_ids)) != len(check_ids):
                errors.append(f"{where}.check ids must be unique")
            if len(set(report_paths)) != len(report_paths):
                errors.append(f"{where}.report paths must be unique")
            if len(set(raw_report_paths)) != len(raw_report_paths):
                errors.append(f"{where}.raw report paths must be unique")
            if "base" not in buckets or "new" not in buckets:
                errors.append(f"{where}.checks must cover base and new buckets")
            if "gate" in buckets and buckets[0] != "gate":
                errors.append(f"{where}.gate must be the first check")

    if len(set(ids)) != len(ids):
        errors.append("task ids must be unique")
    expected_difficulties = {"easy": 2, "medium": 3, "hard": 2, "very-hard": 2}
    actual_difficulties = {name: difficulties.count(name) for name in expected_difficulties}
    if actual_difficulties != expected_difficulties:
        errors.append(f"difficulty distribution mismatch: {actual_difficulties}")

    suites = corpus.get("suites")
    if not isinstance(suites, dict) or set(suites) != {"smoke", "core", "rotation", "all"}:
        errors.append("suites must contain exactly smoke/core/rotation/all")
    else:
        for name, task_ids in suites.items():
            if not isinstance(task_ids, list) or any(
                not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id)
                for task_id in task_ids
            ):
                errors.append(f"suite {name} must be a task-id array")
            elif len(task_ids) != len(set(task_ids)):
                errors.append(f"suite {name} must be a unique array")
            elif any(task_id not in ids for task_id in task_ids):
                errors.append(f"suite {name} references unknown tasks")
        if suites.get("all") != ids:
            errors.append("suite all must preserve the task order and contain every task")
        if not set(suites.get("smoke", [])).issubset(set(suites.get("core", []))):
            errors.append("smoke must be a subset of core")
        if set(suites.get("core", [])) & set(suites.get("rotation", [])):
            errors.append("core and rotation must be disjoint")
        if set(suites.get("core", [])) | set(suites.get("rotation", [])) != set(ids):
            errors.append("core plus rotation must cover all tasks")

    assessment = corpus.get("assessment")
    if not isinstance(assessment, dict) or assessment.get("leaderboard_comparable") is not False:
        errors.append("assessment must explicitly deny official leaderboard comparability")
    else:
        _validate_object_keys(
            assessment,
            where="assessment",
            required={
                "correctness_owner",
                "reward_range",
                "dimensions",
                "composite_score",
                "leaderboard_comparable",
            },
            optional=None,
            errors=errors,
        )
        if assessment.get("composite_score") is not None:
            errors.append("assessment.composite_score must remain null")
        if assessment.get("reward_range") != [0, 1]:
            errors.append("assessment.reward_range must be [0, 1]")
        if not isinstance(assessment.get("correctness_owner"), str) or not assessment.get(
            "correctness_owner", ""
        ).strip():
            errors.append("assessment.correctness_owner must be a non-empty string")
        dimensions = assessment.get("dimensions")
        if (
            not isinstance(dimensions, list)
            or not dimensions
            or any(not isinstance(item, str) or not item.strip() for item in dimensions)
            or len(dimensions) != len(set(dimensions))
        ):
            errors.append("assessment.dimensions must be a non-empty unique string array")
    if errors:
        raise EvaluationError("invalid corpus:\n- " + "\n- ".join(errors))
    return corpus


def load_corpus(path: Path) -> dict[str, Any]:
    return validate_corpus(read_json(path.resolve()))


def task_map(corpus: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(task["id"]): dict(task) for task in corpus["tasks"]}


def require_task(corpus: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    try:
        return task_map(corpus)[task_id]
    except KeyError as exc:
        raise EvaluationError(f"unknown task: {task_id}") from exc


def require_profile(corpus: Mapping[str, Any], profile: str) -> dict[str, Any]:
    try:
        return dict(corpus["profiles"][profile])
    except KeyError as exc:
        raise EvaluationError(f"unknown profile: {profile}") from exc


def suite_task_ids(corpus: Mapping[str, Any], suite: str) -> list[str]:
    try:
        return list(corpus["suites"][suite])
    except KeyError as exc:
        raise EvaluationError(f"unknown suite: {suite}") from exc


def run_capture(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 600,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            [str(item) for item in argv],
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else None,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvaluationError(f"command failed to start or timed out: {argv[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        detail = re.sub(r"\s+", " ", detail).strip()[:600]
        raise EvaluationError(f"command failed ({result.returncode}): {argv[0]}: {detail}")
    return result


def git_command(*arguments: str | Path) -> list[str]:
    """Build a host-independent Git command for Windows-managed repositories."""
    return [*GIT_WINDOWS_PREFIX, *(str(argument) for argument in arguments)]


def git_asset_command(*arguments: str | Path) -> list[str]:
    """Build the fixed Windows projection used by pinned DeepSWE task assets."""
    return [*GIT_WINDOWS_ASSET_PREFIX, *(str(argument) for argument in arguments)]


def git_output(
    repo: Path,
    *arguments: str,
    timeout: int = 600,
    env: Mapping[str, str] | None = None,
) -> str:
    return run_capture(
        git_command("-C", repo, *arguments),
        timeout=timeout,
        env=env,
    ).stdout.decode(
        "utf-8", errors="strict"
    ).strip()


def git_asset_output(
    repo: Path,
    *arguments: str,
    timeout: int = 600,
    env: Mapping[str, str] | None = None,
) -> str:
    return run_capture(
        git_asset_command("-C", repo, *arguments),
        timeout=timeout,
        env=env,
    ).stdout.decode("utf-8", errors="strict").strip()


def git_head(repo: Path) -> str:
    value = git_output(repo, "rev-parse", "HEAD")
    if not GIT_SHA_PATTERN.fullmatch(value):
        raise EvaluationError(f"invalid Git HEAD in {repo}: {value}")
    return value


def _file_set_identity(project_root: Path, pathspecs: Sequence[str]) -> dict[str, Any]:
    result = run_capture(
        git_command(
            "-C",
            project_root,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *pathspecs,
        )
    )
    relative_paths = sorted(
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    )
    files: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = project_root / Path(relative)
        if path.is_symlink() or not path.is_file():
            raise EvaluationError(f"identity surface contains a non-regular file: {relative}")
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {"files": files}
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def candidate_surface_identity(project_root: Path) -> dict[str, Any]:
    return _file_set_identity(
        project_root.resolve(),
        [
            "global/AGENTS.md",
            "global/config.toml",
            "global/agents",
            "skills",
        ],
    )


def framework_identity(project_root: Path) -> dict[str, Any]:
    return _file_set_identity(
        project_root.resolve(),
        [
            "development/agent-evaluation/agent_eval.py",
            "development/agent-evaluation/agentbase_codex.py",
            "development/agent-evaluation/api_pricing_snapshot.json",
            "development/agent-evaluation/codex-eval-overlay.toml",
            "development/agent-evaluation/evaluation_core.py",
            "development/agent-evaluation/invoke_candidate.ps1",
            "development/agent-evaluation/vendor",
            "development/agent-evaluation/windows-adapters",
            "development/agent-evaluation/windows_verifier.py",
            "development/common/codex_runtime.py",
            "development/common/codex_cli_runtime.ps1",
            "development/common/codex_shell_environment_policy.json",
        ],
    )


def source_paths(state_root: Path, corpus: Mapping[str, Any]) -> tuple[Path, Path]:
    root = state_root.resolve() / "sources"
    deep_swe = root / f"deep-swe-{str(corpus['source']['commit'])[:12]}"
    upstreams = root / "upstreams"
    return deep_swe, upstreams


def task_asset_root(state_root: Path, corpus: Mapping[str, Any], task_id: str) -> Path:
    deep_swe, _ = source_paths(state_root, corpus)
    return deep_swe / str(corpus["source"]["task_root"]) / task_id


def windows_adapter_asset(
    project_root: Path,
    task: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]] | None:
    """Resolve, parse, and hash-check one project-owned Windows fixture adapter."""

    value = task.get("windows_adapter")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EvaluationError("task Windows adapter descriptor is invalid")
    relative = str(value.get("path", "")).replace("\\", "/")
    evaluation_root = project_root.resolve() / "development" / "agent-evaluation"
    adapter_root = project_root.resolve() / WINDOWS_ADAPTER_ROOT
    path = require_within(adapter_root, evaluation_root / Path(relative))
    if not path.is_file() or path.is_symlink():
        raise EvaluationError(f"Windows adapter is missing or not a regular file: {relative}")
    actual = sha256_file(path)
    expected = str(value.get("sha256", ""))
    if actual != expected:
        raise EvaluationError(f"Windows adapter hash mismatch: {relative}")
    try:
        parsed = run_capture(
            git_command("-C", project_root.resolve(), "apply", "--numstat", "-z", path),
            timeout=30,
        ).stdout
    except EvaluationError as exc:
        raise EvaluationError(f"Windows adapter is not a valid Git patch: {relative}: {exc}") from exc
    parsed_paths: list[str] = []
    for record in parsed.split(b"\0"):
        if not record:
            continue
        parts = record.split(b"\t", 2)
        if len(parts) != 3 or any(
            value != b"-" and not value.isdigit() for value in parts[:2]
        ):
            raise EvaluationError(f"Windows adapter numstat is invalid: {relative}")
        try:
            patch_path = parts[2].decode("utf-8", errors="strict").replace("\\", "/")
        except UnicodeDecodeError as exc:
            raise EvaluationError(f"Windows adapter path is not UTF-8: {relative}") from exc
        if not _safe_relative_path(patch_path, field=f"Windows adapter {relative}"):
            raise EvaluationError(f"Windows adapter contains an unsafe path: {patch_path}")
        parsed_paths.append(patch_path)
    declared_paths = [str(item).replace("\\", "/") for item in value.get("patch_paths", [])]
    if len(parsed_paths) != len(set(parsed_paths)):
        raise EvaluationError(f"Windows adapter repeats a patch path: {relative}")
    if sorted(parsed_paths) != sorted(declared_paths):
        raise EvaluationError(
            f"Windows adapter patch paths differ from its descriptor: {relative}: "
            f"declared={sorted(declared_paths)}, parsed={sorted(parsed_paths)}"
        )
    descriptor = {
        "path": relative,
        "sha256": actual,
        "bytes": path.stat().st_size,
        "patch_paths": declared_paths,
    }
    return path, descriptor


def verify_windows_adapter_assets(
    project_root: Path,
    corpus: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for task in corpus["tasks"]:
        resolved = windows_adapter_asset(project_root, task)
        if resolved is not None:
            verified[str(task["id"])] = resolved[1]
    return verified


def upstream_source_root(state_root: Path, corpus: Mapping[str, Any], task_id: str) -> Path:
    _, upstreams = source_paths(state_root, corpus)
    task = require_task(corpus, task_id)
    return upstreams / f"{task_id}-{str(task['upstream_base_commit'])[:12]}"


def _remove_staging(path: Path, staging_root: Path) -> None:
    remove_managed_tree(staging_root, path)


def _clone_exact_commit(
    repository: str,
    commit: str,
    destination: Path,
    process_environment: Mapping[str, str] | None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = destination.parent / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    temporary = staging_root / uuid.uuid4().hex
    try:
        run_capture(git_command("init", temporary), env=process_environment)
        git_output(temporary, "remote", "add", "origin", repository, env=process_environment)
        git_output(
            temporary,
            "fetch",
            "--depth=1",
            "origin",
            commit,
            timeout=1800,
            env=process_environment,
        )
        git_output(
            temporary,
            "checkout",
            "-B",
            "agentbase-base",
            "FETCH_HEAD",
            env=process_environment,
        )
        if (temporary / ".gitmodules").is_file():
            raise EvaluationError("selected Windows corpus does not support upstream submodules")
        git_output(temporary, "remote", "remove", "origin")
        fetch_head = temporary / ".git" / "FETCH_HEAD"
        if fetch_head.exists():
            fetch_head.unlink()
        git_output(temporary, "reflog", "expire", "--expire=now", "--all")
        git_output(temporary, "gc", "--prune=now")
        if git_head(temporary) != commit:
            raise EvaluationError(f"upstream checkout identity mismatch: {repository}")
        if destination.exists():
            raise EvaluationError(f"source destination appeared concurrently: {destination}")
        os.replace(temporary, destination)
    finally:
        _remove_staging(temporary, staging_root)


def _prepare_deep_swe(
    state_root: Path,
    corpus: Mapping[str, Any],
    process_environment: Mapping[str, str] | None,
) -> None:
    deep_swe, _ = source_paths(state_root, corpus)
    if deep_swe.exists():
        verify_deep_swe(state_root, corpus)
        return
    deep_swe.parent.mkdir(parents=True, exist_ok=True)
    staging_root = deep_swe.parent / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    temporary = staging_root / uuid.uuid4().hex
    commit = str(corpus["source"]["commit"])
    try:
        run_capture(git_asset_command("init", temporary), env=process_environment)
        git_asset_output(
            temporary,
            "remote",
            "add",
            "origin",
            str(corpus["source"]["repository"]),
            env=process_environment,
        )
        git_asset_output(
            temporary,
            "sparse-checkout",
            "init",
            "--cone",
            env=process_environment,
        )
        task_paths = [f"tasks/{task['id']}" for task in corpus["tasks"]]
        git_asset_output(
            temporary,
            "sparse-checkout",
            "set",
            *task_paths,
            env=process_environment,
        )
        git_asset_output(
            temporary,
            "fetch",
            "--depth=1",
            "origin",
            commit,
            timeout=1800,
            env=process_environment,
        )
        git_asset_output(
            temporary,
            "checkout",
            "--detach",
            "FETCH_HEAD",
            env=process_environment,
        )
        git_asset_output(temporary, "remote", "remove", "origin")
        fetch_head = temporary / ".git" / "FETCH_HEAD"
        if fetch_head.exists():
            fetch_head.unlink()
        if git_head(temporary) != commit:
            raise EvaluationError("DeepSWE checkout identity mismatch")
        if deep_swe.exists():
            raise EvaluationError(f"DeepSWE destination appeared concurrently: {deep_swe}")
        os.replace(temporary, deep_swe)
    finally:
        _remove_staging(temporary, staging_root)
    verify_deep_swe(state_root, corpus)


def verify_deep_swe(state_root: Path, corpus: Mapping[str, Any]) -> dict[str, Any]:
    deep_swe, _ = source_paths(state_root, corpus)
    if not (deep_swe / ".git").is_dir() or git_head(deep_swe) != corpus["source"]["commit"]:
        raise EvaluationError("prepared DeepSWE checkout is missing or stale")
    task_identities: dict[str, Any] = {}
    for task in corpus["tasks"]:
        task_id = str(task["id"])
        root = task_asset_root(state_root, corpus, task_id)
        actual: dict[str, str] = {}
        for relative, expected in task["assets"].items():
            path = root / Path(relative)
            if not path.is_file() or path.is_symlink():
                raise EvaluationError(f"missing pinned task asset: {task_id}/{relative}")
            digest = sha256_file(path)
            if digest != expected:
                raise EvaluationError(f"task asset hash mismatch: {task_id}/{relative}")
            actual[relative] = digest
        tree = git_output(deep_swe, "rev-parse", f"HEAD:tasks/{task_id}")
        task_identities[task_id] = {
            "tree": tree,
            "assets_sha256": sha256_bytes(canonical_bytes(actual)),
        }
    return {"path": str(deep_swe), "commit": git_head(deep_swe), "tasks": task_identities}


def verify_upstream_source(
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
) -> dict[str, Any]:
    task = require_task(corpus, task_id)
    root = upstream_source_root(state_root, corpus, task_id)
    if not (root / ".git").is_dir():
        raise EvaluationError(f"prepared upstream source is missing: {task_id}")
    head = git_head(root)
    if head != task["upstream_base_commit"]:
        raise EvaluationError(f"prepared upstream source is stale: {task_id}")
    if git_output(root, "status", "--porcelain", "--untracked-files=all"):
        raise EvaluationError(f"prepared upstream source is dirty: {task_id}")
    if git_output(root, "remote"):
        raise EvaluationError(f"prepared upstream source retains a remote: {task_id}")
    tree = git_output(root, "rev-parse", "HEAD^{tree}")
    return {"path": str(root), "commit": head, "tree": tree}


def prepare_sources(
    state_root: Path,
    corpus: Mapping[str, Any],
    task_ids: Sequence[str],
    process_environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state_root.resolve().mkdir(parents=True, exist_ok=True)
    _prepare_deep_swe(state_root, corpus, process_environment)
    upstreams: dict[str, Any] = {}
    for task_id in task_ids:
        task = require_task(corpus, task_id)
        destination = upstream_source_root(state_root, corpus, task_id)
        if not destination.exists():
            _clone_exact_commit(
                str(task["repository"]),
                str(task["upstream_base_commit"]),
                destination,
                process_environment,
            )
        upstreams[task_id] = verify_upstream_source(state_root, corpus, task_id)
    return {"deep_swe": verify_deep_swe(state_root, corpus), "upstreams": upstreams}


def prepared_task_identity(
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
) -> dict[str, Any]:
    deep = verify_deep_swe(state_root, corpus)
    upstream = verify_upstream_source(state_root, corpus, task_id)
    payload = {
        "deep_swe_commit": deep["commit"],
        "task_tree": deep["tasks"][task_id]["tree"],
        "task_assets_sha256": deep["tasks"][task_id]["assets_sha256"],
        "upstream_commit": upstream["commit"],
        "upstream_tree": upstream["tree"],
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def create_workspace(
    state_root: Path,
    work_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    relative_name: str,
) -> Path:
    ensure_disjoint_roots(state_root, work_root)
    source = upstream_source_root(state_root, corpus, task_id)
    verify_upstream_source(state_root, corpus, task_id)
    destination = require_within(work_root, work_root / relative_name)
    if destination.exists():
        raise EvaluationError(f"workspace already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_capture(
        git_command(
            "clone",
            "--local",
            "--no-hardlinks",
            source,
            destination,
        ),
        timeout=1200,
    )
    task = require_task(corpus, task_id)
    git_output(destination, "checkout", "-B", "agentbase-work", str(task["upstream_base_commit"]))
    remotes = git_output(destination, "remote")
    for remote in remotes.splitlines():
        if remote:
            git_output(destination, "remote", "remove", remote)
    hooks = destination / ".git" / "agentbase-disabled-hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    git_output(destination, "config", "core.hooksPath", str(hooks))
    exclude = destination / ".git" / "info" / "exclude"
    prior = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    additions = (
        "\n# AgentBase evaluation runtime\n"
        ".agentbase/\n"
        ".agents/skills/\n"
        ".codex/\n"
        ".agentbase-venv/\n"
        "node_modules/\n"
        "ctrf/\n"
    )
    exclude.write_text(prior.rstrip() + additions, encoding="utf-8", newline="\n")
    if git_head(destination) != task["upstream_base_commit"]:
        raise EvaluationError(f"workspace base identity mismatch: {destination}")
    return destination


def _changed_paths(workspace: Path) -> list[str]:
    tracked = git_output(workspace, "diff", "--name-only", "HEAD").splitlines()
    untracked = git_output(workspace, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path.replace("\\", "/") for path in [*tracked, *untracked] if path})


def _path_allowed(path: str, patterns: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def _validate_patch_paths(paths: Sequence[str], task: Mapping[str, Any]) -> None:
    if len(paths) > MAX_PATCH_FILES:
        raise EvaluationError(f"candidate patch touches too many files: {len(paths)}")
    disallowed = [
        path for path in paths if not _path_allowed(path, task["allowed_patch_paths"])
    ]
    if disallowed:
        raise EvaluationError(f"candidate patch touches protected paths: {disallowed}")


def _validate_index_modes(workspace: Path, paths: Sequence[str]) -> None:
    if not paths:
        return
    index = git_output(workspace, "ls-files", "-s", "--", *paths)
    unsafe_modes = [line for line in index.splitlines() if line.startswith(("120000 ", "160000 "))]
    if unsafe_modes:
        raise EvaluationError("candidate patch contains a symlink or submodule")


def validate_staged_patch_scope(
    workspace: Path,
    task: Mapping[str, Any],
) -> list[str]:
    paths = sorted(
        path.replace("\\", "/")
        for path in git_output(workspace, "diff", "--cached", "--name-only", "HEAD").splitlines()
        if path
    )
    _validate_patch_paths(paths, task)
    _validate_index_modes(workspace, paths)
    return paths


def capture_candidate_patch(workspace: Path, task: Mapping[str, Any], output: Path) -> dict[str, Any]:
    paths = _changed_paths(workspace)
    _validate_patch_paths(paths, task)
    if paths:
        run_capture(git_command("-C", workspace, "add", "-A", "--", *paths))
    patch = run_capture(
        git_command(
            "-C",
            workspace,
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "HEAD",
        )
    ).stdout
    if len(patch) > MAX_PATCH_BYTES:
        raise EvaluationError(f"candidate patch exceeds {MAX_PATCH_BYTES} bytes")
    _validate_index_modes(workspace, paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(patch)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    return {
        "path": str(output.resolve()),
        "sha256": sha256_bytes(patch),
        "bytes": len(patch),
        "files": paths,
    }


def normalize_upstream_patch(value: bytes) -> tuple[bytes, int, int]:
    """Project pinned Windows patch bytes to canonical Git input without changing hunks."""

    lines = value.splitlines(keepends=True)
    normalized: list[bytes] = []
    old_remaining = 0
    new_remaining = 0
    inserted_prefixes = 0
    normalized_crlf_endings = 0
    header_pattern = re.compile(
        rb"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@"
    )
    for line_number, line in enumerate(lines, start=1):
        if line.endswith(b"\r\n"):
            content, ending = line[:-2], b"\n"
            normalized_crlf_endings += 1
        elif line.endswith(b"\n"):
            content, ending = line[:-1], b"\n"
        elif line.endswith(b"\r"):
            raise EvaluationError(
                f"upstream patch uses an unsupported bare CR ending at line {line_number}"
            )
        else:
            content, ending = line, b""
        line = content + ending
        header = header_pattern.match(content)
        if header:
            if old_remaining or new_remaining:
                raise EvaluationError(
                    f"upstream patch hunk ended early before line {line_number}"
                )
            old_remaining = int(header.group(1) or b"1")
            new_remaining = int(header.group(2) or b"1")
            normalized.append(line)
            continue
        if old_remaining or new_remaining:
            if content == b"":
                content = b" "
                line = content + ending
                inserted_prefixes += 1
            prefix = content[:1]
            if prefix == b" ":
                old_remaining -= 1
                new_remaining -= 1
            elif prefix == b"-":
                old_remaining -= 1
            elif prefix == b"+":
                new_remaining -= 1
            elif prefix != b"\\":
                raise EvaluationError(
                    f"upstream patch hunk has an invalid line prefix at line {line_number}"
                )
            if old_remaining < 0 or new_remaining < 0:
                raise EvaluationError(
                    f"upstream patch hunk exceeds its declared size at line {line_number}"
                )
        normalized.append(line)
    if old_remaining or new_remaining:
        raise EvaluationError("upstream patch ends before its declared hunk size")
    return b"".join(normalized), inserted_prefixes, normalized_crlf_endings


def apply_git_patch(
    workspace: Path,
    patch: Path,
    *,
    allow_empty: bool = False,
    normalize_upstream: bool = False,
) -> dict[str, Any]:
    if not patch.is_file():
        raise EvaluationError(f"patch does not exist: {patch}")
    source = patch.read_bytes()
    if not source:
        if allow_empty:
            return {
                "source_sha256": sha256_bytes(source),
                "applied_sha256": sha256_bytes(source),
                "bytes": 0,
                "blank_context_prefixes_inserted": 0,
                "crlf_line_endings_normalized": 0,
            }
        raise EvaluationError(f"patch is empty: {patch}")
    applied, inserted, normalized_crlf = (
        normalize_upstream_patch(source)
        if normalize_upstream
        else (source, 0, 0)
    )
    argv = git_command(
        "-C",
        workspace,
        "apply",
        "--index",
        "--binary",
        "--whitespace=nowarn",
    )
    if normalize_upstream:
        run_capture([*argv, "-"], input_bytes=applied)
    else:
        run_capture([*argv, str(patch.resolve())])
    return {
        "source_sha256": sha256_bytes(source),
        "applied_sha256": sha256_bytes(applied),
        "bytes": len(applied),
        "blank_context_prefixes_inserted": inserted,
        "crlf_line_endings_normalized": normalized_crlf,
    }


def apply_windows_adapter_baseline(
    project_root: Path,
    workspace: Path,
    task: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Apply one pinned test-fixture adapter and commit it as the workspace baseline."""

    resolved = windows_adapter_asset(project_root, task)
    if resolved is None:
        return None
    adapter_path, asset = resolved
    if git_output(workspace, "status", "--porcelain", "--untracked-files=all"):
        raise EvaluationError("Windows adapter requires a clean prepared workspace")
    base_commit = git_head(workspace)
    patch = apply_git_patch(workspace, adapter_path)
    paths = sorted(
        path.replace("\\", "/")
        for path in git_output(workspace, "diff", "--cached", "--name-only", "HEAD").splitlines()
        if path
    )
    expected_paths = sorted(str(path).replace("\\", "/") for path in asset["patch_paths"])
    if paths != expected_paths:
        raise EvaluationError(
            f"Windows adapter patch paths differ from its contract: {paths} != {expected_paths}"
        )
    _validate_index_modes(workspace, paths)
    commit_environment = dict(os.environ)
    commit_environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
    )
    run_capture(
        git_command(
            "-C",
            workspace,
            "-c",
            "user.name=AgentBase Windows SWE",
            "-c",
            "user.email=agentbase@example.invalid",
            "commit",
            "--no-gpg-sign",
            "--quiet",
            "-m",
            "Apply pinned AgentBase Windows test adapter",
        ),
        env=commit_environment,
    )
    if git_output(workspace, "status", "--porcelain", "--untracked-files=all"):
        raise EvaluationError("Windows adapter baseline is not clean after commit")
    return {
        **asset,
        **patch,
        "base_commit": base_commit,
        "baseline_commit": git_head(workspace),
        "paths": paths,
    }


def qualification_base_identity(
    project_root: Path,
    corpus_path: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
) -> dict[str, Any]:
    task = require_task(corpus, task_id)
    adapter = windows_adapter_asset(project_root, task)
    payload = {
        "schema": "agentbase.windows-swe-qualification-base/v1",
        "corpus_sha256": sha256_file(corpus_path.resolve()),
        "framework_identity_sha256": framework_identity(project_root)["identity_sha256"],
        "prepared_task_identity": prepared_task_identity(state_root, corpus, task_id),
        "task_id": task_id,
        "adapter": dict(corpus["adapter"]),
        "windows_adapter": adapter[1] if adapter is not None else None,
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def candidate_run_identity(
    *,
    project_root: Path,
    corpus_path: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    profile_name: str,
    qualification_receipt: Mapping[str, Any],
    dependency_identity: Mapping[str, Any],
    runtime_environment: Mapping[str, Any],
    runtime_tools: Mapping[str, Any],
    config_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    profile = require_profile(corpus, profile_name)
    payload = {
        "schema": "agentbase.windows-swe-candidate-identity/v1",
        "corpus_sha256": sha256_file(corpus_path.resolve()),
        "candidate_surface_identity_sha256": candidate_surface_identity(project_root)[
            "identity_sha256"
        ],
        "framework_identity_sha256": framework_identity(project_root)["identity_sha256"],
        "task_id": task_id,
        "profile": profile_name,
        "model": profile["model"],
        "reasoning_effort": profile["reasoning_effort"],
        "qualification_receipt_sha256": qualification_receipt["receipt_sha256"],
        "dependency_identity_sha256": dependency_identity["identity_sha256"],
        "runtime_environment": dict(runtime_environment),
        "runtime_tools": dict(runtime_tools),
        "candidate_config": dict(config_descriptor),
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def validate_identity(identity: Any, *, schema: str | None = None) -> dict[str, Any]:
    if not isinstance(identity, dict):
        raise EvaluationError("identity must be an object")
    if schema is not None and identity.get("schema") != schema:
        raise EvaluationError(f"identity schema mismatch: {identity.get('schema')}")
    value = dict(identity)
    expected = str(value.pop("identity_sha256", ""))
    actual = sha256_bytes(canonical_bytes(value))
    if not HASH_PATTERN.fullmatch(expected) or expected != actual:
        raise EvaluationError("identity hash mismatch")
    return dict(identity)


def with_receipt_hash(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = sha256_bytes(canonical_bytes(value))
    return value


def validate_receipt(receipt: Any, *, schema: str | None = None) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise EvaluationError("receipt must be an object")
    if schema is not None and receipt.get("schema") != schema:
        raise EvaluationError(f"receipt schema mismatch: {receipt.get('schema')}")
    expected = str(receipt.get("receipt_sha256", ""))
    actual = with_receipt_hash(receipt)["receipt_sha256"]
    if not HASH_PATTERN.fullmatch(expected) or expected != actual:
        raise EvaluationError("receipt hash mismatch")
    return dict(receipt)


def write_immutable_receipt(path: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = with_receipt_hash(receipt)
    if path.exists():
        existing = validate_receipt(read_json(path))
        if canonical_bytes(existing) != canonical_bytes(value):
            raise EvaluationError(f"immutable receipt conflict: {path}")
        return existing
    write_json_atomic(path, value)
    return value


def qualification_receipt_dir(state_root: Path, task_id: str) -> Path:
    return state_root.resolve() / "qualifications" / task_id


def candidate_receipt_dir(state_root: Path, task_id: str, profile: str) -> Path:
    return state_root.resolve() / "results" / task_id / profile


def find_qualification_receipts(
    state_root: Path,
    task_id: str,
    base_identity_sha256: str,
) -> list[dict[str, Any]]:
    root = qualification_receipt_dir(state_root, task_id)
    if not root.is_dir():
        return []
    receipts: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), reverse=True):
        receipt = validate_receipt(read_json(path))
        if receipt.get("schema") != QUALIFICATION_SCHEMA:
            continue
        if receipt.get("base_identity_sha256") == base_identity_sha256:
            receipts.append(receipt)
    return receipts


def find_matching_qualification(
    receipts: Sequence[Mapping[str, Any]],
    dependency_identity_sha256: str,
    verifier_runtime_identity_sha256: str,
) -> dict[str, Any] | None:
    for receipt in receipts:
        if (
            receipt.get("dependency_identity_sha256") == dependency_identity_sha256
            and receipt.get("verifier_runtime_identity_sha256")
            == verifier_runtime_identity_sha256
        ):
            return dict(receipt)
    return None


def new_attempt(
    state_root: Path,
    *,
    task_id: str,
    profile: str,
    retry_reason: str | None,
) -> tuple[str, Path, dict[str, Any]]:
    attempt_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    root = state_root.resolve() / "attempts" / attempt_id
    root.mkdir(parents=True, exist_ok=False)
    attempt = {
        "schema": "agentbase.windows-swe-attempt/v1",
        "attempt_id": attempt_id,
        "task_id": task_id,
        "profile": profile,
        "status": "registered",
        "stage": "registered",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "retry_reason": retry_reason,
    }
    write_json_atomic(root / "attempt.json", attempt)
    return attempt_id, root, attempt


def update_attempt(root: Path, attempt: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    value = dict(attempt)
    value.update(changes)
    value["updated_at"] = utc_now()
    write_json_atomic(root / "attempt.json", value)
    return value


def load_attempt(state_root: Path, attempt_id: str) -> tuple[Path, dict[str, Any]]:
    root = require_within(state_root.resolve(), state_root.resolve() / "attempts" / attempt_id)
    return root, dict(read_json(root / "attempt.json"))


def enforce_retry_policy(
    state_root: Path,
    candidate_identity_sha256: str,
    retry_reason: str | None,
) -> None:
    attempts_root = state_root.resolve() / "attempts"
    failures = 0
    recoverable_attempts: list[str] = []
    if attempts_root.is_dir():
        for path in attempts_root.glob("*/attempt.json"):
            try:
                attempt = read_json(path)
            except EvaluationError:
                continue
            if attempt.get("candidate_identity_sha256") == candidate_identity_sha256:
                if attempt.get("stage") in RECOVERABLE_ATTEMPT_STAGES:
                    recoverable_attempts.append(str(attempt.get("attempt_id", path.parent.name)))
                if attempt.get("status") == "infrastructure-failed":
                    failures += 1
    if recoverable_attempts:
        attempt_ids = ", ".join(sorted(recoverable_attempts))
        raise PreconditionError(
            "a completed candidate already has recoverable output; use recover --attempt-id "
            + attempt_ids
        )
    if failures >= 2:
        raise EvaluationError("infrastructure retry limit reached for this unchanged identity")
    if failures == 1 and not retry_reason:
        raise EvaluationError("a bounded infrastructure retry requires --retry-reason")


class CaseLock(AbstractContextManager["CaseLock"]):
    def __init__(self, state_root: Path, key: str) -> None:
        digest = sha256_bytes(key.encode("utf-8"))[:24]
        self.path = state_root.resolve() / "locks" / f"{digest}.lock"
        self.key = key
        self.owner_token = uuid.uuid4().hex
        self._owned = False

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                # Access denied proves that the PID exists; invalid parameters prove it does not.
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _reclaim_stale_lock(self) -> bool:
        try:
            with self.path.open("rb") as handle:
                stat_before = os.fstat(handle.fileno())
                raw = handle.read(16 * 1024)
        except FileNotFoundError:
            return True
        try:
            value = json.loads(raw.decode("utf-8"))
            pid = int(value["pid"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            # A writer can briefly expose an empty file after O_EXCL. Only an old malformed
            # lock is recoverable; a recent one remains conservatively owned.
            if time.time() - stat_before.st_mtime < 60:
                return False
            pid = -1
        if self._pid_is_running(pid):
            return False
        try:
            stat_now = self.path.stat()
        except FileNotFoundError:
            return True
        identity_before = (stat_before.st_dev, stat_before.st_ino, stat_before.st_mtime_ns, stat_before.st_size)
        identity_now = (stat_now.st_dev, stat_now.st_ino, stat_now.st_mtime_ns, stat_now.st_size)
        if identity_now != identity_before:
            return True
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return True

    def __enter__(self) -> "CaseLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "created_at": utc_now(),
                "key": self.key,
                "owner_token": self.owner_token,
            }
        )
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                if attempt == 0 and self._reclaim_stale_lock():
                    continue
                raise EvaluationError(f"evaluation case is already locked: {self.path}") from exc
            try:
                os.write(descriptor, payload.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._owned = True
            return self
        raise EvaluationError(f"evaluation case is already locked: {self.path}")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._owned:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and value.get("owner_token") == self.owner_token:
                    self.path.unlink()
            except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                # Never delete a lock whose current owner cannot be proven.
                pass
            self._owned = False


def bounded_text(value: str, maximum: int = 600) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= maximum:
        return normalized
    half = (maximum - 5) // 2
    return normalized[:half] + " ... " + normalized[-half:]


def elapsed_seconds(started: float) -> float:
    return round(time.monotonic() - started, 3)
