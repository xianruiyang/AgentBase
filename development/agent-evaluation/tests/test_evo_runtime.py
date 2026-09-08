from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.runtime import artifacts, recover, run, submit
from evo.scoring import score_artifacts
from evo.store import Store


def command_argv(reward: int = 1, marker: bool = False) -> list[str]:
    if marker:
        script = (
            "import json,pathlib; p=pathlib.Path('marker.txt'); "
            "fresh=not p.exists(); p.write_text('owned',encoding='utf-8'); "
            f"print(json.dumps({{'quality.reward': {reward}, 'workspace.fresh': fresh}}))"
        )
    else:
        script = f"import json; print(json.dumps({{'quality.reward': {reward}}}))"
    return [sys.executable, "-X", "utf8", "-c", script]


def make_spec(*, item_count: int = 1, study_concurrency: int = 1, marker: bool = False) -> dict:
    items = []
    for index in range(item_count):
        items.append({
            "id": f"case-{index + 1}",
            "input_version": "1",
            "protocol": "command-v1",
            "observations": ["quality"],
            "runtime": {"adapter": "command", "argv": command_argv(marker=marker), "timeout_seconds": 10},
        })
    return {
        "schema": "agentbase-evo-research/v1",
        "id": f"runtime-{item_count}-{study_concurrency}-{int(marker)}",
        "version": "1",
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "empty", "members": {}}],
        "evaluations": {"items": items, "groups": [{"id": "runtime", "active": True, "items": [item["id"] for item in items]}]},
        "fields": [
            {"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "command stdout"},
            {"id": "timing.subject_seconds", "type": "number", "unit": "second", "grain": "attempt", "source": "Evo runtime"},
        ],
        "scoring": [{
            "id": "quality",
            "version": "1",
            "metrics": [
                {"id": "reward", "unit": "ratio", "expression": {"aggregate": "mean", "field": "quality.reward"}},
                {"id": "elapsed", "unit": "second", "expression": {"aggregate": "sum", "field": "timing.subject_seconds"}},
            ],
        }],
        "selection": {"combinations": ["empty"], "groups": ["runtime"], "replicates": 1},
        "budget": {"concurrency": study_concurrency, "max_tokens": 1000},
    }


class RuntimeFixture:
    def __init__(self, test: unittest.TestCase, *, global_concurrency: int = 2, max_disk_mb: int = 64):
        self.temporary = tempfile.TemporaryDirectory()
        test.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.state = root / "state"
        self.work = root / "work"
        self.project.mkdir()
        self.store = Store(self.state)
        self.store.initialize(concurrency=global_concurrency, model_capacity=2, max_disk_mb=max_disk_mb, min_free_mb=1)

    def submit(self, spec: dict) -> int:
        path = self.project / f"{spec['id']}.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return submit(self.store, path, self.project, self.work)


