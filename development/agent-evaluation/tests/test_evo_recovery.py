from __future__ import annotations

import json
import copy
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo import runtime_cli
from evo.runtime import artifacts, immutable_json, prepare_workspace, recover, submit
from evo.store import Store
from evo.spec import EvoError


def spec() -> dict:
    return {
        "schema": "agentbase-evo-research/v1", "id": "recovery", "version": "1",
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "empty", "members": {}}],
        "evaluations": {"items": [{"id": "case", "input_version": "1", "protocol": "command-v1",
            "observations": ["quality"], "runtime": {"adapter": "command", "argv": [sys.executable, "-c", "print('{}')"]}}],
            "groups": [{"id": "all", "active": True, "items": ["case"]}]},
        "fields": [{"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "test"}],
        "scoring": [{"id": "quality", "version": "1", "metrics": [{"id": "reward", "unit": "ratio",
            "expression": {"aggregate": "mean", "field": "quality.reward"}}]}],
        "selection": {"combinations": ["empty"], "groups": ["all"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": 1000},
    }


class EvoRecoveryTests(unittest.TestCase):
    def test_confirm_stopped_releases_cancelled_job_without_fabricating_usage_or_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / 'project', root / 'state', root / 'work'
            project.mkdir()
            source = project / 'spec.json'
            source.write_text(json.dumps(spec()), encoding='utf-8')
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            study = submit(store, source, project, work)
            job = store.claim(study)
            workspace = prepare_workspace(store, store.study(study), job)
            store.finish(job['id'], 'uncertain', usage=7, usage_complete=False, error='interrupted')
            with self.assertRaises(EvoError):
                recover(store, study, confirm_stopped=job['id'], evidence='owned process tree exited')
            store.control(study, 'cancelled')
            with mock.patch('evo.runtime.run_command', side_effect=AssertionError('must not invoke verifier')):
                result = recover(store, study, confirm_stopped=job['id'], evidence='owned process tree exited')
            current = store.jobs(study)[0]
            self.assertEqual((current['state'], current['usage'], current['usage_complete']), ('cancelled', 7, False))
            self.assertIsNone(current['receipt'])
            self.assertEqual(result['resources']['active_jobs'], 0)
            self.assertTrue(workspace.is_dir())

    def test_settled_codex_job_recovers_usage_without_replacing_subject_receipt_or_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            value = spec()
            value["fields"].extend([
                {"id": "usage.total_tokens", "type": "integer", "unit": "token", "grain": "attempt", "source": "native"},
                {"id": "agent_tokens", "type": "integer", "unit": "token", "grain": "agent",
                 "source": "native", "extract": {"from": "agent", "path": "usage.total_tokens"}},
            ])
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(value), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            claimed = store.claim(study)
            attempt = state / "jobs" / f"j{claimed['id']}"
            attempt.mkdir(parents=True)
            with store.connect(True) as db:
                runtime = dict(claimed["runtime"])
                runtime["adapter"] = "codex"
                db.execute("UPDATE jobs SET runtime=? WHERE id=?", (json.dumps(runtime), claimed["id"]))
            old_raw = {
                "schema": "agentbase.evo-codex-run/v1", "status": "completed", "model_invoked": True,
                "root_thread_id": "thread-1", "usage": {"total_tokens": 10},
                "usage_complete": False, "agent_usage": [],
            }
            finalized_raw = {
                **old_raw, "usage": {"total_tokens": 42}, "usage_complete": True,
                "agent_usage": [{"thread_id": "root", "agent_role": "root", "usage_complete": True,
                                 "usage": {"total_tokens": 42}, "request_count": 1, "pricing_groups": []}],
            }
            immutable_json(attempt / "codex-result.json", old_raw)
            immutable_json(attempt / "intent.json", {"execution_identity": claimed["identity"]})
            receipt = {
                "schema": "agentbase-evo-run/v1", "execution_identity": claimed["identity"],
                "job": claimed["id"], "study": study, "codex": old_raw, "subject_seconds": 1.0,
                "values": {"quality.reward": 1}, "usage": 10, "usage_complete": False,
                "facts": [], "awaiting_human": True,
            }
            immutable_json(attempt / "receipt.json", receipt)
            receipt_before = (attempt / "receipt.json").read_bytes()
            store.finish(claimed["id"], "awaiting_human", receipt=f"jobs/j{claimed['id']}/receipt.json",
                         usage=10, usage_complete=False)

            def recovered(**_kwargs):
                (attempt / "codex-result.json").write_text(json.dumps(finalized_raw), encoding="utf-8")
                return {"raw_receipt": finalized_raw, "trace": receipt.get("trace", {})}

            with (
                mock.patch("evo.codex_adapter.recover_codex_artifacts", side_effect=recovered),
                mock.patch("evo.runtime.run_command", side_effect=AssertionError("verifier rerun")),
            ):
                recover(store, study)

            current = store.jobs(study)[0]
            self.assertEqual((current["state"], current["usage"], current["usage_complete"]),
                             ("awaiting_human", 42, True))
            self.assertEqual((attempt / "receipt.json").read_bytes(), receipt_before)
            rows = artifacts(store, study)["rows"]
            attempt_row = next(row for row in rows if row["grain"] == "attempt")
            agent_row = next(row for row in rows if row["grain"] == "agent")
            self.assertEqual(attempt_row["values"]["quality.reward"], 1)
            self.assertEqual(attempt_row["values"]["usage.total_tokens"], 42)
            self.assertEqual(attempt_row["source"]["kind"], "evo-usage-projection")
            self.assertIn(f"jobs/j{claimed['id']}/codex-result.json", attempt_row["source"]["inputs"])
            self.assertEqual(agent_row["values"]["agent_tokens"], 42)

    def test_settled_usage_recovery_rejects_a_raw_receipt_from_another_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(spec()), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            claimed = store.claim(study)
            attempt = state / "jobs" / f"j{claimed['id']}"
            attempt.mkdir(parents=True)
            with store.connect(True) as db:
                runtime = dict(claimed["runtime"])
                runtime["adapter"] = "codex"
                db.execute("UPDATE jobs SET runtime=? WHERE id=?", (json.dumps(runtime), claimed["id"]))
            immutable_json(attempt / "intent.json", {"execution_identity": claimed["identity"]})
            immutable_json(attempt / "codex-result.json", {
                "schema": "agentbase.evo-codex-run/v1", "status": "completed", "model_invoked": True,
                "root_thread_id": "other-thread", "usage": {"total_tokens": 99},
                "usage_complete": True, "agent_usage": [],
            })
            receipt = {
                "schema": "agentbase-evo-run/v1", "execution_identity": claimed["identity"],
                "job": claimed["id"], "study": study,
                "codex": {"schema": "agentbase.evo-codex-run/v1", "status": "completed",
                           "model_invoked": True, "root_thread_id": "thread-1",
                           "usage": {"total_tokens": 10}, "usage_complete": False, "agent_usage": []},
                "subject_seconds": 1.0, "values": {"quality.reward": 1},
                "usage": 10, "usage_complete": False, "facts": [], "awaiting_human": False,
            }
            immutable_json(attempt / "receipt.json", receipt)
            store.finish(claimed["id"], "completed", receipt=f"jobs/j{claimed['id']}/receipt.json",
                         usage=10, usage_complete=False)

            with mock.patch("evo.codex_adapter.recover_codex_artifacts") as finalize:
                with self.assertRaisesRegex(EvoError, "does not match"):
                    recover(store, study)
                finalize.assert_not_called()
            current = store.jobs(study)[0]
            self.assertEqual((current["usage"], current["usage_complete"]), (10, False))
            rows = artifacts(store, study)["rows"]
            self.assertEqual(len([row for row in rows if row["grain"] == "agent"]), 0)
            self.assertEqual(rows[0]["values"]["quality.reward"], 1)

    def test_resources_scans_managed_roots_once_and_status_uses_db_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            store = Store(state)
            store.initialize(concurrency=2, model_capacity=3, max_disk_mb=64, min_free_mb=1)
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(spec()), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            status = store.status(study)
            self.assertEqual(status["resources"]["job_capacity"], 2)
            self.assertEqual(status["resources"]["model_slot_capacity"], 3)
            with mock.patch("evo.runtime.disk_bytes", wraps=__import__("evo.runtime", fromlist=["disk_bytes"]).disk_bytes) as scan:
                result = runtime_cli.handle(SimpleNamespace(action="resources", state_root=state,
                                                             study=f"s{study}"))
            scan.assert_called_once()
            self.assertTrue(result["managed_storage"]["complete"])
            self.assertGreater(result["managed_storage"]["used_bytes"], 0)
            self.assertEqual(result["managed_storage"]["max_bytes"], 64 * 1024**2)
            self.assertEqual(result["capacity"]["job_limit"], 2)
            self.assertEqual(len({volume["volume"] for volume in result["volumes"]}), len(result["volumes"]))
            self.assertNotIn("installed", json.dumps(result).lower())

    def test_failed_launcher_precondition_receipt_is_reconciled_without_model_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(spec()), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            job = store.claim(study)
            workspace = prepare_workspace(store, store.study(study), job)
            attempt = state / "jobs" / f"j{job['id']}"
            attempt.mkdir(parents=True)
            immutable_json(attempt / "intent.json", {"workspace": str(workspace)})
            raw = {"schema": "agentbase.evo-codex-run/v1", "status": "precondition_failed",
                   "process_started": True, "model_invoked": False, "root_thread_id": None,
                   "thread_started_count": 0, "event_count": 0, "exit_code": 1,
                   "diagnostic": "configuration rejected before session"}
            immutable_json(attempt / "codex-result.json", raw)
            with store.connect(True) as db:
                runtime = dict(job["runtime"])
                runtime["adapter"] = "codex"
                db.execute("UPDATE jobs SET runtime=? WHERE id=?", (json.dumps(runtime), job["id"]))
            store.finish(job["id"], "failed", error="adapter ended as failed")
            recovered = {"raw_receipt": raw, "trace": {}}
            with mock.patch("evo.codex_adapter.recover_codex_artifacts", return_value=recovered):
                result = recover(store, study, installed_codex_root=root / "codex")
            current = store.jobs(study)[0]
            self.assertEqual(result["usage_unsettled"], 0)
            self.assertEqual((current["state"], current["usage"], current["usage_complete"]),
                             ("failed", 0, True))
            self.assertEqual(current["error"], "adapter ended as failed")
            self.assertEqual(json.loads((workspace / ".evo-slot.json").read_text())["state"], "reusable")

    def test_candidate_sources_are_frozen_only_from_managed_candidate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            candidate = state / "candidates" / "c1"
            candidate.mkdir(parents=True)
            source = candidate / "rules.md"
            source.write_text("candidate", encoding="utf-8")
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            value = spec()
            value["components"]["agents_md"] = [{"id": "rules", "source": str(source)}]
            value["combinations"][0]["members"] = {"agents_md": ["rules"]}
            value["evaluations"]["items"][0]["runtime"]["candidate_source_roots"] = [str(candidate)]
            spec_path = project / "candidate.json"
            spec_path.write_text(json.dumps(value), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            inventory = store.jobs(study)[0]["plan"]["source_inventory"]
            self.assertEqual(inventory["agents_md:rules"][0]["bytes"], len("candidate"))

            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            invalid = copy.deepcopy(value)
            invalid["id"] = "outside"
            invalid["components"]["agents_md"][0]["source"] = str(outside)
            invalid_path = project / "outside.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(EvoError):
                submit(store, invalid_path, project, work)

    def test_cli_migrates_existing_state_before_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            Store(state).initialize(max_disk_mb=64, min_free_mb=1)
            db = sqlite3.connect(state / "evo.sqlite3")
            try:
                db.execute("ALTER TABLE jobs DROP COLUMN attempt_seq")
                db.commit()
            finally:
                db.close()
            result = runtime_cli.handle(SimpleNamespace(action="status", state_root=state, study=None,
                                                         offset=0, limit=100))
            self.assertEqual(result["total_jobs"], 0)
            db = sqlite3.connect(state / "evo.sqlite3")
            try:
                columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            finally:
                db.close()
            self.assertIn("attempt_seq", columns)

    def test_retry_resumes_after_attempt_archive_precedes_database_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            store = Store(state)
            store.initialize(max_disk_mb=64, min_free_mb=1)
            value = spec()
            spec_path = project / "spec.json"
            spec_path.write_text(json.dumps(value), encoding="utf-8")
            study = submit(store, spec_path, project, work)
            job = store.claim(study)
            workspace = prepare_workspace(store, store.study(study), job)
            attempt = state / "jobs" / f"j{job['id']}"
            immutable_json(attempt / "intent.json", {"execution_identity": job["identity"], "attempt": 1,
                                                       "workspace": str(workspace), "runtime": job["runtime"]})
            (attempt / "preflight.txt").write_text("failed before launch", encoding="utf-8")
            store.finish(job["id"], "uncertain", error="pre-launch probe failed")
            recover(store, study, confirm_not_invoked=job["id"], evidence="adapter exception proves model_invoked=false")

            archive = attempt / "attempts" / "a1"
            archive.mkdir(parents=True)
            for path in list(attempt.iterdir()):
                if path.name != "attempts":
                    path.replace(archive / path.name)

            result = recover(store, study, retry_not_invoked=job["id"],
                             evidence="resume after archive-before-database interruption")
            current = store.jobs(study)[0]
            self.assertEqual(result["counts"], {"queued": 1})
            self.assertEqual(current["attempt_seq"], 2)
            self.assertEqual(current["reason"], "explicit retry after confirmed non-invocation")
            self.assertTrue((archive / "intent.json").is_file())
            kinds = [event["kind"] for event in store.trace(study, job["id"], 0, 50)]
            self.assertIn("reconciled_not_invoked", kinds)
            self.assertIn("retry_queued", kinds)

    def test_settled_zero_usage_prelaunch_failure_can_be_explicitly_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); project, state, work = root / 'project', root / 'state', root / 'work'
            project.mkdir(); store = Store(state); store.initialize(max_disk_mb=64, min_free_mb=1)
            spec_path = project / 'spec.json'; spec_path.write_text(json.dumps(spec()), encoding='utf-8')
            study = submit(store, spec_path, project, work); job = store.claim(study)
            store.finish(job['id'], 'failed', usage=0, usage_complete=True,
                         error='writable slot contains an unmanaged link')
            recover(store, study, confirm_not_invoked=job['id'], evidence='framework settled prelaunch failure at zero usage')
            result = recover(store, study, retry_not_invoked=job['id'], evidence='retry after slot owner repair')
            self.assertEqual(result['counts'], {'queued': 1})
            self.assertEqual(store.jobs(study)[0]['attempt_seq'], 2)


if __name__ == "__main__":
    unittest.main()
