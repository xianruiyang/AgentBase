from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALUATION_ROOT.parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

import agentbase_codex  # noqa: E402
from evaluation_core import EvaluationError, PreconditionError  # noqa: E402
from evo.codex_adapter import recover_codex_artifacts, refresh_codex_trace, run_codex_job  # noqa: E402
from evo.skill_cache import SkillCache  # noqa: E402
from evo.runtime_home import prepare_runtime_home, remove_runtime_auth, runtime_home_from_receipt  # noqa: E402


class EvoCodexAdapterTests(unittest.TestCase):
    def test_default_cli_uses_shared_owner_not_desktop_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            native = Path(temp) / "npm-native.exe"
            native.write_bytes(b"fixture")
            environment = {"PATH": "desktop-first"}
            result = subprocess.CompletedProcess([], 0, str(native).encode("utf-8"), b"")
            with mock.patch.object(agentbase_codex, "run_capture", return_value=result) as capture, \
                    mock.patch.object(agentbase_codex.shutil, "which", side_effect=AssertionError("PATH fallback")):
                self.assertEqual(agentbase_codex.resolve_codex_executable(environment=environment), native)
                self.assertEqual(capture.call_args.kwargs["env"], environment)
                self.assertIn("Resolve-AgentBaseCodexNativeExecutable", capture.call_args.args[0][-1])

    def test_invalid_explicit_cli_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(agentbase_codex, "run_capture", side_effect=AssertionError("fallback")):
            with self.assertRaises(EvaluationError):
                agentbase_codex.resolve_codex_executable(Path(temp) / "missing.exe")

    @staticmethod
    def _write_rollout(path: Path, thread_id: str, usage: dict[str, int], *, parent: str | None = None, expected_child: str | None = None) -> None:
        metadata = {"id": thread_id}
        if parent:
            metadata["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
        lines = [
            {"type": "session_meta", "payload": metadata},
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
        ]
        if expected_child:
            lines.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "SubAgentActivity", "agent_thread_id": expected_child}}})
        lines.extend([
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": usage, "last_token_usage": usage}}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def test_public_signature_keeps_runtime_owned_inputs_explicit(self) -> None:
        self.assertEqual(
            list(inspect.signature(run_codex_job).parameters),
            [
                "project_root",
                "workspace",
                "attempt_root",
                "installed_codex_root",
                "spec",
                "job",
                "process_environment",
                "timeout_seconds",
                "cancel_check",
                "task_runtime_bin",
                "skill_cache_root",
                "output_schema",
            ],
        )

    def test_selected_projection_contains_only_chosen_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            (project / "rules").mkdir(parents=True)
            (project / "skills" / "one").mkdir(parents=True)
            (project / "skills" / "two").mkdir(parents=True)
            (project / "agents").mkdir(parents=True)
            workspace.mkdir()
            (project / "rules" / "AGENTS.md").write_text("selected rule\n", encoding="utf-8")
            (project / "skills" / "one" / "SKILL.md").write_text("one\n", encoding="utf-8")
            (project / "skills" / "two" / "SKILL.md").write_text("two\n", encoding="utf-8")
            (project / "agents" / "worker.toml").write_text('model = "gpt-test"\n', encoding="utf-8")
            projection = agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT,
                workspace=workspace,
                selected={
                    "agents_md": [{"id": "rules", "source": str(project / "rules" / "AGENTS.md")}],
                    "skills": [{"id": "one", "source": str(project / "skills" / "one")}],
                    "agents": [{"id": "roles", "source": str(project / "agents")}],
                },
                max_agents=3,
                candidate_source_roots=[project],
                skill_cache_root=root / "state" / "skill-cache",
            )
            config = tomllib.loads((workspace / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["developer_instructions"], "selected rule\n")
            self.assertTrue(config["agents"]["enabled"])
            self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 2)
            self.assertTrue((workspace / ".agents" / "skills" / "one" / "SKILL.md").is_file())
            self.assertFalse((workspace / ".agents" / "skills" / "two").exists())
            self.assertTrue((workspace / ".codex" / "agents" / "worker.toml").is_file())
            self.assertTrue(projection["identity_sha256"])
            cache = SkillCache(PROJECT_ROOT, root / "state")
            for reference in projection["skill_references"]:
                cache.remove_reference(reference)
            cache.remove_unreferenced_version(projection["skill_references"][0]["identity_sha256"])

    def test_projection_rejects_outside_sources_and_unsupported_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            outside = root / "outside.md"
            project.mkdir()
            workspace.mkdir()
            outside.write_text("outside", encoding="utf-8")
            with self.assertRaisesRegex(PreconditionError, "outside allowed roots"):
                agentbase_codex.stage_codex_component_projection(
                    project_root=project,
                    workspace=workspace,
                    selected={"agents_md": [{"id": "x", "source": str(outside)}]},
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            project.mkdir()
            workspace.mkdir()
            with self.assertRaisesRegex(PreconditionError, "source is unavailable"):
                agentbase_codex.stage_codex_component_projection(
                    project_root=project,
                    workspace=workspace,
                    selected={"hooks": [{"id": "hook", "source": "hook.json"}]},
                )

    def test_model_gate_fails_before_any_projection(self) -> None:
        old = __import__("os").environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED")
        __import__("os").environ["AGENTBASE_AGENT_EVALUATOR_DISABLED"] = "1"
        try:
            with self.assertRaisesRegex(EvaluationError, "disabled"):
                run_codex_job(
                    project_root=Path("missing"),
                    workspace=Path("missing"),
                    attempt_root=Path("missing"),
                    installed_codex_root=Path("missing"),
                    spec={},
                    job={},
                )
        finally:
            if old is None:
                __import__("os").environ.pop("AGENTBASE_AGENT_EVALUATOR_DISABLED", None)
            else:
                __import__("os").environ["AGENTBASE_AGENT_EVALUATOR_DISABLED"] = old

    def test_launcher_supports_shared_result_schema_and_optional_runtime_bin(self) -> None:
        text = (EVALUATION_ROOT / "invoke_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("$ResultSchema = 'agentbase.windows-swe-codex-run/v8'", text)
        self.assertIn("schema = $ResultSchema", text)
        self.assertIn("[string]$TaskRuntimeBinPath = ''", text)
        self.assertIn("$startInfo.ArgumentList.Add($argument)", text)
        self.assertIn("[string]$RuntimeCodexRoot = ''", text)

    def test_launcher_places_optional_answer_schema_on_exec_without_splitting_path(self) -> None:
        launcher = (EVALUATION_ROOT / 'invoke_candidate.ps1').read_text(encoding='utf-8')
        block = launcher[launcher.index("$arguments = New-Object"):launcher.index('$promptItem =')]
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        common = PROJECT_ROOT / 'development/common/codex_cli_runtime.ps1'
        with tempfile.TemporaryDirectory() as directory:
            schema = Path(directory) / "answer's schema.json"
            schema.write_text('{}', encoding='utf-8')
            for selected in ('', str(schema)):
                with self.subTest(schema=selected):
                    script = '\n'.join([
                        "$ErrorActionPreference = 'Stop'", f'. {quote(common)}',
                        f'$resolvedOutputSchema = {quote(selected)}',
                        "$Model = 'synthetic'; $ReasoningEffort = 'low'",
                        "$projectTrustKey = '\"synthetic\"'; $EnableHooks = $false; $ConfigOverride = @()",
                        "$lastMessagePath = 'answer.txt'; $resolvedWorkspace = 'workspace'",
                        block, 'ConvertTo-Json -InputObject $arguments.ToArray() -Compress',
                    ])
                    result = subprocess.run(['pwsh.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                            capture_output=True, text=True, encoding='utf-8', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    argv = json.loads(result.stdout)
                    self.assertEqual(argv[0], 'exec')
                    self.assertEqual(argv[-1], '-')
                    if selected:
                        self.assertEqual(argv.count('--output-schema'), 1)
                        self.assertEqual(argv[argv.index('--output-schema') + 1], selected)
                    else:
                        self.assertNotIn('--output-schema', argv)

    def test_attempt_runtime_home_links_only_auth_and_retains_native_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "attempt"
            installed = root / "installed"
            attempt.mkdir()
            installed.mkdir()
            source = installed / "auth.json"
            source.write_text("{}\n", encoding="utf-8")
            (installed / "AGENTS.md").write_text("host rules\n", encoding="utf-8")
            (installed / "config.toml").write_text("model = 'host'\n", encoding="utf-8")
            (installed / "skills").mkdir()

            runtime_home, record = prepare_runtime_home(
                attempt_root=attempt,
                installed_codex_root=installed,
            )

            self.assertEqual(record["authentication"], "temporary-same-volume-hardlink")
            self.assertEqual(source.stat().st_ino, (runtime_home / "auth.json").stat().st_ino)
            self.assertEqual(sorted(path.name for path in runtime_home.iterdir()), ["auth.json"])
            (runtime_home / "sessions").mkdir()
            rollout = runtime_home / "sessions" / "rollout.jsonl"
            rollout.write_text("{}\n", encoding="utf-8")
            remove_runtime_auth(attempt_root=attempt)
            self.assertFalse((runtime_home / "auth.json").exists())
            self.assertTrue((runtime_home / "sessions" / "rollout.jsonl").is_file())
            self.assertEqual(
                runtime_home_from_receipt(attempt_root=attempt, installed_codex_root=installed),
                runtime_home,
            )
            agentbase_codex.write_json_atomic(
                attempt / "codex-result.json",
                {"schema": "agentbase.evo-codex-run/v1", "agent_usage": [
                    {"rollout": {"path": "sessions/rollout.jsonl"}, "requests": []}
                ]},
            )
            refreshed = refresh_codex_trace(
                project_root=EVALUATION_ROOT.parents[1], attempt_root=attempt,
                installed_codex_root=None,
            )
            self.assertEqual(refreshed["trace"]["capability"], "partial")
            self.assertEqual(
                runtime_home_from_receipt(attempt_root=attempt, installed_codex_root=None),
                runtime_home,
            )

    def test_runtime_home_rejects_linked_auth_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "attempt"
            installed = root / "installed"
            attempt.mkdir()
            installed.mkdir()
            target = root / "auth-target.json"
            target.write_text("{}\n", encoding="utf-8")
            try:
                (installed / "auth.json").symlink_to(target)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(PreconditionError, "regular file"):
                prepare_runtime_home(attempt_root=attempt, installed_codex_root=installed)

    def test_runtime_auth_cleanup_refuses_a_replaced_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "attempt"
            installed = root / "installed"
            attempt.mkdir()
            installed.mkdir()
            source = installed / "auth.json"
            source.write_text("{}\n", encoding="utf-8")
            runtime_home, _ = prepare_runtime_home(attempt_root=attempt, installed_codex_root=installed)
            (runtime_home / "auth.json").unlink()
            runtime_home.rmdir()
            try:
                runtime_home.symlink_to(installed, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlink creation is unavailable")
            with self.assertRaisesRegex(PreconditionError, "reparse point"):
                remove_runtime_auth(attempt_root=attempt)
            self.assertTrue(source.is_file())

    def test_launcher_really_binds_an_empty_runtime_bin_before_fake_subject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            codex_home = root / "installed-codex-home"
            attempt = root / "attempt"
            runtime_home = attempt / "codex-runtime-home"
            (workspace / ".codex").mkdir(parents=True)
            codex_home.mkdir()
            attempt.mkdir()
            runtime_home.mkdir()
            (workspace / ".codex" / "config.toml").write_text('approval_policy = "never"\n', encoding="utf-8")
            (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
            os.link(codex_home / "auth.json", runtime_home / "auth.json")
            prompt = attempt / "prompt.txt"
            result = attempt / "result.json"
            prompt.write_text("bounded fake subject\n", encoding="utf-8")
            pwsh = Path(shutil.which("pwsh.exe") or "")
            fake_executable = root / "fake-codex.cmd"
            fake_executable.write_text(
                '@echo off\r\nif "%1"=="--version" (echo codex-cli 0.0.0& exit /b 0)\r\nexit /b 5\r\n',
                encoding="ascii",
            )
            completed = subprocess.run(
                [
                    str(pwsh), "-NoProfile", "-NonInteractive", "-File",
                    str(EVALUATION_ROOT / "invoke_candidate.ps1"),
                    "-ProjectRoot", str(EVALUATION_ROOT.parents[1]),
                    "-Workspace", str(workspace),
                    "-InstalledCodexRoot", str(codex_home),
                    "-RuntimeCodexRoot", str(runtime_home),
                    "-PromptPath", str(prompt),
                    "-ResultPath", str(result),
                    "-Model", "fake-model",
                    "-ReasoningEffort", "low",
                    "-CodexExecutablePath", str(fake_executable),
                    "-TimeoutSeconds", "60",
                    "-ResultSchema", "agentbase.evo-codex-run/v1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            diagnostic = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
            value = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else None
            self.assertNotIn("Cannot bind argument to parameter 'RuntimeBin'", diagnostic)
            self.assertTrue(result.is_file())
            self.assertTrue((attempt / "codex-logs" / "model-process-started.txt").is_file())
            self.assertTrue(value["process_started"])
            self.assertIsNone(value["model_invoked"])
            self.assertEqual(value["status"], "failed")
            self.assertTrue((codex_home / "auth.json").is_file())
            self.assertFalse((runtime_home / "auth.json").exists())

    def test_single_root_uses_valid_dormant_agent_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            workspace = Path(directory) / "workspace"
            project.mkdir()
            workspace.mkdir()
            projection = agentbase_codex.stage_codex_component_projection(
                project_root=project,
                workspace=workspace,
                selected={},
                max_agents=1,
            )
            config = tomllib.loads(Path(projection["config_path"]).read_text(encoding="utf-8"))
            self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 1)
            self.assertFalse(config["agents"]["enabled"])
            self.assertFalse(config["features"]["multi_agent"])

    def test_single_root_rejects_selected_agent_profiles_and_enabled_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            project.mkdir()
            workspace.mkdir()
            profile = project / "evidence.toml"
            profile.write_text('name = "evidence"\n', encoding="utf-8")
            with self.assertRaisesRegex(PreconditionError, "selected agent profiles"):
                agentbase_codex.stage_codex_component_projection(
                    project_root=project, workspace=workspace,
                    selected={"agents": [{"id": "evidence", "source": str(profile)}]},
                    max_agents=1, candidate_source_roots=[project],
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            project.mkdir()
            workspace.mkdir()
            setting = project / "enabled.toml"
            setting.write_text("[agents]\nenabled = true\n", encoding="utf-8")
            with self.assertRaisesRegex(PreconditionError, "agents.enabled=true"):
                agentbase_codex.stage_codex_component_projection(
                    project_root=project, workspace=workspace,
                    selected={"codex_settings": [{"id": "enabled", "source": str(setting)}]},
                    max_agents=1, candidate_source_roots=[project],
                )

    def test_multi_agent_rejects_disabled_agents_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            workspace = root / "workspace"
            project.mkdir()
            workspace.mkdir()
            setting = project / "disabled.toml"
            setting.write_text("[agents]\nenabled = false\n", encoding="utf-8")
            with self.assertRaisesRegex(PreconditionError, "agents.enabled=false"):
                agentbase_codex.stage_codex_component_projection(
                    project_root=project, workspace=workspace,
                    selected={"codex_settings": [{"id": "disabled", "source": str(setting)}]},
                    max_agents=7, candidate_source_roots=[project],
                )

    def test_recovery_loads_repository_audit_with_its_sibling_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "attempt"
            codex_home = root / "codex-home"
            rollout = codex_home / "sessions" / "rollout.jsonl"
            attempt.mkdir()
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-09-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thread-1", "agent_path": "/root"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-09-09T00:00:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "item": {"type": "CommandExecution", "command": ["Get-Content", "selected/SKILL.md"], "exit_code": 0},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            agentbase_codex.write_json_atomic(attempt / "codex-rollout-before.json", {})
            agentbase_codex.write_json_atomic(
                attempt / "codex-result.json",
                {
                    "schema": "agentbase.evo-codex-run/v1",
                    "status": "completed",
                    "model_invoked": True,
                    "agent_usage_receipt_sha256": "a" * 64,
                    "agent_usage": [{"rollout": {"path": "sessions/rollout.jsonl"}, "requests": []}],
                },
            )
            result = recover_codex_artifacts(
                project_root=EVALUATION_ROOT.parents[1],
                attempt_root=attempt,
                installed_codex_root=codex_home,
            )
            self.assertEqual(result["trace"]["capability"], "partial")
            self.assertEqual(result["trace"]["observed"][0]["identity"]["thread_id"], "thread-1")
            self.assertFalse(result["trace"]["private_reasoning_archived"])
            refreshed = refresh_codex_trace(
                project_root=EVALUATION_ROOT.parents[1],
                attempt_root=attempt,
                installed_codex_root=codex_home,
            )
            self.assertIn("selected/SKILL.md", refreshed["trace"]["observed"][0]["events"][0]["excerpt"])
            self.assertTrue(Path(refreshed["trace_path"]).is_file())

    def test_recovery_corrects_process_started_without_model_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "attempt"
            home = Path(directory) / "home"
            attempt.mkdir()
            home.mkdir()
            agentbase_codex.write_json_atomic(attempt / "codex-rollout-before.json", {})
            agentbase_codex.write_json_atomic(
                attempt / "codex-result.json",
                {
                    "schema": "agentbase.evo-codex-run/v1",
                    "status": "failed",
                    "model_invoked": True,
                    "root_thread_id": None,
                    "thread_started_count": 0,
                    "event_count": 0,
                    "exit_code": 2,
                    "diagnostic": "Error: agents.max_concurrent_threads_per_session must be at least 1",
                    "agent_usage": [],
                },
            )
            recovered = recover_codex_artifacts(
                project_root=EVALUATION_ROOT.parents[1],
                attempt_root=attempt,
                installed_codex_root=home,
            )["raw_receipt"]
            self.assertTrue(recovered["process_started"])
            self.assertFalse(recovered["model_invoked"])
            self.assertEqual(recovered["status"], "precondition_failed")

    def test_recovery_keeps_unknown_no_session_failure_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "attempt"
            home = Path(directory) / "home"
            attempt.mkdir()
            home.mkdir()
            agentbase_codex.write_json_atomic(attempt / "codex-rollout-before.json", {})
            agentbase_codex.write_json_atomic(
                attempt / "codex-result.json",
                {
                    "schema": "agentbase.evo-codex-run/v1", "status": "failed",
                    "model_invoked": None, "root_thread_id": None,
                    "thread_started_count": 0, "event_count": 0, "exit_code": 1,
                    "diagnostic": "connection closed before response", "agent_usage": [],
                },
            )
            recovered = recover_codex_artifacts(
                project_root=EVALUATION_ROOT.parents[1], attempt_root=attempt,
                installed_codex_root=home,
            )["raw_receipt"]
            self.assertIsNone(recovered["model_invoked"])
            self.assertEqual(recovered["status"], "failed")

    def test_rollout_cursor_ignores_large_history_and_keeps_complete_lineage(self) -> None:
        usage = {
            "total_tokens": 13,
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            history = home / "sessions" / "2000" / "01" / "01"
            history.mkdir(parents=True)
            for index in range(agentbase_codex.MAX_ATTEMPT_ROLLOUT_FILES * 8 + 1):
                (history / f"old-{index}.jsonl").write_text("{}\n", encoding="utf-8")
            before = agentbase_codex.candidate_rollout_snapshot(home)
            today = time.gmtime()
            bucket = home / "sessions" / f"{today.tm_year:04d}" / f"{today.tm_mon:02d}" / f"{today.tm_mday:02d}"
            self._write_rollout(bucket / "root.jsonl", "root", usage, expected_child="child")
            self._write_rollout(bucket / "child.jsonl", "child", usage, parent="root")
            (bucket / "unrelated-invalid.jsonl").write_bytes(b"not-json\n")
            with (bucket / "unrelated-oversized.jsonl").open("wb") as stream:
                stream.write(b"x" * (agentbase_codex.MAX_ROLLOUT_METADATA_BYTES + 1))
                stream.truncate(agentbase_codex.MAX_ATTEMPT_ROLLOUT_BYTES + 1)
            receipt = agentbase_codex.candidate_agent_usage_receipt(
                codex_home=home,
                before=before,
                root_thread_id="root",
                root_usage=usage,
            )
            self.assertEqual(receipt["thread_count"], 2)
            self.assertEqual({row["thread_id"] for row in receipt["threads"]}, {"root", "child"})
            self.assertTrue(receipt["usage_complete"])
            root_record = next(row for row in receipt["threads"] if row["thread_id"] == "root")
            self.assertEqual(root_record["requests"][0]["requested_model"], "gpt-5.6-sol")
            self.assertEqual(root_record["requests"][0]["usage"], usage)
            self.assertTrue(root_record["requests"][0]["complete"])

    def test_usage_refuses_to_claim_complete_when_observed_child_rollout_is_missing(self) -> None:
        usage = {
            "total_tokens": 13,
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            before = agentbase_codex.candidate_rollout_snapshot(home)
            self._write_rollout(home / "sessions" / "root.jsonl", "root", usage, expected_child="missing-child")
            with self.assertRaisesRegex(EvaluationError, "child rollout evidence is missing"):
                agentbase_codex.candidate_agent_usage_receipt(
                    codex_home=home,
                    before=before,
                    root_thread_id="root",
                    root_usage=usage,
                )

    def test_job_consumes_runtime_and_returns_raw_receipt_without_scoring(self) -> None:
        class FakeProcess:
            pid = 42
            returncode = 0

            def poll(self):
                return 0

            def communicate(self):
                return b"", b""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = EVALUATION_ROOT.parents[1]
            workspace = root / "workspace"
            attempt = root / "attempt"
            codex_home = root / "codex-home"
            for path in (workspace, attempt, codex_home):
                path.mkdir()
            (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
            executable = root / "codex.exe"
            executable.write_bytes(b"fixture")
            # npm tasks use the prepared host toolchain rather than a workspace venv.
            task_runtime_bin = root / "host-node-runtime"
            task_runtime_bin.mkdir(parents=True)
            receipt = {
                "schema": "agentbase.evo-codex-run/v1",
                "status": "completed",
                "model_invoked": True,
                "root_thread_id": "root",
                "root_usage": {"total_tokens": 1},
                "agent_usage": [],
            }
            spec = {
                "runtime": {"adapter": "codex", "model": "gpt-test", "reasoning_effort": "low"},
                "components": {"agents_md": [{"id": "rules", "source": "global/AGENTS.md"}]},
                "combinations": [{"id": "combo", "members": {"agents_md": ["rules"]}}],
                "evaluations": {"items": [{"id": "item", "runtime": {"prompt": "do work"}}]},
            }
            finalized = {**receipt, "usage_complete": True, "agent_usage": []}
            def start_process(*args, **kwargs):
                agentbase_codex.write_json_atomic(attempt / "codex-result.json", receipt)
                return FakeProcess()
            with (
                mock.patch.dict(os.environ, {"AGENTBASE_AGENT_EVALUATOR_DISABLED": "0"}),
                mock.patch.object(agentbase_codex, "candidate_rollout_snapshot", return_value={}),
                mock.patch.object(agentbase_codex, "finalize_candidate_agent_usage", return_value=finalized),
                mock.patch(
                    "evo.codex_adapter.subprocess.run",
                    return_value=__import__("subprocess").CompletedProcess(
                        [str(executable), "--version"], 0, b"codex-cli test\n", b""
                    ),
                ),
                mock.patch("evo.codex_adapter.subprocess.Popen", side_effect=start_process) as popen,
                mock.patch(
                    "evo.codex_adapter._audit_trace",
                    return_value={"schema": "agentbase.evo-codex-trace/v1"},
                ),
            ):
                result = run_codex_job(
                    project_root=project,
                    workspace=workspace,
                    attempt_root=attempt,
                    installed_codex_root=codex_home,
                    spec=spec,
                    job={"combination": "combo", "item": "item"},
                    process_environment={"AGENTBASE_CODEX_EXECUTABLE_PATH": str(executable)},
                    timeout_seconds=60,
                    task_runtime_bin=task_runtime_bin,
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["raw_receipt"], finalized)
            self.assertNotIn("facts", result)
            argv = popen.call_args.args[0]
            self.assertIn("gpt-test", argv)
            self.assertIn("agentbase.evo-codex-run/v1", argv)
            self.assertEqual(argv[argv.index("-TaskRuntimeBinPath") + 1], str(task_runtime_bin))
            runtime_home = attempt / "codex-runtime-home"
            self.assertEqual(argv[argv.index("-RuntimeCodexRoot") + 1], str(runtime_home))
            self.assertFalse((runtime_home / "auth.json").exists())


if __name__ == "__main__":
    unittest.main()
