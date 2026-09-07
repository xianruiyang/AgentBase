from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


LOGGER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_event_logger.py"
SPEC = importlib.util.spec_from_file_location("codex_event_logger_backfill", LOGGER_PATH)
assert SPEC and SPEC.loader
LOGGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOGGER)


def transcript_row(turn_id: str, role: str, text: str, *, phase: str | None = None) -> str:
    payload = {
        "type": "message",
        "role": role,
        "content": [{"type": "text", "text": text}],
        "internal_chat_message_metadata_passthrough": {"turn_id": turn_id},
    }
    if phase:
        payload["phase"] = phase
    return json.dumps({"timestamp": "2026-09-08T00:00:00Z", "payload": payload})


class TranscriptBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {"max_text_chars": 12000, "lock_timeout_seconds": 1}

    def test_missing_prompt_is_scanned_once_across_repeated_tools(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-backfill-") as raw_root:
            root = Path(raw_root)
            conversation_file = root / "conversation.json"
            transcript_file = root / "transcript.jsonl"
            conversation_file.write_text('{"source":"unknown"}', encoding="utf-8")
            transcript_file.write_text(
                transcript_row("turn-a", "user", "restored prompt")
                + "\n"
                + transcript_row("turn-a", "assistant", "working")
                + "\n",
                encoding="utf-8",
            )
            payload = {"transcript_path": str(transcript_file)}

            original = LOGGER.transcript_turn_messages
            with mock.patch.object(LOGGER, "transcript_turn_messages", wraps=original) as scan:
                for _ in range(3):
                    LOGGER.backfill_conversation_from_transcript(
                        conversation_file,
                        payload,
                        "PostToolUse",
                        "thread-a",
                        "turn-a",
                        self.config,
                    )

            conversation = json.loads(conversation_file.read_text(encoding="utf-8"))
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(conversation["prompt"], "restored prompt")
            self.assertEqual(conversation["source"], "transcript_user_prompt")
            self.assertNotIn("last_assistant_message", conversation)
            self.assertFalse(scan.call_args.kwargs["include_final"])

    def test_normal_user_prompt_submit_does_not_scan_transcript(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-prompt-submit-") as raw_root:
            conversation_file = Path(raw_root) / "conversation.json"
            conversation_file.write_text('{"source":"unknown"}', encoding="utf-8")

            with (
                mock.patch.object(LOGGER, "active_goal_for_thread", return_value=None),
                mock.patch.object(LOGGER, "transcript_turn_messages") as scan,
            ):
                LOGGER.update_conversation(
                    conversation_file,
                    {
                        "prompt": "submitted prompt",
                        "transcript_path": "must-not-be-read.jsonl",
                    },
                    "UserPromptSubmit",
                    "thread-a",
                    "turn-a",
                    self.config,
                )

            conversation = json.loads(conversation_file.read_text(encoding="utf-8"))
            self.assertEqual(scan.call_count, 0)
            self.assertEqual(conversation["prompt"], "submitted prompt")
            self.assertNotIn("last_assistant_message", conversation)

    def test_absent_prompt_is_not_rescanned_by_each_tool(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-backfill-empty-") as raw_root:
            root = Path(raw_root)
            conversation_file = root / "conversation.json"
            transcript_file = root / "transcript.jsonl"
            conversation_file.write_text('{"source":"unknown"}', encoding="utf-8")
            transcript_file.write_text(
                transcript_row("other-turn", "user", "unrelated") + "\n",
                encoding="utf-8",
            )
            payload = {"transcript_path": str(transcript_file)}

            original = LOGGER.transcript_turn_messages
            with mock.patch.object(LOGGER, "transcript_turn_messages", wraps=original) as scan:
                for _ in range(3):
                    LOGGER.backfill_conversation_from_transcript(
                        conversation_file,
                        payload,
                        "PostToolUse",
                        "thread-a",
                        "turn-a",
                        self.config,
                    )

            conversation = json.loads(conversation_file.read_text(encoding="utf-8"))
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(conversation, {"source": "tool_operation"})

    def test_stop_reads_final_and_does_not_promote_incomplete_assistant(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-backfill-stop-") as raw_root:
            root = Path(raw_root)
            transcript_file = root / "transcript.jsonl"
            transcript_file.write_text(
                "\n".join(
                    (
                        transcript_row("turn-a", "user", "prompt"),
                        transcript_row("turn-a", "assistant", "still working"),
                        transcript_row("turn-a", "assistant", "finished", phase="final"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            conversation_file = root / "conversation.json"
            conversation_file.write_text(
                json.dumps({"source": "user_prompt", "prompt": "prompt"}),
                encoding="utf-8",
            )

            LOGGER.update_conversation(
                conversation_file,
                {"transcript_path": str(transcript_file)},
                "Stop",
                "thread-a",
                "turn-a",
                self.config,
            )
            conversation = json.loads(conversation_file.read_text(encoding="utf-8"))
            self.assertEqual(conversation["last_assistant_message"], "finished")

            transcript_file.write_text(
                transcript_row("turn-b", "assistant", "still working") + "\n",
                encoding="utf-8",
            )
            conversation_file.write_text('{"source":"unknown"}', encoding="utf-8")
            LOGGER.update_conversation(
                conversation_file,
                {"transcript_path": str(transcript_file)},
                "Stop",
                "thread-a",
                "turn-b",
                self.config,
            )
            incomplete = json.loads(conversation_file.read_text(encoding="utf-8"))
            self.assertNotIn("last_assistant_message", incomplete)

    def test_complete_legacy_conversation_skips_transcript_and_keeps_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-backfill-legacy-") as raw_root:
            conversation_file = Path(raw_root) / "conversation.json"
            legacy = {
                "turn_source": "user_prompt",
                "prompt": "legacy prompt",
                "last_assistant_message": "legacy final",
                "legacy_metadata": "preserve until normal owner rewrite",
            }
            conversation_file.write_text(json.dumps(legacy), encoding="utf-8")

            with mock.patch.object(LOGGER, "transcript_turn_messages") as scan:
                LOGGER.backfill_conversation_from_transcript(
                    conversation_file,
                    {"transcript_path": "missing.jsonl"},
                    "PostToolUse",
                    "thread-a",
                    "turn-a",
                    self.config,
                )

            self.assertEqual(scan.call_count, 0)
            self.assertEqual(
                json.loads(conversation_file.read_text(encoding="utf-8")),
                legacy,
            )

    def test_goal_prompt_source_does_not_rescan_for_missing_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="AgentBase-backfill-goal-") as raw_root:
            conversation_file = Path(raw_root) / "conversation.json"
            conversation_file.write_text(
                json.dumps({"source": "goal", "goal": {"objective": "continue"}}),
                encoding="utf-8",
            )

            with mock.patch.object(LOGGER, "transcript_turn_messages") as scan:
                LOGGER.backfill_conversation_from_transcript(
                    conversation_file,
                    {"transcript_path": "missing.jsonl"},
                    "PostToolUse",
                    "thread-a",
                    "turn-a",
                    self.config,
                )

            self.assertEqual(scan.call_count, 0)


if __name__ == "__main__":
    unittest.main()
