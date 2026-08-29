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


CORPUS_PATH = EVALUATION_ROOT / "corpus" / "final-v1.json"


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


def make_preflight_receipt(
    *,
    skill_manifest_sha256: str = "a" * 64,
    skill_file_count: int = 3,
    tool_manifest_sha256: str = "b" * 64,
    tool_probes: dict[str, str] | None = None,
    passed: bool = True,
    **overrides: object,
) -> dict[str, object]:
    expected_tools = tool_probes or {"pwsh": "c" * 64}
    value: dict[str, object] = {
        "schema": "agentbase.windows-swe-preflight/v12",
        "passed": passed,
        "canary_readable": False,
        "canary_error_type": "System.UnauthorizedAccessException",
        "auth_readable": False,
        "auth_error_type": "System.UnauthorizedAccessException",
        "installed_auth_readable": False,
        "installed_auth_error_type": "System.UnauthorizedAccessException",
        "project_canary_readable": False,
        "project_canary_error_type": "System.UnauthorizedAccessException",
        "skill_probe_manifest_readable": True,
        "skill_probe_manifest_sha256": skill_manifest_sha256,
        "skill_probe_manifest_error_type": None,
        "skill_projection_readable": True,
        "skill_projection_error_type": None,
        "skill_projection_write_denied": True,
        "skill_projection_write_error_type": "System.UnauthorizedAccessException",
        "skill_files_expected": skill_file_count,
        "skill_files_verified": skill_file_count,
        "workspace_write_probe_passed": True,
        "workspace_write_probe_error_type": None,
        "runtime_temp_attempt_scoped": True,
        "runtime_appdata_attempt_scoped": True,
        "runtime_home_attempt_scoped": True,
        "runtime_localappdata_attempt_scoped": True,
        "pytest_temp_policy_ready": True,
        "task_runtime_path_ready": True,
        "runtime_state_error_type": None,
        "tool_probe_manifest_readable": True,
        "tool_probe_manifest_sha256": tool_manifest_sha256,
        "tool_probe_manifest_error_type": None,
        "tool_probes": {
            name: {
                "expected_sha256": sha256,
                "observed_sha256": sha256,
                "exit_code": 0,
                "summary": f"{name} test",
            }
            for name, sha256 in expected_tools.items()
        },
        "srcq_doctor_exit_code": 0,
        "srcq_scc_doctor_exit_code": 0,
        "srcq_smoke": {
            name: {"passed": True, "summary": f"{name} test"}
            for name in agentbase_codex.SRCQ_SMOKE_CHECKS
        },
        "srcq_doctor_summary": "ok",
        "srcq_scc_doctor_summary": "ok",
    }
    value.update(overrides)
    return value


def make_sandbox_runtime_use_receipt(
    *,
    identity_sha256: str = "d" * 64,
    state_path: Path | None = None,
) -> dict[str, object]:
    return {
        "schema": agentbase_codex.SANDBOX_RUNTIME_USE_SCHEMA,
        "ready": True,
        "setup_invoked": False,
        "identity_sha256": identity_sha256,
        "controlled_identity_sha256": "e" * 64,
        "backend_identity_sha256": "f" * 64,
        "state_path": str(state_path or Path("runtime.json")),
    }


def materialize_fake_sandbox_backend(home: Path) -> dict[str, object]:
    (home / ".sandbox").mkdir(parents=True, exist_ok=True)
    (home / ".sandbox-bin").mkdir(parents=True, exist_ok=True)
    (home / ".sandbox-secrets").mkdir(parents=True, exist_ok=True)
    (home / ".sandbox" / "setup_marker.json").write_text(
        '{"version": 5, "proxy_ports": [], "allow_local_binding": true}\n',
        encoding="utf-8",
    )
    (home / ".sandbox-bin" / "codex-command-runner-0.148.0.exe").write_bytes(
        b"sandbox codex\n"
    )
    (home / "cap_sid").write_text(
        json.dumps(
            {
                "workspace": "S-1-5-21-1-2-3-4",
                "readonly": "S-1-5-21-5-6-7-8",
                "workspace_by_cwd": {},
                "writable_root_by_path": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return agentbase_codex.sandbox_backend_snapshot(home)


def legacy_sandbox_backend_snapshot(home: Path) -> dict[str, object]:
    current = agentbase_codex.sandbox_backend_snapshot(home)
    capability_sid = home.resolve() / "cap_sid"
    payload = {
        "schema": agentbase_codex.LEGACY_SANDBOX_BACKEND_SCHEMA,
        "setup_marker_sha256": current["setup_marker_sha256"],
        "setup_marker_bytes": current["setup_marker_bytes"],
        "sandbox_runners": current["sandbox_runners"],
        "capability_sid_sha256": evaluation_core.sha256_file(capability_sid),
        "capability_sid_bytes": capability_sid.stat().st_size,
        "protected_secret_directory_present": True,
    }
    return {
        **payload,
        "identity_sha256": evaluation_core.sha256_bytes(
            evaluation_core.canonical_bytes(payload)
        ),
    }


def fake_ready_sandbox_status(
    _project_root: Path,
    state_root: Path,
    _installed_codex_root: Path,
    _corpus: dict[str, object],
    _codex_identity: dict[str, object],
) -> dict[str, object]:
    runtime_use = make_sandbox_runtime_use_receipt(
        state_path=evaluation_core.sandbox_runtime_state_path(state_root)
    )
    return {
        "schema": agentbase_codex.SANDBOX_RUNTIME_STATUS_SCHEMA,
        "status": "ready",
        "ready": True,
        "checks": {},
        "reason_codes": [],
        "runtime_use": runtime_use,
        "recovery_action": None,
    }


class CorpusContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = evaluation_core.load_corpus(CORPUS_PATH)

    def test_exact_windows_task_set_and_profiles(self) -> None:
        self.assertEqual(
            [task["id"] for task in self.corpus["tasks"]],
            [
                "returns-validated-error-accumulation",
                "sql-formatter-bigquery-pipe-formatting",
                "httpx-multipart-response-parsing",
                "awilix-async-container-initialization",
                "bandit-interprocedural-taint-checks",
                "fastapi-implicit-head-options",
                "meriyah-explicit-resource-declarations",
                "clack-async-autocomplete-options",
                "superjson-error-stack-serialization",
            ],
        )
        self.assertEqual(
            [task["difficulty"] for task in self.corpus["tasks"]],
            ["easy", "easy", "medium", "medium", "medium", "hard", "hard", "very-hard", "very-hard"],
        )
        self.assertEqual(
            self.corpus["profiles"],
            {
                "sol": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
                "luna": {"model": "gpt-5.6-luna", "reasoning_effort": "max"},
            },
        )
        self.assertFalse(self.corpus["assessment"]["leaderboard_comparable"])

    def test_suites_cover_without_rotation_overlap(self) -> None:
        suites = self.corpus["suites"]
        self.assertTrue(set(suites["smoke"]).issubset(suites["core"]))
        self.assertFalse(set(suites["core"]) & set(suites["rotation"]))
        self.assertEqual(set(suites["all"]), set(suites["core"]) | set(suites["rotation"]))

    def test_rollout_evidence_is_task_local_and_bounded(self) -> None:
        counts = [76, 70, 48, 44, 42, 29, 25, 18, 17]
        self.assertEqual(
            [task["difficulty_evidence"]["successful_rollouts"] for task in self.corpus["tasks"]],
            counts,
        )
        for task in self.corpus["tasks"]:
            evidence = task["difficulty_evidence"]
            self.assertEqual(evidence["total_rollouts"], 116)
            self.assertEqual(
                evidence["source"],
                f"https://deepswe.datacurve.ai/data/v1/tasks/{task['id']}",
            )

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

    def test_hash_pinned_windows_fixture_adapters_are_task_local(self) -> None:
        adapters = {
            task["id"]: task["windows_adapter"]
            for task in self.corpus["tasks"]
            if "windows_adapter" in task
        }
        self.assertEqual(
            set(adapters),
            {
                "bandit-interprocedural-taint-checks",
                "clack-async-autocomplete-options",
                "httpx-multipart-response-parsing",
            },
        )
        self.assertEqual(
            adapters["clack-async-autocomplete-options"]["patch_paths"],
            [
                "packages/core/src/prompts/prompt.ts",
                "packages/core/test/mock-readable.ts",
                "packages/prompts/test/test-utils.ts",
            ],
        )
        self.assertEqual(
            adapters["httpx-multipart-response-parsing"]["patch_paths"],
            ["tests/conftest.py", "tests/test_utils.py"],
        )
        self.assertEqual(
            adapters["bandit-interprocedural-taint-checks"]["patch_paths"],
            [
                "tests/functional/test_functional.py",
                "tests/functional/test_runtime.py",
                "tests/unit/core/test_config.py",
                "tests/unit/core/test_manager.py",
                "tests/unit/core/test_util.py",
                "tests/unit/formatters/test_sarif.py",
            ],
        )
        verified = evaluation_core.verify_windows_adapter_assets(PROJECT_ROOT, self.corpus)
        self.assertEqual(set(verified), set(adapters))
        self.assertEqual(
            verified["httpx-multipart-response-parsing"]["sha256"],
            adapters["httpx-multipart-response-parsing"]["sha256"],
        )
        self.assertEqual(
            verified["clack-async-autocomplete-options"]["sha256"],
            adapters["clack-async-autocomplete-options"]["sha256"],
        )

    def test_task_local_windows_runtime_migrations_are_explicit(self) -> None:
        tasks = {task["id"]: task for task in self.corpus["tasks"]}
        bandit = tasks["bandit-interprocedural-taint-checks"]
        editable_installs = [
            command
            for command in [*bandit["setup"], *bandit["checks"]]
            for command in (
                [command]
                if "before" not in command
                else command["before"]
            )
            if command["argv"][-2:] == ["-e", "."]
        ]
        self.assertEqual(len(editable_installs), 3)
        self.assertTrue(
            all(command.get("env", {}).get("PBR_VERSION") == "0.0.0" for command in editable_installs)
        )

        fastapi = tasks["fastapi-implicit-head-options"]
        self.assertEqual(
            fastapi["windows_oracle"],
            {"p2p_baseline_policy": "exclude-stable-skips"},
        )

        meriyah = tasks["meriyah-explicit-resource-declarations"]
        self.assertEqual(
            meriyah["setup"][0]["argv"][:3],
            ["{npm}", "install", "--include=dev"],
        )
        self.assertIn("package-lock.json", meriyah["setup_cleanup"]["remove_untracked"])
        self.assertTrue(
            all(
                "--configLoader=runner" in check["argv"]
                for check in meriyah["checks"]
            )
        )

        clack = tasks["clack-async-autocomplete-options"]
        self.assertEqual(
            clack["windows_oracle"],
            {"p2p_baseline_policy": "exclude-stable-nonpassing"},
        )
        self.assertIn("--config.node-linker=hoisted", clack["setup"][0]["argv"])
        self.assertTrue(
            all(
                "--configLoader=runner" in check["argv"]
                and "--no-file-parallelism" in check["argv"]
                and check.get("env", {}).get("TERM_PROGRAM") == "vscode"
                for check in clack["checks"]
                if check["report"]["kind"] != "gate-ctrf"
            )
        )

    def test_validator_rejects_profile_and_shell_drift(self) -> None:
        drifted = copy.deepcopy(self.corpus)
        drifted["profiles"]["luna"]["reasoning_effort"] = "medium"
        with self.assertRaises(evaluation_core.EvaluationError):
            evaluation_core.validate_corpus(drifted)

    def test_validator_rejects_unknown_keys_and_incomplete_toolchains(self) -> None:
        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["shadow_owner"] = True
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "unknown keys"):
            evaluation_core.validate_corpus(drifted)
        drifted = copy.deepcopy(self.corpus)
        del drifted["tasks"][1]["toolchain"]["package_manager"]
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "package_manager"):
            evaluation_core.validate_corpus(drifted)
        drifted = copy.deepcopy(self.corpus)
        drifted["tasks"][0]["setup"][0]["argv"] = ["bash", "-c", "pytest"]
        with self.assertRaises(evaluation_core.EvaluationError):
            evaluation_core.validate_corpus(drifted)

        drifted = copy.deepcopy(self.corpus)
        httpx = next(task for task in drifted["tasks"] if task["id"].startswith("httpx-"))
        httpx["windows_adapter"]["path"] = "../outside.patch"
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "windows-adapters"):
            evaluation_core.validate_corpus(drifted)

        drifted = copy.deepcopy(self.corpus)
        fastapi = next(task for task in drifted["tasks"] if task["id"].startswith("fastapi-"))
        fastapi["windows_oracle"]["p2p_baseline_policy"] = "ignore-all-failures"
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "p2p_baseline_policy"):
            evaluation_core.validate_corpus(drifted)

    def test_json_schema_pins_the_same_closed_corpus_contract(self) -> None:
        schema = json.loads((EVALUATION_ROOT / "corpus" / "schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema"]["const"], evaluation_core.CORPUS_SCHEMA)
        self.assertEqual(schema["properties"]["id"]["const"], evaluation_core.CORPUS_ID)
        self.assertEqual(schema["properties"]["tasks"]["minItems"], 9)
        self.assertEqual(schema["properties"]["tasks"]["maxItems"], 9)


