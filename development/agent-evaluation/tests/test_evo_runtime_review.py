from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.review import REVIEW_SUBMISSION_SCHEMA, import_review_assessments
from evo.runtime import run, submit
from evo.runtime_review import prepare_study_reviews, study_artifacts_with_reviews, sync_study_reviews
from evo.scoring import score_artifacts
from evo.store import Store


def make_spec(counter: Path) -> dict:
    script = (
        "import json,pathlib; p=pathlib.Path(" + repr(str(counter)) + "); "
        "n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); "
        "print(json.dumps({'quality.reward': 1}))"
    )
    return {
        "schema": "agentbase-evo-research/v1", "id": "runtime-human", "version": "1",
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "candidate", "members": {}}],
        "evaluations": {
            "items": [{
                "id": "case", "input_version": "1", "protocol": "command-v1", "observations": ["quality"],
                "runtime": {
                    "adapter": "command", "argv": [sys.executable, "-X", "utf8", "-c", script], "timeout_seconds": 10,
                    "rubric": {"scoring": "human", "fields": ["human.quality"], "blind": True},
                },
            }],
            "groups": [{"id": "runtime", "active": True, "items": ["case"]}],
        },
        "fields": [
            {"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "command stdout"},
            {"id": "timing.subject_seconds", "type": "number", "unit": "second", "grain": "attempt", "source": "Evo runtime"},
            {"id": "human.quality", "type": "number", "unit": "score", "grain": "assessment", "source": "explicit human review", "description": "Quality from 0 to 1"},
        ],
        "scoring": [{
            "id": "human", "version": "1", "rubric": {"instructions": "Assign human.quality from 0 to 1."},
            "group_by": ["combination"],
            "metrics": [{"id": "human_mean", "unit": "score", "missing": "exclude", "expression": {"aggregate": "mean", "field": "human.quality"}}],
        }],
        "selection": {"combinations": ["candidate"], "groups": ["runtime"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": 1000},
    }


class EvoRuntimeReviewTests(unittest.TestCase):
    def test_runtime_human_review_resume_and_score_without_subject_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, state, work = root / "project", root / "state", root / "work"
            project.mkdir()
            counter = project / "subject-count.txt"
            spec = make_spec(counter)
            spec_path = project / "study.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            store = Store(state)
            store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
            study = submit(store, spec_path, project, work)

            status = run(store, study=study)
            self.assertEqual(status["counts"], {"awaiting_human": 1})
            self.assertEqual(status["tokens_reserved"], 0)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")
            prepared = prepare_study_reviews(store, study)
            self.assertEqual(len(prepared), 1)
            package_path = Path(prepared[0]["path"])
            package = json.loads(package_path.read_text(encoding="utf-8"))
            self.assertEqual(package["rubric"]["content"]["instructions"], "Assign human.quality from 0 to 1.")

            submission = {
                "schema": REVIEW_SUBMISSION_SCHEMA, "package_id": package["package_id"],
                "research": package["research"], "artifacts": package["artifacts"],
                "rubric": package["rubric"], "fields": package["fields"],
                "assessments": [{"review_key": "item-0001", "field": "human.quality", "value": ""}],
            }
            partial = import_review_assessments(state, submission)
            self.assertFalse(partial["complete"])
            self.assertFalse(sync_study_reviews(store, study)[0]["complete"])
            self.assertEqual(store.jobs(study)[0]["state"], "awaiting_human")
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")

            submission["assessments"] = [{"review_key": "item-0001", "field": "human.quality", "value": 0.4}]
            first = import_review_assessments(state, submission)
            first_id = first["imported"][0]
            synced = sync_study_reviews(store, study)
            self.assertTrue(synced[0]["complete"])
            job = store.jobs(study)[0]
            self.assertEqual(job["state"], "completed")
            self.assertIsNone(job["workspace_slot"])
            self.assertIsNotNone(job["receipt"])
            self.assertEqual(job["usage"], 0)

            submission["assessments"] = [{
                "review_key": "item-0001", "field": "human.quality", "value": 0.9, "supersedes": first_id,
            }]
            import_review_assessments(state, submission)
            observed = study_artifacts_with_reviews(store, study)
            scores = score_artifacts(spec, observed, ["human"])
            self.assertEqual(scores["scores"][0]["groups"][0]["metrics"][0]["value"], 0.9)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")
            self.assertEqual(run(store, study=study)["counts"], {"completed": 1})
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")


if __name__ == "__main__":
    unittest.main()
