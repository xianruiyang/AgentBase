from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
LOGGER_SCRIPT = SKILL_ROOT / "scripts" / "codex_event_logger.py"
READER_SCRIPT = SKILL_ROOT / "scripts" / "read_codex_turn_log.py"


def model_text_cost(text: str) -> int:
    total = 0
    ascii_word = 0
    for character in text:
        if character.isascii() and (character.isalnum() or character == "_"):
            ascii_word += 1
            continue
        if ascii_word:
            total += (ascii_word + 3) // 4
            ascii_word = 0
        if character == "\n" or not character.isspace():
            total += 1
    return total + (ascii_word + 3) // 4


class EventLoggerTests(unittest.TestCase):
    def test_runtime_writes_redacted_conversation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-logger-") as raw_root:
            project_root = Path(raw_root)
            (project_root / ".codex").mkdir()
            payload = {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(project_root),
                "session_id": "thread-a",
                "turn_id": "turn-a",
                "prompt": "keep this sk-1234567890abcdefghijklmnop secret",
            }
            env = os.environ.copy()
            env["CODEX_EVENT_LOGGER_STRICT"] = "1"
            env["CODEX_HOME"] = str(project_root / "fake-codex-home")
            completed = subprocess.run(
                [sys.executable, str(LOGGER_SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            conversations = list(
                (project_root / "codexRuntimeLogFile" / "thread-a").glob(
                    "*/conversation.json"
                )
            )
            self.assertEqual(len(conversations), 1)
            conversation = json.loads(conversations[0].read_text(encoding="utf-8"))
            self.assertIn("<redacted>", conversation["prompt"])
            self.assertNotIn("sk-1234567890abcdefghijklmnop", conversation["prompt"])

    def test_reader_enforces_text_record_and_file_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-reader-") as raw_root:
            project_root = Path(raw_root)
            session_dir = project_root / "codexRuntimeLogFile" / "thread-a"
            old_turn = session_dir / "20260810_010101_001__old"
            turn_dir = session_dir / "20260810_020202_002__new"
            old_turn.mkdir(parents=True)
            turn_dir.mkdir()
            (old_turn / "conversation.json").write_text("{}", encoding="utf-8")
            (old_turn / "file-operations.jsonl").write_text("", encoding="utf-8")
            (turn_dir / "conversation.json").write_text(
                json.dumps({"prompt": "abcdefghijklmnopqrstuvwxyz"}),
                encoding="utf-8",
            )
            operations = [json.dumps({"index": index}) for index in range(5)]
            (turn_dir / "file-operations.jsonl").write_text(
                "\n".join(operations) + "\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--project-root",
                    str(project_root),
                    "--thread-id",
                    "thread-a",
                    "--view",
                    "machine",
                    "--max-text-chars",
                    "12",
                    "--max-operations",
                    "2",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(Path(output["turn_dir"]).name, turn_dir.name)
            self.assertLessEqual(len(output["conversation"]["data"]["prompt"]), 12)
            self.assertTrue(output["file_operations"]["truncated_by_count"])
            self.assertEqual(
                [record["index"] for record in output["file_operations"]["records"]],
                [3, 4],
            )

            secret = "DO_NOT_RETURN_THIS_VALUE" * 20
            (turn_dir / "conversation.json").write_text(
                json.dumps({"prompt": secret}),
                encoding="utf-8",
            )
            oversized = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--turn-dir",
                    str(turn_dir),
                    "--view",
                    "machine",
                    "--max-file-bytes",
                    "64",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(oversized.returncode, 0, oversized.stderr)
            oversized_output = json.loads(oversized.stdout)
            self.assertEqual(oversized_output["conversation"]["status"], "too_large")
            self.assertTrue(oversized_output["file_operations"]["truncated_by_size"])
            self.assertNotIn("DO_NOT_RETURN_THIS_VALUE", oversized.stdout)

    def test_reader_lists_only_requested_number_of_turns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-list-") as raw_root:
            project_root = Path(raw_root)
            session_dir = project_root / "codexRuntimeLogFile" / "thread-a"
            names = [
                "20260810_010101_001__one",
                "20260810_020202_002__two",
                "20260810_030303_003__three",
            ]
            for name in names:
                (session_dir / name).mkdir(parents=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--project-root",
                    str(project_root),
                    "--thread-id",
                    "thread-a",
                    "--view",
                    "machine",
                    "--list-turns",
                    "2",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(
                [turn["name"] for turn in output["turns"]],
                list(reversed(names[-2:])),
            )

    def test_reader_default_model_view_projects_only_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-model-") as raw_root:
            turn_dir = Path(raw_root) / "20260810_020202_002__new"
            turn_dir.mkdir()
            (turn_dir / "conversation.json").write_text(
                json.dumps(
                    {
                        "session_id": "thread-a",
                        "turn_id": "turn-a",
                        "cwd": str(turn_dir.parent),
                        "model": "test-model",
                        "permission_mode": "default",
                        "transcript_path": "not-a-model-input.jsonl",
                        "turn_source": "user_prompt",
                        "prompt_ts": "2026-08-10T02:02:02+08:00",
                        "stop_ts": "2026-08-10T02:03:03+08:00",
                        "prompt": "Implement the owner-aware read surface.",
                        "last_assistant_message": "The contract and tests are ready.",
                        "goal": {
                            "goal_id": "goal-a",
                            "objective": "Finish the model recovery contract",
                            "status": "active",
                            "token_budget": 1000,
                            "tokens_used": 200,
                            "time_used_seconds": 30,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target_path = str(turn_dir / "target.md")
            transient_path = str(turn_dir / "temporary-input.json")
            operation_records = [
                {
                    "ts": "2026-08-10T02:02:30+08:00",
                    "source": "apply_patch",
                    "operation": "modify",
                    "path": target_path,
                    "line_ranges": {
                        "added": [{"start": 3, "end": 5}],
                        "deleted": [],
                    },
                },
                {
                    "ts": "2026-08-10T02:02:40+08:00",
                    "source": "apply_patch",
                    "operation": "modify",
                    "path": target_path,
                    "line_ranges": {
                        "added": [{"start": 6, "end": 7}],
                        "deleted": [],
                    },
                },
                {
                    "source": "apply_patch",
                    "operation": "create",
                    "path": transient_path,
                },
                {
                    "source": "apply_patch",
                    "operation": "delete",
                    "path": transient_path,
                },
            ]
            (turn_dir / "file-operations.jsonl").write_text(
                "\n".join(json.dumps(record) for record in operation_records) + "\n",
                encoding="utf-8",
            )

            model = subprocess.run(
                [sys.executable, str(READER_SCRIPT), "--turn-dir", str(turn_dir)],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(model.returncode, 0, model.stderr)
            self.assertIn(f"turn:{turn_dir.name}", model.stdout)
            self.assertIn("Implement the owner-aware read surface.", model.stdout)
            self.assertIn("The contract and tests are ready.", model.stdout)
            self.assertIn("goal:", model.stdout)
            self.assertIn("base:", model.stdout)
            self.assertIn(f"{turn_dir.name}/target.md", model.stdout)
            self.assertEqual(model.stdout.count("target.md"), 1)
            self.assertIn("start:3,end:7", model.stdout)
            self.assertNotIn("temporary-input.json", model.stdout)
            for redundant in (
                "session_id",
                "transcript_path",
                "prompt_ts",
                "stop_ts",
                "size_bytes",
                "max_file_bytes",
                "source:apply_patch",
            ):
                self.assertNotIn(redundant, model.stdout)

            machine = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--turn-dir",
                    str(turn_dir),
                    "--view",
                    "machine",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(machine.returncode, 0, machine.stderr)
            machine_output = json.loads(machine.stdout)
            self.assertEqual(machine_output["mode"], "read")
            self.assertEqual(
                machine_output["conversation"]["data"]["session_id"], "thread-a"
            )
            self.assertEqual(
                machine_output["file_operations"]["records"][0]["source"],
                "apply_patch",
            )

    def test_reader_model_view_lists_names_without_machine_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-model-list-") as raw_root:
            project_root = Path(raw_root)
            session_dir = project_root / "codexRuntimeLogFile" / "thread-a"
            names = [
                "20260810_010101_001__one",
                "20260810_020202_002__two",
            ]
            for name in names:
                (session_dir / name).mkdir(parents=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--project-root",
                    str(project_root),
                    "--thread-id",
                    "thread-a",
                    "--list-turns",
                    "2",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(names[1], completed.stdout)
            self.assertIn(names[0], completed.stdout)
            self.assertNotIn("session_dir", completed.stdout)
            self.assertNotIn("conversation_size_bytes", completed.stdout)
            self.assertNotIn("file_operations_size_bytes", completed.stdout)

    def test_reader_model_view_preserves_recovery_under_low_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-model-budget-") as raw_root:
            turn_dir = Path(raw_root) / "20260810_020202_002__budget"
            turn_dir.mkdir()
            (turn_dir / "conversation.json").write_text(
                json.dumps(
                    {
                        "turn_source": "auto_or_goal_turn",
                        "prompt": "A" * 6000,
                        "last_assistant_message": "B" * 6000,
                    }
                ),
                encoding="utf-8",
            )
            operations = [
                json.dumps(
                    {
                        "operation": "modify",
                        "path": str(turn_dir / f"very-long-file-name-{index:03d}.md"),
                    }
                )
                for index in range(60)
            ]
            (turn_dir / "file-operations.jsonl").write_text(
                "\n".join(operations) + "\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--turn-dir",
                    str(turn_dir),
                    "--model-token-budget",
                    "256",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertLessEqual(model_text_cost(completed.stdout), 256)
            self.assertIn(f"turn:{turn_dir.name}", completed.stdout)
            self.assertIn("model_token_budget", completed.stdout)
            self.assertIn("--view machine", completed.stdout)
            self.assertNotIn("A" * 200, completed.stdout)

    def test_reader_model_view_reports_rejected_and_partial_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-model-issues-") as raw_root:
            turn_dir = Path(raw_root) / "20260810_020202_002__issues"
            turn_dir.mkdir()
            secret = "DO_NOT_RETURN_THIS_VALUE" * 20
            (turn_dir / "conversation.json").write_text(
                json.dumps({"prompt": secret}), encoding="utf-8"
            )
            operations = [
                json.dumps({"operation": "modify", "path": f"file-{index}.md"})
                for index in range(20)
            ]
            (turn_dir / "file-operations.jsonl").write_text(
                "\n".join(operations) + "\n", encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(READER_SCRIPT),
                    "--turn-dir",
                    str(turn_dir),
                    "--max-file-bytes",
                    "64",
                    "--max-operations",
                    "2",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("status:too_large", completed.stdout)
            self.assertIn("status:partial", completed.stdout)
            self.assertIn("recovery:", completed.stdout)
            self.assertNotIn("DO_NOT_RETURN_THIS_VALUE", completed.stdout)

    def test_runtime_prunes_sessions_and_turns_to_configured_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-retention-") as raw_root:
            project_root = Path(raw_root)
            config_dir = project_root / ".codex"
            config_dir.mkdir()
            (config_dir / "event-logger-settings.json").write_text(
                json.dumps(
                    {
                        "retention_days": 3650,
                        "max_sessions": 2,
                        "max_turns_per_session": 2,
                        "retention_check_interval_seconds": 1,
                    }
                ),
                encoding="utf-8",
            )
            output_root = project_root / "codexRuntimeLogFile"
            now = time.time()
            for session_index, session_name in enumerate(("thread-old-a", "thread-old-b", "thread-current")):
                session_dir = output_root / session_name
                index: dict[str, str] = {}
                for turn_index in range(3):
                    turn_name = f"20260810_0{turn_index}0000_000__turn-{turn_index}"
                    turn_dir = session_dir / turn_name
                    turn_dir.mkdir(parents=True)
                    os.utime(turn_dir, (now - 100 + turn_index, now - 100 + turn_index))
                    index[f"turn-{turn_index}"] = turn_name
                (session_dir / ".turn-index.json").write_text(
                    json.dumps(index), encoding="utf-8"
                )
                os.utime(session_dir, (now - 30 + session_index, now - 30 + session_index))

            payload = {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(project_root),
                "session_id": "thread-current",
                "turn_id": "turn-new",
                "prompt": "retention",
            }
            env = os.environ.copy()
            env["CODEX_EVENT_LOGGER_STRICT"] = "1"
            env["CODEX_HOME"] = str(project_root / "fake-codex-home")
            completed = subprocess.run(
                [sys.executable, str(LOGGER_SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            sessions = [path for path in output_root.iterdir() if path.is_dir() and not path.name.startswith(".")]
            self.assertLessEqual(len(sessions), 2)
            current_session = output_root / "thread-current"
            self.assertTrue(current_session.is_dir())
            current_turns = [path for path in current_session.iterdir() if path.is_dir() and not path.name.startswith(".")]
            self.assertLessEqual(len(current_turns), 2)
            index = json.loads((current_session / ".turn-index.json").read_text(encoding="utf-8"))
            self.assertTrue(all((current_session / folder).is_dir() for folder in index.values()))

    def test_runtime_rejects_output_directory_outside_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-output-root-") as raw_root:
            test_root = Path(raw_root)
            project_root = test_root / "project"
            config_dir = project_root / ".codex"
            config_dir.mkdir(parents=True)
            (config_dir / "event-logger-settings.json").write_text(
                json.dumps({"output_dir_name": "../outside"}), encoding="utf-8"
            )
            payload = {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(project_root),
                "session_id": "thread-a",
                "turn_id": "turn-a",
                "prompt": "must not escape",
            }
            env = os.environ.copy()
            env["CODEX_EVENT_LOGGER_STRICT"] = "1"
            env["CODEX_HOME"] = str(test_root / "fake-codex-home")
            completed = subprocess.run(
                [sys.executable, str(LOGGER_SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((test_root / "outside").exists())

    def test_runtime_retention_does_not_follow_directory_links(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-event-link-") as raw_root:
            test_root = Path(raw_root)
            project_root = test_root / "project"
            config_dir = project_root / ".codex"
            config_dir.mkdir(parents=True)
            (config_dir / "event-logger-settings.json").write_text(
                json.dumps(
                    {
                        "max_sessions": 1,
                        "retention_check_interval_seconds": 1,
                    }
                ),
                encoding="utf-8",
            )
            output_root = project_root / "codexRuntimeLogFile"
            output_root.mkdir()
            outside = test_root / "outside"
            outside.mkdir()
            marker = outside / "must-remain.txt"
            marker.write_text("preserve", encoding="utf-8")
            linked_session = output_root / "linked-session"
            try:
                linked_session.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

            payload = {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(project_root),
                "session_id": "thread-current",
                "turn_id": "turn-new",
                "prompt": "retention must not follow links",
            }
            env = os.environ.copy()
            env["CODEX_EVENT_LOGGER_STRICT"] = "1"
            env["CODEX_HOME"] = str(test_root / "fake-codex-home")
            completed = subprocess.run(
                [sys.executable, str(LOGGER_SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(marker.is_file())
            self.assertTrue(linked_session.is_symlink())


if __name__ == "__main__":
    unittest.main()
