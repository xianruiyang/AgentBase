#!/usr/bin/env python3
"""
Send a Codex hook notification through the official QQ Bot OpenAPI.

This file is intentionally standalone: it uses only Python stdlib and reads all
secrets from environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"
DEFAULT_MAX_CHARS = 900
INTERNAL_ID_RE = re.compile(
    r"^(client-new-thread:)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class NotifyError(RuntimeError):
    pass


def truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def read_json_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_stdin": raw}
    return parsed if isinstance(parsed, dict) else {"stdin": parsed}


def default_cache_file() -> pathlib.Path:
    configured = env("QQ_BOT_TOKEN_CACHE")
    if configured:
        return pathlib.Path(configured).expanduser()

    if os.name == "nt":
        base = env("LOCALAPPDATA") or tempfile.gettempdir()
        return pathlib.Path(base) / "codex-qq-bot" / "token_cache.json"

    xdg = env("XDG_CACHE_HOME")
    if xdg:
        return pathlib.Path(xdg) / "codex-qq-bot" / "token_cache.json"
    return pathlib.Path.home() / ".cache" / "codex-qq-bot" / "token_cache.json"


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise NotifyError(f"HTTP {exc.code} from QQ API: {raw}") from exc
    except urllib.error.URLError as exc:
        raise NotifyError(f"QQ API request failed: {exc}") from exc

    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotifyError(f"QQ API returned non-JSON response: {raw[:300]}") from exc
    if not isinstance(parsed, dict):
        raise NotifyError(f"QQ API returned unexpected response: {parsed!r}")
    code = parsed.get("code")
    if code not in (None, 0, "0"):
        message = parsed.get("message") or parsed.get("msg") or parsed
        raise NotifyError(f"QQ API returned business error {code}: {message}")
    return parsed


def load_cached_token(cache_file: pathlib.Path) -> str | None:
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    token = data.get("access_token")
    expires_at = data.get("expires_at")
    if not isinstance(token, str) or not isinstance(expires_at, (int, float)):
        return None
    if time.time() >= float(expires_at) - 120:
        return None
    return token


def save_cached_token(cache_file: pathlib.Path, token: str, expires_in: int) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": token,
        "expires_at": int(time.time()) + max(expires_in, 60),
    }
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, cache_file)


def get_access_token(timeout: float) -> str:
    app_id = env("QQ_BOT_APP_ID")
    app_secret = env("QQ_BOT_APP_SECRET")
    if not app_id or not app_secret:
        raise NotifyError("Missing QQ_BOT_APP_ID or QQ_BOT_APP_SECRET")

    cache_file = default_cache_file()
    cached = load_cached_token(cache_file)
    if cached:
        return cached

    data = http_json(
        "POST",
        TOKEN_URL,
        {"appId": app_id, "clientSecret": app_secret},
        timeout=timeout,
    )
    token = data.get("access_token")
    expires_in_raw = data.get("expires_in", 7200)
    if not isinstance(token, str) or not token:
        raise NotifyError(f"Token response did not contain access_token: {data}")
    try:
        expires_in = int(expires_in_raw)
    except (TypeError, ValueError):
        expires_in = 7200
    save_cached_token(cache_file, token, expires_in)
    return token


def compact_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    text = "\n".join(line.rstrip() for line in text.strip().splitlines())
    if len(text) > limit:
        return text[: max(0, limit - 12)].rstrip() + "\n...[truncated]"
    return text


def pick_first(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def find_nested(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value not in (None, ""):
                return value
        for value in data.values():
            found = find_nested(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_nested(value, keys)
            if found not in (None, ""):
                return found
    return None


def is_internal_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(INTERNAL_ID_RE.match(value.strip()))


def codex_home() -> pathlib.Path:
    configured = env("CODEX_HOME")
    if configured:
        return pathlib.Path(configured).expanduser()
    return pathlib.Path.home() / ".codex"


def debug_log(event: str, data: dict[str, Any] | None = None, **fields: Any) -> None:
    configured = env("QQ_BOT_DEBUG_LOG")
    if not configured:
        return
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        **fields,
    }
    if data:
        thread_id = normalized_thread_id(data)
        if thread_id:
            record["thread_id"] = thread_id
        hook_event = pick_first(data, ["hook_event_name", "event", "event_name", "hookEventName"])
        if hook_event:
            record["hook_event"] = str(hook_event)
        cwd = pick_first(data, ["cwd", "working_directory", "workspace", "repo_path", "project_dir"])
        if cwd:
            record["cwd"] = str(cwd)

    for raw_path in configured.split(os.pathsep):
        path_text = raw_path.strip()
        if not path_text:
            continue
        try:
            path = pathlib.Path(path_text).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            continue


def lookup_thread_name(thread_id: Any) -> str | None:
    if not isinstance(thread_id, str) or not thread_id.strip():
        return None
    normalized = thread_id.strip()
    if normalized.startswith("client-new-thread:"):
        normalized = normalized.split(":", 1)[1]

    index_path = codex_home() / "session_index.jsonl"
    try:
        with index_path.open("r", encoding="utf-8") as file:
            for line in file:
                if normalized not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("id") == normalized and record.get("thread_name"):
                    return compact_text(record["thread_name"], 80)
    except OSError:
        return None
    return None


def normalized_thread_id(data: dict[str, Any]) -> str | None:
    value = find_nested(
        data,
        {
            "conversation_id",
            "conversationId",
            "thread_id",
            "threadId",
            "session_id",
            "sessionId",
            "id",
        },
    )
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("client-new-thread:"):
        text = text.split(":", 1)[1]
    return text


def goal_db_path() -> pathlib.Path:
    configured = env("QQ_BOT_GOAL_DB")
    if configured:
        return pathlib.Path(configured).expanduser()
    return codex_home() / "goals_1.sqlite"


def read_goal_row(thread_id: str | None) -> dict[str, Any] | None:
    if not thread_id:
        return None
    db_path = goal_db_path()
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                select goal_id, objective, status, updated_at_ms
                from thread_goals
                where thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def goal_gate_allows_send(data: dict[str, Any]) -> bool:
    if env("QQ_BOT_GOAL_AWARE", "1").strip().lower() in {"0", "false", "no", "off"}:
        return True

    thread_id = normalized_thread_id(data)
    goal = read_goal_row(thread_id)
    if not goal:
        return True

    status = str(goal.get("status") or "").strip().lower()
    return status not in {"active", "in_progress", "running"}


def load_thread_switch_config() -> dict[str, Any]:
    configured = env("QQ_BOT_THREAD_SWITCH_CONFIG")
    if configured:
        config_path = pathlib.Path(configured).expanduser()
    else:
        config_path = pathlib.Path.cwd() / ".codex" / "qq-hook-settings.json"

    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"default_enabled": False}
    return data if isinstance(data, dict) else {"default_enabled": False}


def list_contains(items: Any, value: str | None) -> bool:
    if value is None:
        return False
    if not isinstance(items, list):
        return False
    normalized = value.strip()
    return any(isinstance(item, str) and item.strip() == normalized for item in items)


def hook_thread_enabled(data: dict[str, Any]) -> bool:
    enabled, _reason = hook_thread_decision(data)
    return enabled


def hook_thread_decision(data: dict[str, Any]) -> tuple[bool, str]:
    config = load_thread_switch_config()
    default_enabled = config.get("default_enabled", False)
    thread_id = normalized_thread_id(data)
    name = conversation_name(data)

    disabled = list_contains(config.get("disabled_thread_ids"), thread_id) or list_contains(
        config.get("disabled_thread_names"), name
    )
    if disabled:
        return False, "thread_disabled"

    enabled = list_contains(config.get("enabled_thread_ids"), thread_id)
    if enabled:
        return True, "thread_enabled"

    if bool(default_enabled):
        return True, "default_enabled"
    if thread_id:
        return False, "thread_not_enabled"
    return False, "thread_id_missing"


def workspace_name(data: dict[str, Any]) -> str:
    explicit = env("QQ_BOT_WORKSPACE_NAME")
    if explicit:
        return explicit

    raw = pick_first(data, ["workspace_name", "workspaceName", "workspace"])
    if not raw:
        raw = pick_first(data, ["cwd", "working_directory", "repo_path", "project_dir"])
    if not raw:
        raw = os.getcwd()

    text = str(raw).strip()
    if not text:
        return "当前工作区"
    return pathlib.Path(text).name or text


def conversation_name(data: dict[str, Any]) -> str:
    explicit = env("QQ_BOT_CONVERSATION_NAME")
    if explicit:
        return explicit

    title = find_nested(
        data,
        {
            "conversation_title",
            "conversationTitle",
            "thread_title",
            "threadTitle",
            "thread_name",
            "threadName",
            "chat_title",
            "chatTitle",
            "title",
        },
    )
    if title not in (None, "") and not is_internal_id(title):
        return compact_text(title, 80)

    thread_id = find_nested(
        data,
        {
            "conversation_id",
            "conversationId",
            "thread_id",
            "threadId",
            "session_id",
            "sessionId",
            "id",
        },
    )
    resolved = lookup_thread_name(thread_id)
    if resolved:
        return resolved

    if title not in (None, "") and not is_internal_id(title):
        return compact_text(title, 80)
    return "当前对话"


def completion_text(data: dict[str, Any]) -> str:
    value = find_nested(
        data,
        {
            "final_response",
            "finalResponse",
            "last_assistant_message",
            "lastAssistantMessage",
            "last_agent_message",
            "lastAgentMessage",
            "assistant_message",
            "assistantMessage",
            "completion_message",
            "completionMessage",
            "message",
            "summary",
            "output",
            "result",
        },
    )
    if value in (None, ""):
        return "已完成"
    max_chars = int(env("QQ_BOT_COMPLETION_MAX_CHARS", env("QQ_BOT_MAX_CHARS", "700") or "700"))
    return compact_text(value, max_chars)


def build_stop_message(data: dict[str, Any]) -> str:
    workspace = workspace_name(data)
    conversation = conversation_name(data)
    completion = completion_text(data)
    return f"别睡了你个傻逼，你的工作区”{workspace}“下的对话”{conversation}“完成了：”{completion}“"


def event_allowed(data: dict[str, Any]) -> bool:
    configured = env("QQ_BOT_NOTIFY_EVENTS", "Stop")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    if not allowed or "*" in allowed:
        return True
    event_name = str(
        pick_first(data, ["hook_event_name", "event", "event_name", "hookEventName"]) or "manual"
    )
    return event_name in allowed


def build_message(data: dict[str, Any], explicit_message: str | None) -> str:
    if explicit_message:
        body = explicit_message
    elif env("QQ_BOT_STOP_TEMPLATE") == "work_complete":
        body = build_stop_message(data)
    else:
        event_name = str(
            pick_first(data, ["hook_event_name", "event", "event_name", "hookEventName"]) or "Codex"
        )
        cwd = pick_first(data, ["cwd", "working_directory", "workspace", "repo_path"])
        assistant = pick_first(
            data,
            [
                "last_assistant_message",
                "final_response",
                "assistant_message",
                "message",
                "transcript",
            ],
        )
        tool = pick_first(data, ["tool_name", "tool", "matcher"])
        parts = [f"Codex hook: {event_name}"]
        if cwd:
            parts.append(f"cwd: {cwd}")
        if tool:
            parts.append(f"tool: {tool}")
        if assistant:
            max_chars = int(env("QQ_BOT_MAX_CHARS", str(DEFAULT_MAX_CHARS)) or DEFAULT_MAX_CHARS)
            parts.append(compact_text(assistant, max_chars))
        body = "\n".join(parts)

    prefix = env("QQ_BOT_MESSAGE_PREFIX", "[Codex]")
    message = f"{prefix} {body}".strip() if prefix else body.strip()
    max_chars = int(env("QQ_BOT_MAX_CHARS", str(DEFAULT_MAX_CHARS)) or DEFAULT_MAX_CHARS)
    return compact_text(message, max_chars)


def target_endpoint() -> str:
    target_type = (env("QQ_BOT_TARGET_TYPE", "group") or "group").strip().lower()
    if target_type in {"group", "qq_group"}:
        group_openid = env("QQ_BOT_GROUP_OPENID")
        if not group_openid:
            raise NotifyError("QQ_BOT_TARGET_TYPE=group requires QQ_BOT_GROUP_OPENID")
        return f"{API_BASE}/v2/groups/{urllib.parse.quote(group_openid, safe='')}/messages"

    if target_type in {"user", "c2c", "private"}:
        openid = env("QQ_BOT_OPENID")
        if not openid:
            raise NotifyError("QQ_BOT_TARGET_TYPE=user requires QQ_BOT_OPENID")
        return f"{API_BASE}/v2/users/{urllib.parse.quote(openid, safe='')}/messages"

    if target_type in {"channel", "guild_channel"}:
        channel_id = env("QQ_BOT_CHANNEL_ID")
        if not channel_id:
            raise NotifyError("QQ_BOT_TARGET_TYPE=channel requires QQ_BOT_CHANNEL_ID")
        return f"{API_BASE}/channels/{urllib.parse.quote(channel_id, safe='')}/messages"

    raise NotifyError(f"Unsupported QQ_BOT_TARGET_TYPE: {target_type}")


def build_send_payload(content: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": content,
        "msg_type": 0,
    }

    msg_id = env("QQ_BOT_MSG_ID")
    event_id = env("QQ_BOT_EVENT_ID")
    msg_seq = env("QQ_BOT_MSG_SEQ")
    if msg_id:
        payload["msg_id"] = msg_id
    if event_id:
        payload["event_id"] = event_id
    if msg_seq:
        try:
            payload["msg_seq"] = int(msg_seq)
        except ValueError:
            payload["msg_seq"] = msg_seq

    if truthy(env("QQ_BOT_IS_WAKEUP")):
        payload["is_wakeup"] = True

    return payload


def digest_message(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest()[:16]


def redact_endpoint(endpoint: str) -> str:
    endpoint = re.sub(r"/v2/users/[^/]+/messages$", "/v2/users/<openid>/messages", endpoint)
    endpoint = re.sub(r"/v2/groups/[^/]+/messages$", "/v2/groups/<group_openid>/messages", endpoint)
    endpoint = re.sub(r"/channels/[^/]+/messages$", "/channels/<channel_id>/messages", endpoint)
    return endpoint


def send_message(content: str, timeout: float, dry_run: bool) -> dict[str, Any]:
    endpoint = target_endpoint()
    payload = build_send_payload(content)
    if dry_run:
        redacted_payload = dict(payload)
        if len(redacted_payload.get("content", "")) > 160:
            redacted_payload["content"] = redacted_payload["content"][:160] + "...[truncated]"
        return {
            "dry_run": True,
            "endpoint": redact_endpoint(endpoint),
            "payload": redacted_payload,
            "message_sha256_16": digest_message(content),
        }

    access_token = get_access_token(timeout)
    return http_json(
        "POST",
        endpoint,
        payload,
        headers={"Authorization": f"QQBot {access_token}"},
        timeout=timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook-mode", action="store_true", help="Read Codex hook JSON from stdin.")
    parser.add_argument("--message", help="Send this message instead of building one from stdin.")
    parser.add_argument("--dry-run", action="store_true", help="Do not call QQ API.")
    parser.add_argument("--print-result", action="store_true", help="Print JSON result to stdout.")
    args = parser.parse_args()

    data = read_json_stdin() if args.hook_mode else {}

    dry_run = args.dry_run or truthy(env("QQ_BOT_DRY_RUN"))

    if args.hook_mode and not event_allowed(data):
        debug_log("skip", data, reason="event_not_allowed")
        return 0
    if args.hook_mode:
        thread_enabled, thread_reason = hook_thread_decision(data)
        if not thread_enabled:
            debug_log("skip", data, reason=thread_reason)
            return 0
    if args.hook_mode and not goal_gate_allows_send(data):
        debug_log("skip", data, reason="goal_active")
        return 0
    if not dry_run and not truthy(env("QQ_BOT_ENABLE")):
        if args.hook_mode:
            debug_log("skip", data, reason="qq_bot_enable_not_set")
            return 0
        print("codex_qq_notify: set QQ_BOT_ENABLE=1 to send a real QQ message", file=sys.stderr)
        return 1

    timeout = float(env("QQ_BOT_TIMEOUT_SECONDS", "10") or "10")
    message = build_message(data, args.message)
    if not message:
        debug_log("skip", data, reason="empty_message")
        return 0

    try:
        result = send_message(message, timeout=timeout, dry_run=dry_run)
    except NotifyError as exc:
        debug_log("error", data, reason="notify_error", error=str(exc))
        print(f"codex_qq_notify: {exc}", file=sys.stderr)
        return 0 if args.hook_mode else 1

    debug_log(
        "sent",
        data,
        dry_run=dry_run,
        message_sha256_16=digest_message(message),
        target_type=env("QQ_BOT_TARGET_TYPE", "user"),
    )

    if args.print_result or truthy(env("QQ_BOT_PRINT_RESULT")):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
