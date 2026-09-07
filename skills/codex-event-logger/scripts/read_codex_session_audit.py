"""Read-only, bounded projection of explicitly selected native Codex session JSONL."""
from __future__ import annotations

import argparse
import copy
import json
import re
import stat
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from read_codex_turn_log import bounded_integer, model_text_cost, render_model, truncate_text


MAX_EVENTS = 100_000
OPAQUE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b|\bgAAAAA[A-Za-z0-9_=-]+")
DELEGATION = {"spawn_agent", "followup_task", "send_message", "list_agents"}
ACTIVITY = {"command", "file_change", "input", "incoming_message", "tool_call", "external_action", *DELEGATION}


def text(value, limit=180):
    if not isinstance(value, str):
        return None
    return truncate_text(OPAQUE.sub("<opaque>", value), limit)


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def utc_argument(value):
    parsed = timestamp(value)
    if parsed is None:
        raise argparse.ArgumentTypeError("use an ISO timestamp with a timezone")
    return parsed


def object_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return {}
    return value if isinstance(value, dict) else {}


def source_stamp(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("transcript must be a regular file")
    return {
        "bytes": info.st_size,
        "modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
    }


def scan(path, max_bytes, max_line_bytes, include_text=False):
    before = source_stamp(path)
    if before["bytes"] > max_bytes:
        raise ValueError("transcript exceeds --max-scan-bytes; explicitly raise the bounded limit")
    events, pending = [], {}
    child_ids = {}
    issues = Counter()
    first_time = last_time = None
    identity = {}
    line_number = 0

    def add(kind, row_time, line, **fields):
        if len(events) >= MAX_EVENTS:
            raise ValueError("event limit exceeded; select a smaller transcript")
        event = {"line": line, "time": row_time, "kind": kind, **fields}
        events.append(event)
        return event

    with path.open("rb") as handle:
        remaining = before["bytes"]
        while remaining:
            raw = handle.readline(min(max_line_bytes + 1, remaining))
            if not raw:
                issues["short_read"] += 1
                break
            remaining -= len(raw)
            line_number += 1
            if len(raw) > max_line_bytes:
                issues["oversized_lines"] += 1
                while not raw.endswith(b"\n") and remaining:
                    raw = handle.readline(min(max_line_bytes + 1, remaining))
                    remaining -= len(raw)
                    if not raw:
                        break
                continue
            if not raw.endswith(b"\n"):
                issues["incomplete_tail"] += 1
                continue
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError):
                issues["invalid_json_lines"] += 1
                continue
            if not isinstance(row, dict):
                issues["invalid_records"] += 1
                continue
            payload = object_value(row.get("payload"))
            row_time = row.get("timestamp")
            if timestamp(row_time) is None:
                issues["invalid_timestamps"] += 1
                continue
            first_time = first_time or row_time
            last_time = row_time
            record_type, kind = row.get("type"), payload.get("type")
            if record_type == "session_meta":
                spawn = object_value(object_value(payload.get("source")).get("subagent"))
                spawn = object_value(spawn.get("thread_spawn"))
                identity = {
                    "thread_id": payload.get("id"),
                    "parent_thread_id": spawn.get("parent_thread_id"),
                    "agent_path": text(payload.get("agent_path")),
                    "role": text(payload.get("agent_role")),
                }
            elif record_type == "response_item":
                if kind == "function_call":
                    name = str(payload.get("name", "")).split(".")[-1]
                    args = object_value(payload.get("arguments"))
                    if name == "wait_agent":
                        event = add("wait", row_time, line_number, outcome="pending")
                        requested = args.get("timeout_ms")
                        if isinstance(requested, (int, float)) and not isinstance(requested, bool):
                            event["requested_ms"] = requested
                        pending[payload.get("call_id")] = event
                    elif name in DELEGATION:
                        event = add(name, row_time, line_number)
                        if name == "spawn_agent":
                            event.update(name=text(args.get("task_name")), role=text(args.get("agent_type")), outcome="pending")
                            pending[payload.get("call_id")] = event
                        elif "target" in args:
                            event["target"] = text(args["target"])
                    else:
                        add("tool_call", row_time, line_number, tool=text(name))
                elif kind == "function_call_output":
                    event = pending.pop(payload.get("call_id"), None)
                    if event is None:
                        continue
                    output = object_value(payload.get("output"))
                    event.update(end_line=line_number, end_time=row_time)
                    if event["kind"] == "wait":
                        elapsed = (timestamp(row_time) - timestamp(event["time"])).total_seconds()
                        if elapsed < 0:
                            issues["negative_wait_duration"] += 1
                        else:
                            event["seconds"] = round(elapsed, 3)
                        timed_out = output.get("timed_out")
                        event["outcome"] = "timeout" if timed_out is True else "woken" if timed_out is False else "unknown"
                    else:
                        # A call is not a successful child creation without a returned identity.
                        returned = output.get("task_name") or output.get("agent_id") or output.get("thread_id")
                        event["outcome"] = "created" if isinstance(returned, str) and returned else "failed" if output.get("error") else "unknown"
                        if isinstance(output.get("task_name"), str):
                            event["agent_path"] = text(output["task_name"])
                elif kind == "agent_message":
                    add("incoming_message", row_time, line_number, author=text(payload.get("author")), recipient=text(payload.get("recipient")))
                elif kind == "custom_tool_call":
                    add("tool_call", row_time, line_number, tool=text(payload.get("name")))
                # No reasoning, encrypted content, tool output or message bodies are projected here.
                elif kind not in {"message", "reasoning", "custom_tool_call_output"}:
                    issues["unsupported_response_items"] += 1
            elif record_type == "event_msg" and kind == "item_completed":
                item = object_value(payload.get("item"))
                item_kind = item.get("type")
                known = {"CommandExecution": "command", "FileChange": "file_change", "UserMessage": "input", "AgentMessage": "progress", "ContextCompaction": "compaction", "Extension": "external_action"}
                if item_kind in known:
                    event = add(known[item_kind], row_time, line_number)
                    if item_kind == "CommandExecution":
                        event["exit_code"] = item.get("exit_code")
                    if item_kind == "AgentMessage":
                        event["phase"] = text(item.get("phase"))
                    public_text = item_kind == "CommandExecution" or (
                        item_kind == "AgentMessage" and item.get("phase") in {"commentary", "final"}
                    )
                    if include_text and public_text:
                        body = item.get("content") if item_kind == "AgentMessage" else item.get("command")
                        if isinstance(body, list):
                            body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict)) if item_kind == "AgentMessage" else str(body[-1]) if body else ""
                        event["excerpt"] = text(body, 400)
                elif item_kind == "SubAgentActivity":
                    if isinstance(item.get("agent_path"), str) and isinstance(item.get("agent_thread_id"), str):
                        child_ids[item["agent_path"]] = item["agent_thread_id"]
                elif item_kind not in {"Reasoning", "CollabAgentToolCall"}:
                    issues["unsupported_completed_items"] += 1
            elif record_type not in {"event_msg", "world_state", "turn_context", "token_usage_record", "inter_agent_communication_metadata", "compacted"}:
                issues["unsupported_record_types"] += 1
    after = source_stamp(path)
    if before != after:
        issues["source_changed_during_read"] += 1
    if not identity:
        issues["session_identity_missing"] += 1
    for event in events:
        if event["kind"] == "spawn_agent" and event.get("agent_path") in child_ids:
            event["child_thread_id"] = child_ids[event["agent_path"]]
    return {"snapshot": before, "coverage": {"lines": line_number, "first_time": first_time, "last_time": last_time, "issues": dict(issues), "complete_scan": not issues}, "identity": identity, "events": events}


