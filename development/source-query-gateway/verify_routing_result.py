from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOOLEAN_FIELDS = ("authorization_required", "preview_required", "same_snapshot_required")


def load_cases(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(
            f"routing cases not found: {path}. Restore the local private file or pass --cases PATH."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["cases"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--cases", type=Path, default=ROOT / "routing-cases.json")
    args = parser.parse_args()
    expected_cases = load_cases(args.cases)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    actual_by_id = {case["id"]: case for case in result["cases"]}
    failures: list[str] = []
    if len(actual_by_id) != len(result["cases"]):
        failures.append("duplicate result IDs")
    if set(actual_by_id) != {case["id"] for case in expected_cases}:
        failures.append("result ID set differs")
    for case in expected_cases:
        actual = actual_by_id.get(case["id"], {})
        expected = case["expected"]
        for field in ("route", "reference"):
            if actual.get(field) != expected[field]:
                failures.append(f"{case['id']}: {field}")
        for field in BOOLEAN_FIELDS:
            if bool(expected.get(field, False)) and not bool(actual.get(field, False)):
                failures.append(f"{case['id']}: {field}")
    print(json.dumps({"ok": not failures, "cases": len(expected_cases), "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
