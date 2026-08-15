from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "experiment.py"
SPEC = importlib.util.spec_from_file_location("source_query_experiment", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExperimentTests(unittest.TestCase):
    def test_candidate_path_prepend_is_scoped_to_the_recorded_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            runtime = home / "skills" / "source-query" / "bin"
            runtime.mkdir(parents=True)
            resolved = MODULE.resolve_path_prepend(home.resolve(), "skills/source-query/bin", "candidate")
            self.assertEqual(runtime.resolve(), resolved)
            with self.assertRaisesRegex(MODULE.ExperimentError, "escapes codex home"):
                MODULE.resolve_path_prepend(home.resolve(), "../outside", "candidate")

    def test_two_repetition_schedule_is_balanced(self) -> None:
        schedule = MODULE.balanced_schedule(["a", "b"], 2, 7)
        for case_id in ("a", "b"):
            selected = [item for item in schedule if item["case_id"] == case_id]
            self.assertEqual(2, sum(item["environment"] == "control" for item in selected))
            self.assertEqual(2, sum(item["environment"] == "candidate" for item in selected))
            self.assertIn([item["environment"] for item in selected], [
                ["control", "candidate", "candidate", "control"],
                ["candidate", "control", "control", "candidate"],
            ])

    def test_candidate_only_schedule_does_not_rerun_frozen_control(self) -> None:
        schedule = MODULE.selected_schedule(["a", "b"], 2, 7, ["candidate"])
        self.assertEqual(4, len(schedule))
        self.assertTrue(all(item["environment"] == "candidate" for item in schedule))
        self.assertEqual([1, 2], [item["ordinal"] for item in schedule if item["case_id"] == "a"])

    def test_selected_case_ids_supports_affected_only_runs(self) -> None:
        corpus = {"cases": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(["a", "b"], MODULE.selected_case_ids(corpus, None))
        self.assertEqual(["b"], MODULE.selected_case_ids(corpus, ["b"]))
        with self.assertRaisesRegex(MODULE.ExperimentError, "unknown cases"):
            MODULE.selected_case_ids(corpus, ["missing"])
        with self.assertRaisesRegex(MODULE.ExperimentError, "duplicates"):
            MODULE.selected_case_ids(corpus, ["a", "a"])

    def test_capsule_hash_declares_and_excludes_only_its_own_field(self) -> None:
        capsule = {
            "schema": MODULE.CAPSULE_SCHEMA,
            "capsule_hash_scheme": MODULE.CAPSULE_HASH_SCHEME,
            "payload": {"answer": 42},
        }
        digest = MODULE.capsule_sha256(capsule)
        capsule["capsule_sha256"] = digest
        self.assertEqual(digest, MODULE.capsule_sha256(capsule))
        capsule["payload"]["answer"] = 43
        self.assertNotEqual(digest, MODULE.capsule_sha256(capsule))

    def test_environment_diff_rejects_unlisted_change(self) -> None:
        result = MODULE.environment_diff({"same": "1", "extra": "a"}, {"same": "1", "extra": "b"}, ["skills/**"])
        self.assertFalse(result["ok"])
        self.assertEqual(["extra"], result["unexpected"])

    def test_corpus_snapshot_rejects_changed_oracle_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source.txt").write_text("changed", encoding="utf-8")
            corpus = {
                "schema": "agentbase.source-query-corpus/v1",
                "cases": [{
                    "id": "case",
                    "workspace_role": "agentbase",
                    "answer_max_lines": 1,
                    "answer_contract": {"required": ["path"], "supporting": []},
                    "oracle": {"kind": "source-relation", "source": {"path": "source.txt", "sha256": "0" * 64}},
                }],
            }
            with self.assertRaisesRegex(MODULE.ExperimentError, "corpus source is stale"):
                MODULE.validate_corpus_snapshot(corpus, {"agentbase": {"path": str(root)}})

    def test_corpus_snapshot_requires_unambiguous_answer_contract(self) -> None:
        corpus = {
            "schema": MODULE.CORPUS_SCHEMA,
            "cases": [{
                "id": "case",
                "workspace_role": "agentbase",
                "answer_max_lines": 1,
                "answer_contract": {"required": ["same"], "supporting": ["same"]},
                "oracle": {"kind": "source-relation", "sources": []},
            }],
        }
        with self.assertRaisesRegex(MODULE.ExperimentError, "ambiguous answer_contract"):
            MODULE.validate_corpus_snapshot(corpus, {"agentbase": {"path": str(Path.cwd())}})

    def test_monitor_preserves_usage_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "subject.py"
            script.write_text(
                "import json,sys,time\n"
                "if sys.argv[1] == 'slow': time.sleep(3)\n"
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'answer'}}))\n"
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':4,'output_tokens':3,'reasoning_output_tokens':1}}))\n",
                encoding="utf-8",
            )
            output = root / "ok.jsonl"
            error = root / "ok.stderr"
            result = MODULE.monitor_command([sys.executable, str(script), "ok"], root, os.environ.copy(), output, error, 2)
            parsed = MODULE.parse_events(output)
            self.assertEqual(0, result["exit_code"])
            self.assertTrue(parsed["usage_complete"])
            self.assertEqual("answer", parsed["final_answer"])
            slow_output = root / "slow.jsonl"
            slow_error = root / "slow.stderr"
            slow = MODULE.monitor_command([sys.executable, str(script), "slow"], root, os.environ.copy(), slow_output, slow_error, 1)
            self.assertTrue(slow["timed_out"])


if __name__ == "__main__":
    unittest.main()
