"""Explicit execution of a fingerprinted local calculator over frozen Evo facts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .spec import ARTIFACT_SCHEMA, EvoError, load_artifacts, load_spec, read_json, validate_artifacts


MANIFEST_SCHEMA = "agentbase-evo-calculator/v1"
INPUT_SCHEMA = "agentbase-evo-calculator-input/v1"
FACTS_SCHEMA = "agentbase-evo-calculator-facts/v1"
MAX_ARGV = 64
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 2 * 1024 * 1024


class CalculatorError(EvoError):
    """Calculator infrastructure failed; this is not a product-quality score."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _managed_source(manifest_path: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CalculatorError("calculator.code.path must be a non-empty relative path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CalculatorError("calculator.code.path must stay beside the manifest")
    source = (manifest_path.parent / candidate).resolve()
    if not source.is_relative_to(manifest_path.parent.resolve()) or not source.is_file():
        raise CalculatorError("calculator code source is unavailable")
    cursor = manifest_path.parent.resolve()
    for part in candidate.parts:
        cursor /= part
        if cursor.is_symlink() or cursor.is_junction():
            raise CalculatorError("calculator code source must not traverse links")
    return source


def load_manifest(path: Path) -> tuple[dict[str, Any], Path, str]:
    manifest = read_json(path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CalculatorError(f"calculator manifest schema must be {MANIFEST_SCHEMA}")
    for name in ("id", "version"):
        if not isinstance(manifest.get(name), str) or not manifest[name]:
            raise CalculatorError(f"calculator.{name} must be a non-empty string")
    argv = manifest.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_ARGV or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv):
        raise CalculatorError(f"calculator.argv must contain 1..{MAX_ARGV} non-empty strings")
    if argv.count("{calculator}") != 1 or sum(len(arg) for arg in argv) > 30_000:
        raise CalculatorError("calculator.argv must contain the calculator source placeholder exactly once and stay within 30000 characters")
    code = manifest.get("code")
    if not isinstance(code, dict):
        raise CalculatorError("calculator.code must be an object")
    source = _managed_source(path.resolve(), code.get("path"))
    actual = _file_sha256(source)
    if code.get("sha256") != actual:
        raise CalculatorError("calculator code fingerprint does not match its manifest")
    timeout = manifest.get("timeout_seconds", 30)
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise CalculatorError("calculator.timeout_seconds must be an integer from 1 to 600")
    output_limit = manifest.get("max_output_bytes", MAX_OUTPUT_BYTES)
    if type(output_limit) is not int or not 1 <= output_limit <= MAX_OUTPUT_BYTES:
        raise CalculatorError(f"calculator.max_output_bytes must be in 1..{MAX_OUTPUT_BYTES}")
    return manifest, source, actual


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    process.wait(timeout=20)


def _validate_field_contract(spec: dict[str, Any], artifacts: dict[str, Any]) -> None:
    fields = {field["id"]: field for field in spec["fields"]}
    for row in artifacts["rows"]:
        for field_id, value in row["values"].items():
            field = fields.get(field_id)
            if field is None:
                raise CalculatorError(f"calculator artifacts use undeclared field: {field_id}")
            if row["grain"] != field["grain"]:
                raise CalculatorError(f"calculator field {field_id} requires grain {field['grain']}")
            kind = field["type"]
            valid = ((kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)) or
                     (kind == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
                     (kind == "boolean" and isinstance(value, bool)) or
                     (kind == "string" and isinstance(value, str)))
            if value is not None and not valid:
                raise CalculatorError(f"calculator field {field_id} does not match type {kind}")


