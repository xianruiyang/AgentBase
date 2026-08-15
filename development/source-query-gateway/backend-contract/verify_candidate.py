from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from capture_native_oracle import normalize_stdout


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "root"
MODE_SAMPLES: dict[str, list[str]] = {
    "RG-SEARCH-TEXT": ["-F", "alpha", "."],
    "RG-SEARCH-JSON": ["--json", "-F", "alpha", "."],
    "RG-FILES": ["--files", "."],
    "RG-FILES-WITH-MATCHES": ["--files-with-matches", "-F", "alpha", "."],
    "RG-FILES-WITHOUT-MATCH": ["--files-without-match", "-F", "alpha", "."],
    "RG-COUNT": ["--count", "-F", "alpha", "."],
    "RG-COUNT-MATCHES": ["--count-matches", "-F", "alpha", "."],
    "RG-ONLY-MATCHING": ["--only-matching", "-F", "alpha", "."],
    "RG-VIMGREP": ["--vimgrep", "-F", "alpha", "."],
    "RG-REPLACE-DISPLAY": ["--replace", "beta", "-F", "alpha", "."],
    "RG-PASSTHRU": ["--passthru", "-F", "alpha", "."],
    "RG-PREPROCESSOR": ["--pre", "preprocessor.exe", "-F", "alpha", "."],
    "RG-SEARCH-ZIP": ["--search-zip", "-F", "alpha", "."],
    "RG-NUL-PATHS": ["--null", "-F", "alpha", "."],
    "RG-NULL-DATA": ["--null-data", "-F", "alpha", "."],
    "RG-TYPE-LIST": ["--type-list"],
    "RG-GENERATE": ["--generate=man"],
    "RG-HELP": ["--help"],
    "RG-VERSION": ["--version"],
    "FD-PATHS": [".", "."],
    "FD-LIST-DETAILS": ["--list-details", ".", "."],
    "FD-FORMAT": ["--format", "{}", ".", "."],
    "FD-HYPERLINK": ["--hyperlink=always", ".", "."],
    "FD-QUIET": ["--has-results", ".", "."],
    "FD-PRINT0": ["--print0", ".", "."],
    "FD-EXEC": ["--exec", "cmd.exe", "/d", "/c", "echo", "{}"],
    "FD-EXEC-BATCH": ["--exec-batch", "cmd.exe", "/d", "/c", "echo", "{}"],
    "FD-HELP": ["--help"],
    "FD-VERSION": ["--version"],
}


def contract_modes() -> set[str]:
    matrix = json.loads((ROOT / "mode-matrix.json").read_text(encoding="utf-8"))
    return {item["id"] for item in matrix["modes"] if item["backend"] in {"rg", "fd"}}


def check_contract() -> None:
    expected = contract_modes()
    actual = set(MODE_SAMPLES)
    if actual != expected:
        raise RuntimeError(f"mode sample mismatch: missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


def run_defaults(srcq: Path) -> int:
    checked = 0
    for mode_id, argv in MODE_SAMPLES.items():
        backend = "rg" if mode_id.startswith("RG-") else "fd"
        completed = subprocess.run(
            [
                str(srcq),
                "query",
                backend,
                "defaults",
                "--output",
                "machine",
                "--",
                *argv,
            ],
            cwd=FIXTURE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"defaults failed for {mode_id}: {completed.stderr.decode('utf-8', errors='replace')}")
        text = completed.stdout.decode("utf-8")
        found = re.search(r'^\s*"mode": "([^"]+)"$', text, re.MULTILINE)
        if not found or found.group(1) != mode_id:
            raise RuntimeError(f"defaults classified {mode_id} as {found.group(1) if found else '<missing>'}")
        if '"engine_started": false' not in text:
            raise RuntimeError(f"defaults did not report an unstarted engine for {mode_id}")
        checked += 1
    return checked


def replay_oracle(srcq: Path) -> int:
    oracle = json.loads((ROOT / "native-oracle.json").read_text(encoding="utf-8"))
    checked = 0
    with tempfile.TemporaryDirectory(prefix="srcq-oracle-") as temporary:
        for case in oracle["cases"]:
            if case["backend"] not in {"rg", "fd"}:
                continue
            artifact = Path(temporary) / f"{case['id']}.bin"
            if case["id"] == "fd-print0":
                command = [
                    str(srcq),
                    "query",
                    "fd",
                    "exec",
                    "--artifact-out",
                    str(artifact),
                    "--",
                    *case["argv"],
                ]
            else:
                command = [
                    str(srcq),
                    "query",
                    case["backend"],
                    "exec",
                    "--view",
                    "raw",
                    "--",
                    *case["argv"],
                ]
            completed = subprocess.run(command, cwd=FIXTURE, input=case.get("stdin", "").encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env={**os.environ, "NO_COLOR": "1"})
            native_stdout = artifact.read_bytes() if case["id"] == "fd-print0" else completed.stdout
            normalized = normalize_stdout(native_stdout, case.get("normalizer", "raw"))
            if completed.returncode != case["exitCode"]:
                raise RuntimeError(f"{case['id']} exit {completed.returncode}, expected {case['exitCode']}")
            if hashlib.sha256(normalized).hexdigest() != case["stdoutSha256"]:
                raise RuntimeError(f"{case['id']} stdout differs from native oracle")
            if hashlib.sha256(completed.stderr).hexdigest() != case["stderrSha256"]:
                raise RuntimeError(f"{case['id']} stderr differs from native oracle")
            checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srcq", type=Path)
    parser.add_argument("--check-contract", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("the source-query gateway contract is maintained only on Windows")
    check_contract()
    if args.check_contract and args.srcq is None:
        print(json.dumps({"ok": True, "modeSamples": len(MODE_SAMPLES)}))
        return 0
    if args.srcq is None:
        parser.error("--srcq is required unless only --check-contract is requested")
    srcq = args.srcq.resolve()
    if not srcq.is_file():
        raise SystemExit(f"srcq executable does not exist: {srcq}")
    modes = run_defaults(srcq)
    oracle = replay_oracle(srcq)
    print(json.dumps({"ok": True, "modeSamples": modes, "oracleCases": oracle}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
