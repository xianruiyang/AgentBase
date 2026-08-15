from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_benchmark_homes.py"
SPEC = importlib.util.spec_from_file_location("prepare_benchmark_homes", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareBenchmarkHomesTests(unittest.TestCase):
    def test_candidate_is_the_exact_current_query_migration_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "installed"
            installed.mkdir()
            (installed / "AGENTS.md").write_text(MODULE.OLD_ROUTE + "\n", encoding="utf-8")
            skills = installed / "skills"
            skills.mkdir()
            for name in sorted(MODULE.MINIMAL_RELEVANT_SKILLS):
                source = skills / name
                source.mkdir()
                (source / "marker.txt").write_text(f"old:{name}\n", encoding="utf-8")

            control = root / "control"
            candidate = root / "candidate"
            MODULE.copy_common(installed, control, None, minimal=True)
            MODULE.copy_common(installed, candidate, None, minimal=True)
            srcq = root / "srcq.exe"
            srcq.write_bytes(b"current-srcq")
            MODULE.install_candidate_bundle(control, candidate, srcq)

            for name in MODULE.RETIRED_QUERY_SKILLS:
                self.assertTrue((control / "skills" / name / "marker.txt").is_file())
                self.assertFalse((candidate / "skills" / name).exists())
            self.assertEqual(
                "old:powershell-usage\n",
                (candidate / "skills" / "powershell-usage" / "marker.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (MODULE.PROJECT_ROOT / "skills" / "source-query" / "SKILL.md").read_bytes(),
                (candidate / "skills" / "source-query" / "SKILL.md").read_bytes(),
            )
            self.assertEqual(
                (MODULE.PROJECT_ROOT / "skills" / "symbol-structure-workflow" / "SKILL.md").read_bytes(),
                (candidate / "skills" / "symbol-structure-workflow" / "SKILL.md").read_bytes(),
            )
            self.assertEqual(b"current-srcq", (candidate / "bin" / "srcq.exe").read_bytes())
            self.assertFalse((control / "bin" / "srcq.exe").exists())

    def test_current_route_comes_from_project_global_truth(self) -> None:
        route = MODULE.current_route()
        self.assertTrue(route.startswith(MODULE.CURRENT_ROUTE_PREFIX))
        self.assertIn("srcq.exe", route)


if __name__ == "__main__":
    unittest.main()
