from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_workspace_identity_paths_are_relative_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.assertEqual(["."], MODULE.normalize_identity_paths(root, None))
            self.assertEqual(["Source", "AGENTS.md"], MODULE.normalize_identity_paths(root, ["Source", "AGENTS.md", "Source"]))
            with self.assertRaisesRegex(MODULE.ExperimentError, "must be relative"):
                MODULE.normalize_identity_paths(root, [str(root / "Source")])
            with self.assertRaisesRegex(MODULE.ExperimentError, "escapes root"):
                MODULE.normalize_identity_paths(root, ["../outside"])

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

    def test_verify_capsule_recomputes_identity_and_external_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runs").mkdir()
            (root / "runs" / "one.jsonl").write_bytes(b"event\n")
            (root / "environment-diff.json").write_text("{}\n", encoding="utf-8")
            (root / "environment-trees.json").write_text("{}\n", encoding="utf-8")
            experiment = {
                "environment_diff_sha256": MODULE.sha256_file(root / "environment-diff.json"),
                "environment_trees_sha256": MODULE.sha256_file(root / "environment-trees.json"),
                "value": 1,
            }
            experiment["experiment_identity"] = MODULE.experiment_identity_sha256(experiment)
            capsule = {
                "schema": MODULE.CAPSULE_SCHEMA,
                "isolation": "detached-capsule",
                "input_declaration": "test",
                "capsule_hash_scheme": MODULE.CAPSULE_HASH_SCHEME,
                "experiment_identity_scheme": MODULE.EXPERIMENT_IDENTITY_SCHEME,
                "canonicalization": MODULE.CANONICALIZATION,
                "experiment": experiment,
                "corpus": {},
                "environment_diff": {},
                "summary": {"experiment_identity": experiment["experiment_identity"]},
                "raw_file_sha256": {"runs/one.jsonl": MODULE.sha256_file(root / "runs" / "one.jsonl")},
            }
            capsule["capsule_sha256"] = MODULE.capsule_sha256(capsule)
            capsule_path = root / "audit-capsule.json"
            capsule_path.write_text(json.dumps(capsule), encoding="utf-8")
            verified = MODULE.verify_capsule(capsule_path)
            self.assertEqual(1, verified["verified_raw_files"])
            (root / "runs" / "one.jsonl").write_bytes(b"changed\n")
            with self.assertRaisesRegex(MODULE.ExperimentError, "raw file sha256 mismatch"):
                MODULE.verify_capsule(capsule_path)

    def test_environment_diff_rejects_unlisted_change(self) -> None:
        result = MODULE.environment_diff({"same": "1", "extra": "a"}, {"same": "1", "extra": "b"}, ["skills/**"])
        self.assertFalse(result["ok"])
        self.assertEqual(["extra"], result["unexpected"])

    def test_environment_tree_excludes_codex_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "AGENTS.md").write_text("rules", encoding="utf-8")
            (root / ".sandbox_migration").write_text("v2", encoding="utf-8")
            (root / "state_5.sqlite").write_bytes(b"state")
            self.assertEqual({"AGENTS.md": MODULE.sha256_file(root / "AGENTS.md")}, MODULE.environment_tree(root))

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

    def test_corpus_snapshot_hashes_only_selected_case_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "selected.txt").write_text("current", encoding="utf-8")
            (root / "excluded.txt").write_text("changed", encoding="utf-8")
            corpus = {
                "schema": MODULE.CORPUS_SCHEMA,
                "cases": [
                    {
                        "id": "selected",
                        "workspace_role": "agentbase",
                        "answer_max_lines": 1,
                        "answer_contract": {"required": ["path"], "supporting": []},
                        "oracle": {
                            "kind": "source-relation",
                            "source": {
                                "path": "selected.txt",
                                "sha256": MODULE.sha256_file(root / "selected.txt"),
                            },
                        },
                    },
                    {
                        "id": "excluded",
                        "workspace_role": "agentbase",
                        "answer_max_lines": 1,
                        "answer_contract": {"required": ["path"], "supporting": []},
                        "oracle": {
                            "kind": "source-relation",
                            "source": {"path": "excluded.txt", "sha256": "0" * 64},
                        },
                    },
                ],
            }
            workspaces = {"agentbase": {"path": str(root)}}
            MODULE.validate_corpus_snapshot(corpus, workspaces, {"selected"})
            with self.assertRaisesRegex(MODULE.ExperimentError, "corpus source is stale"):
                MODULE.validate_corpus_snapshot(corpus, workspaces, {"excluded"})

    def test_corpus_source_must_be_inside_declared_identity_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "target.cpp"
            source.parent.mkdir()
            source.write_text("target", encoding="utf-8")
            corpus = {
                "schema": MODULE.CORPUS_SCHEMA,
                "cases": [{
                    "id": "case",
                    "workspace_role": "workspace",
                    "answer_max_lines": 1,
                    "answer_contract": {"required": ["path"], "supporting": []},
                    "oracle": {"kind": "source-relation", "source": {
                        "path": "Source/target.cpp",
                        "sha256": MODULE.sha256_file(source),
                    }},
                }],
            }
            MODULE.validate_corpus_snapshot(corpus, {
                "workspace": {"path": str(root), "identity_paths": ["Source"]},
            })
            with self.assertRaisesRegex(MODULE.ExperimentError, "outside workspace identity scope"):
                MODULE.validate_corpus_snapshot(corpus, {
                    "workspace": {"path": str(root), "identity_paths": ["Other"]},
                })

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
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':4,'cache_write_input_tokens':2,'output_tokens':3,'reasoning_output_tokens':1}}))\n",
                encoding="utf-8",
            )
            output = root / "ok.jsonl"
            error = root / "ok.stderr"
            result = MODULE.monitor_command([sys.executable, str(script), "ok"], root, os.environ.copy(), output, error, 2)
            parsed = MODULE.parse_events(output)
            self.assertEqual(0, result["exit_code"])
            self.assertTrue(parsed["usage_complete"])
            self.assertEqual(4, parsed["usage_breakdown"]["ordinary_input_tokens"])
            self.assertEqual(2, parsed["usage_breakdown"]["visible_output_tokens"])
            self.assertEqual(13, parsed["usage_breakdown"]["actual_total_tokens"])
            self.assertEqual("answer", parsed["final_answer"])
            slow_output = root / "slow.jsonl"
            slow_error = root / "slow.stderr"
            slow = MODULE.monitor_command([sys.executable, str(script), "slow"], root, os.environ.copy(), slow_output, slow_error, 1)
            self.assertTrue(slow["timed_out"])

    def test_event_parser_records_progressive_tool_item_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            events = [
                {"type": "item.completed", "item": {"type": "command_execution", "command": "rg"}},
                {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "symbol_info"}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
                {"type": "turn.completed", "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "cache_write_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                }},
            ]
            path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            parsed = MODULE.parse_events(path)
            self.assertEqual(2, len(parsed["tool_items"]))
            self.assertEqual({"command_execution": 1, "mcp_tool_call": 1, "agent_message": 1}, parsed["completed_item_type_counts"])

    def test_usage_breakdown_does_not_double_count_reasoning(self) -> None:
        breakdown = MODULE.normalize_usage({
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        })
        self.assertTrue(breakdown["complete"])
        self.assertTrue(breakdown["pricing_exact"])
        self.assertEqual(4, breakdown["ordinary_input_tokens"])
        self.assertEqual(2, breakdown["visible_output_tokens"])
        self.assertEqual(13, breakdown["actual_total_tokens"])
        estimate = MODULE.price_equivalent(breakdown, MODULE.TOKEN_PRICING)
        self.assertAlmostEqual(24.9, estimate["short_context"]["exact"])
        self.assertAlmostEqual(40.8, estimate["long_context"]["exact"])

    def test_missing_cache_write_is_bounded_not_assumed_zero(self) -> None:
        breakdown = MODULE.normalize_usage({
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        })
        self.assertTrue(breakdown["complete"])
        self.assertFalse(breakdown["pricing_exact"])
        self.assertIsNone(breakdown["ordinary_input_tokens"])
        estimate = MODULE.price_equivalent(breakdown, MODULE.TOKEN_PRICING)
        self.assertEqual("bounded", estimate["cache_write_classification"])
        self.assertAlmostEqual(24.4, estimate["short_context"]["lower"])
        self.assertAlmostEqual(25.9, estimate["short_context"]["upper"])
        self.assertIsNone(estimate["short_context"]["exact"])

    def test_pricing_contract_is_bound_to_the_experiment_model(self) -> None:
        supported = MODULE.token_pricing_contract({"model": "gpt-5.6-sol", "service_tier": "default"})
        self.assertTrue(supported["applicable"])
        self.assertEqual("default", supported["requested_service_tier"])
        unsupported = MODULE.token_pricing_contract({"model": "other-model", "service_tier": "default"})
        self.assertFalse(unsupported["applicable"])
        breakdown = MODULE.normalize_usage({
            "input_tokens": 1,
            "cached_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 0,
        })
        self.assertEqual(
            "pricing_not_applicable_to_experiment_model",
            MODULE.price_equivalent(breakdown, unsupported)["reason"],
        )

    def test_independent_benchmark_rejects_fast_service_tier(self) -> None:
        MODULE.validate_benchmark_codex({"service_tier": "default", "sandbox": "danger-full-access"})
        with self.assertRaisesRegex(MODULE.ExperimentError, "service_tier=default"):
            MODULE.validate_benchmark_codex({"service_tier": "fast", "sandbox": "danger-full-access"})
        with self.assertRaisesRegex(MODULE.ExperimentError, "sandbox=danger-full-access"):
            MODULE.validate_benchmark_codex({"service_tier": "default", "sandbox": "read-only"})
        with self.assertRaisesRegex(MODULE.ExperimentError, "execution identity"):
            MODULE.validate_benchmark_codex({
                "service_tier": "default",
                "sandbox": "danger-full-access",
                "extra_config": ['service_tier="fast"'],
            })

    def test_preflight_requires_successful_representative_command(self) -> None:
        record = {
            "environment": "candidate",
            "exit_code": 0,
            "timed_out": False,
            "usage_complete": True,
            "final_answer": "srcq 0.3.0",
            "tool_items": [{
                "type": "command_execution",
                "command": "srcq.exe --version",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": "srcq 0.3.0\n",
            }],
        }
        MODULE.validate_preflight_record(record, "srcq.exe --version", "srcq ")
        record["tool_items"] = []
        with self.assertRaisesRegex(MODULE.ExperimentError, "required command"):
            MODULE.validate_preflight_record(record, "srcq.exe --version", "srcq ")

    def test_codex_identity_is_bound_to_executable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "codex.exe"
            executable.write_bytes(b"codex")
            raw = {
                "executable": str(executable),
                "service_tier": "default",
                "sandbox": "danger-full-access",
            }
            with mock.patch.object(MODULE, "run_capture", return_value=b"codex-cli 1.2.3\n"):
                identity = MODULE.resolve_codex_identity(raw)
                self.assertEqual(MODULE.sha256_file(executable), identity["executable_sha256"])
                with self.assertRaisesRegex(MODULE.ExperimentError, "sha256"):
                    MODULE.resolve_codex_identity({**raw, "executable_sha256": "0" * 64})

    def test_prepare_freezes_initialized_homes_and_declared_workspace_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            source = workspace / "Source" / "target.txt"
            source.parent.mkdir(parents=True)
            source.write_text("target", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "."], cwd=workspace, check=True)
            subprocess.run([
                "git", "-c", "user.name=AgentBase Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "fixture",
            ], cwd=workspace, check=True)
            corpus = root / "corpus.json"
            corpus.write_text(json.dumps({
                "schema": MODULE.CORPUS_SCHEMA,
                "version": "test",
                "cases": [{
                    "id": "case",
                    "workspace_role": "workspace",
                    "prompt": "find target",
                    "answer_max_lines": 1,
                    "answer_contract": {"required": ["path"], "supporting": []},
                    "oracle": {"kind": "source-relation", "source": {
                        "path": "Source/target.txt", "sha256": MODULE.sha256_file(source),
                    }},
                }],
            }), encoding="utf-8")
            environments = {}
            for name in ("control", "candidate"):
                home = root / name
                home.mkdir()
                (home / "AGENTS.md").write_text("rules", encoding="utf-8")
                environments[name] = {"codex_home": str(home)}
            executable = root / "codex.exe"
            executable.write_bytes(b"codex")
            config = root / "config.json"
            config.write_text(json.dumps({
                "corpus": str(corpus),
                "workspaces": {"workspace": {"path": str(workspace), "identity_paths": ["Source"]}},
                "environments": environments,
                "allowed_differences": [],
                "codex": {
                    "executable": str(executable), "model": "gpt-5.6-sol", "reasoning_effort": "medium",
                    "service_tier": "default", "sandbox": "danger-full-access",
                },
                "repetitions": 1,
                "seed": 1,
                "run_environments": ["candidate"],
                "timeout_seconds": 10,
                "network_policy": "configured",
            }), encoding="utf-8")
            codex_identity = {
                "executable": str(executable.resolve()), "executable_sha256": MODULE.sha256_file(executable),
                "executable_size_bytes": executable.stat().st_size, "observed_version": "codex-cli test",
                "model": "gpt-5.6-sol", "reasoning_effort": "medium", "service_tier": "default",
                "sandbox": "danger-full-access",
            }
            preflight = {"records": [], "usage_report": {"all": {"run_count": 0}}}
            with mock.patch.object(MODULE, "resolve_codex_identity", return_value=codex_identity), mock.patch.object(
                MODULE, "run_preflights", return_value=preflight
            ):
                document = MODULE.build_experiment(config, root / "output")
            self.assertEqual(["Source"], document["workspaces"]["workspace"]["identity_paths"])
            self.assertEqual(preflight, document["preflight"])
            self.assertEqual(1, len(document["schedule"]))

    def test_usage_rejects_conflicting_aliases_and_invalid_subsets(self) -> None:
        conflicting = MODULE.normalize_usage({
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "cache_write_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        })
        self.assertFalse(conflicting["complete"])
        self.assertIn("conflicting cache write token fields", conflicting["diagnostics"])
        invalid = MODULE.normalize_usage({
            "input_tokens": 3,
            "cached_input_tokens": 4,
            "output_tokens": 1,
            "reasoning_output_tokens": 2,
        })
        self.assertFalse(invalid["complete"])
        self.assertIn("cached_input_tokens exceeds input_tokens", invalid["diagnostics"])
        self.assertIn("reasoning_output_tokens exceeds output_tokens", invalid["diagnostics"])

    def test_usage_report_preserves_coverage_and_environment_totals(self) -> None:
        complete = MODULE.normalize_usage({
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        })
        bounded = MODULE.normalize_usage({
            "input_tokens": 8,
            "cached_input_tokens": 2,
            "output_tokens": 2,
            "reasoning_output_tokens": 0,
        })
        incomplete = MODULE.normalize_usage({})
        records = [
            {"run_id": "control-1", "environment": "control", "usage_breakdown": complete,
             "price_equivalent": MODULE.price_equivalent(complete, MODULE.TOKEN_PRICING)},
            {"run_id": "candidate-1", "environment": "candidate", "usage_breakdown": bounded,
             "price_equivalent": MODULE.price_equivalent(bounded, MODULE.TOKEN_PRICING)},
            {"run_id": "candidate-2", "environment": "candidate", "usage_breakdown": incomplete,
             "price_equivalent": MODULE.price_equivalent(incomplete, MODULE.TOKEN_PRICING)},
        ]
        report = MODULE.aggregate_usage(records, MODULE.TOKEN_PRICING)
        self.assertEqual(3, report["all"]["run_count"])
        self.assertEqual(2, report["all"]["usage_complete_runs"])
        self.assertFalse(report["all"]["usage_complete_for_all_runs"])
        self.assertIsNone(report["all"]["price_equivalent"])
        self.assertEqual(["candidate-2"], report["all"]["incomplete_run_ids"])
        self.assertEqual(13, report["by_environment"]["control"]["totals"]["actual_total_tokens"])
        self.assertEqual(["candidate-1"], report["by_environment"]["candidate"]["cache_write_unreported_run_ids"])


if __name__ == "__main__":
    unittest.main()
