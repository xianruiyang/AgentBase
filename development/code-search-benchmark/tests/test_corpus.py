from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "corpus" / "validate_corpus.py"
SPEC = importlib.util.spec_from_file_location("validate_corpus", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CorpusValidationTests(unittest.TestCase):
    def test_stale_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.txt"
            source.write_text("current", encoding="utf-8")
            corpus = root / "corpus.json"
            corpus.write_text(json.dumps({
                "schema": MODULE.SCHEMA,
                "cases": [{
                    "id": "stale",
                    "workspace_role": "agentbase",
                    "oracle": {"kind": "source-relation", "source": {"path": "source.txt", "sha256": "0" * 64}},
                }],
            }), encoding="utf-8")
            result = MODULE.validate(corpus, {"agentbase": root})
            self.assertFalse(result["ok"])
            self.assertIn("stale source", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
