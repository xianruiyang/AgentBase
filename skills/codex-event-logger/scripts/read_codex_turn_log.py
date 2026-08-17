from __future__ import annotations

import argparse
import copy
import heapq
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Iterator

from codex_event_logger import is_sensitive_key, redact_string


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_MAX_FILE_BYTES = 256 * 1024
DEFAULT_MAX_LINE_BYTES = 32 * 1024
DEFAULT_MAX_OPERATIONS = 80
DEFAULT_MAX_TEXT_CHARS = 12_000
DEFAULT_MODEL_TOKEN_BUDGET = 2_048
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


def model_text_cost(text: str) -> int:
    total = 0
    ascii_word = 0
    for character in text:
        if character.isascii() and (character.isalnum() or character == "_"):
            ascii_word += 1
            continue
        if ascii_word:
            total += (ascii_word + 3) // 4
            ascii_word = 0
        if character == "\n" or not character.isspace():
            total += 1
    return total + (ascii_word + 3) // 4


def model_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    reserved = {"null", "true", "false", "yes", "no", "on", "off", "~"}
    unsafe_start = "-?:,[]{}#&*!|>'\"%@`"
    if (
        text
        and text == text.strip()
        and "\n" not in text
        and not text.startswith(tuple(unsafe_start))
        and not any(character in text for character in "{}[],:#\"")
        and text.lower() not in reserved
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


def compact_model(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{key}:{compact_model(item)}" for key, item in value.items()
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(compact_model(item) for item in value) + "]"
    return model_scalar(value)


def render_model_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            compact = compact_model(item)
            if len(compact) <= 800:
                lines.append(f"{prefix}{key}:{compact}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(render_model_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}:{model_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            compact = compact_model(item)
            if len(compact) <= 2_400:
                lines.append(f"{prefix}- {compact}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(render_model_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {model_scalar(item)}")
        return lines
    return [f"{prefix}{model_scalar(value)}"]


def render_model(value: Any) -> str:
    lines = render_model_lines(value)
    return "\n".join(lines) if lines else "ok"


def sparse_model_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            projected = sparse_model_value(item)
            if projected in (None, "", [], {}):
                continue
            result[key] = projected
        return result
    if isinstance(value, list):
        return [
            projected
            for item in value
            if (projected := sparse_model_value(item)) not in (None, "", [], {})
        ]
    return value


def excerpt_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    marker = "…"
    if max_chars <= len(marker):
        return value[:max_chars], True
    head = max(1, (max_chars - len(marker)) * 2 // 3)
    tail = max_chars - len(marker) - head
    return value[:head] + marker + (value[-tail:] if tail else ""), True


def recovery_hint(turn_name: str) -> str:
    return (
        f"repeat turn {turn_name} with a larger --model-token-budget "
        "or explicit --view machine"
    )


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


def status_issue(source_name: str, value: dict[str, Any], turn_name: str) -> dict[str, Any]:
    issue = {
        "source": source_name,
        "status": value.get("status", "unknown"),
    }
    for key in ("size_bytes", "max_file_bytes", "error"):
        if value.get(key) not in (None, ""):
            issue[key] = value[key]
    issue["recovery"] = recovery_hint(turn_name)
    return issue


def project_goal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = {
        "id": value.get("goal_id"),
        "objective": value.get("objective"),
        "status": value.get("status"),
        "token_budget": value.get("token_budget"),
        "tokens_used": value.get("tokens_used"),
    }
    return sparse_model_value(projected)


def project_path(value: Any, base_path: Path | None) -> tuple[Any, bool]:
    if not isinstance(value, str) or base_path is None:
        return value, False
    try:
        relative = Path(value).resolve(strict=False).relative_to(
            base_path.resolve(strict=False)
        )
    except (OSError, ValueError):
        return value, False
    return relative.as_posix() or ".", True


def project_operation(value: Any, base_path: Path | None) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, dict):
        return {}, False
    path, path_is_relative = project_path(value.get("path"), base_path)
    old_path, old_path_is_relative = project_path(value.get("old_path"), base_path)
    projected = {
        "op": value.get("operation"),
        "path": path,
        "old_path": old_path,
        "lines": value.get("line_ranges"),
    }
    return sparse_model_value(projected), path_is_relative or old_path_is_relative


def merge_line_ranges(current: Any, incoming: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for kind in ("added", "deleted"):
        intervals: list[tuple[int, int]] = []
        for source in (current, incoming):
            if not isinstance(source, dict):
                continue
            for row in source.get(kind, []):
                if not isinstance(row, dict):
                    continue
                start = row.get("start")
                end = row.get("end")
                if isinstance(start, int) and isinstance(end, int) and start <= end:
                    intervals.append((start, end))
        compacted: list[tuple[int, int]] = []
        for start, end in sorted(set(intervals)):
            if compacted and start <= compacted[-1][1] + 1:
                compacted[-1] = (compacted[-1][0], max(compacted[-1][1], end))
            else:
                compacted.append((start, end))
        if compacted:
            merged[kind] = [
                {"start": start, "end": end} for start, end in compacted
            ]
    return merged


def project_operations(
    records: Any, base_path: Path | None
) -> tuple[list[dict[str, Any]], int, bool]:
    if not isinstance(records, list):
        return [], 1, False
    rows: list[dict[str, Any] | None] = []
    active_by_path: dict[str, int] = {}
    unprojected = 0
    used_base = False
    for record in records:
        row, row_used_base = project_operation(record, base_path)
        used_base = used_base or row_used_base
        operation = row.get("op")
        path = row.get("path")
        if not isinstance(operation, str) or not isinstance(path, str):
            unprojected += 1
            continue

        if operation == "move":
            old_path = row.get("old_path")
            if isinstance(old_path, str):
                active_by_path.pop(old_path, None)
            active_by_path.pop(path, None)
            rows.append(row)
            continue

        prior_index = active_by_path.get(path)
        prior = rows[prior_index] if prior_index is not None else None
        prior_operation = prior.get("op") if isinstance(prior, dict) else None

        if operation == "modify" and prior_operation in {"create", "modify", "replace"}:
            assert isinstance(prior, dict)
            lines = merge_line_ranges(prior.get("lines"), row.get("lines"))
            if lines:
                prior["lines"] = lines
            continue

        if operation == "create" and prior_operation in {"create", "modify", "replace"}:
            assert isinstance(prior, dict)
            lines = merge_line_ranges(prior.get("lines"), row.get("lines"))
            if lines:
                prior["lines"] = lines
            continue

        if operation == "create" and prior_operation == "delete":
            assert isinstance(prior, dict)
            prior["op"] = "replace"
            lines = merge_line_ranges(None, row.get("lines"))
            if lines:
                prior["lines"] = lines
            continue

        if operation == "delete" and prior_operation == "create":
            assert prior_index is not None
            rows[prior_index] = None
            active_by_path.pop(path, None)
            continue

        if operation == "delete" and prior_operation in {"modify", "replace"}:
            assert isinstance(prior, dict)
            prior["op"] = "delete"
            prior.pop("lines", None)
            continue

        if operation == "delete" and prior_operation == "delete":
            continue

        rows.append(row)
        active_by_path[path] = len(rows) - 1

    return [row for row in rows if isinstance(row, dict)], unprojected, used_base


def model_list_projection(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "turns": [
            turn.get("name")
            for turn in output.get("turns", [])
            if isinstance(turn, dict) and turn.get("name")
        ]
    }


def model_read_projection(output: dict[str, Any]) -> dict[str, Any]:
    turn_path = Path(str(output.get("turn_dir", "unknown_turn")))
    turn_name = turn_path.name
    projected: dict[str, Any] = {"turn": turn_name}
    issues: list[dict[str, Any]] = []
    base_path: Path | None = None
    for parent in turn_path.resolve(strict=False).parents:
        if parent.name.casefold() == "codexruntimelogfile":
            base_path = parent.parent
            break

    conversation = output.get("conversation", {})
    if not isinstance(conversation, dict) or conversation.get("status") != "ok":
        issues.append(
            status_issue(
                "conversation",
                conversation if isinstance(conversation, dict) else {},
                turn_name,
            )
        )
    else:
        data = conversation.get("data")
        if isinstance(data, dict):
            cwd = data.get("cwd")
            if base_path is None and isinstance(cwd, str) and Path(cwd).is_absolute():
                base_path = Path(cwd)
            turn_source = data.get("source") or data.get("turn_source")
            if turn_source and turn_source != "user_prompt":
                projected["source"] = turn_source
            if data.get("prompt"):
                projected["prompt"] = data["prompt"]
            if data.get("last_assistant_message"):
                projected["assistant"] = data["last_assistant_message"]
            goal = project_goal(data.get("goal"))
            if goal:
                projected["goal"] = goal
        else:
            issues.append(
                {
                    "source": "conversation",
                    "status": "invalid_shape",
                    "recovery": recovery_hint(turn_name),
                }
            )

    operations = output.get("file_operations", {})
    if not isinstance(operations, dict) or operations.get("status") != "ok":
        issues.append(
            status_issue(
                "file_operations",
                operations if isinstance(operations, dict) else {},
                turn_name,
            )
        )
    else:
        files, unprojected, used_base = project_operations(
            operations.get("records", []), base_path
        )
        if files:
            if used_base and base_path is not None:
                projected["base"] = str(base_path)
            projected["files"] = files
        partial: dict[str, Any] = {}
        if operations.get("truncated_by_size"):
            partial["by_size"] = True
        if operations.get("truncated_by_count"):
            partial["by_count"] = True
        if partial:
            partial.update(
                {
                    "source": "file_operations",
                    "status": "partial",
                    "candidate_lines": operations.get("candidate_lines_in_window"),
                    "recovery": recovery_hint(turn_name),
                }
            )
            issues.append(sparse_model_value(partial))
        skipped = operations.get("skipped_lines", [])
        if skipped:
            reasons: dict[str, int] = {}
            for row in skipped:
                reason = row.get("reason", "unknown") if isinstance(row, dict) else "unknown"
                reasons[reason] = reasons.get(reason, 0) + 1
            issues.append(
                {
                    "source": "file_operations",
                    "status": "skipped_lines",
                    "count": len(skipped),
                    "reasons": reasons,
                    "recovery": recovery_hint(turn_name),
                }
            )
        if unprojected:
            issues.append(
                {
                    "source": "file_operations",
                    "status": "unrecognized_records",
                    "count": unprojected,
                    "recovery": recovery_hint(turn_name),
                }
            )

    if issues:
        projected["issues"] = issues
    return sparse_model_value(projected)


def add_more(candidate: dict[str, Any], turn_name: str, **details: Any) -> None:
    more = candidate.setdefault("more", {})
    more.update({key: value for key, value in details.items() if value not in (None, "", [], {})})
    more["recovery"] = recovery_hint(turn_name)


def omit_line_ranges(value: dict[str, Any], turn_name: str) -> dict[str, Any]:
    candidate = copy.deepcopy(value)
    omitted = False
    for row in candidate.get("files", []):
        if isinstance(row, dict) and row.pop("lines", None):
            omitted = True
    if omitted:
        add_more(candidate, turn_name, omitted=["file_line_ranges"])
    return candidate


def group_file_operations(value: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(value)
    files = candidate.get("files")
    if not isinstance(files, list):
        return candidate
    grouped: dict[str, list[Any]] = {}
    for row in files:
        if not isinstance(row, dict) or not row.get("op") or not row.get("path"):
            continue
        operation = str(row["op"])
        if operation == "move" and row.get("old_path"):
            item: Any = {"from": row["old_path"], "to": row["path"]}
        else:
            item = row["path"]
        grouped.setdefault(operation, []).append(item)
    if grouped:
        candidate["files"] = grouped
    return candidate


def cap_recovery_text(
    value: dict[str, Any],
    turn_name: str,
    *,
    prompt_chars: int,
    assistant_chars: int,
    objective_chars: int,
) -> dict[str, Any]:
    candidate = copy.deepcopy(value)
    omitted: list[str] = []
    for key, limit in (("prompt", prompt_chars), ("assistant", assistant_chars)):
        text = candidate.get(key)
        if isinstance(text, str):
            candidate[key], shortened = excerpt_text(text, limit)
            if shortened:
                omitted.append(key)
    goal = candidate.get("goal")
    if isinstance(goal, dict) and isinstance(goal.get("objective"), str):
        goal["objective"], shortened = excerpt_text(goal["objective"], objective_chars)
        if shortened:
            omitted.append("goal.objective")
    if omitted:
        add_more(candidate, turn_name, omitted_text=omitted)
    return candidate


def model_variants(output: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if output.get("mode") == "list":
        projected = model_list_projection(output)
        yield projected
        turns = projected.get("turns", [])
        for limit in (25, 10, 5, 1):
            if len(turns) <= limit:
                continue
            candidate = {"turns": turns[:limit]}
            candidate["more"] = {
                "omitted_turns": len(turns) - limit,
                "recovery": "raise --model-token-budget or request fewer recent turns",
            }
            yield candidate
        return

    projected = model_read_projection(output)
    turn_name = str(projected.get("turn", "unknown_turn"))
    yield projected

    compact_files = omit_line_ranges(projected, turn_name)
    grouped_files = group_file_operations(compact_files)
    if grouped_files != projected:
        yield grouped_files

    text_limits = (
        (8_000, 8_000, 1_000),
        (4_000, 3_000, 800),
        (2_000, 1_600, 600),
        (1_000, 800, 400),
        (500, 400, 240),
        (240, 240, 160),
    )
    smallest_text = grouped_files
    for prompt_chars, assistant_chars, objective_chars in text_limits:
        candidate = cap_recovery_text(
            grouped_files,
            turn_name,
            prompt_chars=prompt_chars,
            assistant_chars=assistant_chars,
            objective_chars=objective_chars,
        )
        smallest_text = candidate
        if candidate != grouped_files:
            yield candidate

    files = compact_files.get("files", [])
    if isinstance(files, list):
        for limit in (40, 20, 10, 5, 1):
            if len(files) <= limit:
                continue
            candidate = copy.deepcopy(smallest_text)
            candidate["files"] = group_file_operations(
                {"files": files[-limit:]}
            )["files"]
            add_more(candidate, turn_name, omitted_files=len(files) - limit)
            yield candidate

    core: dict[str, Any] = {"turn": turn_name}
    goal = projected.get("goal")
    if isinstance(goal, dict):
        core_goal = {
            "status": goal.get("status"),
            "objective": goal.get("objective"),
        }
        if isinstance(core_goal["objective"], str):
            core_goal["objective"], _ = excerpt_text(core_goal["objective"], 160)
        core["goal"] = sparse_model_value(core_goal)
    if projected.get("issues"):
        core["issues"] = projected["issues"]
    if projected.get("files"):
        core["file_count"] = len(projected["files"])
    add_more(core, turn_name, reason="model_token_budget")
    yield sparse_model_value(core)

    yield {
        "turn": turn_name,
        "more": {
            "reason": "model_token_budget",
            "recovery": recovery_hint(turn_name),
        },
    }


def fit_model_output(output: dict[str, Any], budget: int) -> str:
    for candidate in model_variants(output):
        text = render_model(candidate)
        if model_text_cost(text) <= budget:
            return text
    raise ValueError("--model-token-budget is too small for a recoverable response")


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
        description=(
            "Read Codex event logs through a bounded model projection or the explicit "
            "complete machine contract."
        )
    )
    parser.add_argument("--view", choices=("model", "machine"), default="model")
    parser.add_argument(
        "--model-token-budget",
        type=bounded_integer("--model-token-budget", 256, 100_000),
        default=DEFAULT_MODEL_TOKEN_BUDGET,
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

    if args.view == "machine":
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        try:
            text = fit_model_output(output, args.model_token_budget)
        except ValueError as exc:
            parser.error(str(exc))
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
