from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


SCHEMA = "agentbase.source-query-native-oracle/v1"
ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = ROOT / "fixtures" / "root"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_executable(name: str, explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if path.is_file():
            return path
        raise SystemExit(f"{name} executable does not exist: {path}")
    located = shutil.which(f"{name}.exe") or shutil.which(name)
    if located and Path(located).suffix.lower() == ".exe":
        return Path(located).resolve()
    if name == "ast-grep":
        app_data = os.environ.get("APPDATA")
        if app_data:
            npm_engine = (
                Path(app_data)
                / "npm"
                / "node_modules"
                / "@ast-grep"
                / "cli"
                / "ast-grep.exe"
            )
            if npm_engine.is_file():
                return npm_engine.resolve()
    raise SystemExit(f"unable to resolve Windows executable for {name}")


def decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def strip_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_timing(item)
            for key, item in value.items()
            if key not in {"elapsed", "elapsed_total"}
        }
    if isinstance(value, list):
        return [strip_timing(item) for item in value]
    return value


def normalize_stdout(data: bytes, normalizer: str) -> bytes:
    if normalizer == "raw":
        return data
    if normalizer not in {"jsonl", "jsonl-strip-timing"}:
        raise ValueError(f"unknown normalizer: {normalizer}")
    documents = []
    for line in data.decode("utf-8").splitlines():
        if not line:
            continue
        value = json.loads(line)
        if normalizer == "jsonl-strip-timing":
            value = strip_timing(value)
        documents.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if not documents:
        return b""
    return ("\n".join(documents) + "\n").encode("utf-8")


def run_case(case: dict[str, Any], engines: dict[str, Path]) -> dict[str, Any]:
    executable = engines[case["backend"]]
    completed = subprocess.run(
        [str(executable), *case["argv"]],
        cwd=FIXTURE_ROOT,
        input=case.get("stdin", "").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )
    normalizer = case.get("normalizer", "raw")
    normalized_stdout = normalize_stdout(completed.stdout, normalizer)
    stdout_text = decode_utf8(normalized_stdout)
    stderr_text = decode_utf8(completed.stderr)
    return {
        "id": case["id"],
        "backend": case["backend"],
        "argv": case["argv"],
        "normalizer": normalizer,
        "exitCode": completed.returncode,
        "stdoutBytes": len(normalized_stdout),
        "stderrBytes": len(completed.stderr),
        "stdoutSha256": sha256(normalized_stdout),
        "stderrSha256": sha256(completed.stderr),
        "stdoutUtf8": stdout_text,
        "stderrUtf8": stderr_text,
        "stdoutBase64": None
        if stdout_text is not None and "\x00" not in stdout_text
        else base64.b64encode(normalized_stdout).decode("ascii"),
    }


def version_output(path: Path) -> str:
    completed = subprocess.run(
        [str(path), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"version probe failed for {path}: {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', errors='replace')}"
        )
    return completed.stdout.decode("utf-8").strip()


def build_oracle(ast_grep: str | None) -> dict[str, Any]:
    if os.name != "nt":
        raise SystemExit("the source-query backend contract is maintained only on Windows")
    engines = {
        "rg": resolve_executable("rg"),
        "fd": resolve_executable("fd"),
        "ast-grep": resolve_executable("ast-grep", ast_grep),
    }
    versions = {backend: version_output(path) for backend, path in engines.items()}
    expected = {
        "rg": "ripgrep 15.1.0",
        "fd": "fd 10.4.2",
        "ast-grep": "ast-grep 0.44.1",
    }
    for backend, prefix in expected.items():
        if not versions[backend].startswith(prefix):
            raise SystemExit(
                f"unexpected {backend} version: {versions[backend]!r}; expected {prefix!r}"
            )
    cases = [
        {
            "id": "rg-match-json",
            "backend": "rg",
            "argv": ["--json", "--sort", "path", "-F", "alpha", "."],
            "normalizer": "jsonl-strip-timing",
        },
        {
            "id": "rg-no-match-json",
            "backend": "rg",
            "argv": ["--json", "--sort", "path", "-F", "__missing__", "."],
            "normalizer": "jsonl-strip-timing",
        },
        {
            "id": "rg-files",
            "backend": "rg",
            "argv": ["--files", "--sort", "path", "."],
        },
        {
            "id": "rg-count-matches",
            "backend": "rg",
            "argv": ["--count-matches", "--sort", "path", "-F", "alpha", "."],
        },
        {
            "id": "fd-files",
            "backend": "fd",
            "argv": ["-t", "f", "--threads", "1", "--path-separator", "/", ".", "."],
        },
        {
            "id": "fd-no-match",
            "backend": "fd",
            "argv": ["-t", "f", "--threads", "1", "__missing__", "."],
        },
        {
            "id": "fd-print0",
            "backend": "fd",
            "argv": ["-0", "-t", "f", "--threads", "1", ".", "."],
        },
        {
            "id": "ast-run-json",
            "backend": "ast-grep",
            "argv": ["run", "-p", "alpha($A)", "-l", "ts", "--json=stream", "src"],
            "normalizer": "jsonl",
        },
        {
            "id": "ast-run-no-match",
            "backend": "ast-grep",
            "argv": ["run", "-p", "missing($A)", "-l", "ts", "--json=stream", "src"],
            "normalizer": "jsonl",
        },
        {
            "id": "ast-outline-json",
            "backend": "ast-grep",
            "argv": ["outline", "--json=stream", "src"],
            "normalizer": "jsonl",
        },
    ]
    return {
        "schema": SCHEMA,
        "fixture": "fixtures/root",
        "versions": versions,
        "cases": [run_case(case, engines) for case in cases],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ast-grep")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    oracle = build_oracle(args.ast_grep)
    if args.verify:
        expected = json.loads(args.verify.read_text(encoding="utf-8"))
        if oracle != expected:
            print(json.dumps({"ok": False, "actual": oracle}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"ok": True, "verified": str(args.verify)}, ensure_ascii=False))
        return 0
    rendered = json.dumps(oracle, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
