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

from evo import cli
from evo.scoring import score_artifacts
from evo.selection import build_plan
from evo.spec import EvoError, load_artifacts, load_spec, validate_artifacts, validate_spec


FIXTURE_ROOT = EVALUATION_ROOT / "tests" / "fixtures" / "evo"
SPEC_PATH = FIXTURE_ROOT / "research-v1.json"
ARTIFACT_PATH = FIXTURE_ROOT / "artifacts-v1.json"


class EvoOfflineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = load_spec(SPEC_PATH)
        self.artifacts = load_artifacts(ARTIFACT_PATH)

    def test_plan_deduplicates_overlapping_groups_and_preserves_membership(self) -> None:
        plan = build_plan(self.spec)
        self.assertEqual(plan["job_count"], 4)
        reuse = [job for job in plan["jobs"] if job["item"] == "reuse"]
        self.assertEqual(len(reuse), 2)
        self.assertTrue(all(job["groups"] == ["core", "overlap"] for job in reuse))

    def test_empty_group_selection_is_an_empty_plan(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["selection"]["groups"] = []
        validate_spec(spec)
        self.assertEqual(build_plan(spec)["jobs"], [])

    def test_item_family_groups_older_facts_without_changing_receipts(self) -> None:
        original = copy.deepcopy(self.artifacts)
        for item in self.spec["evaluations"]["items"]:
            item["family"] = item["id"] + "-family"
        self.spec["scoring"][1]["group_by"] = ["family"]
        result = score_artifacts(self.spec, self.artifacts, ["speed-tools"])
        self.assertEqual({group["dimensions"]["family"] for group in result["scores"][0]["groups"]},
                         {"reuse-family", "direct-family"})
        self.assertEqual(self.artifacts, original)

    def test_unknown_or_deleted_references_are_rejected(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["evaluations"]["items"] = spec["evaluations"]["items"][1:]
        with self.assertRaisesRegex(EvoError, "references unknown evaluation item"):
            validate_spec(spec)

    def test_duplicate_selection_and_excessive_replicates_are_rejected(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["selection"]["groups"] = ["core", "core"]
        with self.assertRaisesRegex(EvoError, "contains duplicates"):
            validate_spec(spec)
        spec = copy.deepcopy(self.spec)
        spec["selection"]["replicates"] = 101
        with self.assertRaisesRegex(EvoError, "from 1 to 100"):
            validate_spec(spec)

    def test_two_score_configs_recompute_from_same_rows_without_mutation(self) -> None:
        original = copy.deepcopy(self.artifacts)
        results = score_artifacts(self.spec, self.artifacts)
        self.assertEqual(self.artifacts, original)
        self.assertEqual([score["id"] for score in results["scores"]], ["quality-cost", "speed-tools"])
        quality = results["scores"][0]["groups"]
        by_combo = {group["dimensions"]["combination"]: {metric["id"]: metric["value"] for metric in group["metrics"]} for group in quality}
        self.assertEqual(by_combo["combo-a"]["pass_rate"], 0.5)
        self.assertEqual(by_combo["combo-a"]["tokens_per_success"], 400)
        self.assertAlmostEqual(by_combo["combo-a"]["efficiency"], 0.6)
        self.assertEqual(by_combo["combo-b"]["pass_rate"], 1)
        self.assertEqual(by_combo["combo-b"]["tokens_per_success"], 300)
        self.assertAlmostEqual(by_combo["combo-b"]["efficiency"], 0.7)
        self.assertTrue(all("source_rows" in metric for group in quality for metric in group["metrics"]))

    def test_missing_values_propagate_unknown_with_coverage(self) -> None:
        artifacts = copy.deepcopy(self.artifacts)
        artifacts["rows"][0]["completeness"] = "partial"
        results = score_artifacts(self.spec, artifacts, ["quality-cost"])
        group = next(group for group in results["scores"][0]["groups"] if group["dimensions"]["combination"] == "combo-a")
        values = {metric["id"]: metric for metric in group["metrics"]}
        self.assertEqual(values["total_tokens"]["status"], "unknown")
        self.assertEqual(values["total_tokens"]["incomplete_sample_count"], 1)

    def test_other_grains_do_not_become_missing_samples_or_sources(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["fields"].append({"id": "agent.messages", "type": "integer", "unit": "message", "grain": "agent", "source": "trace"})
        artifacts = copy.deepcopy(self.artifacts)
        artifacts["rows"].append({"id": "agent-1", "grain": "agent", "dimensions": {"combination": "combo-a", "item": "reuse", "agent": "child"}, "values": {"agent.messages": 2}, "source": {"kind": "trace", "location": "trace/agent-1"}, "completeness": "complete"})
        results = score_artifacts(spec, artifacts, ["quality-cost"])
        group = next(group for group in results["scores"][0]["groups"] if group["dimensions"]["combination"] == "combo-a")
        metric = next(metric for metric in group["metrics"] if metric["id"] == "total_tokens")
        self.assertEqual(metric["sample_count"], 2)
        self.assertEqual(metric["source_rows"], ["a-direct", "a-reuse"])

    def test_zero_denominator_is_unknown(self) -> None:
        artifacts = copy.deepcopy(self.artifacts)
        for row in artifacts["rows"]:
            row["values"]["quality.reward"] = 0
        results = score_artifacts(self.spec, artifacts, ["quality-cost"])
        for group in results["scores"][0]["groups"]:
            values = {metric["id"]: metric for metric in group["metrics"]}
            self.assertEqual(values["tokens_per_success"]["status"], "unknown")

    def test_artifact_field_type_and_grain_are_checked(self) -> None:
        artifacts = copy.deepcopy(self.artifacts)
        artifacts["rows"][0]["values"]["usage.total_tokens"] = "100"
        validate_artifacts(artifacts)
        with self.assertRaisesRegex(EvoError, "does not match type"):
            score_artifacts(self.spec, artifacts)

    def test_nonfinite_values_and_incompatible_units_are_rejected(self) -> None:
        artifacts = copy.deepcopy(self.artifacts)
        artifacts["rows"][0]["values"]["quality.reward"] = float("nan")
        with self.assertRaisesRegex(EvoError, "non-finite"):
            validate_artifacts(artifacts)
        spec = copy.deepcopy(self.spec)
        spec["scoring"][0]["metrics"][-1]["unit"] = "second"
        with self.assertRaisesRegex(EvoError, "incompatible"):
            score_artifacts(spec, self.artifacts)

    def test_cli_scores_and_reports_existing_artifacts(self) -> None:
        original = ARTIFACT_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "scores.json"
            report_path = Path(directory) / "report.md"
            self.assertEqual(cli.main(["score", "--spec", str(SPEC_PATH), "--artifacts", str(ARTIFACT_PATH), "--output", str(result_path)]), 0)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["schema"], "agentbase-evo-scores/v1")
            self.assertEqual(cli.main(["report", "--results", str(result_path), "--output", str(report_path)]), 0)
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("quality-cost", report)
            self.assertIn("tokens_per_success", report)
        self.assertEqual(ARTIFACT_PATH.read_bytes(), original)

    def test_cli_refuses_to_overwrite_inputs(self) -> None:
        self.assertEqual(cli.main(["plan", "--spec", str(SPEC_PATH), "--output", str(SPEC_PATH)]), 2)
        self.assertEqual(cli.main(["score", "--spec", str(SPEC_PATH), "--artifacts", str(ARTIFACT_PATH), "--output", str(ARTIFACT_PATH)]), 2)


if __name__ == "__main__":
    unittest.main()