def calculate(
    *, manifest_path: Path, spec_path: Path, artifacts_path: Path, output_path: Path,
    allow_local_code: bool = False,
) -> dict[str, Any]:
    if os.name != "nt":
        raise CalculatorError("Evo local calculators require Windows")
    if not allow_local_code:
        raise CalculatorError("local calculator execution requires --allow-local-code")
    manifest_path, spec_path, artifacts_path, output_path = (
        manifest_path.resolve(), spec_path.resolve(), artifacts_path.resolve(), output_path.resolve()
    )
    manifest, code_source, code_sha256 = load_manifest(manifest_path)
    stdout_path = output_path.with_suffix(output_path.suffix + ".calculator.stdout.log")
    stderr_path = output_path.with_suffix(output_path.suffix + ".calculator.stderr.log")
    for generated in (output_path, stdout_path, stderr_path):
        if any(_same_path(generated, source) for source in (manifest_path, spec_path, artifacts_path, code_source)):
            raise CalculatorError("calculator outputs must not overwrite manifest, code, spec, or artifacts")
    spec = load_spec(spec_path)
    source_artifacts = load_artifacts(artifacts_path)
    calculator_identity = {
        "id": manifest["id"], "version": manifest["version"], "argv": manifest["argv"],
        "code": {"path": manifest["code"]["path"], "sha256": code_sha256},
        "manifest_sha256": _fingerprint(manifest),
    }
    payload = {
        "schema": INPUT_SCHEMA,
        "spec": {"identity_sha256": _fingerprint(spec), "value": spec},
        "artifacts": {"identity_sha256": _fingerprint(source_artifacts), "value": source_artifacts},
        "calculator": calculator_identity,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [arg.replace("{calculator}", str(code_source)) for arg in manifest["argv"]]
    started = time.monotonic()
    input_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=output_path.parent, prefix=".evo-calculator-") as input_file:
            input_file.write(_canonical(payload))
            input_name = input_file.name
        with open(input_name, "rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=stderr, cwd=manifest_path.parent,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                while process.poll() is None:
                    if time.monotonic() - started > manifest.get("timeout_seconds", 30):
                        raise CalculatorError("calculator timed out")
                    if stdout_path.stat().st_size > manifest.get("max_output_bytes", MAX_OUTPUT_BYTES):
                        raise CalculatorError("calculator output exceeded its byte limit")
                    if stderr_path.stat().st_size > MAX_STDERR_BYTES:
                        raise CalculatorError("calculator stderr exceeded its byte limit")
                    time.sleep(0.05)
            finally:
                _terminate(process)
        if process.returncode != 0:
            raise CalculatorError(f"calculator exited with code {process.returncode}; no quality result was produced")
        if stdout_path.stat().st_size > manifest.get("max_output_bytes", MAX_OUTPUT_BYTES):
            raise CalculatorError("calculator output exceeded its byte limit")
        try:
            returned = json.loads(stdout_path.read_text(encoding="utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError) as exc:
            raise CalculatorError("calculator must return one finite JSON object") from exc
        if not isinstance(returned, dict) or returned.get("schema") != FACTS_SCHEMA or not isinstance(returned.get("rows"), list):
            raise CalculatorError(f"calculator output must use {FACTS_SCHEMA} with rows")
        input_rows = {row["id"] for row in source_artifacts["rows"]}
        derived_rows: list[dict[str, Any]] = []
        for index, value in enumerate(returned["rows"]):
            if not isinstance(value, dict):
                raise CalculatorError(f"calculator row {index} must be an object")
            references = value.get("input_rows")
            if (not isinstance(references, list) or not references or
                    any(not isinstance(item, str) or item not in input_rows for item in references) or
                    len(references) != len(set(references))):
                raise CalculatorError(f"calculator row {index} must reference existing input_rows")
            row = {key: value.get(key) for key in ("id", "grain", "dimensions", "values", "completeness")}
            row["source"] = {
                "kind": "fixed-local-calculator",
                "location": f"{manifest_path}#{manifest['id']}@{manifest['version']}",
            }
            row["input_rows"] = references
            derived_rows.append(row)
        result = {
            "schema": ARTIFACT_SCHEMA,
            "id": f"{source_artifacts['id']}+{manifest['id']}",
            "version": _fingerprint({"input": payload["artifacts"]["identity_sha256"], "calculator": calculator_identity, "rows": derived_rows}),
            "calculator": calculator_identity,
            "input_snapshot": {"spec_sha256": payload["spec"]["identity_sha256"], "artifacts_sha256": payload["artifacts"]["identity_sha256"]},
            "rows": [*source_artifacts["rows"], *derived_rows],
        }
        validate_artifacts(result)
        _validate_field_contract(spec, result)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result
    finally:
        if input_name is not None:
            Path(input_name).unlink(missing_ok=True)
