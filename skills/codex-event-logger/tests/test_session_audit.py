from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import read_codex_session_audit as audit


def record(payload, second=0, kind="response_item"):
    return {"timestamp": f"2026-09-08T00:00:{second:02d}Z", "type": kind, "payload": payload}


def call(name, call_id, args=None, second=0):
    return record({"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args or {})}, second)


def output(call_id, value, second):
    return record({"type": "function_call_output", "call_id": call_id, "output": json.dumps(value)}, second)


class SessionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="AgentBase-session-audit-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def write(self, rows):
        meta = record({"id": "12345678-1234-1234-1234-123456789012", "agent_path": "/root", "agent_role": "default"}, kind="session_meta")
        self.path.write_text("".join(json.dumps(r) + "\n" for r in [meta, *rows]), encoding="utf-8")

    def args(self, *values):
        return audit.build_parser().parse_args(["--transcript", str(self.path), *values])

    def test_creation_success_failure_reuse_and_wait_pairing(self):
        self.write([
            call("spawn_agent", "s1", {"task_name": "lookup", "agent_type": "evidence"}),
            record({"type": "item_completed", "item": {"type": "SubAgentActivity", "agent_path": "/root/lookup", "agent_thread_id": "87654321-1234-1234-1234-123456789012"}}, kind="event_msg"),
            output("s1", {"task_name": "/root/lookup"}, 1),
            call("spawn_agent", "s2", {"task_name": "failed", "agent_type": "experiment"}, 2),
            output("s2", {"error": "capacity"}, 3),
            call("followup_task", "f1", {"target": "lookup", "message": "gAAAAAEncryptedSecret"}, 4),
            call("wait_agent", "w1", {"timeout_ms": 10000}, 5),
            output("w1", {"timed_out": True}, 15),
            call("wait_agent", "w2", second=18),
            record({"type": "agent_message", "author": "/root/lookup", "recipient": "/root", "content": "gAAAAAEncryptedSecret"}, 19),
            output("w2", {"timed_out": False}, 20),
            call("wait_agent", "w3", second=21),
        ])
        result = audit.build_output(self.args())
        summary = result["summary"]
        self.assertEqual(summary["creation_outcomes"], {"created": 1, "failed": 1})
        self.assertEqual(summary["created_roles"], {"evidence": 1})
        self.assertEqual(summary["event_counts"]["followup_task"], 1)
        self.assertEqual(result["events"][0]["followups"], 1)
        self.assertEqual(result["events"][0]["child_thread_id"], "87654321-1234-1234-1234-123456789012")
        self.assertEqual(summary["waits"]["outcomes"], {"timeout": 1, "woken": 1, "pending": 1})
        self.assertEqual(summary["waits"]["completed_seconds"], 12)
        self.assertEqual(summary["timeout_gaps_without_observed_activity"]["seconds"], 3)
        self.assertNotIn("EncryptedSecret", json.dumps(result))
        self.assertNotIn("12345678-1234", audit.model_output(result, 2048))
        self.assertNotIn("87654321-1234", audit.model_output(result, 2048))

    def test_work_between_waits_and_filtered_start_scope(self):
        self.write([
            call("wait_agent", "w1", second=1), output("w1", {"timed_out": True}, 5),
            record({"type": "item_completed", "item": {"type": "CommandExecution", "command": ["pwsh", "Get-Content config"], "exit_code": 0}}, 7, "event_msg"),
            call("wait_agent", "w2", second=10), output("w2", {"timed_out": True}, 20),
        ])
        result = audit.build_output(self.args("--mode", "waits"))
        self.assertEqual(result["summary"]["timeout_gaps_without_observed_activity"]["count"], 0)
        filtered = audit.build_output(self.args("--from-time", "2026-09-08T00:00:09Z", "--to-time", "2026-09-08T00:00:12Z", "--mode", "waits"))
        self.assertEqual(filtered["summary"]["waits"]["count"], 1)
        self.assertEqual(filtered["summary"]["waits"]["completed_seconds"], 10)

    def test_projection_never_exposes_reasoning_or_raw_tool_outputs(self):
        self.write([
            record({"type": "reasoning", "summary": "PRIVATE_REASONING", "encrypted_content": "CIPHER"}),
            record({"type": "item_completed", "item": {"type": "Reasoning", "raw_content": "PRIVATE_REASONING"}}, kind="event_msg"),
            record({"type": "item_completed", "item": {"type": "AgentMessage", "phase": "analysis", "content": [{"text": "PRIVATE_REASONING"}]}}, kind="event_msg"),
            record({"type": "custom_tool_call_output", "output": "RAW_TOOL_OUTPUT"}),
            record({"type": "item_completed", "item": {"type": "AgentMessage", "phase": "commentary", "content": [{"type": "Text", "text": "public progress"}]}}, kind="event_msg"),
        ])
        result = audit.build_output(self.args("--mode", "timeline", "--include-text"))
        encoded = json.dumps(result)
        self.assertIn("public progress", encoded)
        for secret in ("PRIVATE_REASONING", "CIPHER", "RAW_TOOL_OUTPUT"):
            self.assertNotIn(secret, encoded)

    def test_pagination_budget_and_stale_source(self):
        self.write([call("spawn_agent", f"s{i}", {"task_name": "agent" + str(i), "agent_type": "evidence"}, i) for i in range(30)])
        first = audit.build_output(self.args("--limit", "30"))
        rendered = audit.model_output(first, 1200)
        self.assertLessEqual(audit.model_text_cost(rendered), 1200)
        page = audit.build_output(self.args("--limit", "2"))
        stamp = page["snapshot"]
        next_args = self.args("--offset", "2", "--snapshot-size", str(stamp["bytes"]), "--snapshot-modified", stamp["modified"])
        second = audit.build_output(next_args)
        self.assertEqual(second["events"][0]["name"], "agent2")
        self.assertEqual(second["summary"], page["summary"])
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(call("wait_agent", "new")) + "\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            audit.build_output(next_args)
        with self.assertRaisesRegex(ValueError, "pagination requires"):
            audit.build_output(self.args("--offset", "1"))

    def test_incomplete_sources_never_claim_complete_scan(self):
        self.write([])
        with self.path.open("ab") as handle:
            handle.write(b"invalid\n" + b"x" * 500 + b"\n" + b"{partial")
        result = audit.scan(self.path, 10000, 256)
        self.assertFalse(result["coverage"]["complete_scan"])
        self.assertEqual(result["coverage"]["issues"], {"invalid_json_lines": 1, "oversized_lines": 1, "incomplete_tail": 1})
        with self.assertRaisesRegex(ValueError, "exceeds"):
            audit.scan(self.path, 10, 256)

    def test_cli_uses_same_projection(self):
        self.write([call("wait_agent", "w"), output("w", {"timed_out": True}, 2)])
        run = subprocess.run([sys.executable, str(SCRIPTS / "read_codex_session_audit.py"), "--transcript", str(self.path), "--mode", "waits", "--view", "machine"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["summary"]["waits"]["completed_seconds"], 2)
        self.assertEqual(len(result["events"]), 1)


if __name__ == "__main__":
    unittest.main()
