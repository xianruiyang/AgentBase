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

    def test_independent_benchmark_requires_configured_network_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            config.write_text(json.dumps({"network_policy": "ambient"}), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ExperimentError, "network_policy=configured"):
                MODULE.build_experiment(config, Path(temp) / "output")

    def test_runtime_dotenv_projects_only_network_allowlist_and_redacts_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dotenv = Path(temp) / ".env"
            dotenv.write_text(
                "# host settings\nOPENAI_API_KEY=must-not-project\nALL_PROXY='socks5://127.0.0.1:1080'\n",
                encoding="utf-8",
            )
            descriptor, projection = MODULE.resolve_runtime_environment({
                "dotenv_path": str(dotenv),
                "required_keys": ["ALL_PROXY"],
            })
            self.assertEqual({"ALL_PROXY": "socks5://127.0.0.1:1080"}, projection)
            self.assertEqual(["ALL_PROXY"], descriptor["projected_keys"])
            serialized = json.dumps(descriptor)
            self.assertNotIn("socks5://127.0.0.1:1080", serialized)
            self.assertNotIn("must-not-project", serialized)
            self.assertEqual(projection, MODULE.materialize_runtime_environment(descriptor))

    def test_runtime_dotenv_change_invalidates_frozen_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dotenv = Path(temp) / ".env"
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1080\n", encoding="utf-8")
            descriptor, _ = MODULE.resolve_runtime_environment({
                "dotenv_path": str(dotenv),
                "required_keys": ["ALL_PROXY"],
            })
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1081\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ExperimentError, "projection changed"):
                MODULE.materialize_runtime_environment(descriptor)

    def test_runtime_dotenv_can_require_remote_dns_for_socks_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dotenv = Path(temp) / ".env"
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1080\n", encoding="utf-8")
            descriptor, projection = MODULE.resolve_runtime_environment({
                "dotenv_path": str(dotenv),
                "required_keys": ["ALL_PROXY"],
                "proxy_dns": "remote",
            })
            self.assertEqual("socks5h://127.0.0.1:1080", projection["ALL_PROXY"])
            self.assertEqual(
                {"proxy_dns": "remote", "all_proxy_fanout": "none"},
                descriptor["projection_options"],
            )
            self.assertEqual(projection, MODULE.materialize_runtime_environment(descriptor))

    def test_runtime_dotenv_can_fan_out_all_proxy_for_websocket_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dotenv = Path(temp) / ".env"
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1080\n", encoding="utf-8")
            _, projection = MODULE.resolve_runtime_environment({
                "dotenv_path": str(dotenv),
                "required_keys": ["ALL_PROXY"],
                "proxy_dns": "remote",
                "all_proxy_fanout": "http-and-https",
            })
            self.assertEqual("socks5h://127.0.0.1:1080", projection["ALL_PROXY"])
            self.assertEqual(projection["ALL_PROXY"], projection["HTTP_PROXY"])
            self.assertEqual(projection["ALL_PROXY"], projection["HTTPS_PROXY"])

    def test_codex_environment_replaces_unbound_parent_network_settings(self) -> None:
        with mock.patch.dict(os.environ, {
            "ALL_PROXY": "parent-proxy",
            "HTTPS_PROXY": "parent-https-proxy",
        }, clear=False):
            env = MODULE.codex_environment(
                {"codex_home": "D:/isolated", "path_prepend": "D:/isolated/bin"},
                {"ALL_PROXY": "frozen-proxy"},
            )
        self.assertEqual("frozen-proxy", env["ALL_PROXY"])
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual("D:/isolated", env["CODEX_HOME"])
        self.assertTrue(env["PATH"].startswith("D:/isolated/bin" + os.pathsep))

    def test_shared_runtime_scrubs_ambient_credentials_and_control_paths(self) -> None:
        env = MODULE.sanitized_process_environment(
            {"ALL_PROXY": "frozen-proxy", "CODEX_CA_CERTIFICATE": "D:/trusted-ca.pem"},
            base={
                "PATH": "D:/tools",
                "OPENAI_API_KEY": "secret",
                "AZURE_OPENAI_API_KEY": "secret",
                "CODEX_HOME": "D:/ambient-codex",
                "CODEX_CA_CERTIFICATE": "D:/ambient-ca.pem",
                "GITHUB_TOKEN": "secret",
                "NPM_TOKEN": "secret",
                "GIT_DIR": "D:/ambient-git",
                "GIT_ASKPASS": "D:/ambient-askpass.cmd",
                "SSH_AUTH_SOCK": "ambient-agent",
                "NODE_OPTIONS": "--require=D:/ambient.js",
                "PYTHONPATH": "D:/ambient-python",
                "CI": "true",
                "PWD": "D:/ambient-working-directory",
            },
        )
        self.assertEqual("D:/tools", env["PATH"])
        self.assertEqual("frozen-proxy", env["ALL_PROXY"])
        self.assertEqual("D:/trusted-ca.pem", env["CODEX_CA_CERTIFICATE"])
        for name in (
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "CODEX_HOME",
            "GITHUB_TOKEN",
            "NPM_TOKEN",
            "GIT_DIR",
            "GIT_ASKPASS",
            "SSH_AUTH_SOCK",
            "NODE_OPTIONS",
            "PYTHONPATH",
            "CI",
            "PWD",
        ):
            self.assertNotIn(name, env)
        descriptor, policy = MODULE.resolve_shell_environment_policy()
        self.assertEqual("agentbase.codex-shell-environment-policy/v1", descriptor["schema"])
        self.assertEqual("exclude", policy["filters"]["GIT_*"])
        self.assertEqual("exclude", policy["filters"]["SSH_*"])
        self.assertFalse(policy["ignore_default_excludes"])
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "config.toml").write_text(
                '[shell_environment_policy]\ninherit = "none"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.ExperimentError, "only owner"):
                MODULE.validate_shared_shell_policy_owner(home)

            (home / "config.toml").write_text(
                "[features]\nmulti_agent = false\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.benchmark_home_execution_contract(home),
                {"read_only_prompt": True, "multi_agent": False},
            )
            (home / "config.toml").write_text(
                "[features]\nmulti_agent = true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.ExperimentError, "multi_agent=false"):
                MODULE.benchmark_home_execution_contract(home)

    def test_experiment_identity_rejects_changed_runner_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "codex.exe"
            executable.write_bytes(b"codex")
            corpus = root / "corpus.json"
            corpus.write_text("{}", encoding="utf-8")
            experiment = {
                "schema": MODULE.EXPERIMENT_SCHEMA,
                "runner": {"source_sha256": "0" * 64, "python": sys.version},
                "codex": {
                    "executable": str(executable),
                    "executable_sha256": MODULE.sha256_file(executable),
                },
                "corpus": {"path": str(corpus), "sha256": MODULE.sha256_file(corpus)},
                "workspaces": {},
                "environments": {},
                "runtime_environment": {},
            }
            with mock.patch.object(MODULE, "materialize_runtime_environment", return_value={}):
                failures = MODULE.verify_experiment_identity(experiment)
            self.assertIn("runner source changed", failures)

    def test_network_transport_observation_rejects_retry_and_http_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            jsonl = Path(temp) / "stdout.jsonl"
            stderr = Path(temp) / "stderr.txt"
            stderr.write_text(
                "failed to connect to websocket\n"
                "stream disconnected - retrying sampling request\n"
                "falling back to HTTP\n",
                encoding="utf-8",
            )
            jsonl.write_text(
                json.dumps({"type": "item.completed", "item": {
                    "type": "agent_message", "text": "Reconnecting... is source text",
                }}) + "\n" + json.dumps({
                    "type": "error", "message": "Reconnecting... 1/5",
                }) + "\n",
                encoding="utf-8",
            )
            observation = MODULE.network_transport_observation(jsonl, stderr)
            self.assertFalse(observation["clean"])
            self.assertEqual(1, observation["websocket_connect_failures"])
            self.assertEqual(2, observation["sampling_retries"])
            self.assertEqual(1, observation["http_fallbacks"])

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
            capsule["schema"] = "agentbase.source-query-audit-capsule/v2"
            capsule["capsule_sha256"] = MODULE.capsule_sha256(capsule)
            capsule_path.write_text(json.dumps(capsule), encoding="utf-8")
            self.assertEqual(1, MODULE.verify_capsule(capsule_path)["verified_raw_files"])
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
            (root / ".env").write_text("ALL_PROXY=secret", encoding="utf-8")
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
                        "workspace_role": "unselected-workspace",
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
            with self.assertRaisesRegex(MODULE.ExperimentError, "corpus role has no workspace"):
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
        MODULE.validate_benchmark_codex({
            "service_tier": "default", "sandbox": "danger-full-access", "transport": "http-only",
        })
        with self.assertRaisesRegex(MODULE.ExperimentError, "service_tier=default"):
            MODULE.validate_benchmark_codex({
                "service_tier": "fast", "sandbox": "danger-full-access", "transport": "http-only",
            })
        with self.assertRaisesRegex(MODULE.ExperimentError, "sandbox=danger-full-access"):
            MODULE.validate_benchmark_codex({
                "service_tier": "default", "sandbox": "read-only", "transport": "http-only",
            })
        with self.assertRaisesRegex(MODULE.ExperimentError, "explicit websocket or http-only"):
            MODULE.validate_benchmark_codex({
                "service_tier": "default", "sandbox": "danger-full-access", "transport": "auto",
            })
        with self.assertRaisesRegex(MODULE.ExperimentError, "execution identity"):
            MODULE.validate_benchmark_codex({
                "service_tier": "default",
                "sandbox": "danger-full-access",
                "transport": "http-only",
                "extra_config": ['service_tier="fast"'],
            })
        with self.assertRaisesRegex(MODULE.ExperimentError, "execution identity"):
            MODULE.validate_benchmark_codex({
                "service_tier": "default",
                "sandbox": "danger-full-access",
                "transport": "http-only",
                "extra_config": ['shell_environment_policy.inherit="none"'],
            })

    def test_codex_exec_uses_frozen_http_only_chatgpt_provider(self) -> None:
        shell_policy_descriptor, _ = MODULE.resolve_shell_environment_policy()
        argv = MODULE.codex_exec_argv(
            {
                "executable": "codex.exe",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "medium",
                "service_tier": "default",
                "sandbox": "danger-full-access",
                "transport": "http-only",
                "shell_environment_policy": shell_policy_descriptor,
            },
            Path("D:/workspace"),
            "prompt",
        )
        joined = " ".join(argv)
        self.assertIn('model_provider="agentbase_eval_http"', joined)
        self.assertIn('base_url="https://chatgpt.com/backend-api/codex"', joined)
        self.assertIn("supports_websockets=false", joined)
        self.assertIn('shell_environment_policy.filters."ALL_PROXY"="exclude"', joined)
        self.assertIn('shell_environment_policy.filters."GIT_*"="exclude"', joined)

    def test_preflight_requires_successful_representative_command(self) -> None:
        requirements = [
            {"command": "srcq.exe --version", "expected_output": "srcq "},
            {"command": "srcq query scc doctor", "expected_output": "ok", "output_match": "exact-line"},
        ]
        record = {
            "environment": "candidate",
            "exit_code": 0,
            "timed_out": False,
            "usage_complete": True,
            "network_transport": {
                "clean": True,
                "websocket_connect_failures": 0,
                "sampling_retries": 0,
                "http_fallbacks": 0,
            },
            "final_answer": "srcq 0.3.0",
            "tool_items": [
                {
                    "type": "command_execution",
                    "command": "srcq.exe --version",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "srcq 0.3.0\n",
                },
                {
                    "type": "command_execution",
                    "command": "srcq query scc doctor",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "ok\n",
                },
            ],
        }
        MODULE.validate_preflight_record(record, requirements)
        record["network_transport"]["sampling_retries"] = 1
        record["network_transport"]["clean"] = False
        with self.assertRaisesRegex(MODULE.ExperimentError, "network transport degraded"):
            MODULE.validate_preflight_record(record, requirements)
        record["network_transport"]["sampling_retries"] = 0
        record["network_transport"]["clean"] = True
        record["tool_items"][1]["aggregated_output"] = "backend is not ok\n"
        with self.assertRaisesRegex(MODULE.ExperimentError, "srcq query scc doctor"):
            MODULE.validate_preflight_record(record, requirements)
        record["tool_items"][1]["aggregated_output"] = "ok\n"
        record["tool_items"] = record["tool_items"][:1]
        with self.assertRaisesRegex(MODULE.ExperimentError, "srcq query scc doctor"):
            MODULE.validate_preflight_record(record, requirements)

    def test_codex_identity_is_bound_to_executable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "codex.exe"
            executable.write_bytes(b"codex")
            raw = {
                "executable": str(executable),
                "service_tier": "default",
                "sandbox": "danger-full-access",
                "transport": "http-only",
            }
            with mock.patch.object(MODULE, "run_capture", return_value=b"codex-cli 1.2.3\n"):
                identity = MODULE.resolve_codex_identity(raw)
                self.assertEqual(MODULE.sha256_file(executable), identity["executable_sha256"])
                shell_policy_descriptor, _ = MODULE.resolve_shell_environment_policy()
                self.assertEqual(
                    shell_policy_descriptor,
                    identity["shell_environment_policy"],
                )
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
                (home / "config.toml").write_text(
                    "[features]\nmulti_agent = false\n",
                    encoding="utf-8",
                )
                environments[name] = {"codex_home": str(home)}
            executable = root / "codex.exe"
            executable.write_bytes(b"codex")
            dotenv = root / ".env"
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1080\n", encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps({
                "corpus": str(corpus),
                "workspaces": {"workspace": {"path": str(workspace), "identity_paths": ["Source"]}},
                "environments": environments,
                "allowed_differences": [],
                "codex": {
                    "executable": str(executable), "model": "gpt-5.6-sol", "reasoning_effort": "medium",
                    "service_tier": "default", "sandbox": "danger-full-access",
                    "transport": "http-only",
                },
                "repetitions": 1,
                "seed": 1,
                "run_environments": ["candidate"],
                "timeout_seconds": 10,
                "network_policy": "configured",
                "runtime_environment": {
                    "dotenv_path": str(dotenv),
                    "required_keys": ["ALL_PROXY"],
                },
            }), encoding="utf-8")
            codex_identity = {
                "executable": str(executable.resolve()), "executable_sha256": MODULE.sha256_file(executable),
                "executable_size_bytes": executable.stat().st_size, "observed_version": "codex-cli test",
                "model": "gpt-5.6-sol", "reasoning_effort": "medium", "service_tier": "default",
                "sandbox": "danger-full-access", "transport": "http-only",
                "shell_environment_policy": MODULE.resolve_shell_environment_policy()[0],
            }
            preflight = {"records": [], "usage_report": {"all": {"run_count": 0}}}
            def mutate_workspace(*_args, **_kwargs):
                source.write_text("mutated", encoding="utf-8")
                return preflight

            with mock.patch.object(MODULE, "resolve_codex_identity", return_value=codex_identity), mock.patch.object(
                MODULE, "run_preflights", side_effect=mutate_workspace
            ):
                with self.assertRaisesRegex(MODULE.ExperimentError, "preflight modified workspace"):
                    MODULE.build_experiment(config, root / "invalid-output")
            source.write_text("target", encoding="utf-8")

            def mutate_dotenv(*_args, **_kwargs):
                dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1081\n", encoding="utf-8")
                return preflight

            with mock.patch.object(MODULE, "resolve_codex_identity", return_value=codex_identity), mock.patch.object(
                MODULE, "run_preflights", side_effect=mutate_dotenv
            ):
                with self.assertRaisesRegex(MODULE.ExperimentError, "runtime environment projection changed"):
                    MODULE.build_experiment(config, root / "invalid-runtime-output")
            dotenv.write_text("ALL_PROXY=socks5://127.0.0.1:1080\n", encoding="utf-8")
            with mock.patch.object(MODULE, "resolve_codex_identity", return_value=codex_identity), mock.patch.object(
                MODULE, "run_preflights", return_value=preflight
            ) as run_preflights:
                document = MODULE.build_experiment(config, root / "output")
            self.assertEqual(["Source"], document["workspaces"]["workspace"]["identity_paths"])
            self.assertEqual(preflight, document["preflight"])
            self.assertEqual(["ALL_PROXY"], document["runtime_environment"]["projected_keys"])
            self.assertNotIn("socks5://127.0.0.1:1080", json.dumps(document))
            self.assertEqual(1, len(document["schedule"]))
            self.assertEqual(["candidate"], run_preflights.call_args.args[2])
            self.assertEqual(workspace, run_preflights.call_args.args[3])

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
