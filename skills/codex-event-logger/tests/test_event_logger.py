from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
LOGGER_SCRIPT = SKILL_ROOT / "scripts" / "codex_event_logger.py"
READER_SCRIPT = SKILL_ROOT / "scripts" / "read_codex_turn_log.py"


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


if __name__ == "__main__":
    unittest.main()
