"""Human-review handoff for persisted Evo runtime jobs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import runtime
from .review import export_review_package, merge_review_artifacts, review_completion
from .spec import EvoError, validate_artifacts
from .store import Store, fingerprint


def _rubric(job: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    rubric = job["runtime"].get("rubric")
    if not isinstance(rubric, dict) or set(rubric) != {"scoring", "fields", "blind"}:
        raise EvoError("runtime.rubric must be {scoring:<id>, fields:[assessment field ids], blind:bool}")
    if not isinstance(rubric["scoring"], str) or not rubric["scoring"]:
        raise EvoError("runtime.rubric.scoring must be a non-empty string")
    if (not isinstance(rubric["fields"], list) or not rubric["fields"] or
            any(not isinstance(value, str) or not value for value in rubric["fields"])):
        raise EvoError("runtime.rubric.fields must contain assessment field ids")
    if not isinstance(rubric["blind"], bool):
        raise EvoError("runtime.rubric.blind must be boolean")
    fields = {field["id"]: field for field in spec["fields"]}
    for field_id in rubric["fields"]:
        if field_id not in fields or fields[field_id]["grain"] != "assessment":
            raise EvoError(f"runtime rubric field must be a declared assessment field: {field_id}")
    if rubric["scoring"] not in {entry["id"] for entry in spec["scoring"]}:
        raise EvoError(f"runtime rubric references unknown scoring configuration: {rubric['scoring']}")
    return rubric


def _job_artifacts(store: Store, study_id: int, job_id: int, all_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    source = all_artifacts or runtime.artifacts(store, study_id)
    rows = [row for row in source["rows"] if row.get("dimensions", {}).get("job") == f"j{job_id}"]
    if not rows:
        raise EvoError(f"awaiting-human job j{job_id} has no recoverable runtime artifacts")
    return {
        "schema": source["schema"],
        "id": f"s{study_id}-j{job_id}",
        "version": fingerprint(rows),
        "rows": rows,
    }


def _runtime_package_path(store: Store, study_id: int, job_id: int) -> Path:
    return store.root / "reviews" / "runtime" / f"s{study_id}" / "public" / f"j{job_id}.json"


def _runtime_binding_path(store: Store, study_id: int, job_id: int) -> Path:
    return store.root / "reviews" / "runtime" / f"s{study_id}" / "bindings" / f"j{job_id}.json"


def _write_binding_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"cannot read runtime review binding {path}: {exc}") from exc
        if existing != value:
            raise EvoError(f"immutable runtime review binding conflicts for {path.stem}")


def _write_public_once(path: Path, package: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(package, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"cannot read editable review package {path}: {exc}") from exc
        if existing.get("package_id") != package["package_id"]:
            raise EvoError(f"runtime review package binding changed for j{path.stem.removeprefix('j')}")


def prepare_study_reviews(store: Store, study: int) -> list[dict[str, Any]]:
    study_row = store.study(study)
    spec = study_row["spec"]
    source = runtime.artifacts(store, study)
    prepared: list[dict[str, Any]] = []
    for job in store.jobs(study):
        if job["state"] != "awaiting_human":
            continue
        rubric = _rubric(job, spec)
        artifacts = _job_artifacts(store, study, job["id"], source)
        package = export_review_package(
            spec, artifacts, store.root, rubric["scoring"], rubric["fields"],
            blind=rubric["blind"],
        )
        path = _runtime_package_path(store, study, job["id"])
        _write_public_once(path, package)
        _write_binding_once(_runtime_binding_path(store, study, job["id"]), {
            "schema": "agentbase-evo-runtime-review-binding/v1", "study": study, "job": job["id"],
            "package_id": package["package_id"], "alias": package["alias"], "public_path": str(path),
        })
        prepared.append({"job": f"j{job['id']}", "package_id": package["package_id"], "alias": package["alias"], "path": str(path)})
    return prepared


def _runtime_packages(store: Store, study: int) -> list[tuple[int, Path, dict[str, Any]]]:
    root = store.root / "reviews" / "runtime" / f"s{study}" / "bindings"
    if not root.exists():
        return []
    result: list[tuple[int, Path, dict[str, Any]]] = []
    for path in sorted(root.glob("j*.json")):
        suffix = path.stem.removeprefix("j")
        if not suffix.isdecimal() or int(suffix) < 1:
            continue
        try:
            binding = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"cannot read editable review package {path}: {exc}") from exc
        if (binding.get("schema") != "agentbase-evo-runtime-review-binding/v1" or
                binding.get("study") != study or binding.get("job") != int(suffix) or
                not isinstance(binding.get("package_id"), str) or not isinstance(binding.get("public_path"), str)):
            raise EvoError(f"invalid runtime review binding: {path}")
        public_path = Path(binding["public_path"])
        expected = _runtime_package_path(store, study, int(suffix)).resolve()
        if public_path.resolve() != expected:
            raise EvoError(f"runtime review public path does not match its managed binding: {path}")
        result.append((int(suffix), public_path, binding))
    return result


def sync_study_reviews(store: Store, study: int) -> list[dict[str, Any]]:
    store.study(study)
    results: list[dict[str, Any]] = []
    for job_id, path, package in _runtime_packages(store, study):
        status = review_completion(store.root, package["package_id"])
        changed = False
        if status["complete"]:
            with store.connect(True) as db:
                row = db.execute("SELECT state FROM jobs WHERE id=? AND study=?", (job_id, study)).fetchone()
                if row is None:
                    raise EvoError(f"review package job j{job_id} does not belong to study s{study}")
                if row["state"] == "awaiting_human":
                    updated = db.execute(
                        "UPDATE jobs SET state='completed',reason='human review complete',workspace_slot=NULL "
                        "WHERE id=? AND study=? AND state='awaiting_human'", (job_id, study),
                    ).rowcount
                    if updated != 1:
                        raise EvoError(f"human review state changed concurrently for j{job_id}")
                    Store.event(db, study, job_id, "human_review_completed", {"package_id": package["package_id"]})
                    changed = True
                elif row["state"] != "completed":
                    raise EvoError(f"completed human review cannot advance job j{job_id} from {row['state']}")
        results.append({"job": f"j{job_id}", "alias": status["alias"], "path": str(path),
                        "complete": status["complete"], "missing": status["missing"], "state_changed": changed})
    return results


def study_artifacts_with_reviews(store: Store, study: int) -> dict[str, Any]:
    base = runtime.artifacts(store, study)
    rows = list(base["rows"])
    for job_id, _path, package in _runtime_packages(store, study):
        subset = _job_artifacts(store, study, job_id, base)
        merged = merge_review_artifacts(subset, store.root, package["package_id"])
        rows.extend(row for row in merged["rows"] if row["grain"] == "assessment")
    result = {**base, "version": fingerprint(rows), "rows": rows}
    validate_artifacts(result)
    return result
