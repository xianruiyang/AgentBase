from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]


def resolve_artifact_path(path_value: str, artifact_root: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else artifact_root / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_legacy(records: list[dict], environment: str) -> dict[str, int]:
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


def aggregate_current(records: list[dict], environment: str) -> dict[str, int | float]:
    selected = [record for record in records if record["environment"] == environment]
    return {
        "records": len(selected),
        "input_tokens": sum(record["usage_breakdown"]["input_tokens"] for record in selected),
        "cached_input_tokens": sum(
            record["usage_breakdown"]["cache_read_input_tokens"] for record in selected
        ),
        "ordinary_input_tokens": sum(
            record["usage_breakdown"]["ordinary_input_tokens"] for record in selected
        ),
        "output_tokens": sum(record["usage_breakdown"]["output_tokens"] for record in selected),
        "reasoning_output_tokens": sum(
            record["usage_breakdown"]["reasoning_output_tokens"] for record in selected
        ),
        "total_tokens": sum(record["actual_total_tokens"] for record in selected),
        "elapsed_ms": sum(record["elapsed_ms"] for record in selected),
        "command_count": sum(
            record["completed_item_type_counts"].get("command_execution", 0)
            for record in selected
        ),
        "short_price_equivalent": sum(
            record["price_equivalent"]["short_context"]["exact"] for record in selected
        ),
        "long_price_equivalent": sum(
            record["price_equivalent"]["long_context"]["exact"] for record in selected
        ),
    }


def compare_aggregates(
    experiment_id: str,
    expected_by_environment: dict,
    actual_by_environment: dict,
    failures: list[str],
) -> None:
    for environment, expected in expected_by_environment.items():
        actual = actual_by_environment.get(environment)
        if actual is None:
            failures.append(f"{experiment_id}/{environment}: environment missing")
            continue
        for key, expected_value in expected.items():
            if key in actual and actual[key] != expected_value:
                failures.append(f"{experiment_id}/{environment}: {key} mismatch")


def verify_artifact(
    experiment_id: str,
    result: dict,
    path_key: str,
    hash_key: str,
    artifact_root: Path,
    failures: list[str],
) -> dict:
    relative_path = result.get(path_key)
    if relative_path is None:
        return {"declared": False}
    path = resolve_artifact_path(relative_path, artifact_root)
    item = {"declared": True, "path": relative_path, "available": path.is_file()}
    if not path.is_file():
        failures.append(f"{experiment_id}: {path_key} missing")
        return item
    actual_hash = sha256(path)
    item["sha256"] = actual_hash
    if actual_hash != result.get(hash_key):
        failures.append(f"{experiment_id}: {path_key} hash mismatch")
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=ROOT / "index.json")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT,
        help="root for relative artifact paths in the index (default: project root)",
    )
    args = parser.parse_args()
    if not args.index.is_file():
        raise SystemExit(
            f"history index not found: {args.index}. Restore the local private file or pass --index PATH."
        )
    artifact_root = args.artifact_root.resolve()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    failures: list[str] = []
    report: list[dict] = []
    for experiment in index["experiments"]:
        result = experiment["result"]
        experiment_id = experiment["id"]
        item = {"id": experiment_id}
        observed_location = result.get("observed_location")
        observed_summary = result.get("observed_summary")
        if observed_location is None and observed_summary is None:
            item["available"] = True
            item["artifacts"] = {
                "audit": verify_artifact(
                    experiment_id,
                    result,
                    "audit_artifact",
                    "audit_sha256",
                    artifact_root,
                    failures,
                ),
                "capsule_verification": verify_artifact(
                    experiment_id,
                    result,
                    "capsule_verification_artifact",
                    "capsule_verification_sha256",
                    artifact_root,
                    failures,
                ),
            }
            report.append(item)
            continue
        path = resolve_artifact_path(observed_location or observed_summary, artifact_root)
        item["available"] = path.is_file()
        if not path.is_file():
            report.append(item)
            continue
        actual_hash = sha256(path)
        item["sha256"] = actual_hash
        expected_hash = result.get("sha256", result.get("summary_sha256"))
        if actual_hash != expected_hash:
            failures.append(f"{experiment_id}: result hash mismatch")
            report.append(item)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        aggregate_fn = aggregate_legacy if observed_location else aggregate_current
        item["aggregates"] = {
            environment: aggregate_fn(payload["records"], environment)
            for environment in experiment["aggregates"]
        }
        if observed_summary and result.get("audit_artifact"):
            audit_path = resolve_artifact_path(result["audit_artifact"], artifact_root)
            if audit_path.is_file():
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                for environment in experiment["aggregates"]:
                    item["aggregates"][environment]["required_passed"] = sum(
                        bool(record["required_pass"])
                        for record in audit.get("per_run_contract_audit", [])
                        if record.get("environment") == environment
                    )
        compare_aggregates(
            experiment_id,
            experiment["aggregates"],
            item["aggregates"],
            failures,
        )
        item["artifacts"] = {
            "audit": verify_artifact(
                experiment_id,
                result,
                "audit_artifact",
                "audit_sha256",
                artifact_root,
                failures,
            )
        }
        report.append(item)
    print(json.dumps({"ok": not failures, "failures": failures, "experiments": report}, ensure_ascii=False, separators=(",", ":")))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
