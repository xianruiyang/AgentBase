from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
)


TOKEN_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def folder_stamp() -> str:
    dt = datetime.now().astimezone()
    return dt.strftime("%Y%m%d_%H%M%S_") + f"{dt.microsecond // 1000:03d}"


def load_json_file(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def cleanup_json_temps(path: Path) -> None:
    try:
        for tmp in path.parent.glob(f"{path.name}.tmp.*"):
            if tmp.is_file():
                tmp.unlink()
    except Exception:
        pass


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        tmp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        cleanup_json_temps(path)


@contextmanager
def file_lock(lock_path: Path, timeout_seconds: float = 3.0):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock timeout: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def safe_segment(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:160] or fallback


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_string(value: str) -> str:
    result = value
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "<redacted>", result)
    return result


def sanitize(value: Any, max_string_chars: int) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if is_sensitive_key(str(key)):
                clean[str(key)] = "<redacted>"
            else:
                clean[str(key)] = sanitize(item, max_string_chars)
        return clean
    if isinstance(value, list):
        return [sanitize(item, max_string_chars) for item in value]
    if isinstance(value, str):
        text = redact_string(value)
        if len(text) > max_string_chars:
            return text[:max_string_chars] + f"\n<truncated {len(text) - max_string_chars} chars>"
        return text
    return value


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[key] = value
    return merged


def find_project_root(cwd: Path, workspace_roots: list[str]) -> Path:
    try:
        cwd = cwd.resolve()
    except Exception:
        cwd = Path.cwd().resolve()

    candidates: list[Path] = []
    for raw in workspace_roots:
        if not raw:
            continue
        root = Path(raw).expanduser()
        try:
            root = root.resolve()
            cwd.relative_to(root)
            candidates.append(root)
        except Exception:
            continue
    if candidates:
        return max(candidates, key=lambda p: len(str(p)))

    strong_markers = (".git", ".codex", "package.json", "pyproject.toml")
    for current in (cwd, *cwd.parents):
        if any((current / marker).exists() for marker in strong_markers):
            return current
        try:
            if any(current.glob("*.uproject")):
                return current
        except Exception:
            pass
    for current in (cwd, *cwd.parents):
        if (current / "AGENTS.md").exists():
            return current
    return cwd


def path_matches_any(path: Path, roots: list[str]) -> bool:
    if not roots:
        return True
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    for raw in roots:
        try:
            root = Path(raw).expanduser().resolve()
            resolved.relative_to(root)
            return True
        except Exception:
            continue
    return False


def get_event(payload: dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or payload.get("event") or "")


def get_session_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("session_id")
        or payload.get("thread_id")
        or payload.get("threadId")
        or os.environ.get("CODEX_THREAD_ID")
        or "unknown_session"
    )


def get_turn_id(payload: dict[str, Any]) -> str:
    return str(payload.get("turn_id") or payload.get("turnId") or "unknown_turn")


def read_stdin_text() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is not None:
        data = stream.read()
        return data.decode("utf-8-sig", errors="replace")
    return sys.stdin.read().lstrip("\ufeff")


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def goal_db_path(config: dict[str, Any]) -> Path:
    configured = config.get("goal_db_path") or os.environ.get("CODEX_EVENT_LOGGER_GOAL_DB")
    if configured:
        return Path(str(configured)).expanduser()
    return codex_home() / "goals_1.sqlite"


