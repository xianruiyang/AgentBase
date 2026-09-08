from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.calculator import CalculatorError, calculate
from evo.calculator_cli import main
from evo.scoring import score_artifacts


def spec_value() -> dict:
    return {
        "schema": "agentbase-evo-research/v1", "id": "calculator-test", "version": "1",
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "empty", "members": {}}],
        "evaluations": {
            "items": [{"id": "case", "input_version": "1", "protocol": "offline", "observations": ["quality"]}],
            "groups": [{"id": "core", "active": True, "items": ["case"]}],
        },
        "fields": [
            {"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "existing receipt"},
            {"id": "custom.adjusted_reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "fixed local calculator"},
        ],
        "scoring": [{"id": "calculated", "version": "1", "metrics": [
            {"id": "adjusted", "unit": "ratio", "expression": {"aggregate": "mean", "field": "custom.adjusted_reward"}}
        ]}],
        "selection": {"combinations": ["empty"], "groups": ["core"], "replicates": 1},
    }


def artifact_value() -> dict:
    return {
        "schema": "agentbase-evo-artifacts/v1", "id": "existing", "version": "1",
        "rows": [{
            "id": "original", "grain": "attempt",
            "dimensions": {"combination": "empty", "item": "case", "replicate": 1},
            "values": {"quality.reward": 1},
            "source": {"kind": "existing-receipt", "location": "receipts/original.json"},
            "completeness": "complete", "reward": 1, "composite_score": None,
        }],
    }


class CalculatorFixture:
    def __init__(self, test: unittest.TestCase, source: str):
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.spec = self.root / "spec.json"
        self.artifacts = self.root / "artifacts.json"
        self.code = self.root / "calculator.py"
        self.manifest = self.root / "manifest.json"
        self.output = self.root / "calculated.json"
        self.spec.write_text(json.dumps(spec_value()), encoding="utf-8")
        self.artifacts.write_text(json.dumps(artifact_value()), encoding="utf-8")
        self.code.write_text(source, encoding="utf-8")
        digest = hashlib.sha256(self.code.read_bytes()).hexdigest()
        self.manifest_value = {
            "schema": "agentbase-evo-calculator/v1", "id": "double-reward", "version": "1",
            "argv": [sys.executable, "-X", "utf8", "{calculator}"],
            "code": {"path": "calculator.py", "sha256": digest},
            "timeout_seconds": 5, "max_output_bytes": 1024 * 1024,
        }
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest.write_text(json.dumps(self.manifest_value), encoding="utf-8")


SUCCESS_SOURCE = """import json, sys
payload = json.load(sys.stdin)
row = payload['artifacts']['value']['rows'][0]
assert payload['spec']['identity_sha256'] and payload['artifacts']['identity_sha256']
print(json.dumps({'schema': 'agentbase-evo-calculator-facts/v1', 'rows': [{
    'id': 'calculated:adjusted', 'grain': 'attempt', 'dimensions': row['dimensions'],
    'values': {'custom.adjusted_reward': row['values']['quality.reward'] * 2},
    'completeness': 'complete', 'input_rows': [row['id']]
}]}))
"""


class EvoCalculatorTests(unittest.TestCase):
    def test_explicit_cli_calculator_produces_valid_scoreable_facts(self) -> None:
        fixture = CalculatorFixture(self, SUCCESS_SOURCE)
        self.assertEqual(main(["calculate", "--manifest", str(fixture.manifest), "--spec", str(fixture.spec),
                              "--artifacts", str(fixture.artifacts), "--output", str(fixture.output),
                              "--allow-local-code"]), 0)
        result = json.loads(fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(result["rows"][0]["reward"], 1)
        self.assertIsNone(result["rows"][0]["composite_score"])
        derived = result["rows"][1]
        self.assertEqual(derived["values"]["custom.adjusted_reward"], 2)
        self.assertEqual(derived["input_rows"], ["original"])
        self.assertEqual(derived["source"]["kind"], "fixed-local-calculator")
        self.assertEqual(result["calculator"]["code"]["sha256"], hashlib.sha256(fixture.code.read_bytes()).hexdigest())
        score = score_artifacts(spec_value(), result)
        self.assertEqual(score["scores"][0]["groups"][0]["metrics"][0]["value"], 2)

    def test_local_code_requires_explicit_flag_and_is_not_run_implicitly(self) -> None:
        marker_source = "from pathlib import Path\nPath('executed').write_text('yes')\n"
        fixture = CalculatorFixture(self, marker_source)
        with self.assertRaisesRegex(CalculatorError, "allow-local-code"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=False)
        self.assertFalse((fixture.root / "executed").exists())

    def test_code_fingerprint_mismatch_fails_before_execution(self) -> None:
        fixture = CalculatorFixture(self, SUCCESS_SOURCE)
        fixture.code.write_text(SUCCESS_SOURCE + "# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(CalculatorError, "fingerprint"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)
        self.assertFalse(fixture.output.exists())

    def test_manifest_must_execute_its_fingerprinted_code(self) -> None:
        fixture = CalculatorFixture(self, SUCCESS_SOURCE)
        fixture.manifest_value["argv"] = [sys.executable, "-c", "print('{}')"]
        fixture.write_manifest()
        with self.assertRaisesRegex(CalculatorError, "placeholder exactly once"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)

    def test_output_cannot_overwrite_any_input_or_code(self) -> None:
        fixture = CalculatorFixture(self, SUCCESS_SOURCE)
        for output in (fixture.manifest, fixture.spec, fixture.artifacts, fixture.code):
            with self.subTest(output=output.name), self.assertRaisesRegex(CalculatorError, "must not overwrite"):
                calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                          output_path=output, allow_local_code=True)

    def test_nonzero_exit_is_infrastructure_failure_not_quality_zero(self) -> None:
        fixture = CalculatorFixture(self, "import sys\nprint('diagnostic', file=sys.stderr)\nsys.exit(7)\n")
        with self.assertRaisesRegex(CalculatorError, "exited with code 7"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)
        self.assertFalse(fixture.output.exists())
        self.assertIn("diagnostic", fixture.output.with_suffix(".json.calculator.stderr.log").read_text(encoding="utf-8"))

    def test_unknown_lineage_and_nonfinite_output_are_rejected(self) -> None:
        unknown = "import json\nprint(json.dumps({'schema':'agentbase-evo-calculator-facts/v1','rows':[{'id':'x','grain':'attempt','dimensions':{},'values':{'custom.adjusted_reward':1},'completeness':'complete','input_rows':['absent']}]}))\n"
        fixture = CalculatorFixture(self, unknown)
        with self.assertRaisesRegex(CalculatorError, "reference existing"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)
        nonfinite = "print(\"{\\\"schema\\\":\\\"agentbase-evo-calculator-facts/v1\\\",\\\"rows\\\":[],\\\"bad\\\":NaN}\")\n"
        fixture = CalculatorFixture(self, nonfinite)
        with self.assertRaisesRegex(CalculatorError, "finite JSON"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)

    def test_derived_fields_must_be_declared_with_matching_type_and_grain(self) -> None:
        source = "import json\nprint(json.dumps({'schema':'agentbase-evo-calculator-facts/v1','rows':[{'id':'x','grain':'attempt','dimensions':{},'values':{'undeclared':1},'completeness':'complete','input_rows':['original']}]}))\n"
        fixture = CalculatorFixture(self, source)
        with self.assertRaisesRegex(CalculatorError, "undeclared field"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)

    def test_timeout_and_output_limits_are_bounded(self) -> None:
        fixture = CalculatorFixture(self, "import time\ntime.sleep(5)\n")
        fixture.manifest_value["timeout_seconds"] = 1
        fixture.write_manifest()
        with self.assertRaisesRegex(CalculatorError, "timed out"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)
        fixture = CalculatorFixture(self, "print('x' * 5000)\n")
        fixture.manifest_value["max_output_bytes"] = 100
        fixture.write_manifest()
        with self.assertRaisesRegex(CalculatorError, "byte limit"):
            calculate(manifest_path=fixture.manifest, spec_path=fixture.spec, artifacts_path=fixture.artifacts,
                      output_path=fixture.output, allow_local_code=True)


if __name__ == "__main__":
    unittest.main()
