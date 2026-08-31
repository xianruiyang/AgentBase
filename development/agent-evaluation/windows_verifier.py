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
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation_core import (
    EvaluationError,
    apply_git_patch,
    apply_windows_adapter_baseline,
    bounded_text,
    canonical_bytes,
    create_workspace,
    dependency_runtime_projection,
    elapsed_seconds,
    git_output,
    read_json,
    remove_managed_tree,
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


PYTHON_PROXY_BOOTSTRAP_WHEEL = (
    Path(__file__).resolve().parent
    / "vendor"
    / "PySocks-1.7.1-py3-none-any.whl"
)
PYTHON_PROXY_BOOTSTRAP_SHA256 = (
    "2725bd0a9925919b9b51739eea5f9e2bae91e83288108a9ad338b2e3a4435ee5"
)
VERIFIER_RESULT_SCHEMA = "agentbase.windows-swe-verifier-result/v4"
MAX_VERIFIER_REPORT_BYTES = 64 * 1024 * 1024


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


def _pnpm_runtime_paths(workspace: Path) -> tuple[Path, Path]:
    runtime_root = workspace.resolve() / ".agentbase" / "task-runtime"
    wrapper = runtime_root / "bin" / "pnpm.cmd"
    module = runtime_root / "pnpm" / "node_modules" / "pnpm" / "dist" / "pnpm.cjs"
    return wrapper, module


def _prepare_pnpm_runtime(
    workspace: Path,
    environment: Mapping[str, str],
    log_path: Path,
) -> None:
    package = read_json(workspace.resolve() / "package.json")
    package_manager = package.get("packageManager")
    match = (
        re.fullmatch(r"pnpm@([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)", package_manager)
        if isinstance(package_manager, str)
        else None
    )
    if not match:
        raise EvaluationError("pnpm task package.json must pin packageManager to an exact version")
    version = match.group(1)
    npm = _resolve_application("npm.cmd", "npm.exe")
    node = _resolve_application("node.exe", "node")
    wrapper, module = _pnpm_runtime_paths(workspace)
    install_root = module.parents[3]
    install_root.mkdir(parents=True, exist_ok=True)
    _run_logged(
        [
            str(npm),
            "install",
            "--prefix",
            str(install_root),
            "--no-save",
            "--ignore-scripts",
            "--package-lock=false",
            "--fund=false",
            "--audit=false",
            f"pnpm@{version}",
        ],
        workspace=workspace,
        environment=_command_environment(environment, {}),
        timeout=300,
        log_path=log_path,
        check=True,
    )
    if not module.is_file():
        raise EvaluationError("workspace pnpm runtime was not materialized")
    runtime_text = module.read_text(encoding="utf-8")
    replacements = {
        "value: fs.realpathSync(os.tmpdir())": "value: os.tmpdir()",
        "const cwd = fs_1.default.realpathSync((0, better_path_resolve_1.default)(cliOptions.dir ?? npmConfig.localPrefix));": "const cwd = (0, better_path_resolve_1.default)(cliOptions.dir ?? npmConfig.localPrefix);",
    }
    for original, replacement in replacements.items():
        if runtime_text.count(original) != 1:
            raise EvaluationError("pinned pnpm runtime compatibility target changed")
        runtime_text = runtime_text.replace(original, replacement)
    module.write_text(runtime_text, encoding="utf-8", newline="\n")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "@echo off\n"
        "setlocal\n"
        f'"{node}" "%~dp0..\\pnpm\\node_modules\\pnpm\\dist\\pnpm.cjs" %*\n'
        "exit /b %ERRORLEVEL%\n",
        encoding="utf-8",
        newline="\r\n",
    )


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
    if toolchain.get("package_manager") == "pnpm":
        pnpm, pnpm_runtime = _pnpm_runtime_paths(workspace)
        if not pnpm.is_file() or not pnpm_runtime.is_file():
            raise EvaluationError("workspace pnpm runtime is not prepared")
    else:
        pnpm = Path("pnpm.cmd")
        pnpm_runtime = Path("pnpm.cjs")
    return {
        "python": str(Path(sys.executable).resolve()),
        "workspace": str(workspace.resolve()),
        "node": str(node),
        "npm": str(npm),
        "pnpm": str(pnpm.resolve()) if pnpm.is_absolute() else str(pnpm),
        "pnpm_runtime": (
            str(pnpm_runtime.resolve()) if pnpm_runtime.is_absolute() else str(pnpm_runtime)
        ),
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


def _task_runtime_environment(
    task: Mapping[str, Any],
    values: Mapping[str, str],
    inherited_environment: Mapping[str, str],
) -> dict[str, str]:
    projection = dependency_runtime_projection(task, values)
    inherited_path = next(
        (
            str(value)
            for key, value in inherited_environment.items()
            if str(key).upper() == "PATH"
        ),
        "",
    )
    runtime_bin = str(projection["bin_directory"])
    environment = {
        "PATH": (
            runtime_bin + os.pathsep + inherited_path if inherited_path else runtime_bin
        )
    }
    virtual_environment = projection.get("virtual_environment")
    if isinstance(virtual_environment, str) and virtual_environment:
        environment["VIRTUAL_ENV"] = virtual_environment
    return environment


def _absolute_child_argv(argv: Sequence[str]) -> list[str]:
    if not argv:
        raise EvaluationError("verifier child command is empty")
    executable = Path(str(argv[0]))
    if not executable.is_absolute():
        raise EvaluationError(
            f"verifier child executable must use an absolute path: {argv[0]}"
        )
    if not executable.is_file():
        raise EvaluationError(f"verifier child executable is not a file: {executable}")
    return [str(executable.resolve()), *[str(item) for item in argv[1:]]]


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate the exact Windows process tree owned by one verifier command."""

    if process.poll() is not None:
        return
    system_root = os.environ.get("SystemRoot", "").strip()
    taskkill = Path(system_root).resolve() / "System32" / "taskkill.exe"
    if not system_root or not taskkill.is_file():
        process.kill()
        process.wait(timeout=30)
        raise EvaluationError("taskkill.exe is unavailable; only the command root was terminated")
    completed = subprocess.run(
        [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=30)
        raise EvaluationError("timed-out command root did not exit after taskkill") from exc
    if completed.returncode != 0:
        detail = bounded_text(completed.stdout.decode("utf-8", errors="replace"), 500)
        raise EvaluationError(f"taskkill could not confirm descendant termination: {detail}")


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
        process = subprocess.Popen(
            [str(item) for item in argv],
            cwd=str(workspace.resolve()),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise EvaluationError(f"command failed to start: {argv[0]}: {exc}") from exc
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        termination_error: EvaluationError | None = None
        try:
            _terminate_process_tree(process)
        except EvaluationError as termination_exc:
            termination_error = termination_exc
        try:
            output, _ = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            output = exc.output or b""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(output or b"")
        if termination_error is not None:
            raise EvaluationError(
                f"command timed out after {timeout} seconds and process-tree cleanup failed: "
                f"{argv[0]}: {termination_error}"
            ) from exc
        raise EvaluationError(
            f"command timed out after {timeout} seconds; process tree was terminated: {argv[0]}"
        ) from exc
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(output)
    record = {
        "argv": list(argv),
        "exit_code": process.returncode,
        "duration_seconds": elapsed_seconds(started),
        "log_path": str(log_path.resolve()),
        "log_sha256": sha256_file(log_path),
        "log_bytes": log_path.stat().st_size,
    }
    if check and process.returncode != 0:
        detail = bounded_text(output.decode("utf-8", errors="replace"), 700)
        raise EvaluationError(f"command failed ({process.returncode}): {argv[0]}: {detail}")
    return record


def _restore_setup_baseline(task: Mapping[str, Any], workspace: Path) -> None:
    cleanup = task["setup_cleanup"]
    restore = list(cleanup["restore_tracked"])
    if restore:
        git_output(workspace, "checkout", "HEAD", "--", *restore)
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
    elif task["toolchain"].get("package_manager") == "pnpm":
        _prepare_pnpm_runtime(
            workspace,
            network_environment,
            logs / "pnpm-runtime.log",
        )
    values = resolve_task_tools(task, workspace)
    task_environment = _task_runtime_environment(task, values, network_environment)
    if task["toolchain"]["kind"] == "python":
        if not PYTHON_PROXY_BOOTSTRAP_WHEEL.is_file():
            raise EvaluationError("Python SOCKS bootstrap wheel is missing")
        if sha256_file(PYTHON_PROXY_BOOTSTRAP_WHEEL) != PYTHON_PROXY_BOOTSTRAP_SHA256:
            raise EvaluationError("Python SOCKS bootstrap wheel hash mismatch")
        _run_logged(
            [
                values["python"],
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                str(PYTHON_PROXY_BOOTSTRAP_WHEEL),
            ],
            workspace=workspace,
            environment=_command_environment(
                {**network_environment, **task_environment}, {}
            ),
            timeout=180,
            log_path=logs / "python-proxy-bootstrap.log",
            check=True,
        )
    for index, command in enumerate(task["setup"]):
        _run_logged(
            _expanded_argv(command, values),
            workspace=workspace,
            environment=_command_environment(
                {**network_environment, **task_environment}, command
            ),
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
    workspace_spellings = {
        str(workspace.resolve()),
        str(workspace.resolve()).replace("\\", "/"),
    }

    def normalized_workspace_text(value: str) -> str:
        for spelling in workspace_spellings:
            value = re.sub(
                re.escape(spelling),
                "<workspace>",
                value,
                flags=re.IGNORECASE,
            )
        return value

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
    if task["toolchain"]["kind"] == "python":
        inventory_text = normalized_workspace_text(inventory_text)
        inventory = inventory_text.encode("utf-8")
    else:
        try:
            inventory_document = json.loads(inventory_text)
        except json.JSONDecodeError as exc:
            raise EvaluationError("package dependency inventory is not valid JSON") from exc

        def normalize_inventory_value(value: Any) -> Any:
            if isinstance(value, str):
                for spelling in workspace_spellings:
                    value = re.sub(
                        re.escape(spelling),
                        "<workspace>",
                        value,
                        flags=re.IGNORECASE,
                    )
                return value
            if isinstance(value, list):
                return [normalize_inventory_value(item) for item in value]
            if isinstance(value, dict):
                return {
                    key: normalize_inventory_value(item)
                    for key, item in value.items()
                }
            return value

        inventory = canonical_bytes(normalize_inventory_value(inventory_document))
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
    if task["toolchain"]["kind"] == "node" and task["toolchain"]["package_manager"] == "pnpm":
        runtime_path = Path(str(values["pnpm_runtime"])).resolve()
        if not runtime_path.is_file():
            raise EvaluationError("pnpm runtime module is not a regular file")
        tool_identities["pnpm-runtime"] = {
            "sha256": sha256_file(runtime_path),
            "bytes": runtime_path.stat().st_size,
        }
    payload = {
        "toolchain": dict(task["toolchain"]),
        "tools": tool_identities,
        "manifests": manifests,
        "inventory_sha256": sha256_bytes(inventory),
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def _run_trusted_local_check(
    *,
    argv: Sequence[str],
    workspace: Path,
    base_environment: Mapping[str, str],
    command_environment: Mapping[str, str],
    timeout: int,
    log_path: Path,
) -> dict[str, Any]:
    """Run one verifier command in its disposable, independent workspace."""

    environment = dict(base_environment)
    environment.update(command_environment)
    return _run_logged(
        _absolute_child_argv(argv),
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


def _normalize_junit_node_identity(value: str, mode: str | None) -> str:
    if mode is None:
        return value
    if mode != "nfc-utf16-surrogate-replacement":
        raise EvaluationError(f"unsupported JUnit node identity normalization: {mode}")
    normalized = unicodedata.normalize("NFC", value)
    parts: list[str] = []
    for character in normalized:
        codepoint = ord(character)
        if codepoint > 0xFFFF:
            parts.append("\ufffd\ufffd")
        elif 0xD800 <= codepoint <= 0xDFFF:
            parts.append("\ufffd")
        else:
            parts.append(character)
    return "".join(parts)


def convert_junit_to_ctrf(
    raw_path: Path,
    output_path: Path,
    *,
    tool: str,
    fold_whitespace: bool = False,
    node_identity_normalization: str | None = None,
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
        full_name = _normalize_junit_node_identity(
            full_name,
            node_identity_normalization,
        )
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


def _copy_staged_report(source: Path, destination: Path, staging_root: Path) -> None:
    resolved = require_within(staging_root, source)
    if resolved.is_symlink() or not resolved.is_file():
        raise EvaluationError(f"verifier check did not produce a regular report: {source.name}")
    size = resolved.stat().st_size
    if size > MAX_VERIFIER_REPORT_BYTES:
        raise EvaluationError(
            f"verifier check report exceeds {MAX_VERIFIER_REPORT_BYTES} bytes: {source.name}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved, destination)


def _materialize_report(
    report: Mapping[str, Any],
    staged_reports_root: Path,
    reports_root: Path,
    exit_code: int,
) -> None:
    kind = report["kind"]
    output_relative = str(report["path"])
    output = reports_root / output_relative
    staged_output = staged_reports_root / output_relative
    raw_relative = str(report.get("raw_path", report["path"]))
    raw = reports_root / raw_relative
    staged_raw = staged_reports_root / raw_relative
    if kind == "junit":
        _copy_staged_report(staged_output, output, staged_reports_root)
        return
    if kind == "gate-ctrf":
        write_gate_ctrf(
            output,
            name=str(report["name"]),
            tool=str(report.get("tool", "gate")),
            exit_code=exit_code,
        )
        return
    _copy_staged_report(staged_raw, raw, staged_reports_root)
    if kind == "jest-json-to-ctrf":
        convert_jest_json(raw, output, str(report.get("tool", "jest")))
    elif kind == "junit-to-ctrf":
        convert_junit_to_ctrf(
            raw,
            output,
            tool=str(report.get("tool", "junit")),
            fold_whitespace=bool(report.get("fold_whitespace", False)),
            node_identity_normalization=report.get("node_identity_normalization"),
        )
    else:
        raise EvaluationError(f"unsupported report adapter: {kind}")


def run_checks(
    *,
    task: Mapping[str, Any],
    workspace: Path,
    artifact_root: Path,
    values: Mapping[str, str],
    base_environment: Mapping[str, str],
) -> list[dict[str, Any]]:
    reports_root = artifact_root.resolve() / "reports"
    staged_reports_root = workspace.resolve() / ".agentbase-verifier" / "reports"
    logs_root = artifact_root.resolve() / "check-logs"
    reports_root.mkdir(parents=True, exist_ok=True)
    staged_reports_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    gate_failed = False
    task_environment = _task_runtime_environment(task, values, base_environment)
    for index, check in enumerate(task["checks"]):
        report = check["report"]
        report_path = reports_root / str(report["path"])
        staged_report_path = staged_reports_root / str(report["path"])
        staged_raw_path = staged_reports_root / str(
            report.get("raw_path", report["path"])
        )
        if gate_failed:
            records.append({"id": check["id"], "status": "skipped-after-gate"})
            continue
        for before_index, before in enumerate(check.get("before", [])):
            before_record = _run_trusted_local_check(
                argv=_expanded_argv(before, values),
                workspace=workspace,
                base_environment=base_environment,
                command_environment=_command_environment(task_environment, before),
                timeout=int(before["timeout_seconds"]),
                log_path=logs_root / f"{index:02d}-{before_index:02d}-before.log",
            )
            if before_record["exit_code"] != 0:
                raise EvaluationError(f"verifier preparation failed before {check['id']}")
        argv = _expanded_argv(
            check,
            values,
            report=staged_report_path,
            raw_report=staged_raw_path,
        )
        record = _run_trusted_local_check(
            argv=argv,
            workspace=workspace,
            base_environment=base_environment,
            command_environment=_command_environment(task_environment, check),
            timeout=int(check["timeout_seconds"]),
            log_path=logs_root / f"{index:02d}-{check['id']}.log",
        )
        record["id"] = check["id"]
        record["bucket"] = check["bucket"]
        _materialize_report(
            report,
            staged_reports_root,
            reports_root,
            int(record["exit_code"]),
        )
        record["report_path"] = str(report_path)
        records.append(record)
        if check["bucket"] == "gate" and record["exit_code"] != 0:
            gate_failed = True
    return records


def baseline_p2p_exclusions(
    *,
    task_assets: Path,
    task: Mapping[str, Any],
    artifact_root: Path,
) -> list[str]:
    """Project declared Windows JUnit base outcomes onto pinned P2P nodes."""

    policy = task.get("windows_oracle", {}).get("p2p_baseline_policy")
    if policy is None:
        return []
    if policy == "exclude-stable-skips":
        excluded_statuses = {"skipped"}
    elif policy == "exclude-stable-nonpassing":
        excluded_statuses = {"failed", "skipped"}
    else:
        raise EvaluationError(f"unsupported Windows P2P baseline policy: {policy}")

    config = read_json(task_assets / "tests" / "config.json")
    p2p_values = config.get("p2p_node_ids")
    if not isinstance(p2p_values, list) or any(
        not isinstance(item, str) or not item for item in p2p_values
    ):
        raise EvaluationError("pinned DeepSWE config has invalid p2p_node_ids")
    p2p_node_ids = set(p2p_values)
    exact_outcomes: set[str] = set()
    collection_prefixes: set[str] = set()
    reports_root = artifact_root.resolve() / "reports"
    for check in task["checks"]:
        if check["bucket"] != "base":
            continue
        report = check["report"]
        kind = report["kind"]
        if kind == "gate-ctrf":
            continue
        if kind not in {"junit", "junit-to-ctrf"}:
            raise EvaluationError(
                f"{policy} requires JUnit base reports"
            )
        raw_relative = str(report.get("raw_path", report["path"]))
        raw_path = require_within(reports_root, reports_root / raw_relative)
        if not raw_path.is_file():
            raise EvaluationError(
                f"baseline outcome projection is missing JUnit report: {raw_relative}"
            )
        try:
            root = ET.parse(raw_path).getroot()
        except ET.ParseError as exc:
            raise EvaluationError(
                f"baseline outcome projection cannot parse JUnit report: {raw_relative}"
            ) from exc
        for case in root.iter():
            if case.tag.rsplit("}", 1)[-1] != "testcase":
                continue
            status, _ = _junit_status(case)
            if status not in excluded_statuses:
                continue
            name = str(case.attrib.get("name", "")).strip()
            classname = str(case.attrib.get("classname", "")).strip()
            if not name:
                raise EvaluationError("nonpassing JUnit testcase has no name")
            fold_whitespace = bool(report.get("fold_whitespace", False))
            normalization = report.get("node_identity_normalization")
            if classname:
                candidates = {f"{classname}.{name}", f"{classname}: {name}"}
                for candidate in candidates:
                    if fold_whitespace:
                        candidate = re.sub(r"\r\n|[\t\n\r]", " ", candidate).strip()
                    exact_outcomes.add(
                        _normalize_junit_node_identity(candidate, normalization)
                    )
            else:
                if fold_whitespace:
                    name = re.sub(r"\r\n|[\t\n\r]", " ", name).strip()
                collection_prefixes.add(
                    _normalize_junit_node_identity(name, normalization)
                )

    matched = p2p_node_ids & exact_outcomes
    for prefix in collection_prefixes:
        matched.update(
            node_id
            for node_id in p2p_node_ids
            if node_id == prefix or node_id.startswith(f"{prefix}.")
        )
    return sorted(matched)


def grade_reports(
    *,
    task_assets: Path,
    task: Mapping[str, Any],
    artifact_root: Path,
    p2p_exclusions: Sequence[str] = (),
) -> dict[str, Any]:
    grader = task_assets / "tests" / "grader.py"
    config_source = task_assets / "tests" / "config.json"
    if sha256_file(grader) != task["assets"]["tests/grader.py"]:
        raise EvaluationError("pinned DeepSWE grader identity changed")
    config = copy.deepcopy(read_json(config_source))
    original_p2p = config.get("p2p_node_ids")
    if not isinstance(original_p2p, list) or any(
        not isinstance(item, str) or not item for item in original_p2p
    ):
        raise EvaluationError("pinned DeepSWE config has invalid p2p_node_ids")
    exclusions = list(p2p_exclusions)
    if any(not isinstance(item, str) or not item for item in exclusions):
        raise EvaluationError("P2P exclusions must be sorted unique node ids")
    exclusion_set = set(exclusions)
    if exclusions != sorted(exclusion_set):
        raise EvaluationError("P2P exclusions must be sorted unique node ids")
    unknown_exclusions = sorted(exclusion_set - set(original_p2p))
    if unknown_exclusions:
        raise EvaluationError(
            f"P2P exclusions are absent from the pinned config: {unknown_exclusions[:3]}"
        )
    config["p2p_node_ids"] = [
        item for item in original_p2p if item not in exclusion_set
    ]
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
        "p2p_exclusions": exclusions,
        "original_p2p_total": len(original_p2p),
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
    retain_workspace: bool = False,
    p2p_exclusions: Sequence[str] = (),
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
        windows_adapter = apply_windows_adapter_baseline(
            project_root,
            workspace,
            task,
        )
        if windows_adapter is not None:
            applied_patches.append(
                {
                    "kind": "windows-adapter",
                    **windows_adapter,
                }
            )
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
        checks = run_checks(
            task=task,
            workspace=workspace,
            artifact_root=artifact_root,
            values=values,
            base_environment=network_environment,
        )
        failed_gate = next(
            (
                check
                for check in checks
                if check.get("bucket") == "gate" and check.get("exit_code") != 0
            ),
            None,
        )
        if failed_gate is not None and patch_kind in {"noop", "reference"}:
            raise EvaluationError(
                f"Windows {patch_kind} oracle gate failed: {failed_gate['id']}"
            )
        observed_baseline_p2p_exclusions = (
            []
            if failed_gate is not None
            else baseline_p2p_exclusions(
                task_assets=task_assets,
                task=task,
                artifact_root=artifact_root,
            )
        )
        grade = grade_reports(
            task_assets=task_assets,
            task=task,
            artifact_root=artifact_root,
            p2p_exclusions=p2p_exclusions,
        )
        result = {
            "schema": VERIFIER_RESULT_SCHEMA,
            "task_id": task_id,
            "patch_kind": patch_kind,
            "created_at": utc_now(),
            "duration_seconds": elapsed_seconds(started),
            "workspace": str(workspace.resolve()),
            "execution_environment": "trusted-local-independent-workspace",
            "dependency_identity": dependency,
            "applied_patches": applied_patches,
            "checks": checks,
            "observed_baseline_p2p_exclusions": observed_baseline_p2p_exclusions,
            "grade": grade,
        }
        return write_immutable_receipt(
            artifact_root.resolve() / "verifier-result.json",
            result,
        )
    finally:
        active_exception = sys.exc_info()[0] is not None
        if not retain_workspace and workspace.exists():
            try:
                resolved = require_within(work_root.resolve(), workspace)
                remove_managed_tree(work_root, resolved)
            except Exception:
                if not active_exception:
                    raise
