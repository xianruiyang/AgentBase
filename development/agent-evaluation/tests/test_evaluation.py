from __future__ import annotations

import copy
import json
import os
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
        "schema": "agentbase.windows-swe-preflight/v9",
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
        "runtime_localappdata_attempt_scoped": True,
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

    def test_candidate_config_defaults_host_to_deny_and_keeps_workspace_runtime_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "held-out-state"
            installed = Path(directory) / "installed-codex"
            text, descriptor = agentbase_codex.build_candidate_config(
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
        self.assertNotIn("extends", config["permissions"][profile])
        self.assertFalse(config["permissions"][profile]["network"]["enabled"])
        self.assertEqual(config["shell_environment_policy"]["inherit"], "all")
        self.assertFalse(
            config["shell_environment_policy"]["ignore_default_excludes"]
        )
        self.assertFalse(
            config["shell_environment_policy"]["experimental_use_profile"]
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
        self.assertEqual(
            config["permissions"][profile]["filesystem"],
            {
                ":root": "deny",
                ":minimal": "read",
                ":tmpdir": "write",
                ":workspace_roots": {
                    ".": "write",
                    ".agents/skills": "read",
                    ".codex": "read",
                    ".git": "read",
                    "**/*.env": "deny",
                },
                str(PROJECT_ROOT.resolve()): "deny",
                str(state.resolve()): "deny",
                str(installed.resolve()): "deny",
            },
        )
        self.assertEqual(config["model_provider"], "agentbase_eval_http")
        self.assertFalse(config["model_providers"]["agentbase_eval_http"]["supports_websockets"])
        self.assertEqual(descriptor["identity"]["state_root_denied"], str(state.resolve()))
        self.assertEqual(
            descriptor["identity"]["installed_codex_root_denied"],
            str(installed.resolve()),
        )
        self.assertTrue(descriptor["identity"]["host_filesystem_default_denied"])
        self.assertTrue(descriptor["identity"]["minimal_runtime_readable"])
        self.assertEqual(
            descriptor["identity"]["project_root_denied"],
            str(PROJECT_ROOT.resolve()),
        )
        self.assertTrue(descriptor["identity"]["attempt_tmpdir_reopened"])
        self.assertTrue(descriptor["identity"]["process_appdata_scoped_to_tmpdir"])
        self.assertTrue(
            descriptor["identity"]["shell_environment_secret_filtered"]
        )
        shell_policy_descriptor, _ = codex_runtime.resolve_shell_environment_policy()
        self.assertEqual(
            descriptor["identity"]["shell_environment_policy_sha256"],
            shell_policy_descriptor["sha256"],
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
            first_text, first = agentbase_codex.build_candidate_config(
                PROJECT_ROOT,
                state,
                installed,
                self.corpus,
            )
            second_text, second = agentbase_codex.build_candidate_config(
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

    def test_verifier_config_has_no_model_or_network_authority(self) -> None:
        config = tomllib.loads(agentbase_codex.build_verifier_config(self.corpus))
        profile = self.corpus["codex"]["verifier_permission_profile"]
        self.assertEqual(config["default_permissions"], profile)
        self.assertFalse(config["permissions"][profile]["network"]["enabled"])
        self.assertEqual(config["windows"]["sandbox"], "elevated")
        self.assertFalse(config["features"]["multi_agent"])

    def test_candidate_launcher_uses_native_sandbox_command_and_model_catalog(self) -> None:
        text = (EVALUATION_ROOT / "invoke_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("$preflightArguments = @(\n        'sandbox',", text)
        self.assertNotIn("'sandbox', 'windows'", text)
        self.assertIn("'-P', $Profile", text)
        self.assertIn("'-SkillRootPath', $ResolvedSkillRoot", text)
        self.assertIn("'-SkillProbeManifestPath', $ResolvedSkillProbeManifest", text)
        self.assertIn("'-DeniedAuthPath', $ResolvedDeniedAuth", text)
        self.assertIn("'-InstalledAuthPath', $ResolvedInstalledAuth", text)
        self.assertIn("'-ProjectCanaryPath', $ResolvedProjectCanary", text)
        self.assertIn("'-RuntimeTempPath', $RuntimeTemp", text)
        self.assertIn("'-RuntimeAppDataPath', $RuntimeAppData", text)
        self.assertIn("'-RuntimeLocalAppDataPath', $RuntimeLocalAppData", text)
        self.assertIn("[string]$InstalledCodexRoot", text)
        self.assertIn("$authSource = $resolvedInstalledAuth", text)
        self.assertNotIn("$installedCodexRoot = Join-Path $env:USERPROFILE '.codex'", text)
        self.assertIn(
            "'-ExpectedSkillProbeManifestSha256', $ExpectedSkillProbeManifestSha256",
            text,
        )
        self.assertIn("'-ToolProbeManifestPath', $ResolvedToolProbeManifest", text)
        self.assertIn(
            "'-ExpectedToolProbeManifestSha256', $ExpectedToolProbeManifestSha256",
            text,
        )
        self.assertIn("'-WriteProbePath', ($ResolvedOutput + '.write-probe')", text)
        self.assertIn("-FailureResultPath $resolvedResult", text)
        self.assertIn(
            "$runtimeTemp = [IO.Path]::GetFullPath((Join-Path $attemptRuntimeRoot 'runtime-temp'))",
            text,
        )
        self.assertIn("$StartInfo.Environment['TMPDIR']", text)
        self.assertIn("$StartInfo.Environment['LOCALAPPDATA']", text)
        self.assertIn("Result path must be inside the denied state root", text)
        self.assertIn("Candidate prompt must be inside the denied state root", text)
        self.assertIn("model_invoked = $false", text)
        self.assertIn("-AllowFailedReceipt", text)
        self.assertIn("agentbase.windows-swe-sandbox-check/v3", text)
        self.assertIn("New-AgentBaseCodexModelCatalogProjection", text)
        self.assertIn("supports", (EVALUATION_ROOT / "codex-eval-overlay.toml").read_text(encoding="utf-8"))
        self.assertNotIn("WindowsApps\\codex.exe", text)
        self.assertNotIn("[string]$Home", text)
        verifier = (EVALUATION_ROOT / "windows_verifier.py").read_text(encoding="utf-8")
        self.assertNotIn('"sandbox",\n        "windows",', verifier)

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
                    installed_codex_root=PROJECT_ROOT / ".installed-codex",
                    corpus=self.corpus,
                    profile_name="sol",
                    metadata={},
                    process_environment={},
                    codex_executable_path=None,
                    timeout_seconds=60,
                )

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
            }
            attempt_root = root / "attempt"
            attempt_root.mkdir()
            (attempt_root / "codex-result.json").write_text(
                json.dumps(
                    {
                        "schema": "agentbase.windows-swe-codex-run/v3",
                        "status": "blocked-precondition",
                        "model_invoked": False,
                        "exit_code": None,
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
        self.assertIn("agentbase.windows-swe-preflight/v9", text)
        self.assertIn("-not $canaryReadable", text)
        self.assertIn("-not $authReadable", text)
        self.assertIn("-not $installedAuthReadable", text)
        self.assertIn("-not $projectCanaryReadable", text)
        self.assertIn("$skillProjectionReadable", text)
        self.assertIn("$skillFilesVerified -eq $skillFilesExpected", text)
        self.assertIn("$skillProjectionWriteDenied", text)
        self.assertIn("$workspaceWriteProbePassed", text)
        self.assertIn("$runtimeTempAttemptScoped", text)
        self.assertIn("$runtimeLocalAppDataAttemptScoped", text)
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
            runtime_localappdata = runtime_temp / "localappdata"
            runtime_temp.mkdir()
            runtime_appdata.mkdir()
            runtime_localappdata.mkdir()

            def run_preflight(*, mismatched_temp: bool = False) -> subprocess.CompletedProcess[str]:
                environment = os.environ.copy()
                for name in ("TEMP", "TMP", "TMPDIR"):
                    environment[name] = str(runtime_temp)
                environment["APPDATA"] = str(runtime_appdata)
                environment["LOCALAPPDATA"] = str(runtime_localappdata)
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
        self.assertEqual(configured["multi_agent"]["default_reasoning_effort"], "max")
        self.assertEqual(
            contract["projected_assets"]["custom_agents"]["sol"],
            {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
        )
        self.assertTrue(contract["projected_assets"]["skills"]["full_tree_hash_pinned"])
        self.assertTrue(contract["projected_assets"]["skills"]["projection_read_only"])
        self.assertTrue(configured["candidate_model_actions"]["apply_patch"])
        self.assertTrue(configured["candidate_model_actions"]["public_test_execution"])
        self.assertTrue(
            configured["candidate_model_actions"]["shell_environment_secret_filtered"]
        )
        shell_policy_descriptor, _ = codex_runtime.resolve_shell_environment_policy()
        self.assertEqual(
            configured["candidate_model_actions"]["shell_environment_policy_sha256"],
            shell_policy_descriptor["sha256"],
        )
        self.assertTrue(
            configured["candidate_model_actions"]["requires_candidate_model_evidence"]
        )
        self.assertIn("srcq", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertIn("hyperfine", contract["runtime_identity_contract"]["base_cli_tools"])
        self.assertTrue(contract["runtime_probe_contract"]["performed_before_candidate_model"])
        self.assertTrue(configured["sandbox"]["installed_codex_root_denied"])
        self.assertTrue(configured["sandbox"]["host_filesystem_default_denied"])
        self.assertTrue(configured["sandbox"]["minimal_runtime_readable"])
        self.assertTrue(configured["sandbox"]["project_root_denied"])
        self.assertTrue(configured["sandbox"]["attempt_tmpdir_only"])
        self.assertTrue(configured["sandbox"]["process_appdata_scoped_to_tmpdir"])
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
        self.assertEqual(configured["sandbox"]["implementation"], "elevated")

    def test_candidate_prompt_uses_the_prepared_runtime_and_corpus_patch_scope(self) -> None:
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
            dependency_identity = {
                "tools": {
                    "node": {"sha256": evaluation_core.sha256_file(base_paths["node"])},
                    "pnpm": {"sha256": evaluation_core.sha256_file(task_pnpm)},
                }
            }
            manifest = agentbase_codex.candidate_tool_probe_manifest(
                runtime_tools,
                task=task,
                dependency_identity=dependency_identity,
                dependency_values={
                    "node": str(base_paths["node"]),
                    "pnpm": str(task_pnpm),
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
            first = agentbase_codex.stage_candidate_tool_probe_manifest(
                root / "first",
                runtime_tools,
                task=task,
                dependency_identity=dependency_identity,
                dependency_values={
                    "node": str(base_paths["node"]),
                    "pnpm": str(task_pnpm),
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


class RuntimeRootBoundaryTests(unittest.TestCase):
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


class GitPatchBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git.exe", "init", str(self.root)], check=True, stdout=subprocess.DEVNULL)
        (self.root / "src").mkdir()
        (self.root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_value.py").write_text("assert True\n", encoding="utf-8")
        subprocess.run(["git.exe", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            [
                "git.exe",
                "-C",
                str(self.root),
                "-c",
                "user.name=AgentBase Test",
                "-c",
                "user.email=agentbase@example.invalid",
                "commit",
                "-m",
                "base",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        self.task = {"allowed_patch_paths": ["src/**"]}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_capture_includes_tracked_and_untracked_allowed_files(self) -> None:
        (self.root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
        (self.root / "src" / "new.py").write_text("NEW = True\n", encoding="utf-8")
        output = self.root / ".git" / "candidate.patch"
        result = evaluation_core.capture_candidate_patch(self.root, self.task, output)
        self.assertEqual(result["files"], ["src/new.py", "src/value.py"])
        self.assertGreater(result["bytes"], 0)
        self.assertEqual(result["sha256"], evaluation_core.sha256_file(output))

    def test_capture_rejects_test_or_manifest_changes(self) -> None:
        (self.root / "tests" / "test_value.py").write_text("assert False\n", encoding="utf-8")
        with self.assertRaisesRegex(evaluation_core.EvaluationError, "protected"):
            evaluation_core.capture_candidate_patch(
                self.root,
                self.task,
                self.root / ".git" / "candidate.patch",
            )

    def test_pinned_upstream_patch_repairs_only_blank_context_prefixes(self) -> None:
        target = self.root / "src" / "value.py"
        target.write_text("VALUE = 1\n\n", encoding="utf-8")
        subprocess.run(["git.exe", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            [
                "git.exe",
                "-C",
                str(self.root),
                "-c",
                "user.name=AgentBase Test",
                "-c",
                "user.email=agentbase@example.invalid",
                "commit",
                "-m",
                "blank baseline",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        patch = self.root / ".git" / "upstream.patch"
        patch.write_bytes(
            b"diff --git a/src/value.py b/src/value.py\n"
            b"--- a/src/value.py\n"
            b"+++ b/src/value.py\n"
            b"@@ -1,2 +1,2 @@\n"
            b"-VALUE = 1\n"
            b"+VALUE = 2\n"
            b"\n"
        )
        descriptor = evaluation_core.apply_git_patch(
            self.root,
            patch,
            normalize_upstream=True,
        )
        self.assertEqual(descriptor["blank_context_prefixes_inserted"], 1)
        self.assertNotEqual(descriptor["source_sha256"], descriptor["applied_sha256"])
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n\n")


class ReportAdapterTests(unittest.TestCase):
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
                mock.patch.object(windows_verifier, "create_workspace", side_effect=lambda *a, **k: events.append("workspace") or workspace),
                mock.patch.object(windows_verifier, "prepare_dependencies", side_effect=lambda *a, **k: events.append("setup") or ({"identity_sha256": "d" * 64}, {})),
                mock.patch.object(
                    windows_verifier,
                    "apply_git_patch",
                    side_effect=lambda *a, **k: events.append("patch")
                    or {
                        "source_sha256": "a" * 64,
                        "applied_sha256": "a" * 64,
                        "bytes": 1,
                        "blank_context_prefixes_inserted": 0,
                    },
                ),
                mock.patch.object(
                    windows_verifier,
                    "validate_staged_patch_scope",
                    side_effect=lambda *a, **k: events.append("scope") or ["src/value.py"],
                ),
                mock.patch.object(windows_verifier, "stage_verifier_home", side_effect=lambda *a, **k: events.append("home") or root / "home"),
                mock.patch.object(windows_verifier, "run_checks", side_effect=lambda *a, **k: events.append("checks") or []),
                mock.patch.object(
                    windows_verifier,
                    "grade_reports",
                    side_effect=lambda *a, **k: events.append("grade") or {
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
                    codex_executable=root / "codex.exe",
                    retain_workspace=True,
                )
        self.assertEqual(
            events,
            ["workspace", "setup", "patch", "scope", "patch", "home", "checks", "grade"],
        )
        self.assertEqual(result["patch_kind"], "reference")
        self.assertEqual(
            evaluation_core.validate_receipt(
                result,
                schema="agentbase.windows-swe-verifier-result/v1",
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
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            attempt_root = state / "attempts" / "attempt-1"
            attempt_root.mkdir(parents=True)
            (attempt_root / "attempt.json").write_text(
                json.dumps(
                    {
                        "attempt_id": "attempt-1",
                        "candidate_identity_sha256": "a" * 64,
                        "status": "infrastructure-failed",
                        "stage": "patch-captured",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(evaluation_core.PreconditionError, "recover --attempt-id"):
                evaluation_core.enforce_retry_policy(state, "a" * 64, "rerun")


class DeterministicEntryTests(unittest.TestCase):
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
                    "schema": "agentbase.windows-swe-sandbox-check/v3",
                    "status": "passed",
                    "passed": True,
                    "permission_profile": "agentbase_candidate",
                    "duration_seconds": 0.1,
                    "codex": {"version": "codex-cli test"},
                    "preflight": preflight,
                }

            with (
                mock.patch.object(
                    agent_eval,
                    "candidate_runtime_tools",
                    side_effect=fake_candidate_runtime_tools,
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
            self.assertTrue(document["ephemeral_assets_removed"])
            self.assertFalse(document["external_actions"]["model_invoked"])
            self.assertEqual(list(state_root.glob("sandbox-check-*")), [])
            self.assertEqual(list(work_root.glob("sandbox-check-*")), [])

    def test_sandbox_check_reports_elevated_setup_as_blocked_precondition(self) -> None:
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
            failure = evaluation_core.EvaluationError(
                "candidate preflight produced no receipt; "
                "diagnostic=orchestrator_helper_launch_canceled: "
                "ShellExecuteExW failed to launch setup helper: 1223"
            )
            with (
                mock.patch.object(
                    agent_eval,
                    "candidate_runtime_tools",
                    side_effect=fake_candidate_runtime_tools,
                ),
                mock.patch.object(agent_eval, "invoke_candidate_preflight", side_effect=failure),
                mock.patch("builtins.print") as printer,
            ):
                self.assertEqual(agent_eval.command_sandbox_check(args), 3)
            document = json.loads(printer.call_args.args[0])
            self.assertEqual(document["status"], "blocked-precondition")
            self.assertFalse(document["passed"])
            self.assertIsNone(document["runtime_probe"])
            self.assertEqual(
                document["blocking_precondition"]["reason_code"],
                "windows-elevated-sandbox-unavailable",
            )
            self.assertTrue(document["ephemeral_assets_removed"])
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
                    "schema": "agentbase.windows-swe-sandbox-check/v3",
                    "status": "failed",
                    "passed": False,
                    "duration_seconds": 0.1,
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
            self.assertTrue(document["ephemeral_assets_removed"])

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
            "schema": "agentbase.windows-swe-sandbox-assessment/v3",
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
            },
            "infrastructure_health": {
                "infrastructure_failed": 0,
                "cleanup_errors": 0,
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
            "schema": "agentbase.windows-swe-sandbox-assessment/v3",
            "status": "blocked-precondition",
            "passed": False,
            "duration_seconds": 0.2,
            "runtime_probe": None,
            "blocking_precondition": {"reason_code": "windows-elevated-sandbox-unavailable"},
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
            },
            "infrastructure_health": {
                "infrastructure_failed": 0,
                "cleanup_errors": 0,
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