class EvoRuntimeTests(unittest.TestCase):
    def test_command_consumer_runs_and_scores_actual_receipt(self) -> None:
        fixture = RuntimeFixture(self)
        spec = make_spec()
        study = fixture.submit(spec)
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"completed": 1}, status)
        observed = artifacts(fixture.store, study)
        self.assertEqual(observed["rows"][0]["values"]["quality.reward"], 1)
        result = score_artifacts(spec, observed)
        metrics = {metric["id"]: metric for metric in result["scores"][0]["groups"][0]["metrics"]}
        self.assertEqual(metrics["reward"]["value"], 1)
        self.assertGreater(metrics["elapsed"]["value"], 0)
        self.assertEqual(metrics["reward"]["source_rows"], ["j1:attempt"])

    def test_claim_honors_study_and_global_capacity_across_studies(self) -> None:
        fixture = RuntimeFixture(self, global_concurrency=2)
        first = fixture.submit(make_spec(item_count=2, study_concurrency=1))
        second_spec = make_spec(item_count=1)
        second_spec["id"] = "second-study"
        second_spec["evaluations"]["items"][0]["runtime"]["argv"] = command_argv(reward=0)
        second = fixture.submit(second_spec)
        first_job = fixture.store.claim(first)
        self.assertIsNotNone(first_job)
        self.assertIsNone(fixture.store.claim(first))
        second_job = fixture.store.claim(second)
        self.assertIsNotNone(second_job, fixture.store.status(second))
        self.assertIsNone(fixture.store.claim())
        fixture.store.finish(first_job["id"], "completed", usage=0, usage_complete=True)
        fixture.store.finish(second_job["id"], "completed", usage=0, usage_complete=True)

    def test_pause_resume_and_cancel_control_dispatch(self) -> None:
        fixture = RuntimeFixture(self)
        paused = fixture.submit(make_spec(item_count=2))
        fixture.store.control(paused, "paused")
        self.assertIsNone(fixture.store.claim(paused))
        fixture.store.control(paused, "ready")
        claimed = fixture.store.claim(paused)
        self.assertIsNotNone(claimed)
        fixture.store.finish(claimed["id"], "completed", usage=0, usage_complete=True)
        fixture.store.control(paused, "cancelled")
        self.assertEqual(fixture.store.status(paused)["counts"], {"completed": 1, "cancelled": 1})

    def test_receipt_recovery_does_not_repeat_command(self) -> None:
        fixture = RuntimeFixture(self)
        study = fixture.submit(make_spec(marker=True))
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"completed": 1}, status)
        job = fixture.store.jobs(study)[0]
        receipt = fixture.state / job["receipt"]
        before = receipt.read_bytes()
        workspace = next(path for path in fixture.work.iterdir() if path.is_dir())
        self.assertEqual((workspace / "marker.txt").read_text(encoding="utf-8"), "owned")
        with fixture.store.connect(True) as db:
            db.execute("UPDATE jobs SET state='running',receipt=NULL,ended=NULL WHERE id=?", (job["id"],))
        recovered = recover(fixture.store, study)
        self.assertEqual(recovered["counts"], {"completed": 1})
        self.assertEqual(receipt.read_bytes(), before)
        self.assertEqual((workspace / "marker.txt").read_text(encoding="utf-8"), "owned")

    def test_formula_change_reuses_run_and_receipt(self) -> None:
        fixture = RuntimeFixture(self)
        spec = make_spec()
        study = fixture.submit(spec)
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"completed": 1}, status)
        observed = artifacts(fixture.store, study)
        receipt = fixture.state / fixture.store.jobs(study)[0]["receipt"]
        before = receipt.read_bytes()
        changed = copy.deepcopy(spec)
        changed["scoring"][0]["id"] = "quality-percent"
        changed["scoring"][0]["version"] = "2"
        changed["scoring"][0]["metrics"][0] = {
            "id": "reward_percent", "unit": "ratio",
            "expression": {"op": "multiply", "args": [{"aggregate": "mean", "field": "quality.reward"}, {"literal": 100}]},
        }
        result = score_artifacts(changed, observed)
        metric = result["scores"][0]["groups"][0]["metrics"][0]
        self.assertEqual(metric["value"], 100)
        self.assertEqual(receipt.read_bytes(), before)

    def test_distinct_workspaces_do_not_share_writable_state(self) -> None:
        fixture = RuntimeFixture(self)
        spec = make_spec(item_count=2, study_concurrency=2, marker=True)
        spec["fields"].append({"id": "workspace.fresh", "type": "boolean", "unit": "boolean", "grain": "attempt", "source": "command stdout"})
        study = fixture.submit(spec)
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"completed": 2}, status)
        rows = artifacts(fixture.store, study)["rows"]
        self.assertEqual([row["values"]["workspace.fresh"] for row in rows], [True, True])
        self.assertEqual(len([path for path in fixture.work.iterdir() if path.is_dir()]), 2)

    def test_identical_execution_across_studies_runs_once(self) -> None:
        fixture = RuntimeFixture(self)
        counter = fixture.project / "counter.txt"
        script = (
            "import json,pathlib; p=pathlib.Path(" + repr(str(counter)) + "); "
            "n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); "
            "print(json.dumps({'quality.reward': 1}))"
        )
        first_spec = make_spec()
        first_spec["evaluations"]["items"][0]["runtime"]["argv"] = [sys.executable, "-X", "utf8", "-c", script]
        second_spec = copy.deepcopy(first_spec)
        second_spec["id"] = "identical-second-study"
        first = fixture.submit(first_spec)
        second = fixture.submit(second_spec)
        self.assertEqual(run(fixture.store, study=first)["counts"], {"completed": 1})
        self.assertEqual(run(fixture.store, study=second)["counts"], {"completed": 1})
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")
        first_job = fixture.store.jobs(first)[0]
        second_job = fixture.store.jobs(second)[0]
        self.assertEqual(second_job["reused_from"], first_job["id"])
        self.assertEqual(second_job["usage"], 0)
        self.assertEqual(second_job["receipt"], first_job["receipt"])
        self.assertEqual(artifacts(fixture.store, second)["rows"][0]["dimensions"]["study"], f"s{second}")

    def test_sequential_jobs_archive_diff_and_reset_reused_slot(self) -> None:
        fixture = RuntimeFixture(self, global_concurrency=1)
        spec = make_spec(item_count=2, study_concurrency=1, marker=True)
        spec["fields"].append({"id": "workspace.fresh", "type": "boolean", "unit": "boolean", "grain": "attempt", "source": "command stdout"})
        study = fixture.submit(spec)
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"completed": 2}, status)
        rows = artifacts(fixture.store, study)["rows"]
        self.assertEqual([row["values"]["workspace.fresh"] for row in rows], [True, True])
        jobs = fixture.store.jobs(study)
        self.assertEqual([job["workspace_slot"] for job in jobs], [1, 1])
        self.assertEqual((fixture.state / "jobs" / f"j{jobs[0]['id']}" / "workspace-diff" / "marker.txt").read_text(encoding="utf-8"), "owned")

    def test_disk_shortage_keeps_job_queued_with_reason(self) -> None:
        fixture = RuntimeFixture(self, max_disk_mb=1)
        payload = fixture.project / "payload.bin"
        payload.write_bytes(b"x" * (2 * 1024 * 1024))
        spec = make_spec()
        spec["runtime"] = {"files": [{"source": "payload.bin", "target": "payload.bin"}]}
        study = fixture.submit(spec)
        status = run(fixture.store, study=study)
        self.assertEqual(status["counts"], {"queued": 1}, status)
        self.assertIn("disk budget", status["jobs"][0]["reason"])
        self.assertFalse((fixture.state / "jobs" / "j1" / "receipt.json").exists())

    def test_recover_completes_from_raw_codex_receipt_without_model(self) -> None:
        fixture = RuntimeFixture(self)
        spec = make_spec()
        runtime = {
            "adapter": "codex", "model": "synthetic-model", "reasoning_effort": "low",
            "timeout_seconds": 10, "max_agents": 1, "token_reservation": 100,
            "answer_contains": ["PASS"],
        }
        spec["evaluations"]["items"][0]["runtime"] = runtime
        study = fixture.submit(spec)
        job = fixture.store.claim(study)
        self.assertIsNotNone(job)
        attempt = fixture.state / "jobs" / f"j{job['id']}"
        (attempt / "codex-logs").mkdir(parents=True)
        (attempt / "codex-logs" / "last-message.txt").write_text("PASS", encoding="utf-8")
        raw = {
            "schema": "agentbase.evo-codex-run/v1", "model_invoked": True, "status": "completed",
            "duration_seconds": 1.25, "usage": {"total_tokens": 7}, "usage_complete": True,
            "agent_usage": [],
        }
        (attempt / "codex-result.json").write_text(json.dumps(raw), encoding="utf-8")
        status = recover(fixture.store, study)
        self.assertEqual(status["counts"], {"completed": 1}, status)
        receipt = json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["values"]["quality.reward"], 1)
        self.assertEqual(receipt["usage"], 7)
        self.assertEqual(receipt["trace"]["capability"], "unavailable")
        self.assertEqual(artifacts(fixture.store, study)["rows"][0]["values"]["quality.reward"], 1)


if __name__ == "__main__":
    unittest.main()
