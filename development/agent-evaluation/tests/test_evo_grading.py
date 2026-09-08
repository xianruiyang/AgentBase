from __future__ import annotations

import json
import copy
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.grading import merge_model_grading_artifacts, prepare_artifact_grading, prepare_model_grading, run_model_grading, study_artifacts_with_model_grades
from evo.runtime import artifacts, run, submit
from evo.scoring import score_artifacts
from evo.spec import EvoError
from evo.store import Store


def spec_with_grader(grader_value: float = 0.8) -> dict:
    subject_script = "import json; print(json.dumps({'quality.reward': 1}))"
    grader_script = (
        "import json,sys; data=json.loads(sys.argv[1]); "
        f"print(json.dumps({{'assessments':[{{'row':r['row'],'field':'model.quality','value':{grader_value}}} for r in data['rows']]}}))"
    )
    return {
        "schema": "agentbase-evo-research/v1", "id": "model-grading", "version": "1",
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "subject", "members": {}}],
        "evaluations": {"items": [{"id": "case", "input_version": "1", "protocol": "command-v1", "observations": ["quality"],
                                    "runtime": {"adapter": "command", "argv": [sys.executable, "-X", "utf8", "-c", subject_script], "timeout_seconds": 10}}],
                        "groups": [{"id": "runtime", "active": True, "items": ["case"]}]},
        "fields": [
            {"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "subject receipt"},
            {"id": "timing.subject_seconds", "type": "number", "unit": "second", "grain": "attempt", "source": "runtime"},
            {"id": "model.quality", "type": "number", "unit": "score", "grain": "assessment", "source": "independent model grader"},
        ],
        "scoring": [{"id": "model-score", "version": "1", "group_by": ["combination"],
                     "metrics": [{"id": "quality", "unit": "score", "missing": "exclude",
                                  "expression": {"aggregate": "mean", "field": "model.quality"}}]}],
        "grading": [{
            "id": "independent", "version": "1", "rubric": {"instructions": "Judge correctness from 0 to 1."},
            "select": {"grains": ["attempt"], "fields": ["quality.reward"]},
            "outputs": [{"field": "model.quality", "minimum": 0, "maximum": 1}],
            "controller": {"adapter": "command", "argv": [sys.executable, "-X", "utf8", "-c", grader_script, "{grading_json}"],
                           "token_budget": 100, "timeout_seconds": 10},
        }],
        "selection": {"combinations": ["subject"], "groups": ["runtime"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": 1000},
    }


class EvoGradingTests(unittest.TestCase):
    def fixture(self, spec: dict):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project, state, work = root / "project", root / "state", root / "work"
        project.mkdir()
        path = project / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        store = Store(state)
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        return store, project, work, path

    def test_explicit_grader_study_freezes_runs_reports_usage_and_scores(self) -> None:
        spec = spec_with_grader()
        store, _project, _work, path = self.fixture(spec)
        subject = submit(store, path, _project, _work)
        self.assertEqual(run(store, study=subject)["counts"], {"completed": 1})
        subject_receipt = store.root / store.jobs(subject)[0]["receipt"]
        before = subject_receipt.read_bytes()

        prepared = prepare_model_grading(store, subject, "independent")
        repeated = prepare_model_grading(store, subject, "independent")
        self.assertEqual(prepared["grader_study"], repeated["grader_study"])
        grader = int(prepared["grader_study"].removeprefix("s"))
        self.assertEqual(store.jobs(grader)[0]["state"], "queued")
        result = run_model_grading(store, grader)
        self.assertEqual(result["grader_usage"], {"tokens": 0, "complete": True})
        self.assertEqual(result["research_usage"]["total_tokens"], 0)
        self.assertEqual(result["facts"]["rows"][0]["values"]["model.quality"], 0.8)
        self.assertEqual(result["facts"]["rows"][0]["source"]["kind"], "model-grader-receipt")

        merged = study_artifacts_with_model_grades(store, subject)
        score = score_artifacts(spec, merged, ["model-score"])
        self.assertEqual(score["scores"][0]["groups"][0]["metrics"][0]["value"], 0.8)
        self.assertEqual(subject_receipt.read_bytes(), before)
        self.assertEqual(run_model_grading(store, grader)["facts"], result["facts"])

    def test_invalid_grader_value_is_not_converted_to_zero(self) -> None:
        spec = spec_with_grader(1.5)
        store, project, work, path = self.fixture(spec)
        subject = submit(store, path, project, work)
        run(store, study=subject)
        grader = int(prepare_model_grading(store, subject, "independent")["grader_study"].removeprefix("s"))
        with self.assertRaisesRegex(EvoError, "exceeds maximum"):
            run_model_grading(store, grader)

    def test_same_owner_accepts_explicit_existing_artifacts(self) -> None:
        spec = spec_with_grader()
        store, project, work, path = self.fixture(spec)
        subject = submit(store, path, project, work)
        run(store, study=subject)
        existing = artifacts(store, subject)
        prepared = prepare_artifact_grading(store, spec, existing, "independent", project, work)
        grader = int(prepared["grader_study"].removeprefix("s"))
        result = run_model_grading(store, grader)
        self.assertIsNone(result["facts"]["subject_study"])
        self.assertEqual(result["facts"]["rows"][0]["values"]["model.quality"], 0.8)
        before = copy.deepcopy(existing)
        merged = merge_model_grading_artifacts(existing, store, grader)
        self.assertEqual(existing, before)
        self.assertEqual([row["grain"] for row in merged["rows"]], ["attempt", "assessment"])
        self.assertEqual(score_artifacts(spec, merged, ["model-score"])["scores"][0]["groups"][0]["metrics"][0]["value"], 0.8)

    def test_all_linked_grader_reservations_share_subject_budget(self) -> None:
        spec = spec_with_grader()
        second = copy.deepcopy(spec["grading"][0])
        second["id"] = "expensive"
        second["version"] = "2"
        second["controller"]["token_budget"] = 950
        spec["grading"].append(second)
        store, project, work, path = self.fixture(spec)
        subject = submit(store, path, project, work)
        run(store, study=subject)
        first = prepare_model_grading(store, subject, "independent")
        reused = prepare_model_grading(store, subject, "independent")
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["grader_study"], first["grader_study"])
        with self.assertRaisesRegex(EvoError, "all grader usage/reservations"):
            prepare_model_grading(store, subject, "expensive")


if __name__ == "__main__":
    unittest.main()