def normalize_goal_thread_id(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("client-new-thread:"):
        text = text.split(":", 1)[1]
    return text


def active_goal_for_thread(thread_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
    if not config.get("record_active_goal", True):
        return None
    normalized = normalize_goal_thread_id(thread_id)
    if not normalized or normalized == "unknown_session":
        return None

    db_path = goal_db_path(config)
    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                select goal_id, objective, status, token_budget, tokens_used,
                       time_used_seconds, created_at_ms, updated_at_ms
                from thread_goals
                where thread_id = ?
                """,
                (normalized,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    if not row:
        return None
    goal = dict(row)
    status = str(goal.get("status") or "").strip().lower()
    if status not in {"active", "in_progress", "running"}:
        return None
    goal["active"] = True
    return goal


def sanitize_goal(goal: dict[str, Any], max_text: int) -> dict[str, Any]:
    allowed = (
        "objective",
        "status",
        "token_budget",
        "tokens_used",
        "time_used_seconds",
    )
    clean = {key: goal.get(key) for key in allowed if goal.get(key) is not None}
    if clean.get("objective") is not None:
        clean["objective"] = sanitize(clean.get("objective"), max_text)
    return clean


def compact_value(value: Any) -> bool:
    return value is not None and value != ""


def is_goal_internal_prompt(text: str) -> bool:
    return text.lstrip().startswith('<codex_internal_context source="goal">')


def prompt_fields(text: Any, max_text: int, source: str) -> dict[str, Any]:
    if not isinstance(text, str):
        return {}
    if is_goal_internal_prompt(text):
        return {"source": "goal"}
    return {
        "source": source,
        "prompt": sanitize(text, max_text),
    }


def compact_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    source = conversation.get("source") or conversation.get("turn_source")
    ordered = {
        "source": source,
        "prompt_ts": conversation.get("prompt_ts"),
        "stop_ts": conversation.get("stop_ts"),
        "prompt": conversation.get("prompt"),
        "last_assistant_message": conversation.get("last_assistant_message"),
        "goal": conversation.get("goal"),
    }
    return {key: value for key, value in ordered.items() if compact_value(value)}


def content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def transcript_turn_messages(transcript_path: Any, turn_id: str, max_text: int) -> dict[str, Any]:
    if not transcript_path:
        return {}
    path = Path(str(transcript_path).replace("\\\\?\\", ""))
    if not path.exists() or not path.is_file():
        return {}

    result: dict[str, Any] = {}
    last_assistant: str | None = None
    last_assistant_ts: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                meta = payload.get("internal_chat_message_metadata_passthrough")
                if not isinstance(meta, dict) or str(meta.get("turn_id") or "") != turn_id:
                    continue
                text = content_text(payload.get("content"))
                if not text:
                    continue
                role = payload.get("role")
                if role == "user" and "prompt" not in result:
                    result.update(prompt_fields(text, max_text, "transcript_user_prompt"))
                    result["prompt_ts"] = row.get("timestamp")
                elif role == "assistant":
                    last_assistant = str(sanitize(text, max_text))
                    last_assistant_ts = row.get("timestamp")
                    if payload.get("phase") == "final":
                        result["last_assistant_message"] = last_assistant
                        result["stop_ts"] = last_assistant_ts
    except Exception:
        return result

    if last_assistant and "last_assistant_message" not in result:
        result["last_assistant_message"] = last_assistant
        result["assistant_message_ts"] = last_assistant_ts
    return result


def ensure_turn_dir(
    project_root: Path,
    config: dict[str, Any],
    session_id: str,
    turn_id: str,
) -> tuple[Path, Path, Path]:
    output_dir = str(config.get("output_dir_name") or "codexRuntimeLogFile")
    session_dir = project_root / output_dir / safe_segment(session_id, "unknown_session")
    safe_turn = safe_segment(turn_id, "unknown_turn")
    index_path = session_dir / ".turn-index.json"
    timeout = float(config.get("lock_timeout_seconds") or 3)

    with file_lock(session_dir / ".turn-index.lock", timeout):
        index = load_json_file(index_path, {})
        if not isinstance(index, dict):
            index = {}
        folder_name = index.get(turn_id)
        if not folder_name:
            folder_name = f"{folder_stamp()}__{safe_turn}"
            index[turn_id] = folder_name
            write_json_atomic(index_path, index)

    turn_dir = session_dir / safe_segment(folder_name, f"{folder_stamp()}__{safe_turn}")
    turn_dir.mkdir(parents=True, exist_ok=True)
    conversation_file = turn_dir / str(config.get("conversation_file_name") or "conversation.json")
    file_operations_file = turn_dir / str(
        config.get("file_operations_file_name") or "file-operations.jsonl"
    )
    if not file_operations_file.exists():
        file_operations_file.touch()
    if not conversation_file.exists():
        initial = {
            "source": "unknown",
        }
        active_goal = active_goal_for_thread(session_id, config)
        if active_goal:
            max_text = int(config.get("max_text_chars") or 12000)
            initial["goal"] = sanitize_goal(active_goal, max_text)
        write_json_atomic(conversation_file, initial)
    return turn_dir, conversation_file, file_operations_file


def update_conversation(
    conversation_file: Path,
    payload: dict[str, Any],
    event: str,
    session_id: str,
    turn_id: str,
    config: dict[str, Any],
) -> None:
    timeout = float(config.get("lock_timeout_seconds") or 3)
    max_text = int(config.get("max_text_chars") or 12000)
    active_goal = active_goal_for_thread(session_id, config)
    with file_lock(conversation_file.with_suffix(".lock"), timeout):
        conversation = load_json_file(conversation_file, {})
        if not isinstance(conversation, dict):
            conversation = {}
        if active_goal:
            conversation["goal"] = sanitize_goal(active_goal, max_text)

        if event == "UserPromptSubmit":
            conversation["prompt_ts"] = now_iso()
            conversation.update(prompt_fields(payload.get("prompt"), max_text, "user_prompt"))
        elif event == "Stop":
            conversation["stop_ts"] = now_iso()
            if conversation.get("source") not in ("user_prompt", "transcript_user_prompt", "goal"):
                conversation["source"] = "auto_or_goal_turn"
            conversation["last_assistant_message"] = sanitize(
                payload.get("last_assistant_message")
                or payload.get("final_response")
                or payload.get("assistant_final"),
                max_text,
            )

        if not conversation.get("prompt") or not conversation.get("last_assistant_message"):
            transcript = transcript_turn_messages(
                payload.get("transcript_path"),
                turn_id,
                max_text,
            )
            for key, value in transcript.items():
                if value is not None and (
                    not conversation.get(key)
                    or (key == "source" and conversation.get(key) == "unknown")
                ):
                    conversation[key] = value

        write_json_atomic(conversation_file, compact_conversation(conversation))


def backfill_conversation_from_transcript(
    conversation_file: Path,
    payload: dict[str, Any],
    event: str,
    session_id: str,
    turn_id: str,
    config: dict[str, Any],
) -> None:
    max_text = int(config.get("max_text_chars") or 12000)
    transcript = transcript_turn_messages(payload.get("transcript_path"), turn_id, max_text)

    timeout = float(config.get("lock_timeout_seconds") or 3)
    with file_lock(conversation_file.with_suffix(".lock"), timeout):
        conversation = load_json_file(conversation_file, {})
        if not isinstance(conversation, dict):
            conversation = {}
        if transcript:
            for key, value in transcript.items():
                if value is not None and (
                    not conversation.get(key)
                    or (key == "source" and conversation.get(key) == "unknown")
                ):
                    conversation[key] = value
        elif conversation.get("source") in (None, "", "unknown"):
            conversation["source"] = "tool_operation"
        write_json_atomic(conversation_file, compact_conversation(conversation))


def payload_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(payload_strings(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(payload_strings(item))
        return result
    return []


def payload_text(value: Any) -> str:
    strings = payload_strings(value)
    if strings:
        return "\n".join(strings)
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def normalize_path(raw_path: str, project_root: Path, cwd: Path | None) -> str:
    text = raw_path.strip().strip("\"'")
    if not text:
        return text
    path = Path(text)
    if path.is_absolute():
        return str(path)
    base = cwd if cwd is not None else project_root
    try:
        return str((base / path).resolve())
    except Exception:
        return str(base / path)


def read_text_if_exists(path: str) -> tuple[bool, str]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return False, ""
    try:
        return True, target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return True, target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return True, ""
    except Exception:
        return True, ""


def line_ranges(before_text: str, after_text: str) -> dict[str, list[dict[str, int]]]:
    before_lines = before_text.splitlines()
    after_lines = after_text.splitlines()
    added: list[dict[str, int]] = []
    deleted: list[dict[str, int]] = []

    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete") and i1 < i2:
            deleted.append({"start": i1 + 1, "end": i2})
        if tag in ("replace", "insert") and j1 < j2:
            added.append({"start": j1 + 1, "end": j2})

    return {"added": added, "deleted": deleted}


def has_line_ranges(value: dict[str, list[dict[str, int]]]) -> bool:
    return bool(value.get("added") or value.get("deleted"))


def file_operation_record(
    source: str,
    operation: str,
    path: str,
    old_path: str | None = None,
    ranges: dict[str, list[dict[str, int]]] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "ts": now_iso(),
        "source": source,
        "operation": operation,
        "path": path,
    }
    if operation == "move" and old_path:
        record["old_path"] = old_path
    if ranges and has_line_ranges(ranges):
        record["line_ranges"] = ranges
    return record


def parse_apply_patch_targets(
    patch_text: str,
    project_root: Path,
    cwd: Path | None,
) -> list[dict[str, str | None]]:
    targets: list[dict[str, str | None]] = []
    pending_update: str | None = None

    def flush_update() -> None:
        nonlocal pending_update
        if pending_update:
            path = normalize_path(pending_update, project_root, cwd)
            targets.append({"operation": "modify", "path": path, "old_path": None})
            pending_update = None

    for line in patch_text.splitlines():
        if line.startswith("*** Add File: "):
            flush_update()
            raw = line[len("*** Add File: ") :].strip()
            path = normalize_path(raw, project_root, cwd)
            targets.append({"operation": "create", "path": path, "old_path": None})
        elif line.startswith("*** Delete File: "):
            flush_update()
            raw = line[len("*** Delete File: ") :].strip()
            path = normalize_path(raw, project_root, cwd)
            targets.append({"operation": "delete", "path": path, "old_path": None})
        elif line.startswith("*** Update File: "):
            flush_update()
            pending_update = line[len("*** Update File: ") :].strip()
        elif line.startswith("*** Move to: ") and pending_update:
            old_path = normalize_path(pending_update, project_root, cwd)
            raw = line[len("*** Move to: ") :].strip()
            path = normalize_path(raw, project_root, cwd)
            targets.append({"operation": "move", "path": path, "old_path": old_path})
            pending_update = None

    flush_update()
    return targets


def apply_patch_text(payload: dict[str, Any]) -> str:
    patch_text = payload_text(payload.get("tool_input"))
    if "*** Begin Patch" not in patch_text:
        patch_text = payload_text(payload)
    return patch_text


def snapshot_dir(project_root: Path, config: dict[str, Any], session_id: str, turn_id: str, tool_use_id: str) -> Path:
    output_dir = str(config.get("output_dir_name") or "codexRuntimeLogFile")
    return (
        project_root
        / output_dir
        / ".internal"
        / "pretool-snapshots"
        / safe_segment(session_id, "unknown_session")
        / safe_segment(turn_id, "unknown_turn")
        / safe_segment(tool_use_id, "unknown_tool")
    )


def save_pretool_snapshot(
    payload: dict[str, Any],
    session_id: str,
    turn_id: str,
    project_root: Path,
    config: dict[str, Any],
) -> None:
    tool_name = str(payload.get("tool_name") or "").lower()
    if "apply_patch" not in tool_name:
        return

    try:
        cwd = Path(str(payload.get("cwd") or project_root)).resolve()
    except Exception:
        cwd = project_root

    targets = parse_apply_patch_targets(apply_patch_text(payload), project_root, cwd)
    if not targets:
        return

    tool_use_id = str(payload.get("tool_use_id") or "unknown_tool")
    target_dir = snapshot_dir(project_root, config, session_id, turn_id, tool_use_id)
    snapshots: list[dict[str, Any]] = []
    for target in targets:
        before_path = str(target.get("old_path") or target.get("path") or "")
        exists, text = read_text_if_exists(before_path)
        snapshots.append(
            {
                "operation": target.get("operation"),
                "path": target.get("path"),
                "old_path": target.get("old_path"),
                "before_path": before_path,
                "exists_before": exists,
                "before_text": text,
            }
        )

    write_json_atomic(
        target_dir / "snapshot.json",
        {
            "created_at": now_iso(),
            "tool_use_id": tool_use_id,
            "targets": snapshots,
        },
    )


def load_pretool_snapshot(
    project_root: Path,
    config: dict[str, Any],
    session_id: str,
    turn_id: str,
    tool_use_id: str,
) -> dict[str, Any] | None:
    path = snapshot_dir(project_root, config, session_id, turn_id, tool_use_id) / "snapshot.json"
    data = load_json_file(path, None)
    return data if isinstance(data, dict) else None


def cleanup_pretool_snapshot(
    project_root: Path,
    config: dict[str, Any],
    session_id: str,
    turn_id: str,
    tool_use_id: str,
) -> None:
    target_dir = snapshot_dir(project_root, config, session_id, turn_id, tool_use_id)
    try:
        if target_dir.exists():
            for child in target_dir.iterdir():
                if child.is_file():
                    child.unlink()
            target_dir.rmdir()
            root = project_root / str(config.get("output_dir_name") or "codexRuntimeLogFile") / ".internal"
            current = target_dir.parent
            while current != root.parent:
                try:
                    current.rmdir()
                except OSError:
                    break
                if current == root:
                    break
                current = current.parent
    except Exception:
        pass


def parse_apply_patch_operations(
    payload: dict[str, Any],
    session_id: str,
    turn_id: str,
    project_root: Path,
    cwd: Path | None,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    targets = parse_apply_patch_targets(apply_patch_text(payload), project_root, cwd)
    if not targets:
        return []

    tool_use_id = str(payload.get("tool_use_id") or "unknown_tool")
    snapshot = load_pretool_snapshot(project_root, config, session_id, turn_id, tool_use_id)
    snapshot_targets = snapshot.get("targets") if snapshot else None
    if not isinstance(snapshot_targets, list):
        snapshot_targets = []

    records: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        operation = str(target.get("operation") or "")
        path = str(target.get("path") or "")
        old_path = target.get("old_path")

        before_text = ""
        if index < len(snapshot_targets) and isinstance(snapshot_targets[index], dict):
            before_text = str(snapshot_targets[index].get("before_text") or "")
        else:
            before_path = str(old_path or path)
            _, before_text = read_text_if_exists(before_path)

        if operation == "delete":
            after_text = ""
        else:
            _, after_text = read_text_if_exists(path)

        ranges = line_ranges(before_text, after_text)
        records.append(
            file_operation_record(
                "apply_patch",
                operation,
                path,
                old_path=str(old_path) if old_path else None,
                ranges=ranges,
            )
        )

    cleanup_pretool_snapshot(project_root, config, session_id, turn_id, tool_use_id)
    return records


def powershell_paths(command: str, names: tuple[str, ...]) -> list[str]:
    name_pattern = "|".join(re.escape(name) for name in names)
    pattern = re.compile(
        rf"(?:(?<=^)|(?<=[\s|;{{(]))-(?:{name_pattern})\b\s+(?:'([^']+)'|\"([^\"]+)\"|([^\s|;}})]+))",
        re.IGNORECASE,
    )
    paths: list[str] = []
    for match in pattern.finditer(command):
        paths.append(next(group for group in match.groups() if group))
    return paths


def remove_powershell_here_strings(command: str) -> str:
    command = re.sub(r"(?ms)@'\r?\n.*?\r?\n'@", "''", command)
    command = re.sub(r'(?ms)@"\r?\n.*?\r?\n"@', '""', command)
    return command


def powershell_command_paths(
    command: str,
    cmdlets: tuple[str, ...],
    names: tuple[str, ...],
) -> list[str]:
    command = remove_powershell_here_strings(command)
    cmdlet_pattern = "|".join(re.escape(cmdlet) for cmdlet in cmdlets)
    pattern = re.compile(
        rf"(?:(?<=^)|(?<=[\s|;{{(]))(?:{cmdlet_pattern})\b(?P<body>[^|;\r\n}}]*)",
        re.IGNORECASE,
    )
    paths: list[str] = []
    for match in pattern.finditer(command):
        paths.extend(powershell_paths(match.group("body"), names))
    return paths


def parse_shell_file_operations(
    payload: dict[str, Any],
    project_root: Path,
    cwd: Path | None,
) -> list[dict[str, Any]]:
    command = payload_text(payload.get("tool_input"))
    lowered = command.lower()
    records: list[dict[str, Any]] = []

    write_markers = (
        "remove-item",
        "new-item",
        "move-item",
        "copy-item",
        "set-content",
        "add-content",
        "out-file",
    )
    read_only_markers = (
        "get-content",
        "select-string",
        "get-childitem",
        " rg ",
        " ripgrep ",
        " git diff",
        " git status",
    )
    if not any(marker in lowered for marker in write_markers) and any(
        marker in lowered for marker in read_only_markers
    ):
        return records

    def add(operation: str, raw_path: str, old_raw_path: str | None = None) -> None:
        path = normalize_path(raw_path, project_root, cwd)
        old_path = normalize_path(old_raw_path, project_root, cwd) if old_raw_path else None
        if path:
            records.append(
                file_operation_record(
                    "shell_command",
                    operation,
                    path,
                    old_path=old_path,
                )
            )

    if "remove-item" in lowered:
        for raw_path in powershell_command_paths(command, ("Remove-Item",), ("LiteralPath", "Path")):
            add("delete", raw_path)
    elif "new-item" in lowered:
        for raw_path in powershell_command_paths(command, ("New-Item",), ("LiteralPath", "Path")):
            add("create", raw_path)
    elif "move-item" in lowered:
        sources = powershell_command_paths(command, ("Move-Item",), ("LiteralPath", "Path"))
        destinations = powershell_command_paths(command, ("Move-Item",), ("Destination",))
        if sources and destinations:
            add("move", destinations[0], old_raw_path=sources[0])
    elif "copy-item" in lowered:
        destinations = powershell_command_paths(command, ("Copy-Item",), ("Destination",))
        for raw_path in destinations:
            add("create", raw_path)
    elif any(marker in lowered for marker in ("set-content", "add-content", "out-file")):
        paths = powershell_command_paths(
            command,
            ("Set-Content", "Add-Content", "Out-File"),
            ("LiteralPath", "Path", "FilePath"),
        )
        for raw_path in paths:
            add("modify", raw_path)

    return records


def extract_file_operations(
    payload: dict[str, Any],
    event: str,
    session_id: str,
    turn_id: str,
    project_root: Path,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    tool_name = str(payload.get("tool_name") or "").lower()
    try:
        cwd = Path(str(payload.get("cwd") or project_root)).resolve()
    except Exception:
        cwd = project_root

    if "apply_patch" in tool_name:
        return parse_apply_patch_operations(payload, session_id, turn_id, project_root, cwd, config)
    if bool(config.get("record_shell_file_operations", True)) and (
        "shell_command" in tool_name or "bash" in tool_name or "shell" in tool_name
    ):
        return parse_shell_file_operations(payload, project_root, cwd)
    return []


def append_file_operations(
    file_operations_file: Path,
    records: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    timeout = float(config.get("lock_timeout_seconds") or 3)
    max_text = int(config.get("max_text_chars") or 12000)
    if not records:
        return

    with file_lock(file_operations_file.with_suffix(".lock"), timeout):
        with file_operations_file.open("a", encoding="utf-8", newline="") as fh:
            for record in records:
                clean = sanitize(record, max_text)
                fh.write(json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    raw = read_stdin_text().strip()
    if not raw.strip():
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    skill_root = Path(__file__).resolve().parents[1]
    default_config = load_json_file(skill_root / "event-logger-settings.json", {})
    if not isinstance(default_config, dict):
        default_config = {}

    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    project_root = find_project_root(cwd, list(default_config.get("workspace_roots") or []))
    project_config = load_json_file(project_root / ".codex" / "event-logger-settings.json", {})
    if isinstance(project_config, dict):
        config = merge_config(default_config, project_config)
    else:
        config = default_config

    if not config.get("enabled", True):
        return 0

    event = get_event(payload)
    allowed_events = set(config.get("events") or [])
    if allowed_events and event not in allowed_events:
        return 0

    mode = str(config.get("mode") or "all").lower()
    workspace_roots = list(config.get("workspace_roots") or [])
    if mode == "allowlist" and not path_matches_any(project_root, workspace_roots):
        return 0

    session_id = get_session_id(payload)
    turn_id = get_turn_id(payload)

    if event in ("UserPromptSubmit", "Stop"):
        _, conversation_file, _ = ensure_turn_dir(
            project_root,
            config,
            session_id,
            turn_id,
        )
        update_conversation(conversation_file, payload, event, session_id, turn_id, config)
    elif event == "PreToolUse":
        save_pretool_snapshot(payload, session_id, turn_id, project_root, config)
    elif event == "PostToolUse":
        records = extract_file_operations(payload, event, session_id, turn_id, project_root, config)
        if records:
            _, _, file_operations_file = ensure_turn_dir(
                project_root,
                config,
                session_id,
                turn_id,
            )
            conversation_file = file_operations_file.with_name(
                str(config.get("conversation_file_name") or "conversation.json")
            )
            backfill_conversation_from_transcript(
                conversation_file,
                payload,
                event,
                session_id,
                turn_id,
                config,
            )
            append_file_operations(
                file_operations_file,
                records,
                config,
            )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        if os.environ.get("CODEX_EVENT_LOGGER_STRICT") == "1":
            raise
        raise SystemExit(0)
