from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate(records: list[dict], environment: str) -> dict[str, int]:
    selected = [record for record in records if record["environment"] == environment]
    return {
        "records": len(selected),
        "input_tokens": sum(record["usage"]["input_tokens"] for record in selected),
        "cached_input_tokens": sum(record["usage"]["cached_input_tokens"] for record in selected),
        "output_tokens": sum(record["usage"]["output_tokens"] for record in selected),
        "reasoning_output_tokens": sum(record["usage"]["reasoning_output_tokens"] for record in selected),
        "total_tokens": sum(record["usage"]["input_tokens"] + record["usage"]["output_tokens"] for record in selected),
        "elapsed_ms": sum(record["elapsed_ms"] for record in selected),
        "raw_oracle_passed": sum(bool(record["oracle_passed"]) for record in selected),
    }


def main() -> int:
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    report: list[dict] = []
    for experiment in index["experiments"]:
        result = experiment["result"]
        path = Path(result["observed_location"])
        item = {"id": experiment["id"], "available": path.is_file()}
        if not path.is_file():
            report.append(item)
            continue
        actual_hash = sha256(path)
        item["sha256"] = actual_hash
        if actual_hash != result["sha256"]:
            failures.append(f"{experiment['id']}: result hash mismatch")
            report.append(item)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        environments = set(experiment["aggregates"])
        item["aggregates"] = {}
        for environment in environments:
            actual = aggregate(payload["records"], environment)
            expected = experiment["aggregates"][environment]
            for key, value in actual.items():
                if expected[key] != value:
                    failures.append(f"{experiment['id']}/{environment}: {key} mismatch")
            item["aggregates"][environment] = actual
        report.append(item)
    print(json.dumps({"ok": not failures, "failures": failures, "experiments": report}, ensure_ascii=False, separators=(",", ":")))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
