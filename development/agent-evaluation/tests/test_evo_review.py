from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.review import (
    REVIEW_SUBMISSION_SCHEMA,
    export_review_package,
    import_review_assessments,
    merge_review_artifacts,
    review_completion,
)
from evo.review_cli import ACTIONS, add_commands, handle
from evo.scoring import score_artifacts
from evo.spec import EvoError, load_artifacts, load_spec, validate_spec
from evaluation_core import CaseLock


FIXTURE_ROOT = EVALUATION_ROOT / "tests" / "fixtures" / "evo"


def review_spec() -> dict:
    spec = load_spec(FIXTURE_ROOT / "research-v1.json")
    spec = copy.deepcopy(spec)
    spec["fields"].append({
        "id": "human.quality", "type": "number", "unit": "score",
        "grain": "assessment", "source": "explicit human review",
    })
    spec["scoring"].append({
        "id": "human-quality", "version": "1", "group_by": ["combination"],
        "metrics": [{
            "id": "human_mean", "unit": "score", "missing": "exclude",
            "expression": {"aggregate": "mean", "field": "human.quality"},
        }],
    })
    validate_spec(spec)
    return spec


class EvoReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = review_spec()
        self.artifacts = load_artifacts(FIXTURE_ROOT / "artifacts-v1.json")

    def _submission(self, package: dict, assessments: list[dict]) -> dict:
        return {
            "schema": REVIEW_SUBMISSION_SCHEMA,
            "package_id": package["package_id"],
            "research": package["research"],
            "artifacts": package["artifacts"],
            "rubric": package["rubric"],
            "fields": package["fields"],
            "assessments": assessments,
        }

    def test_offline_export_partial_correction_merge_and_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            package = export_review_package(
                self.spec, self.artifacts, state_root, "human-quality", ["human.quality"], blind=True,
            )
            self.assertEqual(package["items"][0]["dimensions"]["combination"], "candidate-1")
            self.assertEqual(package["items"][2]["dimensions"]["combination"], "candidate-2")
            self.assertIn("values", package["items"][0])
            self.assertNotIn("combo-a", json.dumps(package))

            first = self._submission(package, [
                {"review_key": "item-0001", "field": "human.quality", "value": 0.25, "comment": "initial"},
                {"review_key": "item-0002", "field": "human.quality", "value": ""},
            ])
            partial = import_review_assessments(state_root, first)
            self.assertFalse(partial["complete"])
            self.assertEqual(partial["skipped_blank"], 1)
            initial_id = partial["imported"][0]
            self.assertEqual(len(partial["missing"]), 3)

            duplicate = import_review_assessments(state_root, first)
            self.assertEqual(duplicate["imported"], [initial_id])
            assessment_files = list((state_root / "reviews" / "assessments").glob("*.json"))
            self.assertEqual(len(assessment_files), 1)

            completed = self._submission(package, [
                {"review_key": "item-0001", "field": "human.quality", "value": 0.75, "comment": "corrected", "supersedes": initial_id},
                {"review_key": "item-0002", "field": "human.quality", "value": 0.5},
                {"review_key": "item-0003", "field": "human.quality", "value": 1.0},
                {"review_key": "item-0004", "field": "human.quality", "value": 0.5},
            ])
            result = import_review_assessments(state_root, completed)
            self.assertTrue(result["complete"])
            self.assertEqual(result["missing"], [])
            self.assertEqual(review_completion(state_root, package["package_id"])["alias"], package["alias"])

            merged = merge_review_artifacts(self.artifacts, state_root, package["package_id"])
            assessment_rows = [row for row in merged["rows"] if row["grain"] == "assessment"]
            self.assertEqual(len(assessment_rows), 4)
            first_value = next(row["values"]["human.quality"] for row in assessment_rows if row["dimensions"]["combination"] == "combo-a" and row["dimensions"]["item"] == "reuse")
            self.assertEqual(first_value, 0.75)
            scores = score_artifacts(self.spec, merged, ["human-quality"])
            values = {group["dimensions"]["combination"]: group["metrics"][0]["value"] for group in scores["scores"][0]["groups"]}
            self.assertEqual(values, {"combo-a": 0.625, "combo-b": 0.75})
            self.assertEqual(len(list((state_root / "reviews" / "assessments").glob("*.json"))), 5)

    def test_wrong_binding_and_implicit_correction_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            package = export_review_package(self.spec, self.artifacts, state_root, "human-quality", ["human.quality"])
            wrong = self._submission(package, [])
            wrong["rubric"] = {**wrong["rubric"], "version": "wrong"}
            with self.assertRaisesRegex(EvoError, "rubric binding"):
                import_review_assessments(state_root, wrong)
            original = self._submission(package, [{"review_key": "item-0001", "field": "human.quality", "value": 0.2}])
            import_review_assessments(state_root, original)
            implicit = self._submission(package, [{"review_key": "item-0001", "field": "human.quality", "value": 0.3}])
            with self.assertRaisesRegex(EvoError, "must explicitly supersede"):
                import_review_assessments(state_root, implicit)

    def test_frozen_artifact_binding_rejects_different_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            package = export_review_package(self.spec, self.artifacts, state_root, "human-quality", ["human.quality"])
            changed = copy.deepcopy(self.artifacts)
            changed["rows"][0]["values"]["quality.reward"] = 0
            with self.assertRaisesRegex(EvoError, "do not match frozen"):
                merge_review_artifacts(changed, state_root, package["package_id"])

    def test_review_cli_contract_exports_and_reports_status(self) -> None:
        import argparse
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="action", required=True)
        add_commands(commands)
        self.assertEqual(ACTIONS, {"review-export", "review-import", "review-status", "review-merge", "review-prepare", "review-sync"})
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            output_path = Path(directory) / "review.json"
            spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
            args = parser.parse_args([
                "review-export", "--spec", str(spec_path), "--artifacts", str(FIXTURE_ROOT / "artifacts-v1.json"),
                "--state-root", directory, "--scoring", "human-quality", "--field", "human.quality",
                "--blind", "--output", str(output_path),
            ])
            exported = handle(args)
            self.assertTrue(output_path.is_file())
            package = json.loads(output_path.read_text(encoding="utf-8"))
            status_args = parser.parse_args(["review-status", "--state-root", directory, "--package-id", package["package_id"]])
            status = handle(status_args)
            self.assertEqual(exported["id"], package["package_id"])
            self.assertFalse(status["complete"])

    def test_safe_alias_rubric_blind_source_and_explicit_row_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            mixed = copy.deepcopy(self.artifacts)
            mixed["rows"].append({
                "id": "event-extra", "grain": "event", "dimensions": {"combination": "combo-a"},
                "values": {}, "source": {"kind": "trace", "location": "combo-a/private.jsonl"},
                "completeness": "complete",
            })
            package = export_review_package(self.spec, mixed, state_root, "human-quality", ["human.quality"], blind=True)
            self.assertEqual(len(package["items"]), 4)
            self.assertIn("instructions", package["rubric"]["content"])
            self.assertEqual(package["artifacts"]["id"], "anonymous-artifacts")
            self.assertTrue(all(item["source"]["kind"] == "archived-evidence" for item in package["items"]))
            self.assertEqual(review_completion(state_root, package["alias"])["alias"], package["alias"])
            with self.assertRaisesRegex(EvoError, "64-character machine id"):
                review_completion(state_root, "../outside")
            event_package = export_review_package(
                self.spec, mixed, state_root, "human-quality", ["human.quality"], row_ids=["event-extra"],
            )
            self.assertEqual([item["review_key"] for item in event_package["items"]], ["item-0001"])

    def test_import_refuses_concurrent_assessment_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            package = export_review_package(self.spec, self.artifacts, state_root, "human-quality", ["human.quality"])
            submission = self._submission(package, [
                {"review_key": "item-0001", "field": "human.quality", "value": 0.5},
            ])
            with CaseLock(state_root, "evo-review-assessments"):
                with self.assertRaisesRegex(EvoError, "already locked"):
                    import_review_assessments(state_root, submission)
            self.assertFalse((state_root / "reviews" / "assessments").exists())


if __name__ == "__main__":
    unittest.main()