def summarize(events):
    counts = Counter(e["kind"] for e in events)
    waits = [e for e in events if e["kind"] == "wait"]
    creations = [e for e in events if e["kind"] == "spawn_agent"]
    gaps = []
    # Linear merge: avoid rescanning a long timeline for every wait.
    activity = [e["line"] for e in events if e["kind"] in ACTIVITY or e["kind"] == "compaction"]
    cursor = 0
    for previous, following in zip(waits, waits[1:]):
        if previous["outcome"] != "timeout" or "end_line" not in previous:
            continue
        while cursor < len(activity) and activity[cursor] <= previous["end_line"]:
            cursor += 1
        if cursor == len(activity) or activity[cursor] >= following["line"]:
            seconds = (timestamp(following["time"]) - timestamp(previous["end_time"])).total_seconds()
            if seconds >= 0:
                gaps.append({"after_line": previous["end_line"], "before_line": following["line"], "seconds": round(seconds, 3)})
    return {
        "event_counts": dict(counts),
        "creation_outcomes": dict(Counter(e["outcome"] for e in creations)),
        "created_roles": dict(Counter(e.get("role") or "unspecified" for e in creations if e["outcome"] == "created")),
        "waits": {"count": len(waits), "outcomes": dict(Counter(e["outcome"] for e in waits)), "completed_seconds": round(sum(e.get("seconds", 0) for e in waits), 3)},
        "timeout_gaps_without_observed_activity": {"count": len(gaps), "seconds": round(sum(e["seconds"] for e in gaps), 3), "longest": sorted(gaps, key=lambda e: e["seconds"], reverse=True)[:3]},
    }


