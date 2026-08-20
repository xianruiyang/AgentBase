from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import tiktoken


MAX_CAPTURE_BYTES = 256 * 1024 * 1024


def run(executable: Path, argv: list[str], cwd: Path) -> bytes:
    completed = subprocess.run(
        [str(executable), *argv],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{executable.name} exited {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', errors='replace')[:2000]}"
        )
    if len(completed.stdout) > MAX_CAPTURE_BYTES:
        raise RuntimeError(f"{executable.name} stdout exceeds {MAX_CAPTURE_BYTES} bytes")
    return completed.stdout


def version(executable: Path, cwd: Path) -> str:
    return run(executable, ["--version"], cwd).decode("utf-8").strip()


def sha256(executable: Path) -> str:
    digest = hashlib.sha256()
    with executable.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def measurement(data: bytes, encodings: dict[str, Any]) -> dict[str, Any]:
    text = data.decode("utf-8")
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "characters": len(text),
        "tokens": {name: len(encoding.encode(text)) for name, encoding in encodings.items()},
    }


def reduction(raw: int, projected: int) -> float:
    if raw == 0:
        return 0.0
    return round((raw - projected) / raw, 6)


def compare(raw: bytes, projected: bytes, encodings: dict[str, Any]) -> dict[str, Any]:
    raw_measurement = measurement(raw, encodings)
    projected_measurement = measurement(projected, encodings)
    return {
        "raw_json2": raw_measurement,
        "srcq_model": projected_measurement,
        "reduction": {
            "bytes": reduction(raw_measurement["bytes"], projected_measurement["bytes"]),
            "tokens": {
                name: reduction(
                    raw_measurement["tokens"][name],
                    projected_measurement["tokens"][name],
                )
                for name in encodings
            },
        },
    }


def projection(
    srcq: Path,
    scc: Path,
    root: Path,
    view: str,
    *,
    by_file: bool,
) -> bytes:
    native = ["--format", "json2", "."]
    if by_file:
        native.insert(0, "--by-file")
    return run(
        srcq,
        [
            "query",
            "scc",
            "exec",
            "--engine",
            str(scc),
            "--view",
            view,
            "--limit",
            "10000",
            "--model-token-budget",
            "1000000",
            "--",
            *native,
        ],
        root,
    )


def validate_projection(label: str, data: bytes) -> None:
    text = data.decode("utf-8")
    if "@more" in text:
        raise RuntimeError(f"{label} model projection was not complete")
    if any(term in text for term in ("estimatedCost", "estimatedSchedule", "COCOMO")):
        raise RuntimeError(f"{label} model projection leaked cost estimates")


def baseline_improvement(
    baseline: bytes,
    candidate: bytes,
    encodings: dict[str, Any],
) -> dict[str, Any]:
    baseline_measurement = measurement(baseline, encodings)
    candidate_measurement = measurement(candidate, encodings)
    return {
        "baseline_srcq_model": baseline_measurement,
        "reduction": {
            "bytes": reduction(
                baseline_measurement["bytes"], candidate_measurement["bytes"]
            ),
            "tokens": {
                name: reduction(
                    baseline_measurement["tokens"][name],
                    candidate_measurement["tokens"][name],
                )
                for name in encodings
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srcq", type=Path, required=True)
    parser.add_argument("--baseline-srcq", type=Path)
    parser.add_argument("--scc", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if os.name != "nt":
        raise SystemExit("the scc projection benchmark is maintained only on Windows")
    srcq = args.srcq.resolve(strict=True)
    baseline_srcq = args.baseline_srcq.resolve(strict=True) if args.baseline_srcq else None
    scc = args.scc.resolve(strict=True)
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        raise SystemExit(f"benchmark root is not a directory: {root}")

    encodings = {
        "cl100k_base": tiktoken.get_encoding("cl100k_base"),
        "o200k_base": tiktoken.get_encoding("o200k_base"),
    }
    raw_languages = run(scc, ["--format", "json2", "."], root)
    raw_files = run(scc, ["--by-file", "--format", "json2", "."], root)
    model_languages = projection(srcq, scc, root, "languages", by_file=False)
    model_files = projection(srcq, scc, root, "files", by_file=True)
    for label, data in {"languages": model_languages, "files": model_files}.items():
        validate_projection(label, data)

    baseline_files = None
    if baseline_srcq:
        baseline_files = projection(baseline_srcq, scc, root, "files", by_file=True)
        validate_projection("baseline files", baseline_files)

    language_document = json.loads(raw_languages)
    file_document = json.loads(raw_files)
    language_summary = language_document.get("languageSummary")
    file_summary = file_document.get("languageSummary")
    if not isinstance(language_summary, list) or not isinstance(file_summary, list):
        raise RuntimeError("scc json2 is missing languageSummary")
    file_surface = compare(raw_files, model_files, encodings)
    if baseline_files is not None:
        file_surface["improvement_over_baseline"] = baseline_improvement(
            baseline_files, model_files, encodings
        )
    result = {
        "schema": "srcq.scc-projection-benchmark/v2",
        "root": str(root),
        "srcq": {"version": version(srcq, root), "sha256": sha256(srcq)},
        "baseline_srcq": (
            {"version": version(baseline_srcq, root), "sha256": sha256(baseline_srcq)}
            if baseline_srcq
            else None
        ),
        "scc_version": version(scc, root),
        "tokenizers": {name: tiktoken.__version__ for name in encodings},
        "facts": {
            "languages": len(language_summary),
            "files": sum(
                len(language.get("Files", []))
                for language in file_summary
                if isinstance(language, dict)
            ),
        },
        "surfaces": {
            "languages": compare(raw_languages, model_languages, encodings),
            "files": file_surface,
        },
        "boundary": "Token counts compare complete raw json2 with the complete task-facing direct-metric projection; an optional baseline compares the same snapshot and engine. Neither proves end-to-end model behavior.",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
