from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from codex_event_logger import is_sensitive_key, redact_string


DEFAULT_MAX_FILE_BYTES = 256 * 1024
DEFAULT_MAX_LINE_BYTES = 32 * 1024
DEFAULT_MAX_OPERATIONS = 80
DEFAULT_MAX_TEXT_CHARS = 12_000
MAX_COLLECTION_ITEMS = 100
MAX_VALUE_DEPTH = 8
TURN_DIRECTORY_PATTERN = re.compile(r"^\d{8}_\d{6}_\d{3}__")


def bounded_integer(name: str, minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise argparse.ArgumentTypeError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return parsed

    return parse


def safe_segment(value: str, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:160] or fallback


def truncate_text(value: str, max_chars: int) -> str:
    redacted = redact_string(value)
    if len(redacted) <= max_chars:
        return redacted
    marker = "<truncated>"
    if max_chars <= len(marker):
        return redacted[:max_chars]
    return redacted[: max_chars - len(marker)] + marker


def bounded_value(value: Any, max_chars: int, depth: int = 0) -> Any:
    if depth >= MAX_VALUE_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:MAX_COLLECTION_ITEMS]:
            key_text = truncate_text(str(key), max_chars)
            if is_sensitive_key(str(key)):
                output[key_text] = "<redacted>"
            else:
                output[key_text] = bounded_value(item, max_chars, depth + 1)
        if len(items) > MAX_COLLECTION_ITEMS:
            output["_bounded_items"] = len(items) - MAX_COLLECTION_ITEMS
        return output
    if isinstance(value, list):
        output = [
            bounded_value(item, max_chars, depth + 1)
            for item in value[:MAX_COLLECTION_ITEMS]
        ]
        if len(value) > MAX_COLLECTION_ITEMS:
            output.append({"_bounded_items": len(value) - MAX_COLLECTION_ITEMS})
        return output
    if isinstance(value, str):
        return truncate_text(value, max_chars)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return truncate_text(str(value), max_chars)


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def read_conversation(path: Path, max_file_bytes: int, max_text_chars: int) -> dict[str, Any]:
    size = file_size(path)
    result: dict[str, Any] = {
        "path": str(path),
        "size_bytes": size,
    }
    if size is None:
        result["status"] = "missing"
        return result
    if size > max_file_bytes:
        result.update(
            status="too_large",
            max_file_bytes=max_file_bytes,
        )
        return result

    with path.open("rb") as handle:
        raw = handle.read(max_file_bytes + 1)
    if len(raw) > max_file_bytes:
        result.update(
            status="grew_beyond_limit",
            max_file_bytes=max_file_bytes,
        )
        return result

    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        result.update(status="invalid_json", error=type(exc).__name__)
        return result

    result.update(status="ok", data=bounded_value(value, max_text_chars))
    return result


