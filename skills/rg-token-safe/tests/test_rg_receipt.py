from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "rg_receipt.py"


def receipt_metadata(stdout: str) -> dict[str, object]:
    first = stdout.splitlines()[0]
    return json.loads(first.removeprefix("_rg: "))


class RgReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "a.txt").write_text("hit one\nhit two\nnone\n", encoding="utf-8")
        (self.root / "b.txt").write_text("hit three\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_receipt(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--cwd", str(self.root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_distinguishes_exact_limit_from_more_results(self) -> None:
        complete = self.run_receipt("--limit", "3", "--", "-n", "-F", "hit", ".")
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertEqual(
            receipt_metadata(complete.stdout),
            {"mode": "matches", "shown": 3, "complete": True, "text_complete": True},
        )

        truncated = self.run_receipt("--limit", "2", "--", "-n", "-F", "hit", ".")
        self.assertEqual(truncated.returncode, 0, truncated.stderr)
        self.assertEqual(receipt_metadata(truncated.stdout)["shown"], 2)
        self.assertIs(receipt_metadata(truncated.stdout)["complete"], False)

    def test_no_match_is_complete_and_path_mode_is_bounded(self) -> None:
        missing = self.run_receipt("--", "-n", "-F", "absent", ".")
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertEqual(receipt_metadata(missing.stdout)["shown"], 0)
        self.assertIs(receipt_metadata(missing.stdout)["complete"], True)

        paths = self.run_receipt(
            "--mode", "paths", "--limit", "1", "--", "-l", "-F", "hit", "."
        )
        self.assertEqual(paths.returncode, 0, paths.stderr)
        self.assertEqual(receipt_metadata(paths.stdout)["shown"], 1)
        self.assertIs(receipt_metadata(paths.stdout)["complete"], False)

    def test_reports_text_truncation_separately_from_query_completeness(self) -> None:
        output = self.run_receipt(
            "--max-text-chars", "3", "--", "-n", "-F", "hit", "a.txt"
        )
        self.assertEqual(output.returncode, 0, output.stderr)
        metadata = receipt_metadata(output.stdout)
        self.assertIs(metadata["complete"], True)
        self.assertIs(metadata["text_complete"], False)

    def test_propagates_rg_errors_without_a_success_receipt(self) -> None:
        invalid = self.run_receipt("--", "(", ".")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(invalid.stdout, "")

    def test_rejects_context_and_output_modes_owned_by_the_wrapper(self) -> None:
        context = self.run_receipt("--", "-C", "2", "hit", ".")
        self.assertEqual(context.returncode, 2)
        self.assertIn("do not accept context flags", context.stderr)

        json_output = self.run_receipt("--", "--json", "hit", ".")
        self.assertEqual(json_output.returncode, 2)
        self.assertIn("output formatting is owned", json_output.stderr)

        max_count = self.run_receipt("--", "-m", "1", "hit", ".")
        self.assertEqual(max_count.returncode, 2)
        self.assertIn("invalidate the completeness receipt", max_count.stderr)


if __name__ == "__main__":
    unittest.main()
