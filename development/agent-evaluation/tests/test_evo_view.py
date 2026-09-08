from __future__ import annotations

import importlib.util
import copy
import json
import sys
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALUATION_ROOT.parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.spec import EvoError
from evo.view import RECOVERY, model_text_cost, project_model, render_model


def repository_model_text_cost():
    scripts = PROJECT_ROOT / "skills" / "codex-event-logger" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("verified_turn_log", scripts / "read_codex_turn_log.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.model_text_cost


class EvoModelViewTests(unittest.TestCase):
    def test_resources_keeps_storage_limits_and_uncertainty(self) -> None:
        value = {"schema": "agentbase-evo-resources/v1", "study": None,
                 "managed_storage": {"roots": ["C:/private-state"], "used_bytes": 512,
                                     "reserved_bytes": 128, "used_plus_reserved_bytes": 640,
                                     "max_bytes": 4096, "min_free_bytes": 1024, "complete": False,
                                     "error": "unreadable work root"},
                 "volumes": [{"volume": "C:", "free_bytes": 5000, "available": True}],
                 "capacity": {"active_jobs": 1, "job_limit": 2}, "reuse": {"jobs": 3, "selected_jobs": 4}}
        projected = project_model(value)
        self.assertEqual(projected["managed_storage"]["used_plus_reserved_bytes"], 640)
        self.assertFalse(projected["managed_storage"]["complete"])
        self.assertEqual(projected["capacity"]["active_jobs"], 1)
        self.assertEqual(projected["reuse"]["jobs"], 3)
        self.assertNotIn("C:/private-state", render_model(value))

    def test_actual_small_handler_shapes_preserve_success_meaning(self) -> None:
        cases = [
            ({"limits": {"concurrency": 2, "model_capacity": 4, "max_disk_mb": 100, "min_free_mb": 10}}, "init"),
            ({"study": "s7"}, "submit"),
            ({"valid": True, "schema": "agentbase-evo-research/v1", "id": "r", "version": "1"}, "validate"),
            ({"output": "C:/state/review.json", "schema": "agentbase-evo-review-package/v1", "id": "review-12345678"}, "save"),
            ({"schema": "agentbase-evo-artifacts/v1", "id": "a", "version": "f" * 64, "rows": 9,
              "output": "C:/state/calculated.json", "calculator": {"id": "calc", "version": "1", "code": {"path": "calc.py", "sha256": "e" * 64}}}, "calculate"),
        ]
        for machine, operation in cases:
            with self.subTest(operation=operation):
                before = copy.deepcopy(machine)
                view = json.loads(render_model(machine, 128))
                self.assertEqual(view["operation"], operation)
                self.assertEqual(view["recovery"], RECOVERY)
                self.assertEqual(machine, before)
        calculated = project_model(cases[-1][0])
        self.assertEqual(calculated["rows"], 9)
        self.assertEqual(calculated["calculator"], {"id": "calc", "version": "1", "code_source": "calc.py"})
        self.assertNotIn("f" * 64, json.dumps(calculated))

    def test_trace_keeps_page_coverage_gap_and_selected_action_summary(self) -> None:
        machine = {
            "schema": "agentbase-evo-trace/v1", "study": "s2", "source": "native", "snapshot": "a" * 64,
            "coverage": [{"job": "j1", "agent": "a1", "lines": 30, "complete_scan": True,
                          "issues": {"unsupported_record_types": ["new_event"], "truncated_lines": []}}],
            "summary": {"event_counts": {"tool": 2, "message": 1}},
            "events": [{"job": "j1", "agent": "a1", "role": "worker", "kind": "tool", "action": "exec",
                        "time": "2026-09-09T00:00:00Z", "excerpt": "exec srcq rg quality development/agent-evaluation",
                        "payload": {"arguments": "very-large-machine-payload", "source_job": "j0"}}],
            "page": {"offset": 0, "returned": 1, "total": 3, "next_offset": 1},
        }
        before = copy.deepcopy(machine)
        view = json.loads(render_model(machine, 500))
        self.assertEqual(view["page"]["next_offset"], 1)
        self.assertEqual(view["coverage"][0]["issue_counts"]["unsupported_record_types"], 1)
        self.assertTrue(view["coverage"][0]["complete_scan"])
        self.assertEqual(view["coverage"][0]["lines"], 30)
        self.assertEqual(view["events"][0]["agent"], "a1")
        self.assertEqual(view["events"][0]["kind"], "tool")
        self.assertEqual(view["events"][0]["action"], "exec")
        self.assertEqual(view["events"][0]["excerpt"], "exec srcq rg quality development/agent-evaluation")
        self.assertEqual(view["snapshot"], "snapshot-aaaaaaaa")
        self.assertNotIn("a" * 64, json.dumps(view))
        self.assertEqual(machine, before)

    def test_trace_keeps_bounded_mcp_call_arguments_and_result(self) -> None:
        machine = {
            "schema": "agentbase-evo-trace/v1", "study": "s8", "source": "native", "snapshot": "9" * 64,
            "coverage": [], "summary": {"event_counts": {"mcp_tool_call": 1}},
            "events": [{"job": "j2", "agent": "a1", "role": "root", "kind": "mcp_tool_call",
                        "server": "evo-fixture", "tool": "selected_component", "status": "completed",
                        "seconds": 0.0004479, "arguments": {}, "result_excerpt": "EVO_MCP_VALUE=23"}],
            "page": {"offset": 0, "returned": 1, "total": 1, "next_offset": None},
        }
        event = project_model(machine)["events"][0]
        self.assertEqual(event["server"], "evo-fixture")
        self.assertEqual(event["tool"], "selected_component")
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["seconds"], 0.0004479)
        self.assertEqual(event["arguments"], "{}")
        self.assertFalse(event["arguments_truncated"])
        self.assertEqual(event["result_excerpt"], "EVO_MCP_VALUE=23")
        self.assertFalse(event["result_excerpt_truncated"])
        machine["events"][0]["result_excerpt"] = "x" * 700
        long_event = project_model(machine)["events"][0]
        self.assertEqual(len(long_event["result_excerpt"]), 600)
        self.assertTrue(long_event["result_excerpt_truncated"])

    def test_grading_start_and_run_shapes_keep_studies_usage_and_facts(self) -> None:
        started = {"subject_study": "s1", "grader_study": "s2", "grading": "judge", "identity": "a" * 64}
        start_view = project_model(started)
        self.assertEqual(start_view["operation"], "grade-start")
        self.assertEqual(start_view["grader_study"], "s2")
        self.assertNotIn("a" * 64, json.dumps(start_view))
        status = {"schema": "agentbase-evo-status/v1", "study": "s2", "counts": {"completed": 1},
                  "total_jobs": 1, "tokens_observed": 30, "tokens_reserved": 0, "usage_unsettled": 0, "jobs": []}
        facts = {"schema": "agentbase-evo-model-grading-facts/v1", "subject_study": "s1", "grader_study": "s2",
                 "grading": {"id": "judge", "version": "1"}, "usage": 30, "usage_complete": True,
                 "rows": [{"id": "grader-s2-row1", "dimensions": {"item": "case"}, "values": {"judge.score": 0.8},
                           "source": {"location": "large-machine-path"}, "completeness": "complete"}]}
        machine = {"status": status, "facts": facts, "grader_usage": {"tokens": 30, "complete": True},
                   "research_usage": {"subject_tokens_at_freeze": 100, "grader_tokens": 30, "total_tokens": 130, "complete": True}}
        view = project_model(machine)
        self.assertEqual(view["operation"], "grade-run")
        self.assertEqual(view["facts"]["facts"][0]["values"]["judge.score"], 0.8)
        self.assertEqual(view["research_usage"]["total_tokens"], 130)

    def test_runtime_review_prepare_sync_and_evaluate_reviews_are_visible(self) -> None:
        prepared = {"study": "s3", "reviews": [{"job": "j1", "package_id": "b" * 64,
                                                   "alias": "review-bbbbbbbb", "path": "C:/state/reviews/j1.json"}]}
        view = project_model(prepared)
        self.assertEqual(view["operation"], "review-prepare")
        self.assertEqual(view["reviews"]["review_count"], 1)
        self.assertEqual(view["reviews"]["reviews"][0]["alias"], "review-bbbbbbbb")
        self.assertNotIn("b" * 64, json.dumps(view))
        synced = {"study": "s3", "reviews": [{"job": "j1", "alias": "review-bbbbbbbb", "path": "C:/state/reviews/j1.json",
                                                 "complete": True, "missing": [], "state_changed": True}]}
        sync_view = project_model(synced)
        self.assertEqual(sync_view["operation"], "review-sync")
        self.assertEqual(sync_view["reviews"]["state_changed_count"], 1)
        evaluation = {"schema": "agentbase-evo-evaluation/v1", "study": "s3",
                      "status": {"schema": "agentbase-evo-status/v1", "study": "s3", "counts": {"awaiting_human": 1},
                                 "total_jobs": 1, "tokens_observed": 0, "tokens_reserved": 0, "usage_unsettled": 0, "jobs": []},
                      "reviews": prepared["reviews"],
                      "scores": {"schema": "agentbase-evo-scores/v1", "research": {"id": "r", "version": "1"},
                                 "artifacts": {"id": "a", "version": "1"}, "source_row_count": 1, "scores": []}}
        evaluated = project_model(evaluation)
        self.assertEqual(evaluated["reviews"]["review_count"], 1)
        self.assertEqual(evaluated["status"]["counts"], {"awaiting_human": 1})

    def test_optimization_status_and_export_use_actionable_aliases(self) -> None:
        identity = "c" * 64
        candidate = "d" * 64
        status = {"schema": "agentbase-evo-optimization/v1", "id": identity, "alias": "opt-cccccccc", "state": "awaiting_human",
                  "round": 2, "baseline": candidate, "champion": "e" * 64, "controller_tokens": 40, "subject_tokens": 70,
                  "grader_tokens": 15,
                  "stop_reason": None, "awaiting": {"kind": "review", "study": "s4"}, "final_study": None}
        view = project_model(status)
        self.assertEqual(view["optimization"], "opt-cccccccc")
        self.assertEqual(view["state"], "awaiting_human")
        self.assertEqual(view["baseline"], "candidate-dddddddd")
        self.assertEqual(view["grader_tokens"], 15)
        self.assertNotIn(identity, json.dumps(view))
        exported = {"schema": "agentbase-evo-optimization-export/v1", "optimization": identity, "state": "completed",
                    "baseline": candidate, "champion": "e" * 64, "candidate_root": "C:/state/candidates/e",
                    "candidate_manifest": {"large": "x" * 2000}, "controller_tokens": 40, "subject_tokens": 70,
                    "grader_tokens": 15,
                    "final_study": "s5", "note": "Export is evidence only"}
        export_view = project_model(exported)
        self.assertEqual(export_view["operation"], "optimize-export")
        self.assertEqual(export_view["optimization"], "opt-cccccccc")
        self.assertEqual(export_view["candidate_root"], "C:/state/candidates/e")
        self.assertEqual(export_view["grader_tokens"], 15)
        self.assertNotIn("candidate_manifest", export_view)
        status.update(baseline="candidate-dddb08007a45", champion="candidate-d632d24fb0f0",
                      final_acceptance={"status": "observed"})
        actual = project_model(status)
        self.assertNotEqual(actual["baseline"], actual["champion"])
        self.assertEqual(actual["champion"], status["champion"])
        self.assertEqual(actual["final_acceptance"], {"status": "observed"})

    def test_status_keeps_decision_counts_reasons_and_recovery(self) -> None:
        machine = {
            "schema": "agentbase-evo-status/v1", "study": "s3", "counts": {"queued": 2, "failed": 1},
            "total_jobs": 3, "tokens_observed": 120, "tokens_reserved": 50, "usage_unsettled": 1,
            "jobs": [{"job": f"j{i}", "study": "s3", "item": "case", "combination": "combo", "state": "queued",
                      "reason": "model capacity" if i == 1 else None, "error": None, "receipt": "x" * 64,
                      "usage": 0, "usage_complete": True, "workspace_slot": i} for i in range(1, 4)],
            "truncated": True, "next_offset": 3,
        }
        rendered = render_model(machine, 500)
        view = json.loads(rendered)
        self.assertEqual(view["counts"], machine["counts"])
        self.assertEqual(view["usage_unsettled"], 1)
        self.assertEqual(view["jobs"][0]["reason"], "model capacity")
        self.assertTrue(view["omitted"]["source_was_truncated"])
        self.assertEqual(view["recovery"], RECOVERY)
        self.assertNotIn("receipt", view["jobs"][0])

    def test_scores_keep_all_gap_counts_while_bounding_score_lines(self) -> None:
        metrics = [
            {"id": f"m{i}", "value": None if i % 3 == 0 else i, "status": "unknown" if i % 3 == 0 else "computed",
             "unit": "score", "sample_count": 2, "incomplete_sample_count": 1 if i % 4 == 0 else 0,
             "source_rows": ["r" + str(i)], "expression": {"literal": i}}
            for i in range(60)
        ]
        machine = {"schema": "agentbase-evo-scores/v1", "research": {"id": "r", "version": "1"},
                   "artifacts": {"id": "a", "version": "a" * 64}, "source_row_count": 120,
                   "source_snapshot": {"spec_sha256": "b" * 64, "source_rows": {str(i): {"payload": "large" * 100} for i in range(100)}},
                   "scores": [{"id": "quality", "version": "1", "identity_sha256": "c" * 64,
                               "groups": [{"dimensions": {"combination": "c1"}, "metrics": metrics}]}]}
        rendered = render_model(machine, 500)
        view = json.loads(rendered)
        self.assertEqual(view["metric_count"], 60)
        self.assertEqual(view["unknown_metric_count"], 20)
        self.assertEqual(view["incomplete_source_count"], 15)
        self.assertGreater(view["omitted"]["score_lines"], 0)
        self.assertNotIn("a" * 64, rendered)
        self.assertLessEqual(model_text_cost(rendered), 500)

    def test_plan_uses_short_job_aliases_and_explicit_omission(self) -> None:
        jobs = [{"id": f"j{i}", "combination": "c", "item": f"i{i}", "replicate": 1,
                 "groups": ["g"], "observations": ["quality"], "execution_identity": "d" * 64} for i in range(80)]
        machine = {"schema": "agentbase-evo-plan/v1", "source": {"id": "study", "version": "1"},
                   "selection": {"combinations": ["c"], "groups": ["g"], "replicates": 1}, "job_count": 80, "jobs": jobs}
        view = json.loads(render_model(machine, 450))
        self.assertEqual(view["job_count"], 80)
        self.assertGreater(view["omitted"]["jobs"], 0)
        self.assertEqual(view["jobs"][0]["id"], "j0")
        self.assertNotIn("d" * 64, json.dumps(view))

    def test_calculator_artifacts_show_identity_source_and_completeness_without_hashes(self) -> None:
        machine = {"schema": "agentbase-evo-artifacts/v1", "id": "a", "version": "e" * 64,
                   "calculator": {"id": "calc", "version": "2", "manifest_sha256": "f" * 64,
                                  "code": {"path": "calculator.py", "sha256": "1" * 64}},
                   "rows": [{"id": "r1", "grain": "attempt", "values": {"quality.reward": 1}, "completeness": "complete"},
                            {"id": "r2", "grain": "attempt", "values": {"custom.score": None}, "completeness": "missing"}]}
        rendered = render_model(machine)
        view = json.loads(rendered)
        self.assertEqual(view["calculator"], {"id": "calc", "version": "2", "code_source": "calculator.py"})
        self.assertEqual(view["completeness"], {"complete": 1, "missing": 1})
        self.assertIn("custom.score", view["fields"])
        self.assertNotIn("f" * 64, rendered)

    def test_evaluate_projects_nested_status_and_scores_without_recomputing(self) -> None:
        machine = {"schema": "agentbase-evo-evaluation/v1", "study": "s1",
                   "status": {"schema": "agentbase-evo-status/v1", "study": "s1", "counts": {"completed": 1},
                              "total_jobs": 1, "tokens_observed": 0, "tokens_reserved": 0, "usage_unsettled": 0, "jobs": []},
                   "scores": {"schema": "agentbase-evo-scores/v1", "research": {"id": "r", "version": "1"},
                              "artifacts": {"id": "a", "version": "1"}, "source_row_count": 1, "scores": []}}
        view = project_model(machine)
        self.assertEqual(view["status"]["counts"], {"completed": 1})
        self.assertEqual(view["scores"]["metric_count"], 0)
        self.assertEqual(machine["scores"]["scores"], [])

    def test_review_uses_alias_and_keeps_missing_count(self) -> None:
        machine = {"schema": "agentbase-evo-review-package/v1", "package_id": "2" * 64, "alias": "review-12345678",
                   "blind": True, "blind_scope": "identities hidden", "items": [{"large": "x" * 1000}] * 10,
                   "assessments": [], "complete": False,
                   "missing": [{"review_key": f"item-{i}", "field": "human.score"} for i in range(20)]}
        view = json.loads(render_model(machine, 400))
        self.assertEqual(view["package"], "review-12345678")
        self.assertEqual(view["missing_count"], 20)
        self.assertGreater(view["omitted"]["missing"], 0)
        self.assertNotIn("2" * 64, json.dumps(view))
        imported = project_model({"package_id": "2" * 64, "imported": ["3" * 64, "4" * 64], "skipped_blank": 1,
                                  "alias": "review-12345678", "complete": False, "missing": [{"review_key": "i", "field": "f"}]})
        self.assertEqual(imported["imported_count"], 2)
        self.assertEqual(imported["skipped_blank"], 1)

    def test_projection_cost_matches_verified_contract_and_reduces_model_read(self) -> None:
        verified = repository_model_text_cost()
        machine = {"schema": "agentbase-evo-status/v1", "study": "s1", "counts": {"completed": 200},
                   "total_jobs": 200, "tokens_observed": 1000, "tokens_reserved": 0, "usage_unsettled": 0,
                   "jobs": [{"job": f"j{i}", "study": "s1", "item": "case", "combination": "combo", "state": "completed",
                             "reason": None, "error": None, "receipt": "a" * 64, "large": "trace" * 200} for i in range(200)]}
        machine_text = json.dumps(machine, ensure_ascii=False)
        rendered = render_model(machine, 600)
        self.assertEqual(model_text_cost(rendered), verified(rendered))
        self.assertLess(verified(rendered), verified(machine_text) // 5)
        self.assertLessEqual(verified(rendered), 600)

    def test_unknown_schema_and_too_small_limit_fail_explicitly(self) -> None:
        with self.assertRaisesRegex(EvoError, "no model projection"):
            render_model({"schema": "unknown/v1"})
        with self.assertRaisesRegex(EvoError, "from 128"):
            render_model({"schema": "agentbase-evo-status/v1"}, 10)


if __name__ == "__main__":
    unittest.main()
