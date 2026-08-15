from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RoutingCapsuleTests(unittest.TestCase):
    def test_progressive_disclosure_and_direct_enum_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "capsule.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "build_routing_capsule.py"), "--output", str(output)],
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


if __name__ == "__main__":
    unittest.main()
