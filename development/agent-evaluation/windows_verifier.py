"""Windows-native task setup, held-out verification, and DeepSWE grading."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from agentbase_codex import stage_verifier_home
from evaluation_core import (
    EvaluationError,
    apply_git_patch,
    bounded_text,
    canonical_bytes,
    create_workspace,
    elapsed_seconds,
    git_output,
    read_json,
    require_task,
    require_within,
    run_capture,
    sha256_bytes,
    sha256_file,
    task_asset_root,
    utc_now,
    validate_staged_patch_scope,
    write_immutable_receipt,
    write_json_atomic,
)


def _resolve_application(*names: str) -> Path:
    for name in names:
        value = shutil.which(name)
        if value:
            return Path(value).resolve()
    raise EvaluationError(f"required executable not found: {names[0]}")


def _version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not match:
        raise EvaluationError(f"cannot parse tool version: {bounded_text(text, 100)}")
    return tuple(int(part or 0) for part in match.groups())


def _ensure_minimum_version(executable: Path, minimum: str) -> str:
    result = run_capture([str(executable), "--version"], timeout=60, check=False)
    if result.returncode != 0:
        raise EvaluationError(f"cannot read tool version: {executable}")
    text = bounded_text(
        (result.stdout + result.stderr).decode("utf-8", errors="replace"),
        200,
    )
    if _version_tuple(text) < _version_tuple(minimum):
        raise EvaluationError(f"{executable.name} {text} is older than {minimum}")
    return text


def resolve_task_tools(task: Mapping[str, Any], workspace: Path) -> dict[str, str]:
    toolchain = task["toolchain"]
    if toolchain["kind"] == "python":
        if sys.version_info < (3, 11):
            raise EvaluationError("AgentBase Windows SWE requires Python 3.11 or newer")
        python = workspace / ".agentbase-venv" / "Scripts" / "python.exe"
        return {
            "python": str(python.resolve()),
            "workspace": str(workspace.resolve()),
            "npm": str(_resolve_application("npm.cmd", "npm.exe")),
            "pnpm": str(_resolve_application("pnpm.cmd", "pnpm.exe"))
            if task["toolchain"].get("package_manager") == "pnpm"
            else "pnpm.cmd",
        }
    node = _resolve_application("node.exe", "node")
    _ensure_minimum_version(node, str(toolchain["minimum_version"]))
    npm = _resolve_application("npm.cmd", "npm.exe")
    pnpm = (
        _resolve_application("pnpm.cmd", "pnpm.exe")
        if toolchain.get("package_manager") == "pnpm"
        else Path("pnpm.cmd")
    )
    return {
        "python": str(Path(sys.executable).resolve()),
        "workspace": str(workspace.resolve()),
        "node": str(node),
        "npm": str(npm),
        "pnpm": str(pnpm),
    }


def _expanded_argv(
    command: Mapping[str, Any],
    values: Mapping[str, str],
    *,
    report: Path | None = None,
    raw_report: Path | None = None,
) -> list[str]:
    replacements = dict(values)
    replacements["report"] = str(report.resolve()) if report else ""
    replacements["raw_report"] = str(raw_report.resolve()) if raw_report else ""
    try:
        return [str(argument).format_map(replacements) for argument in command["argv"]]
    except KeyError as exc:
        raise EvaluationError(f"unknown command placeholder: {exc}") from exc


def _command_environment(
    base_environment: Mapping[str, str],
    command: Mapping[str, Any],
) -> dict[str, str]:
    environment = dict(base_environment)
    environment.update(
        {
            "NO_COLOR": "1",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    for key, value in command.get("env", {}).items():
        environment[str(key)] = str(value)
    return environment


def _run_logged(
    argv: Sequence[str],
    *,
    workspace: Path,
    environment: Mapping[str, str],
    timeout: int,
    log_path: Path,
    check: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            [str(item) for item in argv],
            cwd=str(workspace.resolve()),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvaluationError(f"command failed to start or timed out: {argv[0]}: {exc}") from exc
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(result.stdout)
    record = {
        "argv": list(argv),
        "exit_code": result.returncode,
        "duration_seconds": elapsed_seconds(started),
        "log_path": str(log_path.resolve()),
        "log_sha256": sha256_file(log_path),
        "log_bytes": log_path.stat().st_size,
    }
    if check and result.returncode != 0:
        detail = bounded_text(result.stdout.decode("utf-8", errors="replace"), 700)
        raise EvaluationError(f"command failed ({result.returncode}): {argv[0]}: {detail}")
    return record


def _restore_setup_baseline(task: Mapping[str, Any], workspace: Path) -> None:
    cleanup = task["setup_cleanup"]
    restore = list(cleanup["restore_tracked"])
    if restore:
        run_capture(["git.exe", "-C", str(workspace), "checkout", "HEAD", "--", *restore])
    for relative in cleanup["remove_untracked"]:
        target = require_within(workspace, workspace / Path(relative))
        if target.exists():
            if target.is_dir():
                raise EvaluationError(f"setup cleanup expected a file, got directory: {relative}")
            target.unlink()
    tracked = git_output(workspace, "status", "--porcelain", "--untracked-files=no")
    if tracked:
        raise EvaluationError(f"dependency setup modified tracked source: {bounded_text(tracked, 500)}")


def prepare_dependencies(
    task: Mapping[str, Any],
    workspace: Path,
    artifact_root: Path,
    network_environment: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    logs = artifact_root.resolve() / "setup-logs"
    logs.mkdir(parents=True, exist_ok=True)
    if task["toolchain"]["kind"] == "python":
        _run_logged(
            [str(Path(sys.executable).resolve()), "-m", "venv", ".agentbase-venv"],
            workspace=workspace,
            environment=network_environment,
            timeout=300,
            log_path=logs / "venv.log",
            check=True,
        )
    values = resolve_task_tools(task, workspace)
    for index, command in enumerate(task["setup"]):
        _run_logged(
            _expanded_argv(command, values),
            workspace=workspace,
            environment=_command_environment(network_environment, command),
            timeout=int(command["timeout_seconds"]),
            log_path=logs / f"{index:02d}.log",
            check=True,
        )
    _restore_setup_baseline(task, workspace)
    identity = dependency_identity(task, workspace, values)
    return identity, values


def dependency_identity(
    task: Mapping[str, Any],
    workspace: Path,
    values: Mapping[str, str],
) -> dict[str, Any]:
    manifests: list[dict[str, Any]] = []
    for relative in (
        "pyproject.toml",
        "setup.cfg",
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "node_modules/.package-lock.json",
        "node_modules/.modules.yaml",
    ):
        path = workspace / Path(relative)
        if path.is_file():
            manifests.append(
                {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            )
    if task["toolchain"]["kind"] == "python":
        inventory_result = run_capture(
            [values["python"], "-m", "pip", "freeze", "--all"],
            cwd=workspace,
            timeout=180,
        )
    else:
        package_manager = task["toolchain"].get("package_manager")
        command = (
            [values["pnpm"], "list", "--depth", "0", "--json"]
            if package_manager == "pnpm"
            else [values["npm"], "ls", "--depth=0", "--json"]
        )
        inventory_result = run_capture(command, cwd=workspace, timeout=180, check=False)
        if not inventory_result.stdout.strip():
            raise EvaluationError("package dependency inventory is empty")
    inventory_text = inventory_result.stdout.decode("utf-8", errors="replace").replace(
        "\r\n", "\n"
    )
    for spelling in {
        str(workspace.resolve()),
        str(workspace.resolve()).replace("\\", "/"),
    }:
        inventory_text = re.sub(re.escape(spelling), "<workspace>", inventory_text, flags=re.IGNORECASE)
    inventory = inventory_text.encode("utf-8")
    identity_tool_names = (
        ["python"]
        if task["toolchain"]["kind"] == "python"
        else ["node", str(task["toolchain"]["package_manager"])]
    )
    tool_identities: dict[str, Any] = {}
    for name in identity_tool_names:
        path = Path(str(values[name])).resolve()
        if not path.is_file():
            raise EvaluationError(f"dependency tool is not a regular file: {name}")
        version_result = run_capture([str(path), "--version"], cwd=workspace, timeout=60)
        version = bounded_text(
            (version_result.stdout + version_result.stderr).decode(
                "utf-8", errors="replace"
            ),
            200,
        )
        if not version:
            raise EvaluationError(f"dependency tool returned an empty version: {name}")
        tool_identities[name] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "version": version,
        }
    payload = {
        "toolchain": dict(task["toolchain"]),
        "tools": tool_identities,
        "manifests": manifests,
        "inventory_sha256": sha256_bytes(inventory),
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def _sandbox_environment(base_environment: Mapping[str, str], codex_home: Path) -> dict[str, str]:
    environment = dict(base_environment)
    for key in list(environment):
        if key.upper() in {
            "ALL_PROXY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "OPENAI_API_KEY",
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
            "AZURE_OPENAI_API_KEY",
        } or key.upper().startswith("CODEX_"):
            environment.pop(key, None)
    environment["CODEX_HOME"] = str(codex_home.resolve())
    environment["NO_COLOR"] = "1"
    environment["PYTHONUTF8"] = "1"
    return environment


def _run_sandboxed_check(
    *,
    codex_executable: Path,
    codex_home: Path,
    permission_profile: str,
    argv: Sequence[str],
    workspace: Path,
    base_environment: Mapping[str, str],
    command_environment: Mapping[str, str],
    timeout: int,
    log_path: Path,
) -> dict[str, Any]:
    environment = _sandbox_environment(base_environment, codex_home)
    environment.update(command_environment)
    sandbox_argv = [
        str(codex_executable.resolve()),
        "sandbox",
        "-P",
        permission_profile,
        "-C",
        str(workspace.resolve()),
        "--",
        *[str(item) for item in argv],
    ]
    return _run_logged(
        sandbox_argv,
        workspace=workspace,
        environment=environment,
        timeout=timeout,
        log_path=log_path,
        check=False,
    )


def _ctrf_document(tests: Sequence[Mapping[str, Any]], tool: str) -> dict[str, Any]:
    normalized = [dict(test) for test in tests]
    passed = sum(test.get("status") == "passed" for test in normalized)
    failed = sum(test.get("status") == "failed" for test in normalized)
    skipped = sum(test.get("status") == "skipped" for test in normalized)
    return {
        "reportFormat": "CTRF",
        "specVersion": "1.0.0",
        "results": {
            "tool": {"name": tool},
            "summary": {
                "tests": len(normalized),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": 0,
            },
            "tests": normalized,
        },
    }


def convert_jest_json(raw_path: Path, output_path: Path, tool: str = "jest") -> None:
    tests: list[dict[str, Any]] = []
    try:
        document = read_json(raw_path)
    except EvaluationError:
        return
    for suite in document.get("testResults", []):
        for assertion in suite.get("assertionResults", []):
            name = str(assertion.get("fullName") or assertion.get("title") or "").strip()
            if not name:
                continue
            raw_status = str(assertion.get("status", "")).lower()
            status = "passed" if raw_status == "passed" else "skipped" if raw_status in {
                "pending",
                "skipped",
                "todo",
            } else "failed"
            row: dict[str, Any] = {"name": name, "status": status}
            failures = assertion.get("failureMessages")
            if status == "failed" and isinstance(failures, list):
                row["message"] = "\n".join(str(item) for item in failures).strip()
            tests.append(row)
    write_json_atomic(output_path, _ctrf_document(tests, tool))


def _junit_status(testcase: ET.Element) -> tuple[str, str]:
    status = "passed"
    message = ""
    for child in testcase:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in {"failure", "error"}:
            parts = [(child.get("message") or "").strip(), (child.text or "").strip()]
            return "failed", "\n".join(part for part in parts if part)
        if tag == "skipped":
            status = "skipped"
    return status, message


def convert_junit_to_ctrf(
    raw_path: Path,
    output_path: Path,
    *,
    tool: str,
    fold_whitespace: bool = False,
) -> None:
    try:
        root = ET.parse(raw_path).getroot()
    except (OSError, ET.ParseError):
        return
    tests: list[dict[str, Any]] = []
    for testcase in root.iter():
        if testcase.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        name = (testcase.attrib.get("name", "") or "").strip()
        classname = (testcase.attrib.get("classname", "") or "").strip()
        if not name:
            continue
        full_name = f"{classname}: {name}" if classname else name
        if fold_whitespace:
            full_name = re.sub(r"\r\n|[\t\n\r]", " ", full_name).strip()
        status, message = _junit_status(testcase)
        row: dict[str, Any] = {"name": full_name, "status": status}
        if message:
            row["message"] = message
        tests.append(row)
    write_json_atomic(output_path, _ctrf_document(tests, tool))


def write_gate_ctrf(path: Path, *, name: str, tool: str, exit_code: int) -> None:
    status = "passed" if exit_code == 0 else "failed"
    write_json_atomic(
        path,
        _ctrf_document([{"name": name, "status": status, "duration": 0}], tool),
    )


def _materialize_report(report: Mapping[str, Any], reports_root: Path, exit_code: int) -> None:
    kind = report["kind"]
    output = reports_root / str(report["path"])
    raw = reports_root / str(report.get("raw_path", report["path"]))
    if kind == "junit":
        return
    if kind == "gate-ctrf":
        write_gate_ctrf(
            output,
            name=str(report["name"]),
            tool=str(report.get("tool", "gate")),
            exit_code=exit_code,
        )
    elif kind == "jest-json-to-ctrf":
        convert_jest_json(raw, output, str(report.get("tool", "jest")))
    elif kind == "junit-to-ctrf":
        convert_junit_to_ctrf(
            raw,
            output,
            tool=str(report.get("tool", "junit")),
            fold_whitespace=bool(report.get("fold_whitespace", False)),
        )
    else:
        raise EvaluationError(f"unsupported report adapter: {kind}")


def run_checks(
    *,
    task: Mapping[str, Any],
    workspace: Path,
    artifact_root: Path,
    values: Mapping[str, str],
    codex_executable: Path,
    codex_home: Path,
    permission_profile: str,
    base_environment: Mapping[str, str],
) -> list[dict[str, Any]]:
    reports_root = artifact_root.resolve() / "reports"
    logs_root = artifact_root.resolve() / "check-logs"
    reports_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    gate_failed = False
    for index, check in enumerate(task["checks"]):
        report = check["report"]
        report_path = reports_root / str(report["path"])
        raw_path = reports_root / str(report.get("raw_path", report["path"]))
        if gate_failed:
            records.append({"id": check["id"], "status": "skipped-after-gate"})
            continue
        for before_index, before in enumerate(check.get("before", [])):
            before_record = _run_sandboxed_check(
                codex_executable=codex_executable,
                codex_home=codex_home,
                permission_profile=permission_profile,
                argv=_expanded_argv(before, values),
                workspace=workspace,
                base_environment=base_environment,
                command_environment=_command_environment({}, before),
                timeout=int(before["timeout_seconds"]),
                log_path=logs_root / f"{index:02d}-{before_index:02d}-before.log",
            )
            if before_record["exit_code"] != 0:
                raise EvaluationError(f"verifier preparation failed before {check['id']}")
        argv = _expanded_argv(check, values, report=report_path, raw_report=raw_path)
        record = _run_sandboxed_check(
            codex_executable=codex_executable,
            codex_home=codex_home,
            permission_profile=permission_profile,
            argv=argv,
            workspace=workspace,
            base_environment=base_environment,
            command_environment=_command_environment({}, check),
            timeout=int(check["timeout_seconds"]),
            log_path=logs_root / f"{index:02d}-{check['id']}.log",
        )
        record["id"] = check["id"]
        record["bucket"] = check["bucket"]
        _materialize_report(report, reports_root, int(record["exit_code"]))
        record["report_path"] = str(report_path)
        records.append(record)
        if check["bucket"] == "gate" and record["exit_code"] != 0:
            gate_failed = True
    return records


def grade_reports(
    *,
    task_assets: Path,
    task: Mapping[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    grader = task_assets / "tests" / "grader.py"
    config_source = task_assets / "tests" / "config.json"
    if sha256_file(grader) != task["assets"]["tests/grader.py"]:
        raise EvaluationError("pinned DeepSWE grader identity changed")
    config = copy.deepcopy(read_json(config_source))
    reports_root = artifact_root.resolve() / "reports"
    reports = [str((reports_root / check["report"]["path"]).resolve()) for check in task["checks"]]
    config["grade"]["reports"] = reports
    config_root = artifact_root.resolve() / "grader-input"
    config_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(config_root / "config.json", config)
    verifier_root = artifact_root.resolve() / "grader-output"
    verifier_root.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "TESTS_DIR": str(config_root),
            "VERIFIER_DIR": str(verifier_root),
            "ARTIFACTS_DIR": str(artifact_root.resolve()),
            "PYTHONUTF8": "1",
            "NO_COLOR": "1",
        }
    )
    record = _run_logged(
        [str(Path(sys.executable).resolve()), str(grader.resolve()), "grade"],
        workspace=artifact_root,
        environment=environment,
        timeout=120,
        log_path=artifact_root / "grader.log",
        check=True,
    )
    reward_path = verifier_root / "reward.json"
    ctrf_path = verifier_root / "ctrf.json"
    reward = read_json(reward_path)
    if reward.get("reward") not in {0, 1}:
        raise EvaluationError("DeepSWE grader returned an invalid reward")
    for key in ("f2p_total", "f2p_passed", "p2p_total", "p2p_passed"):
        if not isinstance(reward.get(key), int):
            raise EvaluationError(f"DeepSWE grader omitted {key}")
    if not ctrf_path.is_file():
        raise EvaluationError("DeepSWE grader produced no canonical CTRF")
    return {
        "reward": reward,
        "reward_sha256": sha256_file(reward_path),
        "ctrf_sha256": sha256_file(ctrf_path),
        "grader_log_sha256": record["log_sha256"],
        "grader_sha256": sha256_file(grader),
    }


def verify_patch(
    *,
    project_root: Path,
    state_root: Path,
    work_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    run_name: str,
    patch_kind: str,
    candidate_patch: Path | None,
    artifact_root: Path,
    network_environment: Mapping[str, str],
    codex_executable: Path,
    retain_workspace: bool = False,
) -> dict[str, Any]:
    if patch_kind not in {"noop", "reference", "candidate"}:
        raise EvaluationError(f"unsupported verifier patch kind: {patch_kind}")
    task = require_task(corpus, task_id)
    task_assets = task_asset_root(state_root, corpus, task_id)
    workspace = create_workspace(
        state_root,
        work_root,
        corpus,
        task_id,
        f"{run_name}/verifier-{patch_kind}",
    )
    started = time.monotonic()
    result: dict[str, Any]
    try:
        dependency, values = prepare_dependencies(
            task,
            workspace,
            artifact_root,
            network_environment,
        )
        applied_patches: list[dict[str, Any]] = []
        if patch_kind == "reference":
            reference_descriptor = apply_git_patch(
                workspace,
                task_assets / "solution" / "solution.patch",
                normalize_upstream=True,
            )
            reference_descriptor["paths"] = validate_staged_patch_scope(workspace, task)
            applied_patches.append(
                {
                    "kind": "reference",
                    **reference_descriptor,
                }
            )
        elif patch_kind == "candidate":
            if candidate_patch is None:
                raise EvaluationError("candidate verification requires a patch")
            candidate_descriptor = apply_git_patch(
                workspace,
                candidate_patch,
                allow_empty=True,
            )
            candidate_descriptor["paths"] = validate_staged_patch_scope(workspace, task)
            applied_patches.append(
                {
                    "kind": "candidate",
                    **candidate_descriptor,
                }
            )
        applied_patches.append(
            {
                "kind": "hidden-tests",
                **apply_git_patch(
                    workspace,
                    task_assets / "tests" / "test.patch",
                    normalize_upstream=True,
                ),
            }
        )
        verifier_home = stage_verifier_home(artifact_root, corpus)
        checks = run_checks(
            task=task,
            workspace=workspace,
            artifact_root=artifact_root,
            values=values,
            codex_executable=codex_executable,
            codex_home=verifier_home,
            permission_profile=str(corpus["codex"]["verifier_permission_profile"]),
            base_environment=network_environment,
        )
        grade = grade_reports(task_assets=task_assets, task=task, artifact_root=artifact_root)
        result = {
            "schema": "agentbase.windows-swe-verifier-result/v1",
            "task_id": task_id,
            "patch_kind": patch_kind,
            "created_at": utc_now(),
            "duration_seconds": elapsed_seconds(started),
            "workspace": str(workspace.resolve()),
            "dependency_identity": dependency,
            "applied_patches": applied_patches,
            "checks": checks,
            "grade": grade,
        }
        return write_immutable_receipt(
            artifact_root.resolve() / "verifier-result.json",
            result,
        )
    finally:
        if not retain_workspace and workspace.exists():
            resolved = require_within(work_root.resolve(), workspace)
            shutil.rmtree(resolved)
