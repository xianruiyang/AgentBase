from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.runtime import _facts, trace
from evo.spec import EvoError
from evo.store import Store


class EvoFactsTests(unittest.TestCase):
    def test_trace_rejects_stale_pagination_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "state")
            store.initialize(max_disk_mb=64, min_free_mb=1)
            with store.connect(True) as db:
                study = db.execute("INSERT INTO studies(identity,name,spec,project,work,created,max_tokens,concurrency) "
                                   "VALUES('identity','trace','{}','P:/project','P:/work',?,100,1)",
                                   (time.time(),)).lastrowid
                Store.event(db, study, None, "one", {})
            first = trace(store, study, source="schedule", limit=1)
            alias = "snapshot-" + first["snapshot"][:8]
            self.assertEqual(trace(store, study, source="schedule", offset=1, limit=1,
                                   snapshot=alias)["events"], [])
            with store.connect(True) as db:
                Store.event(db, study, None, "two", {})
            with self.assertRaisesRegex(EvoError, "source changed"):
                trace(store, study, source="schedule", offset=1, limit=1, snapshot=first["snapshot"])

    def test_raw_usage_and_trace_rebuild_actual_agent_and_request_facts(self) -> None:
        fields = [
            {"id": "attempt_tokens", "grain": "attempt", "extract": {"from": "attempt", "path": "usage.total_tokens"}},
            {"id": "attempt_requests", "grain": "attempt", "extract": {"from": "attempt", "path": "usage.request_count"}},
            {"id": "attempt_tools", "grain": "attempt", "extract": {"from": "attempt", "path": "tools.attempts"}},
            {"id": "attempt_waits", "grain": "attempt", "extract": {"from": "attempt", "path": "events.wait_count"}},
            {"id": "queue_seconds", "grain": "attempt", "extract": {"from": "attempt", "path": "timing.queue_seconds"}},
            {"id": "prepare_seconds", "grain": "attempt", "extract": {"from": "attempt", "path": "timing.prepare_seconds"}},
            {"id": "verify_seconds", "grain": "attempt", "extract": {"from": "attempt", "path": "timing.verify_seconds"}},
            {"id": "reward_value", "grain": "attempt", "extract": {"from": "attempt", "path": ["values", "quality.reward"]}},
            {"id": "agent_tokens", "grain": "agent", "extract": {"from": "agent", "path": "usage.total_tokens"}},
            {"id": "agent_input", "grain": "agent", "extract": {"from": "agent", "path": "usage.input_tokens"}},
            {"id": "agent_requests", "grain": "agent", "extract": {"from": "agent", "path": "request_count"}},
            {"id": "agent_tools", "grain": "agent", "extract": {"from": "agent", "path": "tools.attempts"}},
            {"id": "event_kind", "grain": "event", "extract": {"from": "event", "path": "kind"}},
        ]
        study = {"spec": {"fields": fields}}
        job = {"id": 7, "study": 3, "receipt": "jobs/j7/receipt.json", "runtime": {"adapter": "codex"},
               "plan": {"combination": "c", "item": "i", "replicate": 1, "groups": ["g"]}}
        usage = {"total_tokens": 30, "input_tokens": 24, "cached_input_tokens": 10,
                 "cache_write_input_tokens": 0, "output_tokens": 6, "reasoning_output_tokens": 2}
        root = {"thread_id": "root", "parent_thread_id": None, "agent_role": None, "agent_path": None,
                "usage": usage, "usage_complete": True, "request_count": 2, "pricing_complete": True,
                "pricing_groups": [
                    {"model": "model-a", "requested_models": ["model-a"], "request_count": 1,
                     "usage": {"total_tokens": 10, "input_tokens": 8}},
                    {"model": "model-b", "requested_models": ["model-b"], "request_count": 1,
                     "usage": {"total_tokens": 20, "input_tokens": 16}},
                ]}
        child = {"thread_id": "child", "parent_thread_id": "root", "agent_role": "evidence",
                 "agent_path": "/root/read", "usage": {"total_tokens": 5, "input_tokens": 4, "output_tokens": 1},
                 "usage_complete": True, "request_count": 1, "pricing_complete": True,
                 "pricing_groups": [{"model": "model-c", "requested_models": ["model-c"], "request_count": 1,
                                     "usage": {"total_tokens": 5, "input_tokens": 4}}]}
        receipt = {"subject_seconds": 4.0, "values": {"quality.reward": 1}, "codex": {"usage": usage, "usage_complete": True,
                   "api_equivalent_cost": {"request_count": 3}, "agent_usage": [root, child]},
                   "trace": {"observed": [
                       {"events": [{"kind": "tool_call"}, {"kind": "wait"}]},
                       {"events": [{"kind": "tool_call"}]},
                   ]}}
        rows = _facts(study, job, receipt, {"timing.queue_seconds": 1.0, "timing.prepare_seconds": 2.0,
                                            "timing.verify_seconds": 3.0})
        attempt = rows[0]
        agents = [row for row in rows if row["grain"] == "agent"]
        self.assertEqual(attempt["values"]["attempt_requests"], 3)
        self.assertEqual(attempt["values"]["attempt_tools"], 2)
        self.assertEqual(attempt["values"]["verify_seconds"], 3.0)
        self.assertEqual(attempt["values"]["reward_value"], 1)
        self.assertEqual(agents[0]["dimensions"]["model"], "mixed")
        self.assertEqual(agents[0]["dimensions"]["models"], ["model-a", "model-b"])
        self.assertEqual(agents[1]["dimensions"]["model"], "model-c")
        self.assertEqual(agents[1]["dimensions"]["parent_agent"], "a1")
        self.assertEqual(agents[1]["values"]["agent_requests"], 1)
        self.assertFalse(any(row["grain"] == "request" for row in rows))
        self.assertEqual([row["values"]["event_kind"] for row in rows if row["grain"] == "event"],
                         ["tool_call", "wait", "tool_call"])


if __name__ == "__main__":
    unittest.main()
