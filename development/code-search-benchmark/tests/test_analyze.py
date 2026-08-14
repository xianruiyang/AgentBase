import json
from importlib.util import module_from_spec, spec_from_file_location
import tempfile
import unittest
from pathlib import Path

analyzer_path = Path(__file__).parents[1] / "analyze.py"
spec = spec_from_file_location("agentbase_code_search_benchmark", analyzer_path)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load benchmark analyzer")
analyzer = module_from_spec(spec)
spec.loader.exec_module(analyzer)
analyze = analyzer.analyze
BenchmarkError = analyzer.BenchmarkError


class AnalyzeBenchmarkTests(unittest.TestCase):
    def test_counts_command_results_skills_and_amortizes_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("result", encoding="utf-8")
            (root / "skill.md").write_text("skill", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema": "agentbase.code-search-benchmark/v1",
                "runs": [{
                    "caseId": "ts-medium",
                    "route": "rg+ast",
                    "language": "typescript",
                    "temperature": "warm",
                    "elapsedMs": 12.5,
                    "evidenceComplete": True,
                    "targetCount": 2,
                    "resultFiles": ["result.txt"],
                    "skillFiles": ["skill.md"],
                    "command": "search command",
                }],
            }), encoding="utf-8")
            result = analyze(manifest)
            self.assertGreater(result["runs"][0]["visible_tokens"], 0)
            self.assertEqual(
                result["runs"][0]["tokens_per_target"],
                round(result["runs"][0]["visible_tokens"] / 2, 2),
            )

    def test_rejects_incomplete_or_escaping_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            base = {
                "caseId": "case",
                "route": "rg",
                "language": "python",
                "temperature": "cold",
                "elapsedMs": 1,
                "evidenceComplete": False,
                "targetCount": 1,
                "resultFiles": [],
                "skillFiles": [],
                "command": "rg target",
            }
            manifest.write_text(json.dumps({"schema": "agentbase.code-search-benchmark/v1", "runs": [base]}), encoding="utf-8")
            with self.assertRaises(BenchmarkError):
                analyze(manifest)
            base["evidenceComplete"] = True
            base["resultFiles"] = ["../outside.txt"]
            manifest.write_text(json.dumps({"schema": "agentbase.code-search-benchmark/v1", "runs": [base]}), encoding="utf-8")
            with self.assertRaises(BenchmarkError):
                analyze(manifest)


if __name__ == "__main__":
    unittest.main()
