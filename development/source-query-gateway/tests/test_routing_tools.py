from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import hashlib


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RoutingCapsuleTests(unittest.TestCase):
    def test_progressive_disclosure_and_direct_enum_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cases = Path(temp_dir) / "cases.json"
            write_json(cases, {"cases": [{"id": "synthetic", "prompt": "Find a synthetic symbol."}]})
            output = Path(temp_dir) / "capsule.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "build_routing_capsule.py"), "--output", str(output), "--cases", str(cases)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        initial = payload["candidate"]["initial_selection"]
        selected = payload["candidate"]["after_source_query_selected"]
        self.assertEqual(set(initial), {"global-route", "source-query-frontmatter"})
        self.assertIn("description:", initial["source-query-frontmatter"])
        self.assertNotIn("# Source Query", initial["source-query-frontmatter"])
        self.assertEqual(
            set(selected),
            {"SKILL.md-body", "references/rg-fd.md", "references/ast.md"},
        )

        schema = payload["output_schema"]
        self.assertEqual(schema["case_shape"]["route"], "string selected directly from allowed_values.route")
        self.assertEqual(schema["case_shape"]["reference"], "string selected directly from allowed_values.reference")
        self.assertIsInstance(schema["example_case"]["route"], str)
        self.assertIsInstance(schema["example_case"]["reference"], str)

    def test_verifier_uses_explicit_synthetic_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = root / "cases.json"
            result = root / "result.json"
            write_json(cases, {"cases": [{"id": "one", "prompt": "Synthetic", "expected": {"route": "no_query", "reference": "none"}}]})
            write_json(result, {"cases": [{"id": "one", "route": "no_query", "reference": "none"}]})
            completed = subprocess.run(
                [sys.executable, str(ROOT / "verify_routing_result.py"), str(result), "--cases", str(cases)],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_missing_cases_reports_restore_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "build_routing_capsule.py"), "--output", str(Path(temp_dir) / "out.json"), "--cases", str(Path(temp_dir) / "missing.json")],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Restore the local private file or pass --cases PATH", completed.stderr)

    def test_history_verifies_relative_artifact_and_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = root / "summary.json"
            write_json(summary, {"records": [{"environment": "synthetic", "usage": {"input_tokens": 3, "cached_input_tokens": 1, "output_tokens": 2, "reasoning_output_tokens": 1}, "elapsed_ms": 7, "oracle_passed": True}]})
            index = root / "index.json"
            write_json(index, {"experiments": [{"id": "synthetic", "result": {"observed_location": "summary.json", "sha256": sha256(summary)}, "aggregates": {"synthetic": {"records": 1, "total_tokens": 5, "raw_oracle_passed": 1}}}]})
            completed = subprocess.run(
                [sys.executable, str(ROOT / "history" / "verify_history.py"), "--index", str(index), "--artifact-root", str(root)],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_history_keeps_unavailable_external_results_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index = root / "index.json"
            write_json(index, {"experiments": [{"id": "synthetic", "result": {"observed_location": "missing.json", "sha256": "unused"}, "aggregates": {}}]})
            completed = subprocess.run(
                [sys.executable, str(ROOT / "history" / "verify_history.py"), "--index", str(index), "--artifact-root", str(root)],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertFalse(report["experiments"][0]["available"])
            self.assertNotIn("aggregates", report["experiments"][0])

    def test_history_verifies_artifact_only_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audit = root / "audit.json"
            write_json(audit, {"synthetic": True})
            index = root / "index.json"
            write_json(index, {"experiments": [{"id": "synthetic", "result": {"audit_artifact": "audit.json", "audit_sha256": sha256(audit)}, "aggregates": {}}]})
            completed = subprocess.run(
                [sys.executable, str(ROOT / "history" / "verify_history.py"), "--index", str(index), "--artifact-root", str(root)],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
