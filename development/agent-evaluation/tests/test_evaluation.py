from __future__ import annotations

import copy
import ctypes
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALUATION_ROOT.parents[1]
COMMON_ROOT = PROJECT_ROOT / "development" / "common"
for path in (EVALUATION_ROOT, COMMON_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import agent_eval
import agentbase_codex
import codex_runtime
import evaluation_core
import windows_verifier


CORPUS_PATH = EVALUATION_ROOT / "tests" / "fixtures" / "synthetic-corpus.json"


def empty_api_cost_summary() -> dict[str, object]:
    return {
        "basis": "official-openai-standard-api-text-token-pricing",
        "currency": "USD",
        "actual_billing_observed": False,
        "total_usd_nanos": 0,
        "root_usd_nanos": 0,
        "subagent_usd_nanos": 0,
        "total_usd": "0.000000000",
        "root_usd": "0.000000000",
        "subagent_usd": "0.000000000",
    }


def make_api_cost(
    *,
    total_usd_nanos: int,
    root_usd_nanos: int,
    subagent_usd_nanos: int,
    request_count: int,
    subagent_request_count: int,
) -> dict[str, object]:
    pricing = agentbase_codex.api_pricing_snapshot()
    return {
        "schema": agentbase_codex.API_EQUIVALENT_COST_SCHEMA,
        "basis": pricing["basis"],
        "currency": "USD",
        "actual_billing_observed": False,
        "scope": "root-and-descendant-model-requests",
        "pricing_snapshot_sha256": pricing["identity_sha256"],
        "pricing_observed_at": pricing["observed_at"],
        "complete": True,
        "request_count": request_count,
        "subagent_request_count": subagent_request_count,
        "long_context_request_count": 0,
        "total_usd_nanos": total_usd_nanos,
        "root_usd_nanos": root_usd_nanos,
        "subagent_usd_nanos": subagent_usd_nanos,
        "total_usd": agentbase_codex.format_usd_nanos(total_usd_nanos),
        "root_usd": agentbase_codex.format_usd_nanos(root_usd_nanos),
        "subagent_usd": agentbase_codex.format_usd_nanos(subagent_usd_nanos),
    }


def write_usage_rollout(
    path: Path,
    *,
    thread_id: str,
    usage: dict[str, int] | None,
    parent_thread_id: str | None = None,
    role: str | None = None,
    terminal: bool = True,
    model: str = "gpt-5.6-sol",
    usage_events: list[dict[str, int]] | None = None,
    subagent_history_start_ordinal: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-24T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "session_id": thread_id,
                "id": thread_id,
                "parent_thread_id": parent_thread_id,
                "agent_role": role,
                "subagent_history_start_ordinal": subagent_history_start_ordinal,
            },
        },
        {
            "timestamp": "2026-08-24T00:00:01Z",
            "type": "turn_context",
            "payload": {"model": model},
        },
        {
            "timestamp": "2026-08-24T00:00:02Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
    ]
    cumulative = {field: 0 for field in agentbase_codex.CODEX_USAGE_FIELDS}
    responses = usage_events if usage_events is not None else ([usage] if usage is not None else [])
    for index, response_usage in enumerate(responses, start=1):
        for field in agentbase_codex.CODEX_USAGE_FIELDS:
            cumulative[field] += response_usage[field]
        lines.append(
            {
                "timestamp": f"2026-08-24T00:00:{index + 2:02d}Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": dict(cumulative),
                        "last_token_usage": response_usage,
                    },
                    "rate_limits": None,
                },
            }
        )
    if terminal:
        lines.append(
            {
                "timestamp": "2026-08-24T00:00:59Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            }
        )
    path.write_text(
        "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8",
    )


def fake_candidate_runtime_tools(
    _project_root: Path,
    runtime_root: Path,
    _explicit_codex_path: Path | None = None,
) -> dict[str, object]:
    executable = runtime_root.resolve() / "fake-runtime-tool.exe"
    executable.write_bytes(b"agentbase deterministic fake runtime tool\n")
    identity = {
        "path": str(executable),
        "sha256": evaluation_core.sha256_file(executable),
        "version": "fake 1.0",
    }
    tools = {
        name: dict(identity)
        for name in [*agentbase_codex.REQUIRED_CANDIDATE_TOOLS, "codex"]
    }
    payload = {"tools": tools}
    return {
        **payload,
        "identity_sha256": evaluation_core.sha256_bytes(
            evaluation_core.canonical_bytes(payload)
        ),
    }


class CorpusContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = evaluation_core.load_corpus(CORPUS_PATH)

    def test_synthetic_fixture_is_generic_and_valid(self) -> None:
        self.assertEqual([task["id"] for task in self.corpus["tasks"]], ["synthetic-python-case"])
        self.assertEqual(set(self.corpus["profiles"]), {"test"})
        self.assertFalse(self.corpus["assessment"]["leaderboard_comparable"])

    def test_codex_contract_uses_trusted_local_execution(self) -> None:
        self.assertEqual(
            self.corpus["codex"],
            {
                "auth_mode": "existing-codex-auth-json",
                "transport_overlay": "codex-eval-overlay.toml",
            },
        )

    def test_source_configuration_preserves_repository_boundaries(self) -> None:
        for task_root in ("../outside", "nested/../../outside", "C:/outside", "C:outside", "/outside", "\\outside", "\\\\server\\share", "nested\\..\\outside"):
            with self.subTest(task_root=task_root):
                drifted = copy.deepcopy(self.corpus)
                drifted["source"]["task_root"] = task_root
                with self.assertRaisesRegex(evaluation_core.EvaluationError, "source.task_root"):
                    evaluation_core.validate_corpus(drifted)
        for repository in ("--upload-pack=unexpected", "file:///local/source", "http://example.invalid/source"):
            with self.subTest(repository=repository):
                drifted = copy.deepcopy(self.corpus)
                drifted["source"]["repository"] = repository
                with self.assertRaisesRegex(evaluation_core.EvaluationError, "source.repository"):
                    evaluation_core.validate_corpus(drifted)
        drifted = copy.deepcopy(self.corpus)
        drifted["source"]["task_root"] = "private/tasks"
        evaluation_core.validate_corpus(drifted)

    def test_suites_cover_without_rotation_overlap(self) -> None:
        suites = self.corpus["suites"]
        self.assertTrue(set(suites["smoke"]).issubset(suites["core"]))
        self.assertFalse(set(suites["core"]) & set(suites["rotation"]))
        self.assertEqual(set(suites["all"]), set(suites["core"]) | set(suites["rotation"]))

    def test_rollout_evidence_is_task_local_and_bounded(self) -> None:
        for task in self.corpus["tasks"]:
            evidence = task["difficulty_evidence"]
            self.assertLessEqual(evidence["successful_rollouts"], evidence["total_rollouts"])
            self.assertTrue(evidence["source"])

    def test_no_retired_or_non_windows_runtime_contract(self) -> None:
        text = json.dumps(self.corpus, ensure_ascii=False).lower()
        for forbidden in ("pier", "docker", "/bin/bash", "bash -c", '"linux"'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(self.corpus["adapter"]["platform"], "windows")

    def test_each_task_pins_six_assets_and_argv_commands(self) -> None:
        for task in self.corpus["tasks"]:
            self.assertEqual(set(task["assets"]), set(evaluation_core.REQUIRED_ASSETS))
            self.assertEqual(
                task["assets"]["tests/grader.py"],
                self.corpus["adapter"]["upstream_grader_sha256"],
            )
            for command in [*task["setup"], *task["checks"]]:
                self.assertIsInstance(command["argv"], list)
                self.assertNotIn("&&", " ".join(command["argv"]))

    def test_fixture_requires_no_private_windows_adapter(self) -> None:
        self.assertEqual(evaluation_core.verify_windows_adapter_assets(PROJECT_ROOT, self.corpus), {})

    def test_validator_rejects_profile_and_shell_drift(self) -> None:
        drifted = copy.deepcopy(self.corpus)
        drifted["profiles"]["test"]["reasoning_effort"] = "invalid"
        with self.assertRaises(evaluation_core.EvaluationError):
            evaluation_core.validate_corpus(drifted)

    def test_validator_rejects_unknown_keys_and_incomplete_toolchains(self) -> None:
        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["shadow_owner"] = True
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "unknown keys"):
            evaluation_core.validate_corpus(drifted)
        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["toolchain"] = {"kind": "node", "minimum_version": "20"}
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "package_manager"):
            evaluation_core.validate_corpus(drifted)
        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["setup"][0]["argv"] = ["bash", "-c", "pytest"]
        with self.assertRaises(evaluation_core.EvaluationError):
            evaluation_core.validate_corpus(drifted)

        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["windows_adapter"] = {
            "path": "../outside.patch", "sha256": "a" * 64, "patch_paths": ["src/value.py"]
        }
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "windows-adapters"):
            evaluation_core.validate_corpus(drifted)

        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["windows_oracle"] = {"p2p_baseline_policy": "ignore-all-failures"}
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "p2p_baseline_policy"):
            evaluation_core.validate_corpus(drifted)

    def test_json_schema_pins_the_same_closed_corpus_contract(self) -> None:
        schema = json.loads((EVALUATION_ROOT / "corpus" / "schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema"]["const"], evaluation_core.CORPUS_SCHEMA)
        self.assertEqual(schema["properties"]["id"]["type"], "string")
        self.assertEqual(schema["properties"]["tasks"]["minItems"], 1)
        self.assertNotIn("maxItems", schema["properties"]["tasks"])


class CandidateRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = evaluation_core.load_corpus(CORPUS_PATH)

    def test_candidate_metadata_coexists_only_with_task_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            task_runtime = workspace / ".agentbase" / "task-runtime"
            task_runtime.mkdir(parents=True)
            metadata = agentbase_codex.prepare_candidate_metadata_root(workspace)
            self.assertEqual(metadata, workspace / ".agentbase")
            self.assertTrue(task_runtime.is_dir())

            (metadata / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(
                evaluation_core.EvaluationError,
                "unexpected pre-existing content",
            ):
                agentbase_codex.prepare_candidate_metadata_root(workspace)

    def test_pnpm_runtime_paths_are_workspace_local_patched_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            wrapper, executable = windows_verifier._pnpm_runtime_paths(workspace)
            self.assertEqual(
                wrapper,
                workspace / ".agentbase" / "task-runtime" / "bin" / "pnpm.cmd",
            )
            self.assertEqual(
                executable,
                workspace
                / ".agentbase"
                / "task-runtime"
                / "pnpm"
                / "node_modules"
                / "pnpm"
                / "dist"
                / "pnpm.cjs",
            )

    def test_application_resolution_prefers_native_winget_alias_over_path_shim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local_app_data = Path(directory)
            alias = local_app_data / "Microsoft" / "WinGet" / "Links" / "rg.exe"
            alias.parent.mkdir(parents=True)
            alias.write_bytes(b"native executable placeholder")
            path_shim = local_app_data / "path" / "rg.exe"
            path_shim.parent.mkdir()
            path_shim.write_bytes(b"shim placeholder")
            with (
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}),
                mock.patch.object(agentbase_codex.shutil, "which", return_value=str(path_shim)),
            ):
                resolved = agentbase_codex._resolve_application(("rg.exe", "rg"))
        self.assertEqual(resolved, alias.resolve())

    def test_python_and_powershell_shell_policy_overrides_are_identical(self) -> None:
        common_script = PROJECT_ROOT / "development" / "common" / "codex_cli_runtime.ps1"
        quoted_script = str(common_script).replace("'", "''")
        command = (
            f". '{quoted_script}'; "
            "@(Get-AgentBaseCodexShellEnvironmentArguments) | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        powershell_arguments = json.loads(completed.stdout)
        python_arguments = [
            item
            for override in codex_runtime.codex_shell_environment_overrides()
            for item in ("-c", override)
        ]
        self.assertEqual(python_arguments, powershell_arguments)

    def test_candidate_usage_aggregates_root_and_subagent_rollouts(self) -> None:
        root_usage = {
            "total_tokens": 130,
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "cache_write_input_tokens": 10,
            "output_tokens": 30,
            "reasoning_output_tokens": 12,
        }
        child_usage = {
            "total_tokens": 65,
            "input_tokens": 50,
            "cached_input_tokens": 20,
            "cache_write_input_tokens": 5,
            "output_tokens": 15,
            "reasoning_output_tokens": 6,
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            before = agentbase_codex.candidate_rollout_snapshot(home)
            write_usage_rollout(
                home / "sessions" / "2026" / "08" / "24" / "root.jsonl",
                thread_id="root-thread",
                usage=root_usage,
            )
            write_usage_rollout(
                home / "sessions" / "2026" / "08" / "24" / "child.jsonl",
                thread_id="child-thread",
                parent_thread_id="root-thread",
                role="experiment",
                usage=child_usage,
                model="gpt-5.6-luna",
            )
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root-thread",
                root_usage=root_usage,
            )
        self.assertTrue(receipt["usage_complete"])
        self.assertEqual(receipt["thread_count"], 2)
        self.assertEqual(receipt["subagent_thread_count"], 1)
        self.assertEqual(receipt["usage"]["total_tokens"], 195)
        self.assertEqual(receipt["usage"]["cached_input_tokens"], 60)
        self.assertEqual(receipt["subagent_usage"], child_usage)
        self.assertEqual(receipt["threads"][1]["agent_role"], "experiment")
        self.assertTrue(receipt["api_equivalent_cost"]["complete"])
        self.assertEqual(receipt["api_equivalent_cost"]["request_count"], 2)
        self.assertEqual(receipt["api_equivalent_cost"]["root_usd_nanos"], 866000)
        self.assertEqual(receipt["api_equivalent_cost"]["subagent_usd_nanos"], 24650)
        self.assertEqual(receipt["api_equivalent_cost"]["total_usd_nanos"], 890650)
        self.assertEqual(receipt["api_equivalent_cost"]["total_usd"], "0.000890650")

    def test_unpriced_models_preserve_complete_root_and_child_usage(self) -> None:
        usage = {"total_tokens": 130, "input_tokens": 100, "cached_input_tokens": 40,
                 "cache_write_input_tokens": 10, "output_tokens": 30, "reasoning_output_tokens": 12}
        for root_model in ("gpt-5.6-sol", "unpriced-test-model"):
            with self.subTest(root_model=root_model), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                before = agentbase_codex.candidate_rollout_snapshot(home)
                write_usage_rollout(home / "sessions/root.jsonl", thread_id="root", usage=usage,
                                    model=root_model)
                write_usage_rollout(home / "sessions/child.jsonl", thread_id="child", usage=usage,
                                    usage_events=[usage, usage], parent_thread_id="root",
                                    role="experiment", model="unpriced-test-model")
                value = agentbase_codex.finalize_candidate_agent_usage(
                    {"model_invoked": True, "root_thread_id": "root", "root_usage": usage,
                     "usage_collection_error": "previous pricing coverage failure"},
                    codex_home=home, before=before)
                self.assertTrue(value["usage_complete"])
                self.assertEqual(value["usage"]["total_tokens"], 390)
                self.assertEqual(value["subagent_usage"]["total_tokens"], 260)
                self.assertNotIn("usage_collection_error", value)
                cost = value["api_equivalent_cost"]
                self.assertFalse(cost["complete"])
                self.assertIsNone(cost["total_usd_nanos"])
                self.assertIsNone(cost["subagent_usd_nanos"])
                self.assertEqual(cost["unpriced_models"], ["unpriced-test-model"])
                self.assertEqual(cost["request_count"], 3)
                self.assertEqual(cost["root_usd_nanos"] is None, root_model == "unpriced-test-model")
                child = value["agent_usage"][1]
                self.assertEqual(child["requests"][0]["model"], "unpriced-test-model")
                self.assertEqual(child["pricing_groups"][0]["request_count"], 2)
                self.assertIsNone(child["pricing_groups"][0]["cost_usd"])

    def test_candidate_cost_applies_long_context_pricing_per_response(self) -> None:
        below_threshold = {
            "total_tokens": 150010,
            "input_tokens": 150000,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "output_tokens": 10,
            "reasoning_output_tokens": 5,
        }
        long_request = {
            "total_tokens": 272101,
            "input_tokens": 272001,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "output_tokens": 100,
            "reasoning_output_tokens": 50,
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            before = agentbase_codex.candidate_rollout_snapshot(home)
            write_usage_rollout(
                home / "sessions" / "root.jsonl",
                thread_id="root-thread",
                usage=None,
                usage_events=[below_threshold, below_threshold],
            )
            cumulative = {
                field: below_threshold[field] * 2
                for field in agentbase_codex.CODEX_USAGE_FIELDS
            }
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root-thread",
                root_usage=cumulative,
            )
        self.assertEqual(receipt["api_equivalent_cost"]["long_context_request_count"], 0)
        self.assertEqual(receipt["api_equivalent_cost"]["total_usd_nanos"], 1200400000)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            before = agentbase_codex.candidate_rollout_snapshot(home)
            write_usage_rollout(
                home / "sessions" / "root.jsonl",
                thread_id="root-thread",
                usage=long_request,
                model="gpt-5.6-luna",
            )
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root-thread",
                root_usage=long_request,
            )
        self.assertEqual(receipt["api_equivalent_cost"]["long_context_request_count"], 1)
        self.assertEqual(receipt["api_equivalent_cost"]["total_usd_nanos"], 108980400)
        self.assertEqual(receipt["threads"][0]["pricing_groups"][0]["request_count"], 1)

    def test_candidate_usage_excludes_copied_parent_rollout_prefix(self) -> None:
        parent_usage = {
            "total_tokens": 13,
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }
        child_usage = {
            "total_tokens": 7,
            "input_tokens": 5,
            "cached_input_tokens": 2,
            "cache_write_input_tokens": 1,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
        }
        inherited_total = {
            field: parent_usage[field] + child_usage[field]
            for field in agentbase_codex.CODEX_USAGE_FIELDS
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            before = agentbase_codex.candidate_rollout_snapshot(home)
            write_usage_rollout(
                home / "sessions" / "root.jsonl",
                thread_id="root-thread",
                usage=parent_usage,
            )
            child = home / "sessions" / "child.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "child-thread",
                        "session_id": "root-thread",
                        "parent_thread_id": "root-thread",
                        "agent_role": "evidence",
                        "subagent_history_start_ordinal": 4,
                    },
                },
                {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": parent_usage,
                            "last_token_usage": parent_usage,
                        },
                    },
                },
                {"type": "turn_context", "payload": {"model": "gpt-5.6-luna"}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": inherited_total,
                            "last_token_usage": child_usage,
                        },
                    },
                },
                {"type": "event_msg", "payload": {"type": "task_complete"}},
            ]
            child.write_text(
                "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines),
                encoding="utf-8",
            )
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root-thread",
                root_usage=parent_usage,
            )
        self.assertEqual(receipt["usage"]["total_tokens"], 20)
        self.assertEqual(receipt["subagent_usage"], child_usage)
        self.assertEqual(receipt["api_equivalent_cost"]["request_count"], 2)
        self.assertEqual(receipt["api_equivalent_cost"]["subagent_request_count"], 1)

    def test_candidate_usage_marks_an_unfinished_subagent_incomplete(self) -> None:
        root_usage = {
            "total_tokens": 13,
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            before = agentbase_codex.candidate_rollout_snapshot(home)
            write_usage_rollout(
                home / "sessions" / "root.jsonl",
                thread_id="root-thread",
                usage=root_usage,
            )
            write_usage_rollout(
                home / "sessions" / "child.jsonl",
                thread_id="child-thread",
                parent_thread_id="root-thread",
                role="evidence",
                usage=None,
                terminal=False,
            )
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root-thread",
                root_usage=root_usage,
            )
        self.assertFalse(receipt["usage_complete"])
        self.assertFalse(receipt["threads"][1]["usage_complete"])
        self.assertEqual(receipt["subagent_usage"]["total_tokens"], 0)

    def test_installed_codex_runtime_requires_only_existing_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "installed-codex"
            installed.mkdir()
            with self.assertRaisesRegex(evaluation_core.PreconditionError, "auth.json"):
                agent_eval.require_installed_codex_runtime(installed)
            (installed / "auth.json").write_text("test auth\n", encoding="utf-8")
            agent_eval.require_installed_codex_runtime(installed)

    def test_candidate_runtime_tools_resolve_codex_without_launcher_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths: dict[str, Path] = {}
            for name in [*agentbase_codex.REQUIRED_CANDIDATE_TOOLS, "codex"]:
                path = root / f"{name}.exe"
                path.write_bytes(f"{name}\n".encode())
                paths[name] = path

            def resolve(candidates: tuple[str, ...]) -> Path:
                candidate = Path(candidates[0]).stem
                return paths[candidate]

            with (
                mock.patch.object(
                    agentbase_codex,
                    "_resolve_application",
                    side_effect=resolve,
                ),
                mock.patch.object(
                    agentbase_codex,
                    "run_capture",
                    side_effect=lambda argv, **kwargs: subprocess.CompletedProcess(
                        argv,
                        0,
                        stdout=b"fixture 1.0\n",
                        stderr=b"",
                    ),
                ),
            ):
                tools = agentbase_codex.candidate_runtime_tools(
                    PROJECT_ROOT,
                    root / "attempt",
                    paths["codex"],
                )
        self.assertEqual(
            set(tools["tools"]),
            {*agentbase_codex.REQUIRED_CANDIDATE_TOOLS, "codex"},
        )
        self.assertEqual(
            tools["tools"]["codex"]["schema"],
            "agentbase.codex-cli-identity/v1",
        )

    def test_deterministic_gate_disables_model_invocation(self) -> None:
        with mock.patch.dict(os.environ, {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "1"}):
            with self.assertRaisesRegex(evaluation_core.EvaluationError, "disabled"):
                agentbase_codex.invoke_candidate(
                    project_root=PROJECT_ROOT,
                    workspace=PROJECT_ROOT,
                    attempt_root=PROJECT_ROOT / ".attempt",
                    installed_codex_root=PROJECT_ROOT / ".installed-codex",
                    corpus=self.corpus,
                    profile_name="sol",
                    metadata={},
                    process_environment={},
                    codex_executable_path=None,
                    timeout_seconds=60,
                )

    def test_skill_projection_copies_the_complete_tree_and_reserves_one_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            metadata = workspace / ".agentbase"
            metadata.mkdir(parents=True)
            projection = agentbase_codex.stage_candidate_skill_projection(
                PROJECT_ROOT,
                workspace,
                metadata,
            )
            manifest_path = Path(str(projection["manifest_path"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "agentbase.windows-swe-skill-probes/v1")
            self.assertEqual(manifest["projection_root"], ".agents/skills")
            self.assertEqual(len(manifest["files"]), projection["file_count"])
            relative_paths = {item["path"] for item in manifest["files"]}
            self.assertIn("source-query/references/ast.md", relative_paths)
            self.assertIn("delivery-workflow/SKILL.md", relative_paths)
            self.assertEqual(
                evaluation_core.sha256_file(manifest_path),
                projection["manifest_sha256"],
            )
            with self.assertRaisesRegex(
                evaluation_core.PreconditionError,
                "reserved evaluator path",
            ):
                agentbase_codex.stage_candidate_skill_projection(
                    PROJECT_ROOT,
                    workspace,
                    metadata,
                )

    def test_capability_contract_uses_projected_assets_and_trusted_local_execution(self) -> None:
        contract = agentbase_codex.candidate_capability_contract(PROJECT_ROOT, self.corpus)
        self.assertEqual(
            contract["projected_assets"]["custom_agent_discovery_root"],
            ".codex/agents",
        )
        self.assertEqual(
            contract["projected_assets"]["skills"]["discovery_root"],
            ".agents/skills",
        )
        self.assertTrue(contract["projected_assets"]["content_hash_pinned"])
        execution = contract["execution_contract"]
        self.assertEqual(execution["environment"], "trusted-local-workspace")
        self.assertEqual(execution["sandbox_mode"], "danger-full-access")
        self.assertEqual(execution["approval_policy"], "never")
        self.assertTrue(execution["ignore_user_config"])
        self.assertFalse(execution["credential_copy_or_link"])
        self.assertFalse(execution["hooks_enabled"])
        self.assertEqual(
            execution["installed_codex_root_usage"],
            ["authentication", "session-usage-accounting"],
        )
        self.assertIn("srcq", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertIn("hyperfine", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertIn(
            "separate candidate and verifier workspaces",
            contract["mechanical_boundaries"],
        )
        self.assertEqual(
            contract["separate_evidence_owners"]["vscode_lsp_mcp"],
            "mcp/vscode-lsp-mcp",
        )
        self.assertIn("host-mcp", contract["excluded_from_swe"])

    def test_candidate_codex_projection_is_hash_pinned_and_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            projection = agentbase_codex.stage_candidate_codex_projection(
                PROJECT_ROOT,
                workspace,
            )
            config_path = Path(str(projection["config_path"]))
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["sandbox_mode"], "danger-full-access")
            self.assertEqual(config["approval_policy"], "never")
            self.assertEqual(config["web_search"], "disabled")
            self.assertFalse(config["features"]["hooks"])
            self.assertTrue(config["features"]["multi_agent"])
            self.assertEqual(
                config["developer_instructions"],
                (PROJECT_ROOT / "global" / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((workspace / ".codex" / "agents" / "evidence.toml").is_file())
            self.assertEqual(
                evaluation_core.sha256_file(config_path),
                next(
                    item["sha256"]
                    for item in projection["files"]
                    if item["path"] == ".codex/config.toml"
                ),
            )
            self.assertNotIn("auth.json", {item["path"] for item in projection["files"]})
            with self.assertRaisesRegex(
                evaluation_core.PreconditionError,
                "reserved evaluator path",
            ):
                agentbase_codex.stage_candidate_codex_projection(
                    PROJECT_ROOT,
                    workspace,
                )

    def test_candidate_launcher_uses_trusted_local_cli_without_legacy_setup(self) -> None:
        text = (EVALUATION_ROOT / "invoke_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("'--ignore-user-config'", text)
        self.assertIn("'--sandbox'", text)
        self.assertIn("'danger-full-access'", text)
        self.assertIn("'approval_policy=\"never\"'", text)
        self.assertIn("'--ignore-rules'", text)
        self.assertIn("$startInfo.Environment['CODEX_HOME']", text)
        self.assertNotIn("models_cache.json", text)
        self.assertNotIn("Invoke-AgentBaseSandboxSetup", text)
        self.assertNotIn("permissionProfile", text)
        self.assertNotIn("candidate_preflight.ps1", text)
        self.assertIn("agentbase.windows-swe-codex-run/v8", text)
        self.assertIn("status = if ($codexProcess.exit_code -eq 0)", text)
        self.assertIn("exit $codexProcess.exit_code", text)

    def test_candidate_prompt_uses_the_prepared_runtime_and_corpus_patch_scope(self) -> None:
        self.assertIn(
            "Do not create Git commits",
            agentbase_codex.CANDIDATE_COMPLETION_INSTRUCTION,
        )
        self.assertIn(
            "the evaluator will extract a Git patch",
            agentbase_codex.CANDIDATE_COMPLETION_INSTRUCTION,
        )
        python_task = next(
            task for task in self.corpus["tasks"] if task["toolchain"]["kind"] == "python"
        )
        python_hint = agentbase_codex.candidate_public_tooling_hint(python_task)
        self.assertIn(".agentbase-venv\\Scripts\\python.exe", python_hint)
        self.assertIn("identity-pinned dependencies", python_hint)
        self.assertIn("src/value.py", agentbase_codex.candidate_patch_scope_hint(python_task))
        self.assertIn(
            "outside this list",
            agentbase_codex.candidate_patch_scope_hint(python_task),
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            values = {
                "python": str(workspace / ".agentbase-venv" / "Scripts" / "python.exe"),
                "workspace": str(workspace),
                "npm": "npm.cmd",
                "pnpm": "pnpm.cmd",
            }
            public_checks = agentbase_codex.candidate_public_checks_hint(
                python_task,
                values,
                workspace,
            )
        self.assertIn("tests/base.py", public_checks)
        self.assertIn("safe.directory=", public_checks)
        self.assertIn(
            f"safe.directory={workspace.as_posix()}",
            public_checks,
        )
        self.assertIn("run each relevant listed regression command once", public_checks)
        self.assertNotIn("{report}", public_checks)
        self.assertNotIn("--junitxml", public_checks)

    def test_effective_candidate_config_participates_in_run_identity(self) -> None:
        qualification = {"receipt_sha256": "a" * 64}
        dependency = {"identity_sha256": "b" * 64}
        common = {
            "project_root": PROJECT_ROOT,
            "corpus_path": CORPUS_PATH,
            "corpus": self.corpus,
            "task_id": self.corpus["tasks"][0]["id"],
            "profile_name": "test",
            "qualification_receipt": qualification,
            "dependency_identity": dependency,
            "runtime_environment": {"dotenv_sha256": "c" * 64},
            "runtime_tools": {"identity_sha256": "d" * 64},
        }
        first = evaluation_core.candidate_run_identity(
            **common,
            config_descriptor={"effective_config_sha256": "e" * 64},
        )
        second = evaluation_core.candidate_run_identity(
            **common,
            config_descriptor={"effective_config_sha256": "f" * 64},
        )
        self.assertNotEqual(first["identity_sha256"], second["identity_sha256"])


class RuntimeRootBoundaryTests(unittest.TestCase):
    def test_managed_git_commands_freeze_windows_path_and_eol_behavior(self) -> None:
        command = evaluation_core.git_command(
            "-C", Path(r"C:\managed repository"), "status", "--short"
        )
        self.assertEqual(
            command,
            [
                "git.exe",
                "-c",
                "core.longpaths=true",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.eol=lf",
                "-C",
                r"C:\managed repository",
                "status",
                "--short",
            ],
        )
        self.assertEqual(
            evaluation_core.git_asset_command("checkout", "--detach", "FETCH_HEAD"),
            [
                "git.exe",
                "-c",
                "core.longpaths=true",
                "-c",
                "core.autocrlf=true",
                "-c",
                "core.eol=crlf",
                "checkout",
                "--detach",
                "FETCH_HEAD",
            ],
        )

    def test_generated_roots_are_disjoint_from_project_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            codex = root / "installed-codex"
            state = root / "state"
            work = root / "work"
            evaluation_core.ensure_evaluation_roots(project, state, work, codex)
            with self.assertRaisesRegex(evaluation_core.EvaluationError, "project_root"):
                evaluation_core.ensure_evaluation_roots(project, project / "state", work, codex)
            with self.assertRaisesRegex(evaluation_core.EvaluationError, "codex_root"):
                evaluation_core.ensure_evaluation_roots(project, state, codex / "work", codex)

    def test_managed_tree_cleanup_retries_windows_readonly_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "managed"
            managed.mkdir()
            readonly = managed / "packed-object.idx"
            readonly.write_bytes(b"read only\n")
            os.chmod(readonly, stat.S_IREAD)
            evaluation_core.remove_managed_tree(root, managed)
            self.assertFalse(managed.exists())

    def test_managed_tree_cleanup_retries_transient_windows_locks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "managed"
            managed.mkdir()
            (managed / "value.txt").write_text("value\n", encoding="utf-8")
            real_rmtree = evaluation_core.shutil.rmtree
            attempts = 0

            def transient_lock(*args: object, **kwargs: object) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("simulated delayed Windows handle release")
                real_rmtree(*args, **kwargs)

            with (
                mock.patch.object(evaluation_core.shutil, "rmtree", transient_lock),
                mock.patch.object(evaluation_core.time, "sleep") as sleep,
            ):
                evaluation_core.remove_managed_tree(root, managed)
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(managed.exists())


class GitPatchBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(
            evaluation_core.git_command("init", self.root),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        (self.root / "src").mkdir()
        (self.root / "src" / "value.py").write_text(
            "VALUE = 1\n", encoding="utf-8", newline="\n"
        )
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_value.py").write_text(
            "assert True\n", encoding="utf-8", newline="\n"
        )
        subprocess.run(evaluation_core.git_command("-C", self.root, "add", "."), check=True)
        subprocess.run(
            evaluation_core.git_command(
                "-C",
                self.root,
                "-c",
                "user.name=AgentBase Test",
                "-c",
                "user.email=agentbase@example.invalid",
                "commit",
                "-m",
                "base",
            ),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        self.task = {"allowed_patch_paths": ["src/**"]}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_capture_includes_tracked_and_untracked_allowed_files(self) -> None:
        (self.root / "src" / "value.py").write_text(
            "VALUE = 2\n", encoding="utf-8", newline="\n"
        )
        (self.root / "src" / "new.py").write_text(
            "NEW = True\n", encoding="utf-8", newline="\n"
        )
        output = self.root / ".git" / "candidate.patch"
        result = evaluation_core.capture_candidate_patch(self.root, self.task, output)
        self.assertEqual(result["files"], ["src/new.py", "src/value.py"])
        self.assertGreater(result["bytes"], 0)
        self.assertEqual(result["sha256"], evaluation_core.sha256_file(output))

    def test_capture_rejects_test_or_manifest_changes(self) -> None:
        (self.root / "tests" / "test_value.py").write_text(
            "assert False\n", encoding="utf-8", newline="\n"
        )
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "protected"):
            evaluation_core.capture_candidate_patch(
                self.root,
                self.task,
                self.root / ".git" / "candidate.patch",
            )

    def test_windows_adapter_becomes_a_clean_baseline_not_candidate_output(self) -> None:
        project_root = self.root / ".git" / "adapter-project"
        adapter = (
            project_root
            / "development"
            / "agent-evaluation"
            / "windows-adapters"
            / "fixture.patch"
        )
        adapter.parent.mkdir(parents=True)
        adapter.write_bytes(
            b"diff --git a/tests/test_value.py b/tests/test_value.py\n"
            b"--- a/tests/test_value.py\n"
            b"+++ b/tests/test_value.py\n"
            b"@@ -1 +1 @@\n"
            b"-assert True\n"
            b"+assert 1 == 1\n"
        )
        task = {
            "allowed_patch_paths": ["src/**"],
            "windows_adapter": {
                "path": "windows-adapters/fixture.patch",
                "sha256": evaluation_core.sha256_file(adapter),
                "patch_paths": ["tests/test_value.py"],
            },
        }
        before = evaluation_core.git_head(self.root)
        baseline = evaluation_core.apply_windows_adapter_baseline(
            project_root,
            self.root,
            task,
        )
        self.assertIsNotNone(baseline)
        assert baseline is not None
        self.assertEqual(baseline["base_commit"], before)
        self.assertNotEqual(baseline["baseline_commit"], before)
        self.assertEqual(
            evaluation_core.git_output(
                self.root, "status", "--porcelain", "--untracked-files=all"
            ),
            "",
        )

        (self.root / "src" / "value.py").write_text(
            "VALUE = 2\n", encoding="utf-8", newline="\n"
        )
        output = self.root / ".git" / "candidate-after-adapter.patch"
        captured = evaluation_core.capture_candidate_patch(self.root, task, output)
        self.assertEqual(captured["files"], ["src/value.py"])
        self.assertNotIn(b"tests/test_value.py", output.read_bytes())

    def test_windows_adapter_rejects_asset_hash_drift(self) -> None:
        project_root = self.root / ".git" / "adapter-project"
        adapter = (
            project_root
            / "development"
            / "agent-evaluation"
            / "windows-adapters"
            / "fixture.patch"
        )
        adapter.parent.mkdir(parents=True)
        adapter.write_text("not a patch\n", encoding="utf-8", newline="\n")
        task = {
            "windows_adapter": {
                "path": "windows-adapters/fixture.patch",
                "sha256": "0" * 64,
                "patch_paths": ["tests/test_value.py"],
            }
        }
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "hash mismatch"):
            evaluation_core.windows_adapter_asset(project_root, task)

    def test_windows_adapter_rejects_corrupt_patch_and_path_descriptor_drift(self) -> None:
        project_root = self.root / ".git" / "adapter-project"
        adapter = (
            project_root
            / "development"
            / "agent-evaluation"
            / "windows-adapters"
            / "fixture.patch"
        )
        adapter.parent.mkdir(parents=True)
        adapter.write_bytes(
            b"diff --git a/tests/test_value.py b/tests/test_value.py\n"
            b"--- a/tests/test_value.py\n"
            b"+++ b/tests/test_value.py\n"
            b"@@ -1,2 +1,2 @@\n"
            b"-assert True\n"
            b"+assert 1 == 1\n"
        )
        task = {
            "windows_adapter": {
                "path": "windows-adapters/fixture.patch",
                "sha256": evaluation_core.sha256_file(adapter),
                "patch_paths": ["tests/test_value.py"],
            }
        }
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "not a valid Git patch"):
            evaluation_core.windows_adapter_asset(project_root, task)

        adapter.write_bytes(
            b"diff --git a/tests/test_value.py b/tests/test_value.py\n"
            b"--- a/tests/test_value.py\n"
            b"+++ b/tests/test_value.py\n"
            b"@@ -1 +1 @@\n"
            b"-assert True\n"
            b"+assert 1 == 1\n"
        )
        task["windows_adapter"]["sha256"] = evaluation_core.sha256_file(adapter)
        task["windows_adapter"]["patch_paths"] = ["tests/other.py"]
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "differ from its descriptor"):
            evaluation_core.windows_adapter_asset(project_root, task)

    def test_pinned_upstream_patch_repairs_only_blank_context_prefixes(self) -> None:
        target = self.root / "src" / "value.py"
        target.write_text("VALUE = 1\n\n", encoding="utf-8", newline="\n")
        subprocess.run(evaluation_core.git_command("-C", self.root, "add", "."), check=True)
        subprocess.run(
            evaluation_core.git_command(
                "-C",
                self.root,
                "-c",
                "user.name=AgentBase Test",
                "-c",
                "user.email=agentbase@example.invalid",
                "commit",
                "-m",
                "blank baseline",
            ),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        patch = self.root / ".git" / "upstream.patch"
        patch.write_bytes((
            b"diff --git a/src/value.py b/src/value.py\n"
            b"--- a/src/value.py\n"
            b"+++ b/src/value.py\n"
            b"@@ -1,2 +1,2 @@\n"
            b"-VALUE = 1\n"
            b"+VALUE = 2\n"
            b"\n"
        ).replace(b"\n", b"\r\n"))
        descriptor = evaluation_core.apply_git_patch(
            self.root,
            patch,
            normalize_upstream=True,
        )
        self.assertEqual(descriptor["blank_context_prefixes_inserted"], 1)
        self.assertGreater(descriptor["crlf_line_endings_normalized"], 0)
        self.assertNotEqual(descriptor["source_sha256"], descriptor["applied_sha256"])
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n\n")


class ReportAdapterTests(unittest.TestCase):
    def test_attempt_cost_includes_failed_attempts_and_subagents(self) -> None:
        usage = {
            "total_tokens": 13,
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }
        identity = {
            "candidate_surface_identity_sha256": "a" * 64,
            "framework_identity_sha256": "b" * 64,
            "corpus_sha256": "c" * 64,
        }
        cases = (
            (
                "attempt-complete",
                "completed",
                "terminal",
                make_api_cost(
                    total_usd_nanos=100,
                    root_usd_nanos=80,
                    subagent_usd_nanos=20,
                    request_count=2,
                    subagent_request_count=1,
                ),
                2,
                1,
            ),
            (
                "attempt-failed",
                "infrastructure-failed",
                "candidate-finished",
                make_api_cost(
                    total_usd_nanos=200,
                    root_usd_nanos=200,
                    subagent_usd_nanos=0,
                    request_count=1,
                    subagent_request_count=0,
                ),
                1,
                0,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            for attempt_id, status, stage, cost, agents, subagents in cases:
                root = state / "attempts" / attempt_id
                root.mkdir(parents=True)
                (root / "attempt.json").write_text(
                    json.dumps(
                        {
                            "schema": "agentbase.windows-swe-attempt/v1",
                            "attempt_id": attempt_id,
                            "task_id": "synthetic-python-case",
                            "profile": "sol",
                            "status": status,
                            "stage": stage,
                            "updated_at": "2026-08-24T00:00:00Z",
                            "candidate_identity": identity,
                            "codex_result": {
                                "model_invoked": True,
                                "usage_scope": "root-and-descendant-threads",
                                "usage_complete": True,
                                "usage": usage,
                                "agent_thread_count": agents,
                                "subagent_thread_count": subagents,
                                "duration_seconds": 1.0,
                                "api_equivalent_cost": cost,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            health = agent_eval._attempt_health(
                state,
                {"synthetic-python-case"},
                recent_limit=20,
                current_candidate_surface_sha256="a" * 64,
                current_framework_sha256="b" * 64,
                current_corpus_sha256="c" * 64,
            )
        current = health["current_identity_cost_and_time"]
        self.assertEqual(current["model_attempts"], 2)
        self.assertEqual(current["known_subagent_threads"], 1)
        self.assertEqual(current["api_equivalent_cost"]["total_usd_nanos"], 300)
        self.assertEqual(current["api_equivalent_cost"]["subagent_usd_nanos"], 20)
        self.assertEqual(current["api_equivalent_cost"]["complete_attempts"], 2)

    def test_verifier_child_executable_requires_an_existing_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "tool.exe"
            executable.write_bytes(b"fixture\n")
            self.assertEqual(
                windows_verifier._absolute_child_argv(
                    [str(executable.resolve()), "--version"]
                ),
                [str(executable.resolve()), "--version"],
            )
            with self.assertRaisesRegex(
                evaluation_core.EvaluationError,
                "must use an absolute path",
            ):
                windows_verifier._absolute_child_argv(["tool.exe"])
            with self.assertRaisesRegex(
                evaluation_core.EvaluationError,
                "is not a file",
            ):
                windows_verifier._absolute_child_argv(
                    [str((Path(directory) / "missing.exe").resolve())]
                )

    def test_all_corpus_tasks_stage_reports_inside_the_verifier_workspace(self) -> None:
        corpus = evaluation_core.load_corpus(CORPUS_PATH)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool_root = root / "tools"
            tool_root.mkdir()
            npm = tool_root / "npm.cmd"
            pnpm = tool_root / "pnpm.cmd"
            npm.write_bytes(b"fixture\n")
            pnpm.write_bytes(b"fixture\n")
            for task in corpus["tasks"]:
                workspace = root / task["id"] / "workspace"
                artifact = root / task["id"] / "artifact"
                workspace.mkdir(parents=True)
                artifact.mkdir(parents=True)
                task_python = workspace / ".agentbase-venv" / "Scripts" / "python.exe"
                if task["toolchain"]["kind"] == "python":
                    task_python.parent.mkdir(parents=True)
                    task_python.write_bytes(b"fixture python\n")
                staged_reports = workspace / ".agentbase-verifier" / "reports"
                observed_argv: list[list[str]] = []
                observed_environments: list[dict[str, str]] = []

                def fake_trusted_local_check(**kwargs: object) -> dict[str, object]:
                    argv = [str(item) for item in kwargs["argv"]]
                    observed_argv.append(argv)
                    observed_environments.append(
                        {
                            str(key): str(value)
                            for key, value in kwargs["command_environment"].items()
                        }
                    )
                    for check in task["checks"]:
                        report = check["report"]
                        output = staged_reports / report["path"]
                        raw = staged_reports / report.get("raw_path", report["path"])
                        if any(
                            str(output) in argument or str(raw) in argument
                            for argument in argv
                        ):
                            raw.parent.mkdir(parents=True, exist_ok=True)
                            if report["kind"] == "jest-json-to-ctrf":
                                raw.write_text(
                                    json.dumps(
                                        {
                                            "testResults": [
                                                {
                                                    "assertionResults": [
                                                        {
                                                            "fullName": "fixture passes",
                                                            "status": "passed",
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ),
                                    encoding="utf-8",
                                )
                            else:
                                raw.write_text(
                                    '<testsuite><testcase classname="fixture" name="passes" /></testsuite>',
                                    encoding="utf-8",
                                )
                    return {
                        "exit_code": 0,
                        "duration_seconds": 0.01,
                        "log_path": str(kwargs["log_path"]),
                        "log_sha256": "a" * 64,
                        "log_bytes": 0,
                    }

                with mock.patch.object(
                    windows_verifier,
                    "_run_trusted_local_check",
                    side_effect=fake_trusted_local_check,
                ):
                    records = windows_verifier.run_checks(
                        task=task,
                        workspace=workspace,
                        artifact_root=artifact,
                        values={
                            "python": (
                                str(task_python.resolve())
                                if task["toolchain"]["kind"] == "python"
                                else sys.executable
                            ),
                            "workspace": str(workspace),
                            "npm": str(npm.resolve()),
                            "pnpm": str(pnpm.resolve()),
                        },
                        base_environment={},
                    )
                self.assertEqual(len(records), len(task["checks"]))
                self.assertTrue(observed_argv)
                expected_runtime_bin = (
                    task_python.parent.resolve()
                    if task["toolchain"]["kind"] == "python"
                    else Path(
                        npm if task["toolchain"]["package_manager"] == "npm" else pnpm
                    ).parent.resolve()
                )
                self.assertTrue(
                    all(
                        Path(environment["PATH"].split(os.pathsep, 1)[0]).resolve()
                        == expected_runtime_bin
                        for environment in observed_environments
                    ),
                    f"{task['id']} did not lead PATH with its frozen dependency runtime",
                )
                self.assertTrue(
                    all(Path(argv[0]).is_absolute() for argv in observed_argv),
                    f"{task['id']} left a verifier executable on PATH lookup",
                )
                for check in task["checks"]:
                    report_path = artifact / "reports" / check["report"]["path"]
                    self.assertTrue(
                        report_path.is_file(),
                        f"{task['id']} did not materialize {check['id']}",
                    )
                    if check["report"]["kind"] != "gate-ctrf":
                        staged_raw = staged_reports / check["report"].get(
                            "raw_path", check["report"]["path"]
                        )
                        self.assertTrue(
                            any(
                                any(str(staged_raw) in argument for argument in argv)
                                for argv in observed_argv
                            ),
                            f"{task['id']} passed no workspace-local report path",
                        )
                    self.assertFalse(
                        any(
                            any(str(report_path) in argument for argument in argv)
                            for argv in observed_argv
                        ),
                        f"{task['id']} exposed the artifact path to a checked command",
                    )

    def test_jest_json_uses_full_name_and_worst_status_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "jest.json"
            raw.write_text(
                json.dumps(
                    {
                        "testResults": [
                            {
                                "assertionResults": [
                                    {"fullName": "suite passes", "status": "passed"},
                                    {"fullName": "suite fails", "status": "failed", "failureMessages": ["boom"]},
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = root / "ctrf.json"
            windows_verifier.convert_jest_json(raw, output)
            tests = json.loads(output.read_text(encoding="utf-8"))["results"]["tests"]
            self.assertEqual([test["name"] for test in tests], ["suite passes", "suite fails"])
            self.assertEqual(tests[1]["message"], "boom")

    def test_junit_conversion_matches_official_use_suite_name_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "junit.xml"
            raw.write_text(
                '<testsuite><testcase classname="src/file.test.ts" name="group&#10;case" /></testsuite>',
                encoding="utf-8",
            )
            output = root / "ctrf.json"
            windows_verifier.convert_junit_to_ctrf(
                raw,
                output,
                tool="vitest",
                fold_whitespace=True,
            )
            test = json.loads(output.read_text(encoding="utf-8"))["results"]["tests"][0]
            self.assertEqual(test["name"], "src/file.test.ts: group case")
            self.assertEqual(test["status"], "passed")

    def test_junit_conversion_can_match_pinned_utf16_node_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "junit.xml"
            raw.write_text(
                '<testsuite><testcase classname="unicode.test.ts" name="🀒 𐌭 慨" /></testsuite>',
                encoding="utf-8",
            )
            output = root / "ctrf.json"
            windows_verifier.convert_junit_to_ctrf(
                raw,
                output,
                tool="vitest",
                node_identity_normalization="nfc-utf16-surrogate-replacement",
            )
            test = json.loads(output.read_text(encoding="utf-8"))["results"]["tests"][0]
            self.assertEqual(test["name"], "unicode.test.ts: �� �� 慨")
            self.assertEqual(test["status"], "passed")

    def test_windows_baseline_policy_projects_only_pinned_p2p_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_assets = root / "task"
            tests_root = task_assets / "tests"
            tests_root.mkdir(parents=True)
            (tests_root / "config.json").write_text(
                json.dumps(
                    {
                        "p2p_node_ids": [
                            "module.case_a",
                            "module.case_b",
                            "other.passes",
                            "suite.case",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "artifact"
            reports = artifact / "reports"
            reports.mkdir(parents=True)
            (reports / "base.xml").write_text(
                """
<testsuites><testsuite>
  <testcase classname="suite" name="case"><skipped /></testcase>
  <testcase name="module"><skipped /></testcase>
  <testcase classname="other" name="passes" />
</testsuite></testsuites>
""".strip(),
                encoding="utf-8",
            )
            task = {
                "windows_oracle": {
                    "p2p_baseline_policy": "exclude-stable-skips"
                },
                "checks": [
                    {
                        "bucket": "base",
                        "report": {"kind": "junit", "path": "base.xml"},
                    }
                ],
            }
            self.assertEqual(
                windows_verifier.baseline_p2p_exclusions(
                    task_assets=task_assets,
                    task=task,
                    artifact_root=artifact,
                ),
                ["module.case_a", "module.case_b", "suite.case"],
            )

    def test_windows_baseline_nonpassing_policy_maps_vitest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_assets = root / "task"
            tests_root = task_assets / "tests"
            tests_root.mkdir(parents=True)
            (tests_root / "config.json").write_text(
                json.dumps(
                    {
                        "p2p_node_ids": [
                            "test/base.test.ts: suite > stable Windows failure",
                            "test/base.test.ts: suite > still passes",
                            "test/new.test.ts: suite > task behavior",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "artifact"
            reports = artifact / "reports"
            reports.mkdir(parents=True)
            (reports / "base.xml").write_text(
                """
<testsuites><testsuite>
  <testcase classname="test/base.test.ts" name="suite &gt; stable Windows failure"><failure /></testcase>
  <testcase classname="test/base.test.ts" name="suite &gt; still passes" />
</testsuite></testsuites>
""".strip(),
                encoding="utf-8",
            )
            (reports / "new.xml").write_text(
                """
<testsuites><testsuite>
  <testcase classname="test/new.test.ts" name="suite &gt; task behavior"><failure /></testcase>
</testsuite></testsuites>
""".strip(),
                encoding="utf-8",
            )
            task = {
                "windows_oracle": {
                    "p2p_baseline_policy": "exclude-stable-nonpassing"
                },
                "checks": [
                    {
                        "bucket": "base",
                        "report": {
                            "kind": "junit-to-ctrf",
                            "raw_path": "base.xml",
                            "path": "base-ctrf.json",
                        },
                    },
                    {
                        "bucket": "new",
                        "report": {
                            "kind": "junit-to-ctrf",
                            "raw_path": "new.xml",
                            "path": "new-ctrf.json",
                        },
                    },
                ],
            }
            self.assertEqual(
                windows_verifier.baseline_p2p_exclusions(
                    task_assets=task_assets,
                    task=task,
                    artifact_root=artifact,
                ),
                ["test/base.test.ts: suite > stable Windows failure"],
            )

    def test_gate_report_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "gate.json"
            windows_verifier.write_gate_ctrf(
                output,
                name="[gate] npm run build",
                tool="npm",
                exit_code=1,
            )
            test = json.loads(output.read_text(encoding="utf-8"))["results"]["tests"][0]
            self.assertEqual(test, {"name": "[gate] npm run build", "status": "failed", "duration": 0})


class VerifierLifecycleTests(unittest.TestCase):
    def test_trusted_local_verifier_does_not_invoke_codex_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                windows_verifier,
                "_run_logged",
                return_value={"exit_code": 0},
            ) as run_logged:
                result = windows_verifier._run_trusted_local_check(
                    argv=[str(Path(sys.executable).resolve()), "--version"],
                    workspace=root,
                    base_environment={"BASE": "1"},
                    command_environment={"COMMAND": "2"},
                    timeout=10,
                    log_path=root / "check.log",
                )

        self.assertEqual(result["exit_code"], 0)
        launched = run_logged.call_args.args[0]
        self.assertEqual(launched[0], str(Path(sys.executable).resolve()))
        self.assertNotIn("sandbox", launched)
        self.assertEqual(run_logged.call_args.kwargs["environment"]["BASE"], "1")
        self.assertEqual(run_logged.call_args.kwargs["environment"]["COMMAND"], "2")

    def test_node_dependency_identity_ignores_workspace_and_json_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir()
            node = tools / "node.exe"
            npm = tools / "npm.cmd"
            node.write_bytes(b"node\n")
            npm.write_bytes(b"npm\n")
            workspaces = [root / "noop", root / "reference"]
            for workspace in workspaces:
                workspace.mkdir()
                (workspace / "package.json").write_text(
                    '{"name":"fixture","version":"1.0.0"}\n',
                    encoding="utf-8",
                )

            def capture(argv, *, cwd=None, **_kwargs):
                if "ls" in argv:
                    dependencies = (
                        {"alpha": {"version": "1"}, "beta": {"version": "2"}}
                        if Path(cwd).name == "noop"
                        else {"beta": {"version": "2"}, "alpha": {"version": "1"}}
                    )
                    payload = {
                        "path": str(Path(cwd).resolve()),
                        "dependencies": dependencies,
                    }
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        stdout=json.dumps(payload).encode("utf-8"),
                        stderr=b"",
                    )
                return subprocess.CompletedProcess(argv, 0, stdout=b"1.0.0\n", stderr=b"")

            task = {
                "toolchain": {
                    "kind": "node",
                    "minimum_version": "20",
                    "package_manager": "npm",
                }
            }
            values = {"node": str(node), "npm": str(npm)}
            with mock.patch.object(windows_verifier, "run_capture", side_effect=capture):
                identities = [
                    windows_verifier.dependency_identity(task, workspace, values)
                    for workspace in workspaces
                ]
            self.assertEqual(
                identities[0]["inventory_sha256"],
                identities[1]["inventory_sha256"],
            )
            self.assertEqual(
                identities[0]["identity_sha256"],
                identities[1]["identity_sha256"],
            )

    @staticmethod
    def _windows_pid_is_running(process_id: int) -> bool:
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    def test_logged_timeout_terminates_descendants_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid_path = root / "child.pid"
            parent_code = (
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(60)'])\n"
                f"Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding='utf-8')\n"
                "time.sleep(60)\n"
            )
            child_pid: int | None = None
            try:
                with self.assertRaisesRegex(
                    evaluation_core.EvaluationError,
                    "process tree was terminated",
                ):
                    windows_verifier._run_logged(
                        [sys.executable, "-c", parent_code],
                        workspace=root,
                        environment=os.environ,
                        timeout=2,
                        log_path=root / "timeout.log",
                        check=True,
                    )
                self.assertTrue(child_pid_path.is_file())
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                self.assertFalse(self._windows_pid_is_running(child_pid))
                self.assertTrue((root / "timeout.log").is_file())
            finally:
                if child_pid is not None and self._windows_pid_is_running(child_pid):
                    taskkill = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
                    subprocess.run(
                        [str(taskkill), "/PID", str(child_pid), "/T", "/F"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )

    def test_python_proxy_bootstrap_wheel_is_hash_pinned_and_offline_installable(self) -> None:
        wheel = windows_verifier.PYTHON_PROXY_BOOTSTRAP_WHEEL
        self.assertEqual(
            evaluation_core.sha256_file(wheel),
            windows_verifier.PYTHON_PROXY_BOOTSTRAP_SHA256,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(
                [sys.executable, "-m", "venv", str(root / "venv")],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            python = root / "venv" / "Scripts" / "python.exe"
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    str(wheel),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            probe = subprocess.run(
                [str(python), "-c", "import socks; print(socks.__version__)"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(probe.stdout.strip(), "1.7.1")

    def test_verifier_setup_precedes_patch_and_hidden_tests(self) -> None:
        corpus = evaluation_core.load_corpus(CORPUS_PATH)
        task = corpus["tasks"][0]
        events: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "artifact"
            artifact.mkdir()
            with (
                mock.patch.object(
                    windows_verifier,
                    "create_workspace",
                    side_effect=lambda *a, **k: events.append("workspace") or workspace,
                ),
                mock.patch.object(
                    windows_verifier,
                    "prepare_dependencies",
                    side_effect=lambda *a, **k: events.append("setup")
                    or ({"identity_sha256": "d" * 64}, {}),
                ),
                mock.patch.object(
                    windows_verifier,
                    "apply_windows_adapter_baseline",
                    side_effect=lambda *a, **k: events.append("adapter")
                    or {
                        "path": "windows-adapters/synthetic.patch",
                        "sha256": "f" * 64,
                        "paths": ["tests/conftest.py"],
                    },
                ),
                mock.patch.object(
                    windows_verifier,
                    "apply_git_patch",
                    side_effect=lambda *a, **k: events.append("patch")
                    or {
                        "source_sha256": "a" * 64,
                        "applied_sha256": "a" * 64,
                        "bytes": 1,
                        "blank_context_prefixes_inserted": 0,
                        "crlf_line_endings_normalized": 0,
                    },
                ),
                mock.patch.object(
                    windows_verifier,
                    "validate_staged_patch_scope",
                    side_effect=lambda *a, **k: events.append("scope")
                    or ["src/value.py"],
                ),
                mock.patch.object(
                    windows_verifier,
                    "run_checks",
                    side_effect=lambda *a, **k: events.append("checks") or [],
                ),
                mock.patch.object(
                    windows_verifier,
                    "baseline_p2p_exclusions",
                    side_effect=lambda *a, **k: events.append("baseline") or [],
                ),
                mock.patch.object(
                    windows_verifier,
                    "grade_reports",
                    side_effect=lambda *a, **k: events.append("grade")
                    or {
                        "reward": {"reward": 1},
                        "grader_sha256": task["assets"]["tests/grader.py"],
                    },
                ),
            ):
                result = windows_verifier.verify_patch(
                    project_root=PROJECT_ROOT,
                    state_root=root / "state",
                    work_root=root / "work",
                    corpus=corpus,
                    task_id=task["id"],
                    run_name="run",
                    patch_kind="reference",
                    candidate_patch=None,
                    artifact_root=artifact,
                    network_environment={},
                    retain_workspace=True,
                )
        self.assertEqual(
            events,
            [
                "workspace",
                "setup",
                "adapter",
                "patch",
                "scope",
                "patch",
                "checks",
                "baseline",
                "grade",
            ],
        )
        self.assertEqual(result["patch_kind"], "reference")
        self.assertEqual(
            result["execution_environment"],
            "trusted-local-independent-workspace",
        )
        self.assertEqual(
            evaluation_core.validate_receipt(
                result,
                schema=windows_verifier.VERIFIER_RESULT_SCHEMA,
            )["receipt_sha256"],
            result["receipt_sha256"],
        )

    def test_receipt_hash_detects_tampering_and_dependency_match_is_exact(self) -> None:
        receipt = evaluation_core.with_receipt_hash(
            {
                "schema": agent_eval.QUALIFICATION_SCHEMA,
                "dependency_identity_sha256": "a" * 64,
                "verifier_runtime_identity_sha256": "b" * 64,
            }
        )
        self.assertEqual(
            evaluation_core.find_matching_qualification([receipt], "a" * 64, "b" * 64),
            receipt,
        )
        self.assertIsNone(
            evaluation_core.find_matching_qualification([receipt], "a" * 64, "c" * 64)
        )
        tampered = dict(receipt)
        tampered["dependency_identity_sha256"] = "b" * 64
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "hash mismatch"):
            evaluation_core.validate_receipt(tampered)

    def test_embedded_identity_hash_detects_tampering(self) -> None:
        payload = {
            "schema": "agentbase.windows-swe-candidate-identity/v1",
            "value": "frozen",
        }
        identity = {
            **payload,
            "identity_sha256": evaluation_core.sha256_bytes(
                evaluation_core.canonical_bytes(payload)
            ),
        }
        evaluation_core.validate_identity(
            identity,
            schema="agentbase.windows-swe-candidate-identity/v1",
        )
        identity["value"] = "changed"
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "identity hash mismatch"):
            evaluation_core.validate_identity(identity)

    def test_case_lock_blocks_concurrent_owner_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with evaluation_core.CaseLock(root, "case"):
                with self.assertRaisesRegex(evaluation_core.EvaluationError, "already locked"):
                    with evaluation_core.CaseLock(root, "case"):
                        pass
            with evaluation_core.CaseLock(root, "case"):
                pass

    def test_case_lock_reclaims_a_dead_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = evaluation_core.CaseLock(root, "stale-case")
            lock.path.parent.mkdir(parents=True)
            lock.path.write_text(
                json.dumps(
                    {
                        "pid": 2147483647,
                        "created_at": "2000-01-01T00:00:00Z",
                        "key": "stale-case",
                        "owner_token": "dead",
                    }
                ),
                encoding="utf-8",
            )
            with lock:
                current = json.loads(lock.path.read_text(encoding="utf-8"))
                self.assertEqual(current["owner_token"], lock.owner_token)
            self.assertFalse(lock.path.exists())

    def test_retry_policy_requires_recovery_after_candidate_output(self) -> None:
        cases = (
            ("infrastructure-failed", "patch-captured"),
            ("blocked-precondition", "verifier-running"),
        )
        for status, stage in cases:
            with self.subTest(status=status, stage=stage), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                attempt_root = state / "attempts" / "attempt-1"
                attempt_root.mkdir(parents=True)
                (attempt_root / "attempt.json").write_text(
                    json.dumps(
                        {
                            "attempt_id": "attempt-1",
                            "candidate_identity_sha256": "a" * 64,
                            "status": status,
                            "stage": stage,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    evaluation_core.PreconditionError,
                    "recover --attempt-id",
                ):
                    evaluation_core.enforce_retry_policy(state, "a" * 64, "rerun")


class DeterministicEntryTests(unittest.TestCase):
    def test_attempt_stage_progress_uses_stderr_and_only_reports_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = {
                "schema": "agentbase.windows-swe-attempt/v1",
                "attempt_id": "attempt-test",
                "stage": "registered",
            }
            with mock.patch("builtins.print") as printer:
                updated = agent_eval.update_attempt(
                    root,
                    attempt,
                    stage="candidate-running",
                )
            printer.assert_called_once_with(
                "STAGE attempt-test candidate-running",
                file=sys.stderr,
                flush=True,
            )
            with mock.patch("builtins.print") as printer:
                agent_eval.update_attempt(
                    root,
                    updated,
                    status="running",
                )
            printer.assert_not_called()

    def test_validate_command_performs_no_external_action(self) -> None:
        parser = agent_eval.build_parser()
        args = parser.parse_args(
            [
                "validate",
                "--project-root",
                str(PROJECT_ROOT),
                "--corpus",
                str(CORPUS_PATH),
                "--view",
                "machine",
            ]
        )
        with mock.patch("builtins.print") as printer:
            self.assertEqual(agent_eval.command_validate(args), 0)
        document = json.loads(printer.call_args.args[0])
        self.assertFalse(document["external_actions"])

    def test_missing_default_corpus_reports_the_local_recovery_actions(self) -> None:
        parser = agent_eval.build_parser()
        with tempfile.TemporaryDirectory() as directory:
            args = parser.parse_args(
                ["validate", "--project-root", directory, "--view", "machine"]
            )
            with self.assertRaisesRegex(
                evaluation_core.PreconditionError,
                r"Restore the private corpus.*--corpus <local-json>",
            ):
                agent_eval.command_validate(args)

    def test_publish_validation_script_only_calls_static_validation_and_unittest(self) -> None:
        text = (EVALUATION_ROOT / "test_agent_evaluation_infrastructure.ps1").read_text(encoding="utf-8")
        self.assertIn("AGENTBASE_AGENT_EVALUATOR_DISABLED", text)
        self.assertIn("$entryPoint validate", text)
        self.assertNotIn("$entryPoint run", text)
        self.assertNotIn("$entryPoint oracle", text)

    def test_recover_contract_refuses_to_rerun_model(self) -> None:
        source = (EVALUATION_ROOT / "agent_eval.py").read_text(encoding="utf-8")
        recover_body = source.split("def command_recover", 1)[1].split("def command_report", 1)[0]
        self.assertNotIn("invoke_candidate(", recover_body)
        self.assertIn("never reruns a model", recover_body)
        self.assertIn('codex_result.get("status") != "completed"', recover_body)
        self.assertIn('codex_result.get("exit_code") != 0', recover_body)

    def test_recover_rejects_failed_candidate_before_patch_or_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            work_root = root / "work"
            attempt_root = state_root / "attempts" / "attempt-1"
            candidate_workspace = work_root / "candidate"
            attempt_root.mkdir(parents=True)
            candidate_workspace.mkdir(parents=True)

            qualification = evaluation_core.with_receipt_hash(
                {"schema": agent_eval.QUALIFICATION_SCHEMA}
            )
            identity_payload = {
                "schema": "agentbase.windows-swe-candidate-identity/v1",
                "task_id": "task-1",
            }
            identity = {
                **identity_payload,
                "identity_sha256": evaluation_core.sha256_bytes(
                    evaluation_core.canonical_bytes(identity_payload)
                ),
            }
            attempt = {
                "attempt_id": "attempt-1",
                "task_id": "task-1",
                "profile": "clean",
                "stage": "candidate-finished",
                "candidate_workspace": str(candidate_workspace),
                "runtime_environment": {},
                "qualification_receipt": qualification,
                "candidate_identity": identity,
                "candidate_identity_sha256": identity["identity_sha256"],
                "codex_result": {
                    "schema": agentbase_codex.CODEX_RUN_RESULT_SCHEMA,
                    "status": "failed",
                    "model_invoked": True,
                    "exit_code": 1,
                    "execution_environment": "trusted-local-workspace",
                },
            }
            args = mock.Mock(
                attempt_id="attempt-1",
                view="machine",
                retain_workspace=True,
            )

            with (
                mock.patch.object(
                    agent_eval,
                    "resolve_context",
                    return_value=(root, root / "corpus.json", state_root, work_root, {}),
                ),
                mock.patch.object(agent_eval, "ensure_evaluation_roots"),
                mock.patch.object(
                    agent_eval,
                    "load_attempt",
                    return_value=(attempt_root, attempt),
                ),
                mock.patch.object(agent_eval, "require_task", return_value={"id": "task-1"}),
                mock.patch.object(agent_eval, "rematerialize_network", return_value=({}, {})),
                mock.patch.object(agent_eval, "process_environment", return_value={}),
                mock.patch.object(agent_eval, "verify_deep_swe"),
                mock.patch.object(agent_eval, "verify_upstream_source"),
                mock.patch.object(
                    agent_eval,
                    "qualification_base_identity",
                    return_value={"identity_sha256": "b" * 64},
                ),
                mock.patch.object(
                    agent_eval,
                    "find_qualification_receipts",
                    return_value=[qualification],
                ),
                mock.patch.object(
                    agent_eval,
                    "update_attempt",
                    return_value=attempt,
                ) as update_attempt,
                mock.patch.object(agent_eval, "capture_candidate_patch") as capture_patch,
                mock.patch.object(agent_eval, "run_candidate_verifier") as run_verifier,
            ):
                with self.assertRaisesRegex(
                    evaluation_core.EvaluationError,
                    "omits its completed candidate result",
                ):
                    agent_eval.command_recover(args)

            capture_patch.assert_not_called()
            run_verifier.assert_not_called()
            update_attempt.assert_called_once()
            self.assertEqual(update_attempt.call_args.args, (attempt_root, attempt))
            self.assertEqual(
                set(update_attempt.call_args.kwargs),
                {"recovery_failure"},
            )
