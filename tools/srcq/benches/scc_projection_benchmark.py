from __future__ import annotations

import argparse
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


def measurement(data: bytes, encodings: dict[str, Any]) -> dict[str, Any]:
    text = data.decode("utf-8")
    return {
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srcq", type=Path, required=True)
    parser.add_argument("--scc", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if os.name != "nt":
        raise SystemExit("the scc projection benchmark is maintained only on Windows")
    srcq = args.srcq.resolve(strict=True)
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
    model_languages = run(
        srcq,
        [
            "query",
            "scc",
            "exec",
            "--engine",
            str(scc),
            "--view",
            "languages",
            "--limit",
            "10000",
            "--model-token-budget",
            "1000000",
            "--",
            "--format",
            "json2",
            ".",
        ],
        root,
    )
    model_files = run(
        srcq,
        [
            "query",
            "scc",
            "exec",
            "--engine",
            str(scc),
            "--view",
            "files",
            "--limit",
            "10000",
            "--model-token-budget",
            "1000000",
            "--",
            "--by-file",
            "--format",
            "json2",
            ".",
        ],
        root,
    )
    for label, data in {"languages": model_languages, "files": model_files}.items():
        text = data.decode("utf-8")
        if "@more" in text:
            raise RuntimeError(f"{label} model projection was not complete")
        if any(term in text for term in ("estimatedCost", "estimatedSchedule", "COCOMO")):
            raise RuntimeError(f"{label} model projection leaked cost estimates")

    language_document = json.loads(raw_languages)
    file_document = json.loads(raw_files)
    language_summary = language_document.get("languageSummary")
    file_summary = file_document.get("languageSummary")
    if not isinstance(language_summary, list) or not isinstance(file_summary, list):
        raise RuntimeError("scc json2 is missing languageSummary")
    result = {
        "schema": "srcq.scc-projection-benchmark/v1",
        "root": str(root),
        "srcq_version": version(srcq, root),
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
            "files": compare(raw_files, model_files, encodings),
        },
        "boundary": "Token counts compare complete raw json2 with the complete task-facing direct-metric projection; they do not prove end-to-end model behavior.",
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