def read_file_operations(
    path: Path,
    max_file_bytes: int,
    max_line_bytes: int,
    max_operations: int,
    max_text_chars: int,
) -> dict[str, Any]:
    size = file_size(path)
    result: dict[str, Any] = {
        "path": str(path),
        "size_bytes": size,
        "max_file_bytes": max_file_bytes,
        "max_line_bytes": max_line_bytes,
        "max_operations": max_operations,
    }
    if size is None:
        result.update(status="missing", records=[])
        return result

    read_size = min(size, max_file_bytes)
    start = max(0, size - read_size)
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read(read_size)

    if start > 0:
        first_newline = raw.find(b"\n")
        raw = raw[first_newline + 1 :] if first_newline >= 0 else b""

    selected: deque[bytes] = deque(maxlen=max_operations)
    candidate_count = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        candidate_count += 1
        selected.append(line)

    records: list[Any] = []
    skipped_lines: list[dict[str, Any]] = []
    first_selected_index = max(0, candidate_count - len(selected))
    for offset, line in enumerate(selected):
        line_index = first_selected_index + offset + 1
        if len(line) > max_line_bytes:
            skipped_lines.append(
                {"line_in_window": line_index, "reason": "line_too_large", "size_bytes": len(line)}
            )
            continue
        try:
            value = json.loads(line.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            skipped_lines.append(
                {"line_in_window": line_index, "reason": type(exc).__name__}
            )
            continue
        records.append(bounded_value(value, max_text_chars))

    result.update(
        status="ok",
        read_bytes=read_size,
        truncated_by_size=size > max_file_bytes,
        truncated_by_count=candidate_count > max_operations,
        candidate_lines_in_window=candidate_count,
        skipped_lines=skipped_lines,
        records=records,
    )
    return result


def iter_turn_directories(session_dir: Path) -> Iterable[Path]:
    resolved_session = session_dir.resolve()
    for item in session_dir.iterdir():
        if not item.is_dir() or not TURN_DIRECTORY_PATTERN.match(item.name):
            continue
        try:
            item.resolve().relative_to(resolved_session)
        except (OSError, ValueError):
            continue
        yield item


def turn_metadata(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "conversation_size_bytes": file_size(path / "conversation.json"),
        "file_operations_size_bytes": file_size(path / "file-operations.jsonl"),
    }


def resolve_session_dir(project_root: Path, thread_id: str) -> Path:
    root = project_root.resolve()
    log_root = (root / "codexRuntimeLogFile").resolve()
    session_dir = (log_root / safe_segment(thread_id, "unknown_session")).resolve()
    try:
        session_dir.relative_to(log_root)
    except ValueError as exc:
        raise ValueError("resolved session directory is outside codexRuntimeLogFile") from exc
    if not session_dir.is_dir():
        raise FileNotFoundError(f"session directory not found: {session_dir}")
    return session_dir


def resolve_turn_dir(args: argparse.Namespace, session_dir: Path | None) -> Path:
    if args.turn_dir is not None:
        turn_dir = args.turn_dir.resolve()
    elif args.turn_name:
        if session_dir is None:
            raise ValueError("--turn-name requires a resolved session")
        if Path(args.turn_name).name != args.turn_name or args.turn_name in (".", ".."):
            raise ValueError("--turn-name must be one direct child directory name")
        turn_dir = (session_dir / args.turn_name).resolve()
        try:
            turn_dir.relative_to(session_dir)
        except ValueError as exc:
            raise ValueError("resolved turn directory is outside the selected session") from exc
    else:
        if session_dir is None:
            raise ValueError("a session or --turn-dir is required")
        try:
            turn_dir = max(iter_turn_directories(session_dir), key=lambda path: path.name)
        except ValueError as exc:
            raise FileNotFoundError(f"no turn directories found in: {session_dir}") from exc

    turn_dir = turn_dir.resolve()
    if session_dir is not None:
        try:
            turn_dir.relative_to(session_dir.resolve())
        except ValueError as exc:
            raise ValueError("resolved turn directory is outside the selected session") from exc
    if not turn_dir.is_dir():
        raise FileNotFoundError(f"turn directory not found: {turn_dir}")
    return turn_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read Codex event logs with enforced file, line, record, and text bounds."
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument("--turn-name")
    parser.add_argument("--turn-dir", type=Path)
    parser.add_argument(
        "--list-turns",
        type=bounded_integer("--list-turns", 1, 50),
        metavar="N",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=bounded_integer("--max-file-bytes", 1, 1024 * 1024),
        default=DEFAULT_MAX_FILE_BYTES,
    )
    parser.add_argument(
        "--max-line-bytes",
        type=bounded_integer("--max-line-bytes", 1, 64 * 1024),
        default=DEFAULT_MAX_LINE_BYTES,
    )
    parser.add_argument(
        "--max-operations",
        type=bounded_integer("--max-operations", 1, 200),
        default=DEFAULT_MAX_OPERATIONS,
    )
    parser.add_argument(
        "--max-text-chars",
        type=bounded_integer("--max-text-chars", 1, 20_000),
        default=DEFAULT_MAX_TEXT_CHARS,
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.turn_dir is not None and any(
        (args.thread_id, args.turn_name, args.list_turns)
    ):
        parser.error("--turn-dir cannot be combined with --thread-id, --turn-name, or --list-turns")
    if args.turn_dir is None and args.project_root is None:
        parser.error("--project-root is required unless --turn-dir is used")

    session_dir: Path | None = None
    try:
        if args.turn_dir is None:
            thread_id = args.thread_id or os.environ.get("CODEX_THREAD_ID")
            if not thread_id:
                raise ValueError("thread id is required; pass --thread-id or set CODEX_THREAD_ID")
            session_dir = resolve_session_dir(args.project_root, thread_id)

        if args.list_turns:
            assert session_dir is not None
            turns = heapq.nlargest(
                args.list_turns,
                iter_turn_directories(session_dir),
                key=lambda path: path.name,
            )
            output = {
                "mode": "list",
                "session_dir": str(session_dir),
                "limit": args.list_turns,
                "turns": [turn_metadata(path) for path in turns],
            }
        else:
            turn_dir = resolve_turn_dir(args, session_dir)
            output = {
                "mode": "read",
                "turn_dir": str(turn_dir),
                "limits": {
                    "max_file_bytes": args.max_file_bytes,
                    "max_line_bytes": args.max_line_bytes,
                    "max_operations": args.max_operations,
                    "max_text_chars": args.max_text_chars,
                },
                "conversation": read_conversation(
                    turn_dir / "conversation.json",
                    args.max_file_bytes,
                    args.max_text_chars,
                ),
                "file_operations": read_file_operations(
                    turn_dir / "file-operations.jsonl",
                    args.max_file_bytes,
                    args.max_line_bytes,
                    args.max_operations,
                    args.max_text_chars,
                ),
            }
    except (FileNotFoundError, OSError, ValueError) as exc:
        parser.error(str(exc))

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