class SandboxConfigTests(unittest.TestCase):
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

    @unittest.skipUnless(os.name == "nt", "sandbox temp ACLs are Windows-only")
    def test_sandbox_temp_precreates_pytest_owner_roots_and_cleanup_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_temp = root / "runtime-temp"
            evaluation_core.prepare_sandbox_writable_root(root, runtime_temp)
            environment = evaluation_core.sandbox_temp_environment(runtime_temp)

            self.assertTrue((runtime_temp / "pytest-of-unknown").is_dir())
            username = os.environ.get("USERNAME", "").strip()
            if username and not any(character in username for character in '\\/:*?"<>|'):
                self.assertTrue((runtime_temp / f"pytest-of-{username}").is_dir())
            self.assertEqual(
                environment[evaluation_core.PYTEST_DEBUG_TEMPROOT_ENV_KEY],
                str(runtime_temp.resolve()),
            )
            self.assertEqual(
                environment[evaluation_core.PYTEST_ADDOPTS_ENV_KEY],
                evaluation_core.PYTEST_RETENTION_ADDOPTS,
            )
            self.assertEqual(environment["HOME"], str((runtime_temp / "home").resolve()))
            self.assertEqual(
                environment["USERPROFILE"],
                str((runtime_temp / "home").resolve()),
            )

    @unittest.skipUnless(os.name == "nt", "WinGet aliases are Windows-only")
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

    def test_candidate_config_defaults_host_to_deny_and_keeps_workspace_runtime_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "held-out-state"
            installed = Path(directory) / "installed-codex"
            text, descriptor = agentbase_codex.build_evaluation_runtime_config(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
        config = tomllib.loads(text)
        profile = self.corpus["codex"]["candidate_permission_profile"]
        self.assertNotIn("sandbox_mode", config)
        self.assertEqual(config["default_permissions"], profile)
        self.assertEqual(config["approval_policy"], "never")
        self.assertEqual(config["web_search"], "disabled")
        self.assertEqual(config["windows"]["sandbox"], "elevated")
        self.assertTrue(config["agents"]["enabled"])
        self.assertTrue(config["features"]["multi_agent"])
        self.assertEqual(config["permissions"][profile]["extends"], ":workspace")
        self.assertFalse(config["permissions"][profile]["network"]["enabled"])
        self.assertTrue(
            config["permissions"][profile]["network"]["allow_local_binding"]
        )
        verifier_profile = self.corpus["codex"]["verifier_permission_profile"]
        self.assertFalse(
            config["permissions"][verifier_profile]["network"]["enabled"]
        )
        self.assertTrue(
            config["permissions"][verifier_profile]["network"][
                "allow_local_binding"
            ]
        )
        self.assertEqual(config["shell_environment_policy"]["inherit"], "all")
        self.assertFalse(
            config["shell_environment_policy"]["ignore_default_excludes"]
        )
        self.assertFalse(
            config["shell_environment_policy"]["experimental_use_profile"]
        )
        self.assertEqual(
            config["shell_environment_policy"]["set"],
            {agentbase_codex.WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY: "1"},
        )
        for name in (
            "ALL_PROXY",
            "CODEX_*",
            "OPENAI_*",
            "SSL_CERT_FILE",
            "GIT_*",
            "SSH_*",
            "NODE_OPTIONS",
            "*PASSWORD*",
        ):
            self.assertEqual(
                config["shell_environment_policy"]["filters"][name],
                "exclude",
            )
        self.assertEqual(
            config["permissions"][profile]["filesystem"][str(state.resolve())],
            "deny",
        )
        filesystem = config["permissions"][profile]["filesystem"]
        self.assertEqual(filesystem["glob_scan_max_depth"], 1)
        self.assertEqual(filesystem[":root"], "deny")
        self.assertEqual(filesystem[":minimal"], "read")
        self.assertEqual(filesystem[":tmpdir"], "write")
        self.assertEqual(
            filesystem[":workspace_roots"],
            {
                ".": "write",
                ".agentbase": "read",
                ".agents/skills": "read",
                ".codex": "read",
                ".git": "read",
                "**/*.env": "deny",
            },
        )
        self.assertEqual(filesystem[str(state.resolve())], "deny")
        runtime_home = evaluation_core.sandbox_runtime_home(state)
        self.assertEqual(filesystem[str(runtime_home)], "read")
        self.assertEqual(filesystem[str(runtime_home / "auth.json")], "deny")
        self.assertEqual(filesystem[str(runtime_home / ".sandbox-secrets")], "deny")
        self.assertEqual(filesystem[str(PROJECT_ROOT.resolve())], "deny")
        self.assertNotIn(str(PROJECT_ROOT.resolve() / "*"), filesystem)
        self.assertEqual(filesystem[str(installed.resolve())], "deny")
        self.assertNotIn(str(installed.resolve() / "*"), filesystem)
        for candidates in agentbase_codex.REQUIRED_CANDIDATE_TOOLS.values():
            tool_path = agentbase_codex._resolve_application(candidates)
            self.assertEqual(filesystem[str(tool_path)], "read")
        self.assertEqual(config["model_provider"], "agentbase_eval_http")
        self.assertFalse(config["model_providers"]["agentbase_eval_http"]["supports_websockets"])
        self.assertEqual(descriptor["identity"]["state_root_denied"], str(state.resolve()))
        self.assertEqual(
            descriptor["identity"]["installed_codex_contents_denied"],
            str(installed.resolve()),
        )
        self.assertTrue(descriptor["identity"]["host_filesystem_default_denied"])
        self.assertTrue(descriptor["identity"]["minimal_runtime_readable"])
        self.assertEqual(
            descriptor["identity"]["project_root_contents_denied"],
            str(PROJECT_ROOT.resolve()),
        )
        self.assertFalse(
            descriptor["identity"]["protected_root_listing_may_be_readable"]
        )
        self.assertTrue(
            descriptor["identity"]["runtime_home_minimal_read_reopened"]
        )
        self.assertTrue(descriptor["identity"]["attempt_tmpdir_reopened"])
        self.assertTrue(descriptor["identity"]["process_appdata_scoped_to_tmpdir"])
        self.assertTrue(
            descriptor["identity"]["shell_environment_secret_filtered"]
        )
        shell_policy_descriptor, _ = (
            agentbase_codex._resolved_shell_environment_policy()
        )
        self.assertEqual(
            descriptor["identity"]["shell_environment_policy_sha256"],
            shell_policy_descriptor["sha256"],
        )
        self.assertEqual(
            descriptor["identity"]["shell_environment_managed_set_keys"],
            [agentbase_codex.WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY],
        )
        self.assertTrue(descriptor["identity"]["codex_home_under_denied_state"])
        self.assertEqual(
            descriptor["identity"]["repository_skill_projection"],
            ".agents/skills read-only derived copy",
        )

    def test_candidate_config_identity_and_runtime_hash_are_stable_for_same_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            installed = Path(directory) / "installed-codex"
            first_text, first = agentbase_codex.build_evaluation_runtime_config(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            second_text, second = agentbase_codex.build_evaluation_runtime_config(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
        self.assertEqual(first["identity"], second["identity"])
        self.assertEqual(first_text, second_text)
        self.assertEqual(first["effective_config_sha256"], second["effective_config_sha256"])

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

    def test_shared_runtime_config_gives_verifier_no_network_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_text, _ = agentbase_codex.build_evaluation_runtime_config(
                PROJECT_ROOT,
                Path(directory) / "state",
                Path(directory) / "installed",
                self.corpus,
            )
        config = tomllib.loads(config_text)
        profile = self.corpus["codex"]["verifier_permission_profile"]
        self.assertEqual(
            config["default_permissions"],
            self.corpus["codex"]["candidate_permission_profile"],
        )
        self.assertEqual(config["permissions"][profile]["extends"], ":workspace")
        self.assertFalse(config["permissions"][profile]["network"]["enabled"])
        environment = agent_eval.process_environment({})
        self.assertEqual(
            environment[agentbase_codex.WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY],
            "1",
        )
        self.assertEqual(
            config["shell_environment_policy"]["filters"]["CODEX_*"],
            "exclude",
        )
        self.assertEqual(config["windows"]["sandbox"], "elevated")
        self.assertTrue(config["features"]["multi_agent"])
        self.assertNotIn("schema", config["shell_environment_policy"])

    def test_candidate_launcher_uses_app_server_sandbox_command_and_model_catalog(self) -> None:
        text = (EVALUATION_ROOT / "invoke_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("$preflightCommand = @(\n        $preflightShell", text)
        self.assertIn("$startInfo.ArgumentList.Add('app-server')", text)
        self.assertIn("method = 'command/exec'", text)
        self.assertIn("permissionProfile = $PermissionProfile", text)
        self.assertIn("capabilities = [ordered]@{", text)
        self.assertIn("experimentalApi = $true", text)
        self.assertIn(
            "$startInfo.Environment['CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED'] = '1'",
            text,
        )
        self.assertIn(
            "$StartInfo.Environment['CODEX_NETWORK_ALLOW_LOCAL_BINDING'] = '1'",
            text,
        )
        self.assertNotIn("$preflightArguments = @(\n        'sandbox',", text)
        self.assertIn("-PermissionProfile $Profile", text)
        self.assertIn("'-SkillRootPath', $ResolvedSkillRoot", text)
        self.assertIn("'-SkillProbeManifestPath', $ResolvedSkillProbeManifest", text)
        self.assertIn("'-DeniedAuthPath', $ResolvedDeniedAuth", text)
        self.assertIn("'-InstalledAuthPath', $ResolvedInstalledAuth", text)
        self.assertIn("'-ProjectCanaryPath', $ResolvedProjectCanary", text)
        self.assertIn("'-RuntimeTempPath', $RuntimeTemp", text)
        self.assertIn("'-RuntimeAppDataPath', $RuntimeAppData", text)
        self.assertIn("'-RuntimeHomePath', $RuntimeHome", text)
        self.assertIn("'-RuntimeLocalAppDataPath', $RuntimeLocalAppData", text)
        self.assertIn("$toolPaths[$probeId] = $resolvedProbePath", text)
        self.assertIn("-ResolvedPreflightShell $toolProbeManifest.tool_paths['pwsh']", text)
        self.assertIn(
            "$preflightShell, '-NoProfile', '-NonInteractive', '-File', $preflightScript",
            text,
        )
        self.assertNotIn(
            "'pwsh.exe', '-NoProfile', '-NonInteractive', '-File', $preflightScript",
            text,
        )
        self.assertIn("[string]$InstalledCodexRoot", text)
        self.assertIn("$authSource = $resolvedInstalledAuth", text)
        self.assertNotIn("$installedCodexRoot = Join-Path $env:USERPROFILE '.codex'", text)
        self.assertIn(
            "$projectTrustKey = ConvertTo-AgentBaseCodexTomlString "
            "($resolvedWorkspace.ToLowerInvariant())",
            text,
        )
        self.assertIn(
            "'-c', \"projects={$projectTrustKey={trust_level=`\"trusted`\"}}\"",
            text,
        )
        self.assertIn(
            '"projects={$projectTrustKey={trust_level=`"trusted`"}}"',
            text,
        )
        self.assertNotIn("projects.$projectTrustKey.trust_level", text)
        self.assertNotIn("'--ephemeral'", text)
        self.assertIn("usage_scope = 'root-thread-only'", text)
        self.assertIn("root_thread_id = $jsonlSummary.thread_id", text)
        self.assertIn(
            "'-ExpectedSkillProbeManifestSha256', $ExpectedSkillProbeManifestSha256",
            text,
        )
        self.assertIn("'-ToolProbeManifestPath', $ResolvedToolProbeManifest", text)
        self.assertIn(
            "'-ExpectedToolProbeManifestSha256', $ExpectedToolProbeManifestSha256",
            text,
        )
        self.assertIn(
            "'-WriteProbePath', (Join-Path $ResolvedWorkspace '.agentbase-workspace-write-probe')",
            text,
        )
        self.assertIn("-FailureResultPath $resolvedResult", text)
        self.assertIn("$runtimeTemp = [IO.Path]::GetFullPath($RuntimeTemp)", text)
        self.assertNotIn("$attemptRuntimeRoot", text)
        self.assertIn("$StartInfo.Environment['TMPDIR']", text)
        self.assertIn("$StartInfo.Environment['LOCALAPPDATA']", text)
        self.assertIn("$StartInfo.Environment['PYTEST_DEBUG_TEMPROOT']", text)
        self.assertIn(
            "--override-ini=tmp_path_retention_policy=none",
            text,
        )
        self.assertIn("Result path must be inside the denied state root", text)
        self.assertIn("Candidate prompt must be inside the denied state root", text)
        self.assertIn("model_invoked = $false", text)
        self.assertIn("-AllowFailedReceipt", text)
        self.assertIn("Invoke-AgentBaseSandboxSetup", text)
        self.assertEqual(text.count("Invoke-AgentBaseSandboxSetup"), 2)
        setup_branch = text.split("if ($Action -eq 'Setup')", 1)[1].split(
            "\n\nforeach ($required in @{", 1
        )[0]
        setup_function = text.split("function Invoke-AgentBaseSandboxSetup", 1)[1].split(
            "function Get-AgentBaseSandboxRuntimeUse", 1
        )[0]
        self.assertIn("Invoke-AgentBaseSandboxSetup", setup_branch)
        self.assertIn("'-P', $PermissionProfile", setup_function)
        self.assertIn("Join-Path $env:SystemRoot 'System32\\cmd.exe'", setup_function)
        self.assertIn("$setupShell, '/d', '/c', 'exit 0'", setup_function)
        self.assertNotIn("'pwsh.exe', '-NoProfile'", setup_function)
        self.assertIn("agentbase.windows-swe-sandbox-setup/v1", text)
        self.assertIn("agentbase.windows-swe-sandbox-check/v5", text)
        self.assertIn("agentbase.windows-swe-sandbox-runtime-use/v1", text)
        self.assertIn("setup_invoked = $false", text)
        self.assertIn("New-AgentBaseCodexModelCatalogProjection", text)
        self.assertIn("Remove-Item -LiteralPath $catalogPath -Force", text)
        self.assertIn("supports", (EVALUATION_ROOT / "codex-eval-overlay.toml").read_text(encoding="utf-8"))
        self.assertNotIn("WindowsApps\\codex.exe", text)
        self.assertNotIn("[string]$Home", text)
        verifier = (EVALUATION_ROOT / "windows_verifier.py").read_text(encoding="utf-8")
        self.assertNotIn('"sandbox",\n        "windows",', verifier)
        cli = (EVALUATION_ROOT / "agent_eval.py").read_text(encoding="utf-8")
        self.assertEqual(cli.count("invoke_sandbox_setup("), 1)
        setup_command = cli.split("def command_sandbox_setup", 1)[1].split(
            "def build_sandbox_assessment", 1
        )[0]
        self.assertIn("invoke_sandbox_setup(", setup_command)
        self.assertNotIn("invoke_sandbox_setup(", verifier)

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

    def test_installed_codex_runtime_requires_auth_and_run_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "installed-codex"
            installed.mkdir()
            with self.assertRaisesRegex(evaluation_core.PreconditionError, "auth.json"):
                agent_eval.require_installed_codex_runtime(
                    installed,
                    require_model_catalog=False,
                )
            (installed / "auth.json").write_text("test auth\n", encoding="utf-8")
            agent_eval.require_installed_codex_runtime(
                installed,
                require_model_catalog=False,
            )
            with self.assertRaisesRegex(evaluation_core.PreconditionError, "models_cache.json"):
                agent_eval.require_installed_codex_runtime(
                    installed,
                    require_model_catalog=True,
                )
            (installed / "models_cache.json").write_text("{}\n", encoding="utf-8")
            agent_eval.require_installed_codex_runtime(
                installed,
                require_model_catalog=True,
            )

    def test_deterministic_gate_disables_model_invocation(self) -> None:
        with mock.patch.dict(os.environ, {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "1"}):
            with self.assertRaisesRegex(evaluation_core.EvaluationError, "disabled"):
                agentbase_codex.invoke_candidate(
                    project_root=PROJECT_ROOT,
                    workspace=PROJECT_ROOT,
                    state_root=PROJECT_ROOT / ".state",
                    attempt_root=PROJECT_ROOT / ".attempt",
                    codex_home=PROJECT_ROOT / ".home",
                    runtime_temp=PROJECT_ROOT / ".attempt" / "runtime-temp",
                    sandbox_runtime=make_sandbox_runtime_use_receipt(),
                    installed_codex_root=PROJECT_ROOT / ".installed-codex",
                    corpus=self.corpus,
                    profile_name="sol",
                    metadata={},
                    process_environment={},
                    codex_executable_path=None,
                    timeout_seconds=60,
                )

    def test_setup_launcher_classifies_canceled_uac_without_retrying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("workspace", "state", "home"):
                (root / name).mkdir()
            runtime = root / "state" / "runtime"
            runtime.mkdir()
            marker = root / "home" / ".sandbox" / "setup_marker.json"
            marker.parent.mkdir()
            original_marker = (
                '{"version": 5, "proxy_ports": [], '
                '"allow_local_binding": false}\n'
            )
            marker.write_text(original_marker, encoding="utf-8")
            codex = root / "codex.exe"
            codex.write_bytes(b"fixture\n")
            completed = subprocess.CompletedProcess(
                args=["pwsh.exe"],
                returncode=1,
                stdout=b"",
                stderr=(
                    b"orchestrator_helper_launch_canceled: "
                    b"ShellExecuteExW failed to launch setup helper: 1223"
                ),
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agentbase_codex,
                    "run_capture",
                    return_value=completed,
                ) as launch,
            ):
                with self.assertRaisesRegex(
                    evaluation_core.SandboxSetupApprovalError,
                    "approval.*not completed",
                ):
                    agentbase_codex.invoke_sandbox_setup(
                        project_root=PROJECT_ROOT,
                        workspace=root / "workspace",
                        state_root=root / "state",
                        codex_home=root / "home",
                        runtime_temp=runtime,
                        result_path=root / "state" / "setup-result.json",
                        codex_executable_path=codex,
                        permission_profile="agentbase_verifier",
                        process_environment={},
                    )
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(marker.read_text(encoding="utf-8"), original_marker)
            self.assertFalse((runtime / "setup-marker-before.json").exists())

    def test_setup_launcher_commits_only_a_local_binding_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("workspace", "state", "home"):
                (root / name).mkdir()
            runtime = root / "state" / "runtime"
            runtime.mkdir()
            marker = root / "home" / ".sandbox" / "setup_marker.json"
            marker.parent.mkdir()
            marker.write_text(
                '{"version": 5, "proxy_ports": [], '
                '"allow_local_binding": false}\n',
                encoding="utf-8",
            )
            codex = root / "codex.exe"
            codex.write_bytes(b"fixture\n")
            result_path = root / "state" / "setup-result.json"

            def successful_setup(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                self.assertFalse(marker.exists())
                marker.write_text(
                    '{"version": 5, "proxy_ports": [], '
                    '"allow_local_binding": true}\n',
                    encoding="utf-8",
                )
                result_path.write_text(
                    json.dumps(
                        {
                            "schema": agentbase_codex.SANDBOX_SETUP_RESULT_SCHEMA,
                            "passed": True,
                            "setup_invoked": True,
                            "model_invoked": False,
                            "exit_code": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    args=["pwsh.exe"],
                    returncode=0,
                    stdout=b"",
                    stderr=b"",
                )

            with (
                mock.patch.dict(os.environ, {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"}),
                mock.patch.object(agentbase_codex, "run_capture", side_effect=successful_setup),
            ):
                result = agentbase_codex.invoke_sandbox_setup(
                    project_root=PROJECT_ROOT,
                    workspace=root / "workspace",
                    state_root=root / "state",
                    codex_home=root / "home",
                    runtime_temp=runtime,
                    result_path=result_path,
                    codex_executable_path=codex,
                    permission_profile="agentbase_verifier",
                    process_environment={},
                )
            self.assertTrue(result["passed"])
            self.assertTrue(
                json.loads(marker.read_text(encoding="utf-8"))["allow_local_binding"]
            )
            self.assertFalse((runtime / "setup-marker-before.json").exists())

    def test_candidate_preflight_failure_is_a_non_model_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preflight_path = root / "preflight.json"
            preflight_receipt = make_preflight_receipt(passed=False)
            preflight_receipt["tool_probes"]["pwsh"]["exit_code"] = 1
            preflight_receipt["tool_probes"]["pwsh"]["summary"] = "pwsh probe failed"
            preflight_path.write_text(
                json.dumps(preflight_receipt),
                encoding="utf-8",
            )
            task_runtime_bin = root / "runtime-bin"
            task_runtime_bin.mkdir()
            metadata = {
                "prompt_path": root / "prompt.txt",
                "canary_path": root / "canary.txt",
                "skill_root_path": root / "workspace" / ".agents" / "skills",
                "skill_probe_manifest_path": root / "skill-probes.json",
                "skill_probe_manifest_sha256": "a" * 64,
                "expected_skill_file_count": 3,
                "tool_probe_manifest_path": root / "tool-probes.json",
                "tool_probe_manifest_sha256": "b" * 64,
                "expected_tool_probes": {"pwsh": "c" * 64},
                "preflight_output_path": preflight_path,
                "task_runtime": {
                    "kind": "node",
                    "executable": str(task_runtime_bin / "npm.cmd"),
                    "bin_directory": str(task_runtime_bin),
                    "virtual_environment": None,
                },
            }
            attempt_root = root / "attempt"
            attempt_root.mkdir()
            (attempt_root / "codex-result.json").write_text(
                json.dumps(
                    {
                        "schema": "agentbase.windows-swe-codex-run/v7",
                        "status": "blocked-precondition",
                        "model_invoked": False,
                        "exit_code": None,
                        "sandbox_runtime": make_sandbox_runtime_use_receipt(),
                        "preflight": json.loads(preflight_path.read_text(encoding="utf-8")),
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"",
                stderr=b"candidate preflight failed",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(agentbase_codex.subprocess, "run", return_value=process),
                mock.patch.object(
                    agentbase_codex,
                    "prepare_sandbox_writable_root",
                    side_effect=lambda _root, candidate, **_kwargs: candidate,
                ),
            ):
                with self.assertRaisesRegex(
                    evaluation_core.PreconditionError,
                    "tool:pwsh",
                ):
                    agentbase_codex.invoke_candidate(
                        project_root=PROJECT_ROOT,
                        workspace=root / "workspace",
                        state_root=root / "state",
                        attempt_root=attempt_root,
                        codex_home=root / "home",
                        runtime_temp=attempt_root / "runtime-temp",
                        sandbox_runtime=make_sandbox_runtime_use_receipt(),
                        installed_codex_root=root / "installed-codex",
                        corpus=self.corpus,
                        profile_name="sol",
                        metadata=metadata,
                        process_environment={},
                        codex_executable_path=None,
                        timeout_seconds=60,
                    )
                with self.assertRaisesRegex(
                    evaluation_core.EvaluationError,
                    "candidate launcher failed",
                ):
                    agentbase_codex.invoke_candidate(
                        project_root=PROJECT_ROOT,
                        workspace=root / "workspace",
                        state_root=root / "state",
                        attempt_root=root / "untrusted-attempt",
                        codex_home=root / "home",
                        runtime_temp=root / "untrusted-attempt" / "runtime-temp",
                        sandbox_runtime=make_sandbox_runtime_use_receipt(),
                        installed_codex_root=root / "installed-codex",
                        corpus=self.corpus,
                        profile_name="sol",
                        metadata=metadata,
                        process_environment={},
                        codex_executable_path=None,
                        timeout_seconds=60,
                    )

    def test_preflight_requires_hidden_deny_and_workspace_read_write_probes(self) -> None:
        text = (EVALUATION_ROOT / "candidate_preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("agentbase.windows-swe-preflight/v12", text)
        self.assertIn("-not $canaryReadable", text)
        self.assertIn("-not $authReadable", text)
        self.assertIn("-not $installedAuthReadable", text)
        self.assertIn("-not $projectCanaryReadable", text)
        self.assertIn("$skillProjectionReadable", text)
        self.assertIn("$skillFilesVerified -eq $skillFilesExpected", text)
        self.assertIn("$skillProjectionWriteDenied", text)
        self.assertIn("$workspaceWriteProbePassed", text)
        self.assertIn("$runtimeTempAttemptScoped", text)
        self.assertIn("$runtimeHomeAttemptScoped", text)
        self.assertIn("$runtimeLocalAppDataAttemptScoped", text)
        self.assertIn("$taskRuntimePathReady", text)
        self.assertIn("$toolProbeManifestHash -ceq $ExpectedToolProbeManifestSha256", text)
        self.assertIn("$observedProbeHash -cne $probe.sha256", text)
        self.assertIn("$srcqSmoke['rg-pagination']", text)
        self.assertIn("--cache on", text)
        self.assertIn("--artifact-out $artifactPath", text)
        self.assertNotIn("$toolCommands", text)

    def test_preflight_executes_hash_pinned_cmd_paths_and_reports_manifest_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            metadata = workspace / ".agentbase"
            metadata.mkdir(parents=True)
            skill_projection = agentbase_codex.stage_candidate_skill_projection(
                PROJECT_ROOT,
                workspace,
                metadata,
            )
            runtime_tools = agentbase_codex.candidate_runtime_tools(PROJECT_ROOT, root)
            staged = agentbase_codex.stage_candidate_tool_probe_manifest(
                metadata,
                runtime_tools,
            )
            write_probe = metadata / "write-probe.txt"
            installed_auth = root / "unreadable-installed-auth.json"
            project_canary = root / "unreadable-project-canary.md"
            runtime_temp = root / "runtime-temp"
            runtime_appdata = runtime_temp / "appdata"
            runtime_home = runtime_temp / "home"
            runtime_localappdata = runtime_temp / "localappdata"
            runtime_temp.mkdir()
            runtime_appdata.mkdir()
            runtime_home.mkdir()
            runtime_localappdata.mkdir()

            def run_preflight(*, mismatched_temp: bool = False) -> subprocess.CompletedProcess[str]:
                environment = os.environ.copy()
                for name in ("TEMP", "TMP", "TMPDIR"):
                    environment[name] = str(runtime_temp)
                environment["APPDATA"] = str(runtime_appdata)
                environment["HOME"] = str(runtime_home)
                environment["LOCALAPPDATA"] = str(runtime_localappdata)
                environment["USERPROFILE"] = str(runtime_home)
                environment["PYTEST_DEBUG_TEMPROOT"] = str(runtime_temp)
                environment["PYTEST_ADDOPTS"] = (
                    evaluation_core.PYTEST_RETENTION_ADDOPTS
                )
                if mismatched_temp:
                    environment["TMP"] = str(root / "mismatched-temp")
                return subprocess.run(
                    [
                        "pwsh.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-File",
                        str(EVALUATION_ROOT / "candidate_preflight.ps1"),
                        "-CanaryPath",
                        str(root / "unreadable-canary.txt"),
                        "-DeniedAuthPath",
                        str(root / "unreadable-auth.json"),
                        "-InstalledAuthPath",
                        str(installed_auth),
                        "-ProjectCanaryPath",
                        str(project_canary),
                        "-SkillRootPath",
                        str(skill_projection["root"]),
                        "-SkillProbeManifestPath",
                        str(skill_projection["manifest_path"]),
                        "-ExpectedSkillProbeManifestSha256",
                        str(skill_projection["manifest_sha256"]),
                        "-ToolProbeManifestPath",
                        str(staged["path"]),
                        "-ExpectedToolProbeManifestSha256",
                        str(staged["sha256"]),
                        "-WriteProbePath",
                        str(write_probe),
                        "-RuntimeTempPath",
                        str(runtime_temp),
                        "-RuntimeAppDataPath",
                        str(runtime_appdata),
                        "-RuntimeHomePath",
                        str(runtime_home),
                        "-RuntimeLocalAppDataPath",
                        str(runtime_localappdata),
                    ],
                    cwd=workspace,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )

            baseline = run_preflight()
            self.assertEqual(baseline.returncode, 1, baseline.stderr)
            receipt = json.loads(baseline.stdout)
            self.assertFalse(receipt["passed"])
            self.assertTrue(receipt["skill_projection_readable"])
            self.assertFalse(receipt["skill_projection_write_denied"])
            self.assertEqual(
                receipt["skill_files_verified"],
                skill_projection["file_count"],
            )
            self.assertTrue(all(item["passed"] for item in receipt["srcq_smoke"].values()))
            self.assertEqual(receipt["tool_probe_manifest_sha256"], staged["sha256"])
            self.assertEqual(set(receipt["tool_probes"]), set(staged["expected_tools"]))
            self.assertEqual(
                agentbase_codex.candidate_preflight_failed_checks(
                    receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
                ["skill-projection-writable"],
            )
            self.assertFalse(write_probe.exists())

            installed_auth.write_text("exposed auth\n", encoding="utf-8")
            exposed = run_preflight()
            self.assertEqual(exposed.returncode, 1, exposed.stderr)
            exposed_receipt = json.loads(exposed.stdout)
            self.assertTrue(exposed_receipt["installed_auth_readable"])
            self.assertEqual(
                agentbase_codex.candidate_preflight_failed_checks(
                    exposed_receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
                ["installed-auth-readable", "skill-projection-writable"],
            )
            installed_auth.unlink()

            project_canary.write_text("exposed project source\n", encoding="utf-8")
            exposed_project = run_preflight()
            self.assertEqual(exposed_project.returncode, 1, exposed_project.stderr)
            exposed_project_receipt = json.loads(exposed_project.stdout)
            self.assertTrue(exposed_project_receipt["project_canary_readable"])
            self.assertEqual(
                agentbase_codex.candidate_preflight_failed_checks(
                    exposed_project_receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
                ["project-root-readable", "skill-projection-writable"],
            )
            project_canary.unlink()

            mismatched_temp = run_preflight(mismatched_temp=True)
            self.assertEqual(mismatched_temp.returncode, 1, mismatched_temp.stderr)
            mismatched_temp_receipt = json.loads(mismatched_temp.stdout)
            self.assertFalse(mismatched_temp_receipt["runtime_temp_attempt_scoped"])
            self.assertEqual(
                agentbase_codex.candidate_preflight_failed_checks(
                    mismatched_temp_receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
                ["skill-projection-writable", "runtime-temp-outside-attempt-tmpdir"],
            )

            skill_manifest_path = Path(str(skill_projection["manifest_path"]))
            original_skill_manifest = skill_manifest_path.read_bytes()
            skill_manifest_path.write_text("{}\n", encoding="utf-8")
            failed_skill_manifest = run_preflight()
            self.assertEqual(failed_skill_manifest.returncode, 1, failed_skill_manifest.stderr)
            failed_skill_receipt = json.loads(failed_skill_manifest.stdout)
            self.assertIn(
                "skill-probe-manifest-hash",
                agentbase_codex.candidate_preflight_failed_checks(
                    failed_skill_receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
            )
            skill_manifest_path.write_bytes(original_skill_manifest)

            Path(str(staged["path"])).write_text("{}\n", encoding="utf-8")
            failed = run_preflight()
            self.assertEqual(failed.returncode, 1, failed.stderr)
            failed_receipt = json.loads(failed.stdout)
            self.assertFalse(failed_receipt["passed"])
            self.assertEqual(failed_receipt["tool_probes"], {})
            self.assertIn(
                "tool-probe-manifest-hash",
                agentbase_codex.candidate_preflight_failed_checks(
                    failed_receipt,
                    expected_skill_file_count=int(skill_projection["file_count"]),
                    expected_skill_probe_manifest_sha256=str(
                        skill_projection["manifest_sha256"]
                    ),
                    expected_tool_probes=staged["expected_tools"],
                    expected_tool_probe_manifest_sha256=str(staged["sha256"]),
                ),
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
            self.assertIn("delivery-workflow/scripts/workctl.py", relative_paths)
            self.assertIn("delivery-workflow/assets/templates/design.md", relative_paths)
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

    def test_capability_contract_separates_projected_probed_and_host_capabilities(self) -> None:
        contract = agentbase_codex.candidate_capability_contract(PROJECT_ROOT, self.corpus)
        configured = contract["configured_capabilities"]
        self.assertEqual(configured["multi_agent"]["default_model"], "gpt-5.6-luna")
        self.assertEqual(configured["multi_agent"]["default_reasoning_effort"], "medium")
        self.assertEqual(
            contract["projected_assets"]["custom_agents"],
            {
                "evidence": {"model": "gpt-5.6-luna", "reasoning_effort": "medium"},
                "experiment": {"model": "gpt-5.6-sol", "reasoning_effort": "low"},
                "operator": {"model": "gpt-5.6-luna", "reasoning_effort": "max"},
            },
        )
        self.assertEqual(
            contract["evaluator_profiles"],
            {
                "sol": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
                "luna": {"model": "gpt-5.6-luna", "reasoning_effort": "max"},
            },
        )
        self.assertTrue(contract["projected_assets"]["skills"]["full_tree_hash_pinned"])
        self.assertTrue(contract["projected_assets"]["skills"]["projection_read_only"])
        self.assertTrue(configured["candidate_model_actions"]["apply_patch"])
        self.assertTrue(configured["candidate_model_actions"]["public_test_execution"])
        self.assertTrue(
            configured["candidate_model_actions"]["shell_environment_secret_filtered"]
        )
        shell_policy_descriptor, _ = (
            agentbase_codex._resolved_shell_environment_policy()
        )
        self.assertEqual(
            configured["candidate_model_actions"]["shell_environment_policy_sha256"],
            shell_policy_descriptor["sha256"],
        )
        self.assertEqual(
            configured["candidate_model_actions"]["shell_environment_managed_set_keys"],
            [agentbase_codex.WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY],
        )
        self.assertTrue(
            configured["candidate_model_actions"]["requires_candidate_model_evidence"]
        )
        self.assertIn("srcq", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertIn("hyperfine", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertTrue(contract["runtime_probe_contract"]["performed_before_candidate_model"])
        self.assertTrue(configured["sandbox"]["installed_codex_contents_denied"])
        self.assertTrue(configured["sandbox"]["host_filesystem_default_denied"])
        self.assertTrue(configured["sandbox"]["minimal_runtime_readable"])
        self.assertTrue(configured["sandbox"]["project_root_contents_denied"])
        self.assertTrue(configured["sandbox"]["state_hidden_assets_denied"])
        self.assertFalse(configured["sandbox"]["protected_root_listing_may_be_readable"])
        self.assertTrue(configured["sandbox"]["runtime_home_minimal_read_reopened"])
        self.assertTrue(configured["sandbox"]["attempt_tmpdir_only"])
        self.assertTrue(configured["sandbox"]["process_appdata_scoped_to_tmpdir"])
        self.assertFalse(configured["sandbox"]["external_network_enabled"])
        self.assertTrue(configured["sandbox"]["loopback_network_enabled"])
        self.assertTrue(contract["runtime_probe_contract"]["installed_auth_unreadable"])
        self.assertTrue(contract["runtime_probe_contract"]["project_root_probe_unreadable"])
        self.assertTrue(
            contract["runtime_probe_contract"]["process_temp_scoped_to_attempt_tmpdir"]
        )
        self.assertTrue(contract["runtime_probe_contract"]["srcq_ast_cache_round_trip"])
        self.assertTrue(
            contract["runtime_probe_contract"]["srcq_rg_model_pagination_round_trip"]
        )
        self.assertIn(
            "ast-grep",
            contract["runtime_probe_contract"]["base_cli_exact_identity_probes"],
        )
        self.assertTrue(contract["runtime_probe_contract"]["tool_probe_manifest_hash_pinned"])
        self.assertIn("pnpm", contract["runtime_identity_contract"]["task_toolchains"]["package_managers"])
        self.assertIn("vscode-lsp-mcp", {
            item["capability"] for item in contract["separate_evidence_owners"]
        })
        self.assertIn("host-mcp", contract["excluded_from_swe"])
        self.assertIn("external-network", contract["excluded_from_swe"])
        self.assertEqual(configured["sandbox"]["implementation"], "elevated")

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
        node_task = next(
            task for task in self.corpus["tasks"] if task["toolchain"]["kind"] == "node"
        )
        python_hint = agentbase_codex.candidate_public_tooling_hint(python_task)
        node_hint = agentbase_codex.candidate_public_tooling_hint(node_task)
        self.assertIn(".agentbase-venv\\Scripts\\python.exe", python_hint)
        self.assertIn("identity-pinned dependencies", python_hint)
        self.assertIn(str(node_task["toolchain"]["package_manager"]), node_hint)
        self.assertIn("node_modules", node_hint)
        bandit_task = next(
            task
            for task in self.corpus["tasks"]
            if task["id"] == "bandit-interprocedural-taint-checks"
        )
        meriyah_task = next(
            task
            for task in self.corpus["tasks"]
            if task["id"] == "meriyah-explicit-resource-declarations"
        )
        self.assertIn("setup.cfg", agentbase_codex.candidate_patch_scope_hint(bandit_task))
        self.assertIn(
            "test/parser/miscellaneous/__snapshots__/**",
            agentbase_codex.candidate_patch_scope_hint(meriyah_task),
        )
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
        self.assertIn("tests/test_result/test_result_bind.py", public_checks)
        self.assertIn("safe.directory=", public_checks)
        self.assertIn(
            f"safe.directory={workspace.as_posix()}",
            public_checks,
        )
        self.assertIn("run each relevant listed regression command once", public_checks)
        self.assertNotIn("{report}", public_checks)
        self.assertNotIn("--junitxml", public_checks)
        self.assertNotIn("tests/test_validated", public_checks)
        sql_task = next(
            task
            for task in self.corpus["tasks"]
            if task["id"] == "sql-formatter-bigquery-pipe-formatting"
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            node_checks = agentbase_codex.candidate_public_checks_hint(
                sql_task,
                {
                    "python": "python.exe",
                    "workspace": str(workspace),
                    "npm": "npm.cmd",
                    "pnpm": "pnpm.cmd",
                },
                workspace,
            )
        self.assertIn("node_modules", node_checks)
        self.assertNotIn("bigquery-pipe.test.ts", node_checks)
        self.assertNotIn("--json", node_checks)
        self.assertNotIn("--outputFile", node_checks)

    def test_tool_probe_manifest_pins_exact_base_and_task_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_tools: dict[str, object] = {"tools": {}}
            runtime_map = runtime_tools["tools"]
            self.assertIsInstance(runtime_map, dict)
            base_paths: dict[str, Path] = {}
            for name in agentbase_codex.REQUIRED_CANDIDATE_TOOLS:
                executable = root / f"base-{name}.cmd"
                executable.write_bytes(f"{name}\n".encode())
                base_paths[name] = executable
                runtime_map[name] = {
                    "path": str(executable),
                    "sha256": evaluation_core.sha256_file(executable),
                }
            task = next(
                item
                for item in self.corpus["tasks"]
                if item["toolchain"].get("package_manager") == "pnpm"
            )
            task_pnpm = root / "task-pnpm.cmd"
            task_pnpm.write_bytes(b"task pnpm\n")
            task_pnpm_runtime = root / "pnpm.exe"
            task_pnpm_runtime.write_bytes(b"task pnpm runtime\n")
            dependency_identity = {
                "tools": {
                    "node": {"sha256": evaluation_core.sha256_file(base_paths["node"])},
                    "pnpm": {"sha256": evaluation_core.sha256_file(task_pnpm)},
                    "pnpm-runtime": {
                        "sha256": evaluation_core.sha256_file(task_pnpm_runtime)
                    },
                }
            }
            manifest = agentbase_codex.candidate_tool_probe_manifest(
                runtime_tools,
                task=task,
                dependency_identity=dependency_identity,
                dependency_values={
                    "node": str(base_paths["node"]),
                    "pnpm": str(task_pnpm),
                    "pnpm_runtime": str(task_pnpm_runtime),
                },
            )
            probes = {item["id"]: item for item in manifest["probes"]}
            self.assertEqual(probes["task-pnpm"]["path"], str(task_pnpm.resolve()))
            self.assertEqual(
                probes["task-pnpm"]["sha256"],
                evaluation_core.sha256_file(task_pnpm),
            )
            self.assertEqual(probes["ast-grep"]["argv"], ["--version"])
            self.assertNotIn("task-node", probes)
            self.assertNotIn("task-pnpm-runtime", probes)
            self.assertEqual(
                probes["task-pnpm-workspace"]["argv"],
                ["list", "--depth", "0", "--json"],
            )
            first = agentbase_codex.stage_candidate_tool_probe_manifest(
                root / "first",
                runtime_tools,
                task=task,
                dependency_identity=dependency_identity,
                dependency_values={
                    "node": str(base_paths["node"]),
                    "pnpm": str(task_pnpm),
                    "pnpm_runtime": str(task_pnpm_runtime),
                },
            )
            second = agentbase_codex.stage_candidate_tool_probe_manifest(
                root / "second",
                runtime_tools,
                task=task,
                dependency_identity=dependency_identity,
                dependency_values={
                    "node": str(base_paths["node"]),
                    "pnpm": str(task_pnpm),
                    "pnpm_runtime": str(task_pnpm_runtime),
                },
            )
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["expected_tools"], second["expected_tools"])

            python_task = next(
                item for item in self.corpus["tasks"] if item["toolchain"]["kind"] == "python"
            )
            task_python = root / "task-python.exe"
            task_python.write_bytes(b"task python\n")
            python_manifest = agentbase_codex.candidate_tool_probe_manifest(
                runtime_tools,
                task=python_task,
                dependency_identity={
                    "tools": {
                        "python": {"sha256": evaluation_core.sha256_file(task_python)}
                    }
                },
                dependency_values={"python": str(task_python)},
            )
            self.assertIn("task-python", {item["id"] for item in python_manifest["probes"]})

    def test_effective_candidate_config_participates_in_run_identity(self) -> None:
        qualification = {"receipt_sha256": "a" * 64}
        dependency = {"identity_sha256": "b" * 64}
        common = {
            "project_root": PROJECT_ROOT,
            "corpus_path": CORPUS_PATH,
            "corpus": self.corpus,
            "task_id": self.corpus["tasks"][0]["id"],
            "profile_name": "sol",
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


class SandboxRuntimeLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = evaluation_core.load_corpus(CORPUS_PATH)

    def _codex_identity(self, path: Path) -> dict[str, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"codex runtime fixture\n")
        return {
            "schema": "agentbase.codex-cli-identity/v1",
            "path": str(path.resolve()),
            "sha256": evaluation_core.sha256_file(path),
            "version": "codex-cli fixture",
        }

    def test_protected_secret_directory_is_never_enumerated_by_runtime_checks(self) -> None:
        python_source = (EVALUATION_ROOT / "agentbase_codex.py").read_text(
            encoding="utf-8"
        )
        backend_check = python_source.split("def sandbox_backend_snapshot", 1)[1].split(
            "def _runtime_identity_payload", 1
        )[0]
        powershell_source = (EVALUATION_ROOT / "invoke_candidate.ps1").read_text(
            encoding="utf-8"
        )
        runtime_check = powershell_source.split(
            "function Get-AgentBaseSandboxRuntimeUse", 1
        )[1].split("function Invoke-AgentBaseCandidatePreflight", 1)[0]
        self.assertNotIn("rglob", backend_check)
        self.assertNotIn("iterdir", backend_check)
        self.assertNotIn("Get-ChildItem -LiteralPath $secretsRoot", runtime_check)

    def test_backend_runner_identity_accepts_versioned_and_legacy_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            versioned = materialize_fake_sandbox_backend(home)
            versioned_runner = home / ".sandbox-bin" / "codex-command-runner-0.148.0.exe"
            versioned_runner.rename(home / ".sandbox-bin" / "codex.exe")
            legacy = agentbase_codex.sandbox_backend_snapshot(home)
        self.assertEqual(
            versioned["sandbox_runners"][0]["name"],
            "codex-command-runner-0.148.0.exe",
        )
        self.assertEqual(legacy["sandbox_runners"][0]["name"], "codex.exe")

    def test_mutable_capability_sid_registry_does_not_change_backend_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            before = materialize_fake_sandbox_backend(home)
            registry_path = home / "cap_sid"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["workspace_by_cwd"]["c:/evaluation/workspace"] = (
                "S-1-5-21-9-10-11-12"
            )
            registry["writable_root_by_path"]["c:/evaluation/runtime-temp"] = (
                "S-1-5-21-13-14-15-16"
            )
            registry_path.write_text(
                json.dumps(registry, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            after = agentbase_codex.sandbox_backend_snapshot(home)
        self.assertEqual(before, after)
        self.assertNotIn("capability_sid_sha256", after)
        self.assertTrue(after["capability_sid_registry"]["mutable"])

    def test_command_start_errors_do_not_invalidate_the_prepared_backend(self) -> None:
        self.assertFalse(
            agentbase_codex.is_elevated_sandbox_runtime_rejection(
                "CreateProcessAsUserW failed: 2 (The system cannot find the file specified.)"
            )
        )
        self.assertFalse(
            agentbase_codex.is_sandbox_setup_approval_error(
                "CreateProcessAsUserW failed: 2"
            )
        )
        self.assertTrue(
            agentbase_codex.is_elevated_sandbox_runtime_rejection(
                "This command requires the elevated Windows sandbox backend"
            )
        )
        self.assertTrue(
            agentbase_codex.is_sandbox_setup_approval_error(
                "orchestrator_helper_launch_canceled"
            )
        )

    def test_controlled_home_sync_preserves_persistent_backend_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            installed = root / "installed"
            home, first = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            backend_before = materialize_fake_sandbox_backend(home)
            (home / "AGENTS.md").write_text("stale\n", encoding="utf-8")
            (home / "config.toml").write_text("stale = true\n", encoding="utf-8")
            home_again, second = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            backend_after = agentbase_codex.sandbox_backend_snapshot(home_again)
            actual = agentbase_codex.evaluation_runtime_home_controlled_identity(
                home_again
            )
        self.assertEqual(home, home_again)
        self.assertEqual(first["identity_sha256"], second["identity_sha256"])
        self.assertEqual(actual["identity_sha256"], second["identity_sha256"])
        self.assertEqual(backend_before, backend_after)

    def test_ready_state_binds_codex_and_backend_without_recording_secret_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            installed = root / "installed"
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            backend = materialize_fake_sandbox_backend(home)
            codex = self._codex_identity(root / "codex.exe")
            runtime_state = agentbase_codex.write_ready_sandbox_runtime_state(
                state,
                codex,
                backend,
            )
            status = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                codex,
            )
            state_text = evaluation_core.sandbox_runtime_state_path(state).read_text(
                encoding="utf-8"
            )
            changed_codex = dict(codex)
            changed_codex["sha256"] = "0" * 64
            changed_status = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                changed_codex,
            )
            secret_children = list((home / ".sandbox-secrets").iterdir())
        self.assertTrue(status["ready"])
        self.assertEqual(
            status["runtime_use"]["identity_sha256"],
            runtime_state["identity_sha256"],
        )
        self.assertTrue(backend["protected_secret_directory_present"])
        self.assertEqual(secret_children, [])
        self.assertNotIn(".sandbox-secrets", state_text)
        self.assertIn("codex-identity-changed", changed_status["reason_codes"])
        self.assertFalse(changed_status["ready"])

    def test_transient_cleanup_removes_auth_and_catalog_but_preserves_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                root / "state",
                root / "installed",
                self.corpus,
            )
            backend = materialize_fake_sandbox_backend(home)
            (home / "auth.json").write_text("temporary auth\n", encoding="utf-8")
            (home / "models-evaluation.json").write_text("{}\n", encoding="utf-8")
            cleanup = agentbase_codex.cleanup_evaluation_runtime_transients(home)
            transients_absent = agentbase_codex.evaluation_runtime_transients_absent(home)
            after = agentbase_codex.sandbox_backend_snapshot(home)
        self.assertEqual(cleanup, {"removed": 2, "clean": True})
        self.assertTrue(transients_absent)
        self.assertEqual(backend, after)

    def test_normal_runtime_preparation_blocks_before_any_codex_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self._codex_identity(root / "codex.exe")
            with mock.patch.object(
                agentbase_codex,
                "invoke_sandbox_setup",
            ) as setup:
                with self.assertRaisesRegex(
                    evaluation_core.PreconditionError,
                    "sandbox-setup explicitly",
                ):
                    agent_eval._prepare_ready_sandbox_runtime(
                        project_root=PROJECT_ROOT,
                        state_root=root / "state",
                        installed_codex_root=root / "installed",
                        corpus=self.corpus,
                        codex_identity=codex,
                    )
            setup.assert_not_called()

    def test_sandbox_status_is_read_only_and_never_invokes_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            codex = self._codex_identity(root / "codex.exe")
            args = agent_eval.build_parser().parse_args(
                [
                    "sandbox-status",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )
            with (
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(agent_eval, "invoke_sandbox_setup") as setup,
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_status(args), 0)
            document = json.loads(printer.call_args.args[0])
            state_exists = state.exists()
        setup.assert_not_called()
        self.assertEqual(document["status"], "setup-required")
        self.assertFalse(document["external_actions"]["sandbox_process_launched"])
        self.assertFalse(state_exists)

    def test_explicit_setup_is_reused_without_a_second_setup_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            installed.mkdir()
            codex = self._codex_identity(root / "codex.exe")
            parser = agent_eval.build_parser()
            args = parser.parse_args(
                [
                    "sandbox-setup",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )

            def fake_setup(**kwargs: object) -> dict[str, object]:
                materialize_fake_sandbox_backend(Path(str(kwargs["codex_home"])))
                return {
                    "schema": agentbase_codex.SANDBOX_SETUP_RESULT_SCHEMA,
                    "passed": True,
                    "setup_invoked": True,
                    "model_invoked": False,
                    "exit_code": 0,
                    "duration_seconds": 0.1,
                    "diagnostic": None,
                }

            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(
                    agent_eval,
                    "invoke_sandbox_setup",
                    side_effect=fake_setup,
                ) as setup,
                mock.patch("builtins.print"),
            ):
                self.assertEqual(agent_eval.command_sandbox_setup(args), 0)
                self.assertEqual(agent_eval.command_sandbox_setup(args), 0)
                agentbase_codex.invalidate_sandbox_runtime(
                    state,
                    "fixture-invalidated",
                )
                self.assertEqual(agent_eval.command_sandbox_setup(args), 0)
            self.assertEqual(setup.call_count, 2)
            self.assertEqual(
                list(evaluation_core.sandbox_runtime_root(state).glob("setup-*")),
                [],
            )
            self.assertEqual(list(work.glob("sandbox-setup-*")), [])

    def test_explicit_setup_refreshes_legacy_mutable_state_without_uac(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            installed.mkdir()
            codex = self._codex_identity(root / "codex.exe")
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            materialize_fake_sandbox_backend(home)
            legacy = legacy_sandbox_backend_snapshot(home)
            agentbase_codex.write_ready_sandbox_runtime_state(state, codex, legacy)
            registry_path = home / "cap_sid"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["workspace_by_cwd"]["c:/evaluation/new-workspace"] = (
                "S-1-5-21-17-18-19-20"
            )
            registry_path.write_text(
                json.dumps(registry, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            before = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                codex,
            )
            args = agent_eval.build_parser().parse_args(
                [
                    "sandbox-setup",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(agent_eval, "invoke_sandbox_setup") as setup,
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_setup(args), 0)
            document = json.loads(printer.call_args.args[0])
            after = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                codex,
            )
        self.assertFalse(before["ready"])
        self.assertEqual(
            before["reason_codes"],
            ["sandbox-runtime-state-refresh-required"],
        )
        self.assertTrue(before["checks"]["runtime_state_refreshable"])
        setup.assert_not_called()
        self.assertFalse(document["setup_invoked"])
        self.assertTrue(document["runtime_state_refreshed"])
        self.assertTrue(document["reused_existing_runtime"])
        self.assertTrue(after["ready"])

    def test_setup_failure_invalidates_runtime_and_removes_attempt_scoped_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            installed.mkdir()
            codex = self._codex_identity(root / "codex.exe")
            args = agent_eval.build_parser().parse_args(
                [
                    "sandbox-setup",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(
                    agent_eval,
                    "invoke_sandbox_setup",
                    side_effect=evaluation_core.EvaluationError("fixture setup failure"),
                ),
            ):
                with self.assertRaisesRegex(
                    evaluation_core.EvaluationError,
                    "fixture setup failure",
                ):
                    agent_eval.command_sandbox_setup(args)
            runtime_state = agentbase_codex.validate_sandbox_runtime_state(
                evaluation_core.read_json(
                    evaluation_core.sandbox_runtime_state_path(state)
                )
            )
            self.assertEqual(runtime_state["status"], "invalidated")
            self.assertEqual(
                runtime_state["invalidated_reason_code"],
                "explicit-sandbox-setup-failed",
            )
            self.assertEqual(
                list(evaluation_core.sandbox_runtime_root(state).glob("setup-*")),
                [],
            )
            self.assertEqual(list(work.glob("sandbox-setup-*")), [])

    def test_post_setup_cleanup_failure_preserves_a_refreshable_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            installed.mkdir()
            codex = self._codex_identity(root / "codex.exe")
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            backend = materialize_fake_sandbox_backend(home)
            agentbase_codex.write_ready_sandbox_runtime_state(
                state,
                codex,
                backend,
            )
            invalidated = agentbase_codex.invalidate_sandbox_runtime(
                state,
                "explicit-sandbox-setup-cleanup-failed",
            )
            args = agent_eval.build_parser().parse_args(
                [
                    "sandbox-setup",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )
            before = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                codex,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(agent_eval, "invoke_sandbox_setup") as setup,
                mock.patch("builtins.print"),
            ):
                self.assertEqual(agent_eval.command_sandbox_setup(args), 0)
            after = agentbase_codex.sandbox_runtime_status(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
                codex,
            )
        self.assertEqual(
            invalidated["invalidated_reason_code"],
            "explicit-sandbox-setup-cleanup-failed",
        )
        self.assertTrue(before["checks"]["runtime_state_refreshable"])
        setup.assert_not_called()
        self.assertTrue(after["ready"])

    def test_setup_approval_cancellation_is_structured_and_never_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            work = root / "work"
            installed = root / "installed"
            installed.mkdir()
            codex = self._codex_identity(root / "codex.exe")
            args = agent_eval.build_parser().parse_args(
                [
                    "sandbox-setup",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state),
                    "--work-root",
                    str(work),
                    "--installed-codex-root",
                    str(installed),
                    "--view",
                    "machine",
                ]
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"},
                ),
                mock.patch.object(
                    agent_eval,
                    "_resolve_current_codex_identity",
                    return_value=codex,
                ),
                mock.patch.object(
                    agent_eval,
                    "invoke_sandbox_setup",
                    side_effect=evaluation_core.SandboxSetupApprovalError(
                        "fixture approval canceled"
                    ),
                ) as setup,
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_setup(args), 3)
            document = json.loads(printer.call_args.args[0])
            self.assertEqual(setup.call_count, 1)
            self.assertEqual(document["status"], "blocked-precondition")
            self.assertTrue(document["setup_invoked"])
            self.assertFalse(document["setup_completed"])
            self.assertFalse(
                document["external_actions"]["administrator_approval_completed"]
            )
            self.assertEqual(
                document["blocking_precondition"]["reason_code"],
                "windows-sandbox-administrator-approval-not-completed",
            )
            self.assertEqual(
                list(evaluation_core.sandbox_runtime_root(state).glob("setup-*")),
                [],
            )
            self.assertEqual(list(work.glob("sandbox-setup-*")), [])

    def test_conditional_invalidation_does_not_overwrite_a_newer_ready_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                root / "installed",
                self.corpus,
            )
            backend = materialize_fake_sandbox_backend(home)
            old = agentbase_codex.write_ready_sandbox_runtime_state(
                state,
                self._codex_identity(root / "old-codex.exe"),
                backend,
            )
            current = agentbase_codex.write_ready_sandbox_runtime_state(
                state,
                self._codex_identity(root / "current-codex.exe"),
                backend,
            )
            observed = agentbase_codex.invalidate_sandbox_runtime(
                state,
                "stale-rejection",
                expected_identity_sha256=str(old["identity_sha256"]),
            )
            persisted = agentbase_codex.validate_sandbox_runtime_state(
                evaluation_core.read_json(
                    evaluation_core.sandbox_runtime_state_path(state)
                )
            )
        self.assertEqual(observed, current)
        self.assertEqual(persisted, current)
        self.assertEqual(persisted["status"], "ready")

    def test_candidate_and_verifier_reuse_one_ready_runtime_without_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            installed = root / "installed"
            home, _ = agentbase_codex.sync_evaluation_runtime_home(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            backend = materialize_fake_sandbox_backend(home)
            codex = self._codex_identity(root / "codex.exe")
            agentbase_codex.write_ready_sandbox_runtime_state(
                state,
                codex,
                backend,
            )
            with mock.patch.object(agent_eval, "invoke_sandbox_setup") as setup:
                first_home, first_runtime, _ = agent_eval._prepare_ready_sandbox_runtime(
                    project_root=PROJECT_ROOT,
                    state_root=state,
                    installed_codex_root=installed,
                    corpus=self.corpus,
                    codex_identity=codex,
                )
                second_home, second_runtime, _ = agent_eval._prepare_ready_sandbox_runtime(
                    project_root=PROJECT_ROOT,
                    state_root=state,
                    installed_codex_root=installed,
                    corpus=self.corpus,
                    codex_identity=codex,
                )
                windows_verifier._assert_sandbox_runtime_reusable(
                    second_home,
                    second_runtime,
                    full_backend_check=True,
                )
            setup.assert_not_called()
        self.assertEqual(first_home, second_home)
        self.assertEqual(first_runtime, second_runtime)


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
                            "task_id": "returns-validated-error-accumulation",
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
                {"returns-validated-error-accumulation"},
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

    def test_sandbox_child_executable_requires_an_existing_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "tool.exe"
            executable.write_bytes(b"fixture\n")
            self.assertEqual(
                windows_verifier._absolute_sandbox_child_argv(
                    [str(executable.resolve()), "--version"]
                ),
                [str(executable.resolve()), "--version"],
            )
            with self.assertRaisesRegex(
                evaluation_core.EvaluationError,
                "must use an absolute path",
            ):
                windows_verifier._absolute_sandbox_child_argv(["tool.exe"])
            with self.assertRaisesRegex(
                evaluation_core.EvaluationError,
                "is not a file",
            ):
                windows_verifier._absolute_sandbox_child_argv(
                    [str((Path(directory) / "missing.exe").resolve())]
                )

    def test_all_nine_tasks_stage_sandbox_reports_inside_the_workspace(self) -> None:
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
                sandbox_reports = workspace / ".agentbase-verifier" / "reports"
                observed_argv: list[list[str]] = []
                observed_environments: list[dict[str, str]] = []

                def fake_sandboxed_check(**kwargs: object) -> dict[str, object]:
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
                        output = sandbox_reports / report["path"]
                        raw = sandbox_reports / report.get("raw_path", report["path"])
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
                    "_run_sandboxed_check",
                    side_effect=fake_sandboxed_check,
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
                        codex_executable=root / "codex.exe",
                        codex_home=root / "codex-home",
                        sandbox_runtime=make_sandbox_runtime_use_receipt(),
                        permission_profile="agentbase_verifier",
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
                    f"{task['id']} left a sandbox executable on PATH lookup",
                )
                for check in task["checks"]:
                    report_path = artifact / "reports" / check["report"]["path"]
                    self.assertTrue(
                        report_path.is_file(),
                        f"{task['id']} did not materialize {check['id']}",
                    )
                    if check["report"]["kind"] != "gate-ctrf":
                        sandbox_raw = sandbox_reports / check["report"].get(
                            "raw_path", check["report"]["path"]
                        )
                        self.assertTrue(
                            any(
                                any(str(sandbox_raw) in argument for argument in argv)
                                for argv in observed_argv
                            ),
                            f"{task['id']} passed no workspace-local report path",
                        )
                    self.assertFalse(
                        any(
                            any(str(report_path) in argument for argument in argv)
                            for argv in observed_argv
                        ),
                        f"{task['id']} exposed the trusted artifact path to the sandbox",
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

    @unittest.skipUnless(os.name == "nt", "candidate runtime cleanup is Windows-only")
    def test_candidate_cleanup_runner_uses_staged_script_and_removes_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            metadata = workspace / ".agentbase"
            metadata.mkdir(parents=True)
            cleanup_script = metadata / "runtime-cleanup.ps1"
            shutil.copy2(
                EVALUATION_ROOT / "sandbox_runtime_cleanup.ps1",
                cleanup_script,
            )
            attempt_root = root / "attempt"
            runtime_temp = attempt_root / "runtime-temp"
            child = runtime_temp / "home" / "nested"
            child.mkdir(parents=True)
            (child / "value.txt").write_text("temporary\n", encoding="utf-8")
            codex = root / "codex.exe"
            codex.write_bytes(b"fixture\n")
            pwsh_value = shutil.which("pwsh.exe")
            self.assertIsNotNone(pwsh_value)
            pwsh = Path(str(pwsh_value)).resolve()

            def run_cleanup(argv, **_kwargs):
                self.assertIn("agentbase_candidate", argv)
                separator = argv.index("--")
                child_argv = argv[separator + 1 :]
                self.assertEqual(child_argv[-1], "Candidate")
                return subprocess.run(
                    child_argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

            with mock.patch.object(
                agentbase_codex,
                "run_capture",
                side_effect=run_cleanup,
            ):
                receipt = agentbase_codex.cleanup_candidate_runtime_temp(
                    workspace=workspace,
                    attempt_root=attempt_root,
                    runtime_temp=runtime_temp,
                    codex_home=root / "codex-home",
                    codex_executable_path=codex,
                    pwsh_executable_path=pwsh,
                    expected_pwsh_sha256=evaluation_core.sha256_file(pwsh),
                    cleanup_script_path=cleanup_script,
                    expected_cleanup_script_sha256=evaluation_core.sha256_file(
                        cleanup_script
                    ),
                    permission_profile="agentbase_candidate",
                    process_environment=os.environ,
                )
            self.assertTrue(receipt["passed"])
            self.assertTrue(receipt["root_removed"])
            self.assertFalse(runtime_temp.exists())

    @unittest.skipUnless(os.name == "nt", "sandbox runtime cleanup is Windows-only")
    def test_sandbox_runtime_cleanup_is_exact_and_leaves_the_root_empty(self) -> None:
        script = EVALUATION_ROOT / "sandbox_runtime_cleanup.ps1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            runtime_temp = workspace / ".agentbase-verifier" / "runtime-temp"
            child = runtime_temp / "nested"
            child.mkdir(parents=True)
            (child / "value.txt").write_text("temporary\n", encoding="utf-8")
            accepted = subprocess.run(
                [
                    "pwsh.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script),
                    "-WorkspaceRoot",
                    str(workspace),
                    "-RuntimeTempPath",
                    str(runtime_temp),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(list(runtime_temp.iterdir()), [])

            attempt_root = root / "attempt"
            candidate_temp = attempt_root / "runtime-temp"
            private_child = candidate_temp / "home" / "AppData" / "Local"
            private_child.mkdir(parents=True)
            readonly = private_child / "telemetry.uuid"
            readonly.write_text("temporary\n", encoding="utf-8")
            readonly.chmod(stat.S_IREAD)
            candidate = subprocess.run(
                [
                    "pwsh.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script),
                    "-OwnerRoot",
                    str(attempt_root),
                    "-RuntimeTempPath",
                    str(candidate_temp),
                    "-Scope",
                    "Candidate",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(candidate.returncode, 0, candidate.stderr)
            self.assertEqual(list(candidate_temp.iterdir()), [])

            outside = root / "outside"
            outside.mkdir()
            (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
            rejected = subprocess.run(
                [
                    "pwsh.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script),
                    "-WorkspaceRoot",
                    str(workspace),
                    "-RuntimeTempPath",
                    str(outside),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertTrue((outside / "keep.txt").is_file())

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
        task = next(
            task
            for task in corpus["tasks"]
            if task["id"] == "httpx-multipart-response-parsing"
        )
        events: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "artifact"
            artifact.mkdir()

            def fake_checks(**kwargs: object) -> list[dict[str, object]]:
                events.append("checks")
                runtime_temp = (
                    Path(str(kwargs["workspace"]))
                    / ".agentbase-verifier"
                    / "runtime-temp"
                )
                runtime_temp.mkdir(parents=True)
                (runtime_temp / "transient.txt").write_text(
                    "transient\n",
                    encoding="utf-8",
                )
                return []

            def fake_runtime_cleanup(**kwargs: object) -> None:
                events.append("sandbox-cleanup")
                runtime_temp = (
                    Path(str(kwargs["workspace"]))
                    / ".agentbase-verifier"
                    / "runtime-temp"
                )
                (runtime_temp / "transient.txt").unlink()
                runtime_temp.rmdir()

            with (
                mock.patch.object(windows_verifier, "create_workspace", side_effect=lambda *a, **k: events.append("workspace") or workspace),
                mock.patch.object(windows_verifier, "prepare_dependencies", side_effect=lambda *a, **k: events.append("setup") or ({"identity_sha256": "d" * 64}, {})),
                mock.patch.object(
                    windows_verifier,
                    "apply_windows_adapter_baseline",
                    side_effect=lambda *a, **k: events.append("adapter")
                    or {
                        "path": "windows-adapters/httpx-ephemeral-loopback.patch",
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
                    side_effect=lambda *a, **k: events.append("scope") or ["src/value.py"],
                ),
                mock.patch.object(
                    windows_verifier,
                    "evaluation_runtime_home_controlled_identity",
                    return_value={"identity_sha256": "e" * 64},
                ),
                mock.patch.object(
                    windows_verifier,
                    "_assert_sandbox_runtime_reusable",
                    side_effect=lambda *a, **k: events.append("runtime"),
                ),
                mock.patch.object(
                    windows_verifier,
                    "run_checks",
                    side_effect=fake_checks,
                ),
                mock.patch.object(
                    windows_verifier,
                    "grade_reports",
                    side_effect=lambda *a, **k: events.append("grade") or {
                        "reward": {"reward": 1},
                        "grader_sha256": task["assets"]["tests/grader.py"],
                    },
                ),
                mock.patch.object(
                    windows_verifier,
                    "_cleanup_sandbox_runtime_temp",
                    side_effect=fake_runtime_cleanup,
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
                    codex_executable=root / "codex.exe",
                    pwsh_executable=root / "pwsh.exe",
                    codex_home=root / "home",
                    sandbox_runtime=make_sandbox_runtime_use_receipt(),
                    retain_workspace=True,
                )
            verifier_runtime_temp_removed = not (
                workspace / ".agentbase-verifier" / "runtime-temp"
            ).exists()
        self.assertEqual(
            events,
            [
                "workspace",
                "setup",
                "adapter",
                "patch",
                "scope",
                "patch",
                "runtime",
                "checks",
                "grade",
                "sandbox-cleanup",
            ],
        )
        self.assertEqual(result["patch_kind"], "reference")
        self.assertTrue(verifier_runtime_temp_removed)
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
        args = parser.parse_args(["validate", "--project-root", str(PROJECT_ROOT), "--view", "machine"])
        with mock.patch("builtins.print") as printer:
            self.assertEqual(agent_eval.command_validate(args), 0)
        document = json.loads(printer.call_args.args[0])
        self.assertFalse(document["external_actions"])

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

    def test_sandbox_check_stages_fake_auth_and_removes_ephemeral_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            work_root = root / "work"
            installed_root = root / "installed-codex"
            installed_root.mkdir()
            (installed_root / "auth.json").write_text("test auth\n", encoding="utf-8")
            parser = agent_eval.build_parser()
            args = parser.parse_args(
                [
                    "sandbox-check",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state_root),
                    "--work-root",
                    str(work_root),
                    "--installed-codex-root",
                    str(installed_root),
                    "--view",
                    "machine",
                ]
            )

            def fake_preflight(**kwargs: object) -> dict[str, object]:
                denied_auth = Path(str(kwargs["denied_auth_path"]))
                self.assertEqual(
                    Path(str(kwargs["installed_codex_root"])),
                    installed_root.resolve(),
                )
                skill_root = Path(str(kwargs["skill_root_path"]))
                self.assertEqual(
                    denied_auth.read_text(encoding="utf-8"),
                    "agentbase-fake-auth-canary-no-credentials\n",
                )
                self.assertTrue((skill_root / "source-query" / "SKILL.md").is_file())
                skill_manifest = Path(str(kwargs["skill_probe_manifest_path"]))
                self.assertEqual(
                    evaluation_core.sha256_file(skill_manifest),
                    kwargs["expected_skill_probe_manifest_sha256"],
                )
                tool_manifest = Path(str(kwargs["tool_probe_manifest_path"]))
                self.assertEqual(
                    evaluation_core.sha256_file(tool_manifest),
                    kwargs["expected_tool_probe_manifest_sha256"],
                )
                expected_tool_probes = kwargs["expected_tool_probes"]
                self.assertIsInstance(expected_tool_probes, dict)
                sandbox_environment = kwargs["process_environment"]
                self.assertNotIn("OPENAI_API_KEY", sandbox_environment)
                self.assertNotIn("GITHUB_TOKEN", sandbox_environment)
                self.assertNotIn("CODEX_HOME", sandbox_environment)
                preflight = make_preflight_receipt(
                    skill_manifest_sha256=str(
                        kwargs["expected_skill_probe_manifest_sha256"]
                    ),
                    skill_file_count=int(kwargs["expected_skill_file_count"]),
                    tool_manifest_sha256=str(
                        kwargs["expected_tool_probe_manifest_sha256"]
                    ),
                    tool_probes=expected_tool_probes,
                )
                return {
                    "schema": "agentbase.windows-swe-sandbox-check/v5",
                    "status": "passed",
                    "passed": True,
                    "permission_profile": "agentbase_candidate",
                    "duration_seconds": 0.1,
                    "codex": {"version": "codex-cli test"},
                    "sandbox_runtime": dict(kwargs["sandbox_runtime"]),
                    "preflight": preflight,
                }

            with (
                mock.patch.object(
                    agent_eval,
                    "candidate_runtime_tools",
                    side_effect=fake_candidate_runtime_tools,
                ),
                mock.patch.object(
                    agent_eval,
                    "get_sandbox_runtime_status",
                    side_effect=fake_ready_sandbox_status,
                ),
                mock.patch.object(agent_eval, "invoke_candidate_preflight", side_effect=fake_preflight),
                mock.patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "ambient-secret",
                        "GITHUB_TOKEN": "ambient-secret",
                        "CODEX_HOME": "D:/ambient-codex-home",
                    },
                    clear=False,
                ),
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_check(args), 0)
            document = json.loads(printer.call_args.args[0])
            self.assertTrue(document["passed"])
            self.assertTrue(document["temporary_assets_removed"])
            self.assertFalse(document["external_actions"]["model_invoked"])
            self.assertFalse(
                document["external_actions"]["host_sandbox_setup_may_be_requested"]
            )
            self.assertTrue(
                (evaluation_core.sandbox_runtime_home(state_root) / "config.toml").is_file()
            )
            self.assertFalse(
                (evaluation_core.sandbox_runtime_home(state_root) / "auth.json").exists()
            )
            self.assertEqual(list(state_root.glob("sandbox-check-*")), [])
            self.assertEqual(list(work_root.glob("sandbox-check-*")), [])

    def test_sandbox_check_blocks_before_launch_when_explicit_setup_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            work_root = root / "work"
            installed_root = root / "installed-codex"
            installed_root.mkdir()
            (installed_root / "auth.json").write_text("test auth\n", encoding="utf-8")
            parser = agent_eval.build_parser()
            args = parser.parse_args(
                [
                    "sandbox-check",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state_root),
                    "--work-root",
                    str(work_root),
                    "--installed-codex-root",
                    str(installed_root),
                    "--view",
                    "machine",
                ]
            )
            unready = {
                "schema": agentbase_codex.SANDBOX_RUNTIME_STATUS_SCHEMA,
                "status": "setup-required",
                "ready": False,
                "checks": {},
                "reason_codes": ["setup-state-missing-or-invalid"],
                "runtime_use": None,
                "recovery_action": "run sandbox-setup explicitly",
            }
            with (
                mock.patch.object(
                    agent_eval,
                    "candidate_runtime_tools",
                    side_effect=fake_candidate_runtime_tools,
                ),
                mock.patch.object(
                    agent_eval,
                    "get_sandbox_runtime_status",
                    return_value=unready,
                ),
                mock.patch.object(agent_eval, "invoke_candidate_preflight") as preflight,
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_check(args), 3)
            preflight.assert_not_called()
            document = json.loads(printer.call_args.args[0])
            self.assertEqual(document["status"], "blocked-precondition")
            self.assertFalse(document["passed"])
            self.assertIsNone(document["runtime_probe"])
            self.assertEqual(
                document["blocking_precondition"]["reason_code"],
                "windows-elevated-sandbox-setup-required",
            )
            self.assertTrue(document["temporary_assets_removed"])
            self.assertEqual(list(state_root.glob("sandbox-check-*")), [])
            self.assertEqual(list(work_root.glob("sandbox-check-*")), [])

    def test_sandbox_check_reports_real_acceptance_failures_without_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            work_root = root / "work"
            installed_root = root / "installed-codex"
            installed_root.mkdir()
            (installed_root / "auth.json").write_text("test auth\n", encoding="utf-8")
            parser = agent_eval.build_parser()
            args = parser.parse_args(
                [
                    "sandbox-check",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--state-root",
                    str(state_root),
                    "--work-root",
                    str(work_root),
                    "--installed-codex-root",
                    str(installed_root),
                    "--view",
                    "machine",
                ]
            )

            def failed_preflight(**kwargs: object) -> dict[str, object]:
                expected_tool_probes = kwargs["expected_tool_probes"]
                self.assertIsInstance(expected_tool_probes, dict)
                preflight = make_preflight_receipt(
                    skill_manifest_sha256=str(
                        kwargs["expected_skill_probe_manifest_sha256"]
                    ),
                    skill_file_count=int(kwargs["expected_skill_file_count"]),
                    tool_manifest_sha256=str(
                        kwargs["expected_tool_probe_manifest_sha256"]
                    ),
                    tool_probes=expected_tool_probes,
                    passed=False,
                )
                preflight["tool_probes"]["hyperfine"]["exit_code"] = 1
                return {
                    "schema": "agentbase.windows-swe-sandbox-check/v5",
                    "status": "failed",
                    "passed": False,
                    "duration_seconds": 0.1,
                    "sandbox_runtime": dict(kwargs["sandbox_runtime"]),
                    "preflight": preflight,
                }

            with (
                mock.patch.object(
                    agent_eval,
                    "candidate_runtime_tools",
                    side_effect=fake_candidate_runtime_tools,
                ),
                mock.patch.object(
                    agent_eval,
                    "get_sandbox_runtime_status",
                    side_effect=fake_ready_sandbox_status,
                ),
                mock.patch.object(
                    agent_eval,
                    "invoke_candidate_preflight",
                    side_effect=failed_preflight,
                ),
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_check(args), 2)
            document = json.loads(printer.call_args.args[0])
            self.assertEqual(document["status"], "failed")
            self.assertEqual(document["failure"]["failed_checks"], ["tool:hyperfine"])
            self.assertIsNone(document["blocking_precondition"])
            self.assertTrue(document["temporary_assets_removed"])

    def test_sandbox_check_does_not_downgrade_unknown_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed_root = root / "installed-codex"
            installed_root.mkdir()
            (installed_root / "auth.json").write_text("test auth\n", encoding="utf-8")
            corpus = evaluation_core.load_corpus(CORPUS_PATH)
            with mock.patch.object(
                agent_eval,
                "candidate_runtime_tools",
                side_effect=fake_candidate_runtime_tools,
            ), mock.patch.object(
                agent_eval,
                "get_sandbox_runtime_status",
                side_effect=fake_ready_sandbox_status,
            ), mock.patch.object(
                agent_eval,
                "invoke_candidate_preflight",
                side_effect=evaluation_core.EvaluationError("unexpected receipt corruption"),
            ):
                with self.assertRaisesRegex(
                    evaluation_core.EvaluationError,
                    "unexpected receipt corruption",
                ):
                    agent_eval.build_sandbox_assessment(
                        project_root=PROJECT_ROOT,
                        state_root=root / "state",
                        work_root=root / "work",
                        installed_codex_root=installed_root,
                        corpus=corpus,
                    )

    def test_final_assessment_keeps_dimensions_and_pending_evidence_separate(self) -> None:
        corpus = evaluation_core.load_corpus(CORPUS_PATH)
        capabilities = agentbase_codex.candidate_capability_contract(PROJECT_ROOT, corpus)
        native = {
            "schema": "agentbase.native-validation/v2",
            "status": "passed",
            "passed": True,
            "duration_seconds": 2.0,
            "validation": {"action": "Validate"},
            "diagnostic": None,
        }
        sandbox = {
            "schema": "agentbase.windows-swe-sandbox-assessment/v5",
            "status": "passed",
            "passed": True,
            "duration_seconds": 0.5,
            "runtime_probe": {"duration_seconds": 0.5},
            "capability_contract": capabilities,
        }
        routing = {
            "status": "current",
            "current_cycle_attempts": {
                "failures": 0,
                "total_tokens": 10,
                "cached_input_tokens": 2,
            },
        }
        swe = {
            "summary": {
                "qualified_tasks": 0,
                "task_count": 9,
                "static_current_runs": 0,
                "expected_runs": 18,
            },
            "cost_and_time": {
                "known_total_tokens": 3,
                "known_cached_input_tokens": 1,
                "api_equivalent_cost": empty_api_cost_summary(),
            },
            "infrastructure_health": {
                "infrastructure_failed": 0,
                "cleanup_errors": 0,
                "current_identity_cost_and_time": {
                    "api_equivalent_cost": empty_api_cost_summary(),
                },
            },
            "candidate_capabilities": capabilities,
        }
        with (
            mock.patch.object(agent_eval, "_collect_native_validation", return_value=native),
            mock.patch.object(agent_eval, "build_sandbox_assessment", return_value=sandbox),
            mock.patch.object(agent_eval, "_collect_routing_assessment", return_value=routing),
            mock.patch.object(agent_eval, "build_swe_report", return_value=swe),
        ):
            result = agent_eval.build_final_assessment(
                project_root=PROJECT_ROOT,
                corpus_path=CORPUS_PATH,
                state_root=PROJECT_ROOT / ".test-state",
                work_root=PROJECT_ROOT / ".test-work",
                installed_codex_root=PROJECT_ROOT / ".test-installed-codex",
                corpus=corpus,
                suite="all",
                result_offset=0,
                result_limit=100,
                attempt_limit=20,
                codex_executable=None,
            )
        self.assertEqual(result["status"], "evidence-pending")
        self.assertIsNone(result["composite_score"])
        self.assertEqual(
            set(result["dimensions"]),
            set(corpus["assessment"]["dimensions"]),
        )
        self.assertEqual(result["dimensions"]["cost-and-time"]["known_total_tokens"], 13)
        self.assertEqual(result["installation_status"], "not-assessed")
        self.assertFalse(result["external_actions"]["model_invoked"])

    def test_final_assessment_preserves_failed_blocked_and_pending_dimensions(self) -> None:
        corpus = evaluation_core.load_corpus(CORPUS_PATH)
        capabilities = agentbase_codex.candidate_capability_contract(PROJECT_ROOT, corpus)
        native = {
            "schema": "agentbase.native-validation/v2",
            "status": "failed",
            "passed": False,
            "duration_seconds": 1.0,
            "validation": None,
            "diagnostic": "deterministic contract failure",
        }
        sandbox = {
            "schema": "agentbase.windows-swe-sandbox-assessment/v5",
            "status": "blocked-precondition",
            "passed": False,
            "duration_seconds": 0.2,
            "runtime_probe": None,
            "blocking_precondition": {
                "reason_code": "windows-elevated-sandbox-setup-required"
            },
            "capability_contract": capabilities,
        }
        routing = {
            "status": "current",
            "current_cycle_attempts": {
                "failures": 0,
                "total_tokens": 0,
                "cached_input_tokens": 0,
            },
        }
        swe = {
            "summary": {
                "qualified_tasks": 0,
                "task_count": 9,
                "static_current_runs": 0,
                "expected_runs": 18,
            },
            "cost_and_time": {
                "known_total_tokens": 0,
                "known_cached_input_tokens": 0,
                "api_equivalent_cost": empty_api_cost_summary(),
            },
            "infrastructure_health": {
                "infrastructure_failed": 0,
                "cleanup_errors": 0,
                "current_identity_cost_and_time": {
                    "api_equivalent_cost": empty_api_cost_summary(),
                },
            },
            "candidate_capabilities": capabilities,
        }
        with (
            mock.patch.object(agent_eval, "_collect_native_validation", return_value=native),
            mock.patch.object(agent_eval, "build_sandbox_assessment", return_value=sandbox),
            mock.patch.object(agent_eval, "_collect_routing_assessment", return_value=routing),
            mock.patch.object(agent_eval, "build_swe_report", return_value=swe),
        ):
            result = agent_eval.build_final_assessment(
                project_root=PROJECT_ROOT,
                corpus_path=CORPUS_PATH,
                state_root=PROJECT_ROOT / ".test-state",
                work_root=PROJECT_ROOT / ".test-work",
                installed_codex_root=PROJECT_ROOT / ".test-installed-codex",
                corpus=corpus,
                suite="all",
                result_offset=0,
                result_limit=100,
                attempt_limit=20,
                codex_executable=None,
            )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["evidence_state"]["failed_dimensions"], ["windows-native-contract"])
        self.assertEqual(
            result["evidence_state"]["blocked_dimensions"],
            ["candidate-verifier-isolation"],
        )
        self.assertEqual(
            result["evidence_state"]["pending_dimensions"],
            ["external-generalization-reward"],
        )


if __name__ == "__main__":
    unittest.main()
