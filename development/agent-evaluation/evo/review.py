from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .spec import EvoError, validate_artifacts, validate_spec
from evaluation_core import CaseLock, EvaluationError


REVIEW_PACKAGE_SCHEMA = "agentbase-evo-review-package/v1"
REVIEW_SUBMISSION_SCHEMA = "agentbase-evo-review-submission/v1"
ASSESSMENT_SCHEMA = "agentbase-evo-assessment/v1"
PROJECTION_SCHEMA = "agentbase-evo-review-projection/v1"
MACHINE_ID = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _identity(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_immutable(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise EvoError(f"immutable review record conflicts with existing file: {path}")


def _write_projection(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="projection-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _reviews_root(state_root: Path) -> Path:
    return state_root / "reviews"


def _selected_scoring(spec: dict[str, Any], scoring_id: str) -> dict[str, Any]:
    configs = {entry["id"]: entry for entry in spec["scoring"]}
    if scoring_id not in configs:
        raise EvoError(f"unknown scoring configuration: {scoring_id}")
    return configs[scoring_id]


def _assessment_fields(spec: dict[str, Any], field_ids: list[str]) -> list[dict[str, Any]]:
    fields = {entry["id"]: entry for entry in spec["fields"]}
    if not field_ids:
        raise EvoError("at least one assessment field is required")
    if len(field_ids) != len(set(field_ids)):
        raise EvoError("assessment fields contain duplicates")
    selected: list[dict[str, Any]] = []
    for field_id in field_ids:
        field = fields.get(field_id)
        if field is None:
            raise EvoError(f"unknown assessment field: {field_id}")
        if field["grain"] != "assessment":
            raise EvoError(f"review field {field_id} must use assessment grain")
        selected.append(field)
    return selected


def export_review_package(
    spec: dict[str, Any], artifacts: dict[str, Any], state_root: Path, scoring_id: str,
    field_ids: list[str], *, blind: bool = False, grains: list[str] | None = None,
    row_ids: list[str] | None = None,
) -> dict[str, Any]:
    validate_spec(spec)
    validate_artifacts(artifacts)
    scoring = _selected_scoring(spec, scoring_id)
    fields = _assessment_fields(spec, field_ids)
    artifact_rows = artifacts["rows"]
    known_rows = {row["id"] for row in artifact_rows}
    if row_ids is not None:
        if len(row_ids) != len(set(row_ids)):
            raise EvoError("review row selection contains duplicates")
        unknown_rows = set(row_ids) - known_rows
        if unknown_rows:
            raise EvoError(f"review selection references unknown artifact rows: {sorted(unknown_rows)}")
    if grains is not None and (not grains or any(not isinstance(grain, str) or not grain for grain in grains)):
        raise EvoError("review grain selection must contain non-empty strings")
    if row_ids is None and grains is None:
        grains = ["attempt"]
    selected_rows = [
        row for row in artifact_rows
        if (row_ids is None or row["id"] in row_ids) and (grains is None or row["grain"] in grains)
    ]
    if not selected_rows:
        if row_ids is None and grains == ["attempt"]:
            raise EvoError("artifacts contain no attempt rows; select review rows or grains explicitly")
        raise EvoError("review selection is empty")
    aliases: dict[str, str] = {}
    public_items: list[dict[str, Any]] = []
    bindings: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(selected_rows, 1):
        review_key = f"item-{index:04d}"
        dimensions = dict(row.get("dimensions", {}))
        combination = dimensions.get("combination")
        if blind and combination is not None:
            aliases.setdefault(str(combination), f"candidate-{len(aliases) + 1}")
            dimensions["combination"] = aliases[str(combination)]
        public_source = ({"kind": "archived-evidence", "location": f"evidence/{review_key}"}
                         if blind else row["source"])
        public_items.append({
            "review_key": review_key,
            "dimensions": dimensions,
            "values": row["values"],
            "source": public_source,
            "completeness": row["completeness"],
        })
        bindings[review_key] = {"artifact_row": row}
    rubric_content = scoring.get("rubric")
    if rubric_content is None:
        rubric_content = {
            "instructions": "Score each listed field from the supplied evidence. A blank value remains awaiting review.",
            "assessment_fields": [
                {"id": field["id"], "type": field["type"], "unit": field["unit"], "description": field.get("description", field["source"])}
                for field in fields
            ],
            "score_scope": {"select": scoring.get("select", {}), "group_by": scoring.get("group_by", []), "metrics": scoring["metrics"]},
        }
    rubric_binding = {"id": scoring_id, "version": scoring["version"], "sha256": _identity(scoring), "content": rubric_content}
    frozen = {
        "research": {"id": spec["id"], "version": spec["version"], "sha256": _identity(spec)},
        "artifacts": {"id": artifacts["id"], "version": artifacts["version"], "sha256": _identity(artifacts)},
        "rubric": rubric_binding,
        "fields": [{"id": field["id"], "type": field["type"], "unit": field["unit"], "sha256": _identity(field)} for field in fields],
        "blind": blind,
        "bindings": bindings,
    }
    package_id = _identity(frozen)
    short_alias = f"review-{package_id[:8]}"
    public_binding = {
        "research": frozen["research"],
        "artifacts": ({**frozen["artifacts"], "id": "anonymous-artifacts"} if blind else frozen["artifacts"]),
        "rubric": rubric_binding,
        "fields": frozen["fields"],
    }
    manifest = {"schema": REVIEW_PACKAGE_SCHEMA, "package_id": package_id, "alias": short_alias, **frozen, "public_binding": public_binding}
    _write_immutable(_reviews_root(state_root) / "packages" / f"{package_id}.json", manifest)
    return {
        "schema": REVIEW_PACKAGE_SCHEMA,
        "package_id": package_id,
        "alias": short_alias,
        **public_binding,
        "blind": blind,
        "blind_scope": ("Candidate labels and original evidence locations are hidden; evidence values and task dimensions remain visible for judging." if blind else "Candidate and evidence identities are visible."),
        "items": public_items,
        "assessments": [],
    }


def _read_manifest(state_root: Path, package_reference: str) -> dict[str, Any]:
    if not isinstance(package_reference, str) or not package_reference:
        raise EvoError("review package id or alias must be a non-empty string")
    packages = _reviews_root(state_root) / "packages"
    if MACHINE_ID.fullmatch(package_reference):
        package_id = package_reference
    elif re.fullmatch(r"review-[0-9a-f]{8}", package_reference):
        matches = []
        if packages.exists():
            for candidate in packages.glob("*.json"):
                if MACHINE_ID.fullmatch(candidate.stem):
                    try:
                        value = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                        raise EvoError(f"cannot read frozen review package {candidate}: {exc}") from exc
                    if value.get("alias") == package_reference:
                        matches.append(value["package_id"])
        if len(matches) != 1:
            raise EvoError(f"review package alias must resolve uniquely: {package_reference}")
        package_id = matches[0]
    else:
        raise EvoError("review package reference must be a 64-character machine id or review-xxxxxxxx alias")
    path = packages / f"{package_id}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoError(f"cannot read frozen review package {package_reference}: {exc}") from exc
    if manifest.get("schema") != REVIEW_PACKAGE_SCHEMA or manifest.get("package_id") != package_id:
        raise EvoError(f"invalid frozen review package: {package_reference}")
    return manifest


def _records(state_root: Path) -> list[dict[str, Any]]:
    directory = _reviews_root(state_root) / "assessments"
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"cannot read assessment record {path}: {exc}") from exc
        if record.get("schema") != ASSESSMENT_SCHEMA or record.get("assessment_id") != path.stem:
            raise EvoError(f"invalid immutable assessment record: {path}")
        records.append(record)
    return records


def _build_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {record["assessment_id"]: record for record in records}
    superseded: set[str] = set()
    coordinates: dict[tuple[str, str, str], list[str]] = {}
    for record in records:
        coordinate = (record["package_id"], record["review_key"], record["field"])
        coordinates.setdefault(coordinate, []).append(record["assessment_id"])
        parent = record.get("supersedes")
        if parent:
            previous = by_id.get(parent)
            if previous is None:
                raise EvoError(f"assessment {record['assessment_id']} supersedes unknown assessment: {parent}")
            prior_coordinate = (previous["package_id"], previous["review_key"], previous["field"])
            if prior_coordinate != coordinate:
                raise EvoError(f"assessment {record['assessment_id']} supersedes a different review item")
            superseded.add(parent)
    heads: dict[str, dict[str, Any]] = {}
    for coordinate, identities in coordinates.items():
        live = [identity for identity in identities if identity not in superseded]
        if len(live) != 1:
            raise EvoError(f"review coordinate has {len(live)} current assessments: {coordinate}")
        heads["|".join(coordinate)] = by_id[live[0]]
    return {"schema": PROJECTION_SCHEMA, "record_count": len(records), "heads": heads}


def load_review_projection(state_root: Path) -> dict[str, Any]:
    projection = _build_projection(_records(state_root))
    _write_projection(_reviews_root(state_root) / "projection.json", projection)
    return projection


def _valid_value(value: Any, field: dict[str, Any]) -> bool:
    kind = field["type"]
    return ((kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)) or
            (kind == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
            (kind == "boolean" and isinstance(value, bool)) or
            (kind == "string" and isinstance(value, str)))


def import_review_assessments(state_root: Path, submission: dict[str, Any]) -> dict[str, Any]:
    try:
        with CaseLock(state_root, "evo-review-assessments"):
            return _import_review_assessments_locked(state_root, submission)
    except EvaluationError as exc:
        raise EvoError(str(exc)) from exc


def _import_review_assessments_locked(state_root: Path, submission: dict[str, Any]) -> dict[str, Any]:
    if submission.get("schema") not in {REVIEW_SUBMISSION_SCHEMA, REVIEW_PACKAGE_SCHEMA}:
        raise EvoError(f"review submission schema must be {REVIEW_SUBMISSION_SCHEMA}")
    package_id = submission.get("package_id")
    if not isinstance(package_id, str) or not package_id:
        raise EvoError("review submission package_id must be a non-empty string")
    manifest = _read_manifest(state_root, package_id)
    for key in ("research", "artifacts", "rubric", "fields"):
        if submission.get(key) != manifest["public_binding"][key]:
            raise EvoError(f"review submission {key} binding does not match frozen package")
    assessments = submission.get("assessments")
    if not isinstance(assessments, list):
        raise EvoError("review submission assessments must be an array")
    fields = {field["id"]: field for field in manifest["fields"]}
    persisted = _records(state_root)
    existing = _build_projection(persisted)
    known_ids = {item["assessment_id"] for item in persisted}
    pending: list[dict[str, Any]] = []
    imported: list[str] = []
    skipped_blank = 0
    for index, raw in enumerate(assessments):
        if not isinstance(raw, dict):
            raise EvoError(f"assessments[{index}] must be an object")
        review_key = raw.get("review_key")
        field_id = raw.get("field")
        if review_key not in manifest["bindings"]:
            raise EvoError(f"assessment references unknown review_key: {review_key}")
        if field_id not in fields:
            raise EvoError(f"assessment references unbound field: {field_id}")
        value = raw.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            skipped_blank += 1
            continue
        if not _valid_value(value, fields[field_id]):
            raise EvoError(f"assessment value for {field_id} does not match type {fields[field_id]['type']}")
        supersedes = raw.get("supersedes")
        if supersedes is not None and (not isinstance(supersedes, str) or not supersedes):
            raise EvoError("assessment supersedes must be a non-empty assessment id")
        comment = raw.get("comment", "")
        reviewer = raw.get("reviewer", "human")
        if not isinstance(comment, str) or not isinstance(reviewer, str) or not reviewer.strip():
            raise EvoError("assessment comment and reviewer must be strings, with a non-empty reviewer")
        body = {
            "schema": ASSESSMENT_SCHEMA,
            "package_id": package_id,
            "review_key": review_key,
            "artifact_row_id": manifest["bindings"][review_key]["artifact_row"]["id"],
            "field": field_id,
            "value": value,
            "comment": comment,
            "reviewer": reviewer,
            "supersedes": supersedes,
        }
        assessment_id = _identity(body)
        record = {**body, "assessment_id": assessment_id}
        if assessment_id in known_ids:
            imported.append(assessment_id)
            continue
        coordinate = f"{package_id}|{review_key}|{field_id}"
        current = existing["heads"].get(coordinate)
        if current is not None and supersedes != current["assessment_id"]:
            raise EvoError(f"correction for {review_key}/{field_id} must explicitly supersede current assessment {current['assessment_id']}")
        if current is None and supersedes is not None:
            raise EvoError(f"initial assessment for {review_key}/{field_id} must not supersede another record")
        pending.append(record)
        known_ids.add(assessment_id)
        imported.append(assessment_id)
        existing = _build_projection([*persisted, *pending])
    for record in pending:
        _write_immutable(_reviews_root(state_root) / "assessments" / f"{record['assessment_id']}.json", record)
    projection = load_review_projection(state_root)
    status = review_completion(state_root, package_id, projection=projection)
    return {"package_id": package_id, "imported": imported, "skipped_blank": skipped_blank, **status}


def review_completion(state_root: Path, package_id: str, *, projection: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = _read_manifest(state_root, package_id)
    package_id = manifest["package_id"]
    current = projection or load_review_projection(state_root)
    missing = [
        {"review_key": review_key, "field": field["id"]}
        for review_key in manifest["bindings"]
        for field in manifest["fields"]
        if f"{package_id}|{review_key}|{field['id']}" not in current["heads"]
    ]
    return {"alias": manifest["alias"], "complete": not missing, "missing": missing}


def merge_review_artifacts(artifacts: dict[str, Any], state_root: Path, package_id: str) -> dict[str, Any]:
    try:
        with CaseLock(state_root, "evo-review-assessments"):
            return _merge_review_artifacts_locked(artifacts, state_root, package_id)
    except EvaluationError as exc:
        raise EvoError(str(exc)) from exc


def _merge_review_artifacts_locked(artifacts: dict[str, Any], state_root: Path, package_id: str) -> dict[str, Any]:
    validate_artifacts(artifacts)
    manifest = _read_manifest(state_root, package_id)
    package_id = manifest["package_id"]
    if manifest["artifacts"] != {"id": artifacts["id"], "version": artifacts["version"], "sha256": _identity(artifacts)}:
        raise EvoError("artifacts do not match frozen review package")
    projection = load_review_projection(state_root)
    rows = list(artifacts["rows"])
    for coordinate, record in sorted(projection["heads"].items()):
        if record["package_id"] != package_id:
            continue
        source_row = manifest["bindings"][record["review_key"]]["artifact_row"]
        rows.append({
            "id": f"assessment-{record['assessment_id']}",
            "grain": "assessment",
            "dimensions": {**source_row.get("dimensions", {}), "review_key": record["review_key"]},
            "values": {record["field"]: record["value"]},
            "source": {"kind": "human-assessment", "location": f"reviews/assessments/{record['assessment_id']}.json"},
            "completeness": "complete",
        })
    merged = {**artifacts, "version": f"{artifacts['version']}+{manifest['alias']}", "rows": rows}
    validate_artifacts(merged)
    return merged
