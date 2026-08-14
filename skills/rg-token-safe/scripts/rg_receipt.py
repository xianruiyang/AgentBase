#!/usr/bin/env python3
"""Run bounded ripgrep queries and emit a compact completeness receipt."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import BinaryIO


STDERR_LIMIT = 64 * 1024


class ReceiptError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run rg with a bounded N+1 completeness receipt.",
        allow_abbrev=False,
    )
    parser.add_argument("--mode", choices=("matches", "paths"), default="matches")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-text-chars", type=int, default=240)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--rg", default="rg.exe")
    parser.add_argument("rg_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 10_000:
        parser.error("--limit must be from 1 through 10000")
    if args.max_text_chars < 1 or args.max_text_chars > 16_384:
        parser.error("--max-text-chars must be from 1 through 16384")
    if args.rg_args[:1] == ["--"]:
        args.rg_args = args.rg_args[1:]
    if not args.rg_args:
        parser.error("native rg arguments are required after --")
    validate_native_args(parser, args.mode, args.rg_args)
    return args


def validate_native_args(
    parser: argparse.ArgumentParser, mode: str, native_args: list[str]
) -> None:
    output_flags = {
        "--json",
        "--heading",
        "--no-heading",
        "--count",
        "--count-matches",
        "--vimgrep",
        "--only-matching",
        "-o",
        "-q",
        "--quiet",
        "--passthru",
        "--stats",
        "--debug",
        "--trace",
        "--type-list",
        "--null",
        "-0",
        "--null-data",
    }
    context_prefixes = (
        "-A",
        "-B",
        "-C",
        "--after-context",
        "--before-context",
        "--context",
    )
    mutation_or_preprocess = {"-r", "--replace", "--pre", "--pre-glob"}
    if any(arg in output_flags for arg in native_args):
        parser.error("rg output formatting is owned by the receipt wrapper")
    if mode == "matches" and any(
        arg.startswith("-m") or arg == "--max-count" or arg.startswith("--max-count=")
        for arg in native_args
    ):
        parser.error("match limits would invalidate the completeness receipt")
    if any(arg.startswith(context_prefixes) for arg in native_args):
        parser.error("receipt queries do not accept context flags; read selected files directly")
    if any(arg in mutation_or_preprocess for arg in native_args):
        parser.error("receipt queries do not accept replacement or preprocessor flags")
    path_modes = {"-l", "--files-with-matches", "--files"}
    has_path_mode = any(arg in path_modes for arg in native_args)
    if "--files-without-match" in native_args:
        parser.error("--files-without-match is not a supported receipt mode")
    if mode == "matches" and has_path_mode:
        parser.error("path-list arguments require --mode paths")
    if mode == "paths" and not has_path_mode:
        parser.error("--mode paths requires -l, --files-with-matches, or --files")


def drain_stderr(stream: BinaryIO, chunks: list[bytes]) -> None:
    retained = 0
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        if retained < STDERR_LIMIT:
            keep = chunk[: STDERR_LIMIT - retained]
            chunks.append(keep)
            retained += len(keep)


def value_text(value: object) -> str:
    if not isinstance(value, dict):
        raise ReceiptError("rg JSON text field is not an object")
    text = value.get("text")
    if isinstance(text, str):
        return text
    encoded = value.get("bytes")
    if isinstance(encoded, str):
        try:
            return os.fsdecode(base64.b64decode(encoded, validate=True))
        except (ValueError, base64.binascii.Error) as error:
            raise ReceiptError("rg JSON bytes field is invalid base64") from error
    raise ReceiptError("rg JSON text field has neither text nor bytes")


def match_record(line: bytes, max_text_chars: int) -> tuple[str, str, bool] | None:
    try:
        event = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptError("rg emitted invalid UTF-8 JSON") from error
    if event.get("type") != "match":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        raise ReceiptError("rg match event is missing data")
    path = value_text(data.get("path"))
    line_number = data.get("line_number")
    if not isinstance(line_number, int) or line_number < 1:
        raise ReceiptError("rg match event has an invalid line number")
    text = value_text(data.get("lines")).rstrip("\r\n")
    truncated = len(text) > max_text_chars
    if truncated:
        text = f"{text[:max_text_chars]}…"
    return path.replace("\\", "/"), f"{line_number}:{text}", truncated


def path_record(line: bytes) -> str | None:
    value = os.fsdecode(line).rstrip("\r\n")
    return value.replace("\\", "/") if value else None


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def run(args: argparse.Namespace) -> tuple[list[object], bool, int]:
    command = [args.rg, *args.rg_args]
    if args.mode == "matches":
        command.insert(1, "--json")
    process = subprocess.Popen(
        command,
        cwd=args.cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_chunks: list[bytes] = []
    stderr_thread = threading.Thread(
        target=drain_stderr, args=(process.stderr, stderr_chunks), daemon=True
    )
    stderr_thread.start()
    records: list[object] = []
    text_truncated = 0
    cutoff = False
    try:
        for line in process.stdout:
            if args.mode == "matches":
                parsed = match_record(line, args.max_text_chars)
                if parsed is None:
                    continue
                path, match, was_truncated = parsed
                record: object = (path, match)
                text_truncated += int(was_truncated)
            else:
                record = path_record(line)
                if record is None:
                    continue
            if len(records) == args.limit:
                cutoff = True
                terminate_process(process)
                break
            records.append(record)
    except Exception:
        terminate_process(process)
        raise
    finally:
        process.stdout.close()
    return_code = process.wait()
    stderr_thread.join(timeout=2)
    stderr = b"".join(stderr_chunks)
    if not cutoff and return_code not in (0, 1):
        if stderr:
            sys.stderr.buffer.write(stderr)
        raise SystemExit(return_code)
    return records, not cutoff, text_truncated


def emit_matches(records: list[object]) -> None:
    groups: list[tuple[str, list[str]]] = []
    index: dict[str, int] = {}
    for value in records:
        path, match = value
        group_index = index.get(path)
        if group_index is None:
            index[path] = len(groups)
            groups.append((path, [match]))
        else:
            groups[group_index][1].append(match)
    print("results:")
    for path, matches in groups:
        print(f"- file: {json.dumps(path, ensure_ascii=False)}")
        print("  matches:")
        for match in matches:
            print(f"  - {json.dumps(match, ensure_ascii=False)}")


def emit(args: argparse.Namespace, records: list[object], complete: bool, truncated: int) -> None:
    metadata = {
        "mode": args.mode,
        "shown": len(records),
        "complete": complete,
        "text_complete": truncated == 0,
    }
    print(f"_rg: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))}")
    if args.mode == "matches":
        emit_matches(records)
    else:
        print("results:")
        for value in records:
            print(f"- {json.dumps(value, ensure_ascii=False)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    if os.name != "nt":
        print("rg_receipt.py supports only Windows", file=sys.stderr)
        return 2
    args = parse_args()
    try:
        records, complete, truncated = run(args)
    except FileNotFoundError as error:
        print(f"rg receipt could not start {args.rg!r}: {error}", file=sys.stderr)
        return 2
    except ReceiptError as error:
        print(f"rg receipt rejected output: {error}", file=sys.stderr)
        return 2
    emit(args, records, complete, truncated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
