from __future__ import annotations

import hashlib
import base64
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class BackendContractTests(unittest.TestCase):
    def test_help_manifest_is_complete_and_current(self) -> None:
        manifest = load_json("help-manifest.json")
        declared = {entry["path"]: entry for entry in manifest["files"]}
        actual = {
            path.relative_to(ROOT).as_posix(): path
            for path in (ROOT / "help").glob("*.txt")
        }
        self.assertEqual(set(declared), set(actual))
        for relative, path in actual.items():
            data = path.read_bytes()
            self.assertEqual(declared[relative]["bytes"], len(data), relative)
            self.assertEqual(
                declared[relative]["sha256"], hashlib.sha256(data).hexdigest(), relative
            )

    def test_versions_reference_real_help_and_version_specific_commands(self) -> None:
        versions = load_json("versions.json")["backends"]
        ids = [entry["id"] for entry in versions]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in versions:
            if "help" in entry:
                paths = entry["help"]
            else:
                prefix = entry["helpPrefix"]
                paths = [f"{prefix}.txt"] + [
                    f"{prefix}-{command}.txt"
                    for command in entry["commands"]
                    if command not in {"help", "version"}
                ]
            for relative in paths:
                self.assertTrue((ROOT / relative).is_file(), relative)

        ast_041 = next(entry for entry in versions if entry["id"] == "ast-grep-0.41.1")
        ast_042 = next(entry for entry in versions if entry["id"] == "ast-grep-0.42.0")
        ast_044 = next(entry for entry in versions if entry["id"] == "ast-grep-0.44.1")
        self.assertNotIn("outline", ast_041["commands"])
        self.assertNotIn("outline", ast_042["commands"])
        self.assertIn("outline", ast_044["commands"])

    def test_mode_ids_are_unique_and_cover_every_command_domain(self) -> None:
        matrix = load_json("mode-matrix.json")
        modes = matrix["modes"]
        ids = [mode["id"] for mode in modes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({mode["backend"] for mode in modes}, {"rg", "fd", "ast-grep"})
        self.assertTrue(
            {mode["handling"] for mode in modes}
            <= set(matrix["handling"]),
        )
        ast_selectors = " ".join(mode["selector"] for mode in modes if mode["backend"] == "ast-grep")
        for command in ("run", "scan", "test", "new", "lsp", "outline", "completions"):
            self.assertIn(command, ast_selectors)

    def test_native_oracle_records_distinct_no_match_semantics(self) -> None:
        oracle = load_json("native-oracle.json")
        cases = {case["id"]: case for case in oracle["cases"]}
        self.assertEqual(cases["rg-no-match-json"]["exitCode"], 1)
        self.assertEqual(cases["fd-no-match"]["exitCode"], 0)
        self.assertEqual(cases["ast-run-no-match"]["exitCode"], 1)
        encoded = cases["fd-print0"]["stdoutBase64"]
        self.assertIsInstance(encoded, str)
        self.assertIn(b"\0", base64.b64decode(encoded))

    def test_native_oracle_replays_on_the_current_exact_versions(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(ROOT / "capture_native_oracle.py"),
                "--verify",
                str(ROOT / "native-oracle.json"),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