def build_output(args):
    source = args.transcript.resolve()
    if args.offset and (args.snapshot_size is None or args.snapshot_modified is None):
        raise ValueError("pagination requires --snapshot-size and --snapshot-modified from the previous page")
    stamp = source_stamp(source)
    if ((args.snapshot_size is not None and stamp["bytes"] != args.snapshot_size)
            or (args.snapshot_modified is not None and stamp["modified"] != args.snapshot_modified)):
        raise ValueError("source changed; restart at --offset 0 without snapshot arguments")
    data = scan(source, args.max_scan_bytes, args.max_line_bytes, args.include_text)
    if data["snapshot"] != stamp:
        raise ValueError("source changed before reading; restart the query")
    events = [e for e in data["events"] if (args.from_time is None or timestamp(e["time"]) >= args.from_time) and (args.to_time is None or timestamp(e["time"]) < args.to_time)]
    selected = [e for e in events if (args.mode == "agents" and e["kind"] == "spawn_agent") or (args.mode == "waits" and e["kind"] == "wait") or args.mode == "timeline"]
    if args.offset > len(selected):
        raise ValueError("offset exceeds selected events")
    rows = selected[args.offset:args.offset + args.limit]
    followups = Counter(e.get("target") for e in events if e["kind"] == "followup_task")
    for event in selected:
        if event["kind"] == "spawn_agent" and event["outcome"] == "created":
            # Bare names are scoped to this parent; an explicit path is a distinct target.
            targets = {event.get("name"), event.get("agent_path")} - {None}
            event["followups"] = sum(followups[t] for t in targets)
    result = {
        "schema": "codex.session-audit/v1",
        "source": str(source),
        "snapshot": data["snapshot"],
        "coverage": data["coverage"],
        "identity": data["identity"],
        "scope": {"from": args.from_time.isoformat() if args.from_time else None, "to_exclusive": args.to_time.isoformat() if args.to_time else None, "mode": args.mode},
        "summary": summarize(events),
        "events": rows,
        "page": {"offset": args.offset, "returned": len(rows), "total": len(selected), "next_offset": args.offset + len(rows) if args.offset + len(rows) < len(selected) else None},
        "limits": ["Counts describe this file and selected start timestamps, not all descendants.", "Wait duration includes tool overhead; gaps do not prove wasted thinking.", "No reasoning, encrypted text or full tool output is read into the projection."],
    }
    return result


def model_output(result, budget):
    result = copy.deepcopy(result)
    result.pop("schema")
    result["source"] = "selected transcript"
    result["identity"] = {k: v for k, v in result["identity"].items() if k in {"agent_path", "role"} and v}
    for event in result["events"]:
        event.pop("child_thread_id", None)
    while True:
        rendered = render_model(result)
        if model_text_cost(rendered) <= budget:
            return rendered
        if not result["events"]:
            raise ValueError("budget too small for audit summary; raise --model-token-budget")
        result["events"].pop()
        page = result["page"]
        page["returned"] = len(result["events"])
        page["next_offset"] = page["offset"] + page["returned"]
        if not result["events"] and page["total"] > page["offset"]:
            raise ValueError("budget too small for one recoverable event; raise --model-token-budget")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--mode", choices=("agents", "waits", "timeline"), default="agents")
    parser.add_argument("--view", choices=("model", "machine"), default="model")
    parser.add_argument("--from-time", type=utc_argument)
    parser.add_argument("--to-time", type=utc_argument)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--offset", type=bounded_integer("offset", 0, MAX_EVENTS), default=0)
    parser.add_argument("--limit", type=bounded_integer("limit", 1, 100), default=20)
    parser.add_argument("--snapshot-size", type=bounded_integer("snapshot-size", 0, 512 * 1024 * 1024))
    parser.add_argument("--snapshot-modified")
    parser.add_argument("--max-scan-bytes", type=bounded_integer("max-scan-bytes", 1, 512 * 1024 * 1024), default=128 * 1024 * 1024)
    parser.add_argument("--max-line-bytes", type=bounded_integer("max-line-bytes", 128, 8 * 1024 * 1024), default=4 * 1024 * 1024)
    parser.add_argument("--model-token-budget", type=bounded_integer("model-token-budget", 256, 100_000), default=2048)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.from_time and args.to_time and args.from_time >= args.to_time:
        parser.error("--from-time must precede --to-time")
    try:
        result = build_output(args)
        output = json.dumps(result, ensure_ascii=False) if args.view == "machine" else model_output(result, args.model_token_budget)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
