#!/usr/bin/env python3
"""Deterministic, evidence-backed task state for long-running Codex plans."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PLAN_SCHEMA = "task.plan.v1"
STATE_SCHEMA = "task.state.v1"
EVIDENCE_SCHEMA = "task.evidence.v1"
INDEX_SCHEMA = "task.evidence.index.v1"
DECISION_SCHEMA = "task.decision.v1"
COMPLETION_SCHEMA = "task.completion.v1"
PLANNING_AUDIT_SCHEMA = "task.planning-audit.v1"

TASK_STATUSES = {"todo", "ready", "active", "needs_review", "done", "blocked"}
SOURCE_CLASSES = {"registered_machine", "derived_machine", "human_decision", "agent_context"}
TRUST_STATES = {"qualified", "untrusted_legacy", "retired", "invalid"}
TESTS_FIRST_MODES = {"required", "prequalified", "not_applicable"}
VERIFICATION_MODES = {"task_evidence", "direct_flow"}
SOURCE_INVENTORY_MODES = {"advisory", "exact"}
SOURCE_FINGERPRINT_MODES = {"label", "file_sha256"}
EVIDENCE_SHAPES = {"module", "vertical"}
FLOW_EVIDENCE_MODES = {"single_receipt", "coverage_matrix"}
ENFORCEMENT_PROFILES = {"legacy_compat", "strict_v1", "strict_v2"}
STRICT_ENFORCEMENT_PROFILE = "strict_v1"
PIPELINE_STRICT_ENFORCEMENT_PROFILE = "strict_v2"
STRICT_ENFORCEMENT_PROFILES = {
    STRICT_ENFORCEMENT_PROFILE,
    PIPELINE_STRICT_ENFORCEMENT_PROFILE,
}
LEGACY_ENFORCEMENT_PROFILE = "legacy_compat"
TRACE_ORIGIN_KINDS = {"user_explicit", "confirmed_design", "derived_proposal"}
GAP_STATUSES = {"satisfied", "partial", "missing", "unknown"}
UNCERTAINTY_BOUNDARY_FIELDS = {
    "owner",
    "identity",
    "lifecycle",
    "persistence",
    "build",
}
TRACE_SOURCE_INVENTORIES = {
    "acceptance_clause": ("acceptance_clause_ids", "acceptance_clause_prefix"),
    "design_clause": ("design_clause_ids", "design_clause_prefix"),
    "solution_step": ("solution_step_ids", "solution_step_prefix"),
    "gap_item": ("gap_ids", "gap_prefix"),
}
COMPLETION_LEVELS = {
    "contract_ready": 0,
    "scaffold_ready": 1,
    "module_ready": 2,
    "integration_ready": 3,
    "production_ready": 4,
    "domain_complete": 5,
}
EVIDENCE_RESULTS = {"pass", "expected_fail", "fail"}
PHASES = {"tests", "implementation", "verification"}
BASE_FRESHNESS_KEYS = {"contract", "production_scope", "test_scope"}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
CLAIM_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[/\\]")


class TaskCtlError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def _require(condition: bool, message: str, *, code: str = "invalid") -> None:
    if not condition:
        raise TaskCtlError(message, code=code)


def _expect_object(value: Any, path: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{path} must be an object")
    return value


def _expect_list(value: Any, path: str) -> list[Any]:
    _require(isinstance(value, list), f"{path} must be an array")
    return value


def _expect_string(value: Any, path: str, *, nonempty: bool = True) -> str:
    _require(isinstance(value, str), f"{path} must be a string")
    if nonempty:
        _require(bool(value.strip()), f"{path} must not be empty")
    return value


def _expect_id(value: Any, path: str) -> str:
    text = _expect_string(value, path)
    _require(bool(ID_RE.fullmatch(text)), f"{path} has an invalid id: {text!r}")
    return text


def _expect_claim(value: Any, path: str) -> str:
    text = _expect_string(value, path)
    _require(bool(CLAIM_RE.fullmatch(text)), f"{path} has an invalid claim id: {text!r}")
    return text


def _enforcement_profile(plan: dict[str, Any]) -> str:
    return plan.get("enforcement_profile", LEGACY_ENFORCEMENT_PROFILE)


def _validate_uncertainty_boundary(value: Any, path: str) -> dict[str, str]:
    boundary = _expect_object(value, path)
    _expect_keys(
        boundary,
        required=UNCERTAINTY_BOUNDARY_FIELDS,
        optional=set(),
        path=path,
    )
    return {
        field: _expect_string(boundary[field], f"{path}.{field}")
        for field in sorted(UNCERTAINTY_BOUNDARY_FIELDS)
    }


def _expect_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    _require(not missing, f"{path} is missing fields: {', '.join(missing)}")
    _require(not unknown, f"{path} has unknown fields: {', '.join(unknown)}")


def _unique_strings(
    value: Any,
    path: str,
    *,
    ids: bool = False,
    claims: bool = False,
    allow_empty: bool = True,
) -> list[str]:
    items = _expect_list(value, path)
    if not allow_empty:
        _require(bool(items), f"{path} must not be empty")
    result: list[str] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if ids:
            result.append(_expect_id(item, item_path))
        elif claims:
            result.append(_expect_claim(item, item_path))
        else:
            result.append(_expect_string(item, item_path))
    _require(len(result) == len(set(result)), f"{path} contains duplicate values")
    return result


def _load_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"missing JSON file: {path}", code="missing_file")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskCtlError(f"cannot read JSON {path}: {exc}", code="invalid_json") from exc
    return _expect_object(data, str(path))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _json_identity(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _controller_identity() -> str:
    script_path = Path(__file__).resolve()
    skill_path = script_path.parents[1] / "SKILL.md"
    inputs = []
    for path in (script_path, skill_path):
        _require(path.is_file(), f"controller identity input is missing: {path}")
        inputs.append({"name": path.name, "sha256": _sha256_file(path)})
    return _json_identity(inputs)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_bytes_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        _require(path.is_file(), f"immutable evidence path is not a file: {path}")
        _require(path.read_bytes() == payload, f"immutable evidence snapshot conflict: {path}")
        return
    _write_bytes_atomic(path, payload)


def _write_json_atomic(path: Path, value: Any) -> None:
    _write_bytes_atomic(path, _pretty_bytes(value))


def _write_state(plan_dir: Path, state: dict[str, Any]) -> None:
    state_path = plan_dir / "state.json"
    previous_path = plan_dir / "state.prev.json"
    if state_path.is_file():
        _write_bytes_atomic(previous_path, state_path.read_bytes())
    _write_json_atomic(state_path, state)


def _write_plan(plan_dir: Path, plan: dict[str, Any]) -> None:
    plan_path = plan_dir / "plan.json"
    previous_path = plan_dir / "plan.prev.json"
    if plan_path.is_file():
        _write_bytes_atomic(previous_path, plan_path.read_bytes())
    _write_json_atomic(plan_path, plan)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_relative_path(value: str, path: str) -> str:
    text = value.replace("\\", "/")
    pure = PurePosixPath(text)
    _require(not pure.is_absolute(), f"{path} must be relative")
    _require(not WINDOWS_ABSOLUTE_RE.match(text), f"{path} must be relative")
    _require(".." not in pure.parts, f"{path} must not traverse outside its root")
    _require(bool(pure.parts), f"{path} must not be empty")
    return pure.as_posix()


def _task_dir(args: argparse.Namespace) -> Path:
    raw = Path(_expect_string(args.task_dir, "--task-dir")).expanduser()
    _require(
        raw.is_absolute(),
        "--task-dir must be an absolute path",
        code="task_dir_not_absolute",
    )
    task_dir = raw.resolve()
    _require(
        task_dir.is_dir(),
        f"task directory does not exist: {task_dir}",
        code="missing_task_dir",
    )
    return task_dir


def _project_root(plan_dir: Path, explicit: str | None) -> Path:
    if explicit:
        raw = Path(explicit).expanduser()
        _require(
            raw.is_absolute(),
            "--project-root must be an absolute path",
            code="project_root_not_absolute",
        )
        root = raw.resolve()
        _require(root.is_dir(), f"project root does not exist: {root}", code="missing_project_root")
        _require(_inside(plan_dir, root), f"task directory is outside project root: {plan_dir}")
        return root
    if plan_dir.parent.name.lower() == "plan" and plan_dir.parent.parent.name.lower() == "docs":
        return plan_dir.parent.parent.parent.resolve()
    raise TaskCtlError("cannot infer project root; pass --project-root", code="missing_project_root")


def _resolve_allowed_path(
    value: str,
    *,
    root_kind: str,
    project_root: Path,
    plan_dir: Path,
) -> Path:
    relative = _validate_relative_path(value, "artifact path")
    root = project_root if root_kind == "project" else plan_dir
    resolved = (root / Path(relative)).resolve()
    _require(_inside(resolved, root), f"artifact path escapes {root_kind} root: {value}")
    return resolved


def _expand_scope(project_root: Path, entries: Iterable[str]) -> tuple[str, int, list[str]]:
    records: dict[str, str] = {}
    missing: list[str] = []
    for raw_entry in entries:
        entry = _validate_relative_path(raw_entry, "scope path")
        has_magic = any(character in entry for character in "*?[")
        candidates: list[Path]
        if has_magic:
            candidates = [candidate for candidate in project_root.glob(entry) if candidate.is_file()]
            if not candidates:
                missing.append(entry)
        else:
            candidate = (project_root / Path(entry)).resolve()
            _require(_inside(candidate, project_root), f"scope path escapes project root: {entry}")
            if candidate.is_file():
                candidates = [candidate]
            elif candidate.is_dir():
                candidates = [item for item in candidate.rglob("*") if item.is_file()]
            else:
                candidates = []
                missing.append(entry)
        for candidate in candidates:
            resolved = candidate.resolve()
            _require(_inside(resolved, project_root), f"scope file escapes project root: {candidate}")
            relative = resolved.relative_to(project_root).as_posix()
            records[relative] = _sha256_file(resolved)
    digest_input = {
        "files": [{"path": path, "sha256": records[path]} for path in sorted(records)],
        "missing": sorted(set(missing)),
    }
    return _json_identity(digest_input), len(records), sorted(set(missing))


def _plan_hash(plan: dict[str, Any]) -> str:
    return _json_identity(plan)


def _task_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in plan["tasks"]}


def _requirement_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {requirement["id"]: requirement for requirement in plan["requirements"]}


def _required_claims(plan: dict[str, Any], task: dict[str, Any]) -> list[str]:
    overrides = task.get("claim_overrides", {})
    claims = overrides.get("required_claims")
    if claims:
        return list(claims)
    return list(plan["evidence_profiles"][task["claim_profile"]]["required_claims"])


def _claim_rule(plan: dict[str, Any], task: dict[str, Any], claim: str) -> dict[str, Any]:
    profile = plan["evidence_profiles"][task["claim_profile"]]
    return profile["claim_rules"][claim]


def _task_contract_identity(plan: dict[str, Any], task: dict[str, Any]) -> str:
    requirements = _requirement_map(plan)
    claims = _required_claims(plan, task)
    profile = plan["evidence_profiles"][task["claim_profile"]]
    producer_ids: set[str] = set()
    for claim in claims:
        producer_ids.update(profile["claim_rules"][claim]["producers"])
    test_ids = task.get("claim_overrides", {}).get("automation_test_ids", [])
    task_contract = {
        key: task.get(key)
        for key in (
            "id",
            "outcome",
            "completion_level",
            "claim_scope",
            "requirement_ids",
            "depends_on",
            "mutation_scope",
            "test_scope",
            "freshness_scopes",
            "build_profile",
            "rollback_scope",
            "claim_profile",
            "claim_overrides",
            "tests_first",
        )
    }
    # Keep existing evidence compatible when the optional field is absent or
    # empty. Only a real planned scope changes the task contract identity.
    if task.get("planned_test_scope"):
        task_contract["planned_test_scope"] = task["planned_test_scope"]
    data = {
        "task": task_contract,
        "requirements": [requirements[requirement_id] for requirement_id in task["requirement_ids"]],
        "profile": {
            "required_claims": claims,
            "claim_rules": {claim: profile["claim_rules"][claim] for claim in claims},
        },
        "producers": {producer_id: plan["producers"][producer_id] for producer_id in sorted(producer_ids)},
        "test_qualifications": {
            test_id: plan["test_qualifications"].get(test_id) for test_id in sorted(test_ids)
        },
    }
    return _json_identity(data)


def _task_identities(
    plan: dict[str, Any],
    task: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    production, production_count, production_missing = _expand_scope(project_root, task["mutation_scope"])
    planned_test_scope = task.get("planned_test_scope", [])
    tests, test_count, all_test_missing = _expand_scope(
        project_root, [*task["test_scope"], *planned_test_scope]
    )
    _, _, test_missing = _expand_scope(project_root, task["test_scope"])
    _, _, planned_test_missing = _expand_scope(project_root, planned_test_scope)
    result: dict[str, Any] = {
        "contract": _task_contract_identity(plan, task),
        "production_scope": production,
        "test_scope": tests,
        "scope_summary": {
            "production_files": production_count,
            "test_files": test_count,
            "production_missing": production_missing,
            "test_missing": test_missing,
            "planned_test_missing": planned_test_missing,
            "missing": production_missing + test_missing + planned_test_missing,
            "custom": {},
        },
    }
    for key, entries in sorted(task["freshness_scopes"].items()):
        identity, count, missing = _expand_scope(project_root, entries)
        result[key] = identity
        result["scope_summary"]["custom"][key] = {"files": count, "missing": missing}
    return result


def _validate_plan(
    plan: dict[str, Any],
    *,
    enforce_source_durability: bool = True,
) -> None:
    _expect_keys(
        plan,
        required={
            "schema",
            "plan_id",
            "design_revision",
            "scope_sources",
            "requirements",
            "producers",
            "evidence_profiles",
            "test_qualifications",
            "groups",
            "tasks",
        },
        optional={
            "decision_refs",
            "acceptance_flows",
            "enforcement_profile",
            "acceptance_clauses",
            "design_clauses",
            "solution_steps",
            "gap_items",
            "planning_audit",
        },
        path="plan",
    )
    _require(plan["schema"] == PLAN_SCHEMA, f"plan.schema must be {PLAN_SCHEMA}")
    _expect_id(plan["plan_id"], "plan.plan_id")
    _expect_string(plan["design_revision"], "plan.design_revision")
    plan_decision_refs = set(
        _unique_strings(plan.get("decision_refs", []), "plan.decision_refs")
    )
    enforcement_profile = _expect_string(
        _enforcement_profile(plan), "plan.enforcement_profile"
    )
    _require(
        enforcement_profile in ENFORCEMENT_PROFILES,
        f"plan.enforcement_profile must be one of {', '.join(sorted(ENFORCEMENT_PROFILES))}",
    )
    strict = enforcement_profile in STRICT_ENFORCEMENT_PROFILES
    pipeline_strict = enforcement_profile == PIPELINE_STRICT_ENFORCEMENT_PROFILE
    if pipeline_strict:
        for field in (
            "acceptance_clauses",
            "design_clauses",
            "solution_steps",
            "gap_items",
            "planning_audit",
        ):
            _require(field in plan, f"strict_v2 plan must declare {field}")

    source_ids: set[str] = set()
    sources_by_id: dict[str, dict[str, Any]] = {}
    scope_sources = _expect_list(plan["scope_sources"], "plan.scope_sources")
    _require(bool(scope_sources), "plan.scope_sources must not be empty")
    for index, source_value in enumerate(scope_sources):
        source = _expect_object(source_value, f"plan.scope_sources[{index}]")
        _expect_keys(
            source,
            required={"id", "ref"},
            optional={
                "fingerprint",
                "inventory_mode",
                "requirement_ids",
                "fingerprint_mode",
                "root",
                "source_audit_ref",
                "inventory_prefix",
                "acceptance_clause_ids",
                "acceptance_clause_prefix",
                "design_clause_ids",
                "design_clause_prefix",
                "solution_step_ids",
                "solution_step_prefix",
                "gap_ids",
                "gap_prefix",
            },
            path=f"plan.scope_sources[{index}]",
        )
        source_id = _expect_id(source["id"], f"plan.scope_sources[{index}].id")
        _require(source_id not in source_ids, f"duplicate scope source id: {source_id}")
        source_ids.add(source_id)
        sources_by_id[source_id] = source
        _expect_string(source["ref"], f"plan.scope_sources[{index}].ref")
        if "fingerprint" in source:
            _expect_string(source["fingerprint"], f"plan.scope_sources[{index}].fingerprint")
        if strict:
            _require("fingerprint" in source, f"strict source {source_id} must declare fingerprint")
            _require(
                "inventory_mode" in source,
                f"strict source {source_id} must declare inventory_mode",
            )
            _require(
                "fingerprint_mode" in source,
                f"strict source {source_id} must declare fingerprint_mode",
            )
        inventory_mode = _expect_string(
            source.get("inventory_mode", "advisory"),
            f"plan.scope_sources[{index}].inventory_mode",
        )
        _require(inventory_mode in SOURCE_INVENTORY_MODES, f"source {source_id} has invalid inventory_mode")
        declared_requirements = _unique_strings(
            source.get("requirement_ids", []),
            f"plan.scope_sources[{index}].requirement_ids",
            ids=True,
        )
        inventory_prefix = source.get("inventory_prefix")
        if inventory_prefix is not None:
            inventory_prefix = _expect_string(
                inventory_prefix,
                f"plan.scope_sources[{index}].inventory_prefix",
            )
            _require(
                all(requirement_id.startswith(inventory_prefix) for requirement_id in declared_requirements),
                f"source {source_id} inventory contains ids outside prefix {inventory_prefix}",
            )
        fingerprint_mode = _expect_string(
            source.get("fingerprint_mode", "label"),
            f"plan.scope_sources[{index}].fingerprint_mode",
        )
        _require(
            fingerprint_mode in SOURCE_FINGERPRINT_MODES,
            f"source {source_id} has invalid fingerprint_mode",
        )
        if inventory_mode == "exact":
            _require(bool(declared_requirements), f"source {source_id} exact inventory must not be empty")
            _expect_string(source.get("source_audit_ref"), f"plan.scope_sources[{index}].source_audit_ref")
            _require("fingerprint" in source, f"source {source_id} exact inventory requires fingerprint")
            _expect_string(
                source.get("inventory_prefix"),
                f"plan.scope_sources[{index}].inventory_prefix",
            )
        if fingerprint_mode == "file_sha256":
            _require("fingerprint" in source, f"source {source_id} file_sha256 requires fingerprint")
            root_kind = _expect_string(source.get("root"), f"plan.scope_sources[{index}].root")
            _require(root_kind in {"project", "task"}, f"source {source_id} has invalid root")
        elif "root" in source:
            _require(False, f"source {source_id}.root is only valid for file_sha256")
        for kind, (ids_field, prefix_field) in TRACE_SOURCE_INVENTORIES.items():
            declared_trace_ids = _unique_strings(
                source.get(ids_field, []),
                f"plan.scope_sources[{index}].{ids_field}",
                ids=True,
            )
            prefix_value = source.get(prefix_field)
            if declared_trace_ids:
                prefix = _expect_string(
                    prefix_value,
                    f"plan.scope_sources[{index}].{prefix_field}",
                )
                _require(
                    all(item_id.startswith(prefix) for item_id in declared_trace_ids),
                    f"source {source_id} {kind} inventory contains ids outside prefix {prefix}",
                )
                _require(
                    fingerprint_mode == "file_sha256",
                    f"source {source_id} {kind} inventory requires file_sha256",
                )
            elif prefix_value is not None:
                _require(
                    False,
                    f"source {source_id}.{prefix_field} requires a non-empty {ids_field}",
                )

    requirement_ids: set[str] = set()
    in_scope_requirements: set[str] = set()
    direct_flow_requirements: set[str] = set()
    acceptance_scope_by_requirement: dict[str, set[str]] = {}
    observable_claims_by_requirement: dict[str, set[str]] = {}
    for index, requirement_value in enumerate(_expect_list(plan["requirements"], "plan.requirements")):
        path = f"plan.requirements[{index}]"
        requirement = _expect_object(requirement_value, path)
        _expect_keys(
            requirement,
            required={"id", "source_ref", "source_fingerprint", "status", "observable_claims"},
            optional={
                "out_of_scope_reason",
                "user_decision_ref",
                "verification_mode",
                "acceptance_scope",
            },
            path=path,
        )
        requirement_id = _expect_id(requirement["id"], f"{path}.id")
        _require(requirement_id not in requirement_ids, f"duplicate requirement id: {requirement_id}")
        requirement_ids.add(requirement_id)
        source_ref = _expect_string(requirement["source_ref"], f"{path}.source_ref")
        _require(
            any(source_ref == source_id or source_ref.startswith(source_id + ":") for source_id in source_ids),
            f"{path}.source_ref must belong to a registered scope source",
        )
        _expect_string(requirement["source_fingerprint"], f"{path}.source_fingerprint")
        status = _expect_string(requirement["status"], f"{path}.status")
        _require(status in {"in_scope", "out_of_scope"}, f"{path}.status is invalid")
        observable_claims = _unique_strings(
            requirement["observable_claims"], f"{path}.observable_claims", claims=True
        )
        if status == "in_scope":
            _require(bool(observable_claims), f"{path}.observable_claims must not be empty for in_scope")
            in_scope_requirements.add(requirement_id)
            _require("out_of_scope_reason" not in requirement, f"{path} cannot carry out_of_scope_reason")
            if strict:
                _require(
                    "verification_mode" in requirement,
                    f"strict in-scope requirement {requirement_id} must declare verification_mode",
                )
                _require(
                    "acceptance_scope" in requirement,
                    f"strict in-scope requirement {requirement_id} must declare acceptance_scope",
                )
            verification_mode = _expect_string(
                requirement.get("verification_mode", "task_evidence"),
                f"{path}.verification_mode",
            )
            _require(verification_mode in VERIFICATION_MODES, f"{path}.verification_mode is invalid")
            acceptance_scope = set(
                _unique_strings(requirement.get("acceptance_scope", []), f"{path}.acceptance_scope")
            )
            if verification_mode == "direct_flow":
                _require(bool(acceptance_scope), f"{path}.acceptance_scope must not be empty for direct_flow")
                direct_flow_requirements.add(requirement_id)
            acceptance_scope_by_requirement[requirement_id] = acceptance_scope
            observable_claims_by_requirement[requirement_id] = set(observable_claims)
        else:
            _expect_string(requirement.get("out_of_scope_reason"), f"{path}.out_of_scope_reason")
            _expect_string(requirement.get("user_decision_ref"), f"{path}.user_decision_ref")

    non_exact_requirement_sources: list[str] = []
    non_file_requirement_sources: list[str] = []
    for source_id, source in sources_by_id.items():
        declared = set(source.get("requirement_ids", []))
        actual = {
            requirement["id"]
            for requirement in plan["requirements"]
            if requirement["source_ref"] == source_id
            or requirement["source_ref"].startswith(source_id + ":")
        }
        if strict:
            if actual:
                if source.get("inventory_mode") != "exact":
                    non_exact_requirement_sources.append(source_id)
                if source.get("fingerprint_mode") != "file_sha256":
                    non_file_requirement_sources.append(source_id)
            _require(
                "requirement_ids" in source,
                f"strict source {source_id} must declare requirement_ids",
            )
            _require(
                declared == actual,
                f"strict source {source_id} requirement inventory mismatch; missing="
                + ",".join(sorted(actual - declared))
                + " extra="
                + ",".join(sorted(declared - actual)),
            )
            for requirement in plan["requirements"]:
                if requirement["id"] not in actual:
                    continue
                _require(
                    requirement["source_fingerprint"] == source["fingerprint"],
                    f"strict source requirement {requirement['id']} must use the source fingerprint",
                )
        if source.get("inventory_mode", "advisory") != "exact":
            continue
        _require(
            declared == actual,
            f"source {source_id} exact requirement inventory mismatch; missing="
            + ",".join(sorted(actual - declared))
            + " extra="
            + ",".join(sorted(declared - actual)),
        )
        for requirement in plan["requirements"]:
            if requirement["id"] not in actual or requirement["status"] != "in_scope":
                continue
            _require(
                requirement["source_fingerprint"] == source["fingerprint"],
                f"exact source requirement {requirement['id']} must use the source fingerprint",
            )
            _require(
                "verification_mode" in requirement,
                f"exact source requirement {requirement['id']} must declare verification_mode",
            )
            _require(
                bool(requirement.get("acceptance_scope", [])),
                f"exact source requirement {requirement['id']} must declare acceptance_scope",
            )
    if strict and enforce_source_durability:
        _require(
            not non_exact_requirement_sources and not non_file_requirement_sources,
            "strict requirement sources must be durable; non_exact="
            + ",".join(sorted(non_exact_requirement_sources))
            + " non_file_sha256="
            + ",".join(sorted(non_file_requirement_sources)),
            code="strict_source_not_durable",
        )

    acceptance_clause_by_id: dict[str, dict[str, Any]] = {}
    design_clause_by_id: dict[str, dict[str, Any]] = {}
    solution_step_by_id: dict[str, dict[str, Any]] = {}
    gap_item_by_id: dict[str, dict[str, Any]] = {}
    acceptance_clauses_by_requirement: dict[str, set[str]] = {
        requirement_id: set() for requirement_id in in_scope_requirements
    }
    acceptance_verification_scope_by_requirement: dict[str, set[str]] = {
        requirement_id: set() for requirement_id in in_scope_requirements
    }
    acceptance_claims_by_requirement: dict[str, set[str]] = {
        requirement_id: set() for requirement_id in in_scope_requirements
    }

    def trace_source_id(source_ref: str, path: str) -> str:
        matches = [
            source_id
            for source_id in source_ids
            if source_ref == source_id or source_ref.startswith(source_id + ":")
        ]
        _require(bool(matches), f"{path}.source_ref must belong to a registered scope source")
        return max(matches, key=len)

    def validate_trace_source(item: dict[str, Any], path: str) -> str:
        source_ref = _expect_string(item["source_ref"], f"{path}.source_ref")
        source_id = trace_source_id(source_ref, path)
        fingerprint = _expect_string(
            item["source_fingerprint"], f"{path}.source_fingerprint"
        )
        _require(
            fingerprint == sources_by_id[source_id].get("fingerprint"),
            f"{path} must use the registered source fingerprint",
        )
        return source_id

    trace_actual_by_source: dict[str, dict[str, set[str]]] = {
        source_id: {kind: set() for kind in TRACE_SOURCE_INVENTORIES}
        for source_id in source_ids
    }
    if pipeline_strict:
        for index, clause_value in enumerate(
            _expect_list(plan["acceptance_clauses"], "plan.acceptance_clauses")
        ):
            path = f"plan.acceptance_clauses[{index}]"
            clause = _expect_object(clause_value, path)
            _expect_keys(
                clause,
                required={
                    "id",
                    "requirement_id",
                    "statement",
                    "verification_scope",
                    "required_claims",
                    "source_ref",
                    "source_fingerprint",
                    "origin_kind",
                    "origin_ref",
                },
                optional={"decision_ref"},
                path=path,
            )
            clause_id = _expect_id(clause["id"], f"{path}.id")
            _require(
                clause_id not in acceptance_clause_by_id,
                f"duplicate acceptance clause id: {clause_id}",
            )
            requirement_id = _expect_id(
                clause["requirement_id"], f"{path}.requirement_id"
            )
            _require(
                requirement_id in in_scope_requirements,
                f"acceptance clause {clause_id} references non-active requirement {requirement_id}",
            )
            origin_kind = _expect_string(clause["origin_kind"], f"{path}.origin_kind")
            _require(
                origin_kind in TRACE_ORIGIN_KINDS,
                f"acceptance clause {clause_id} has invalid origin_kind",
            )
            _expect_string(clause["origin_ref"], f"{path}.origin_ref")
            _expect_string(clause["statement"], f"{path}.statement")
            verification_scope = set(
                _unique_strings(
                    clause["verification_scope"],
                    f"{path}.verification_scope",
                    allow_empty=False,
                )
            )
            required_claims = set(
                _unique_strings(
                    clause["required_claims"],
                    f"{path}.required_claims",
                    claims=True,
                    allow_empty=False,
                )
            )
            if "decision_ref" in clause:
                decision_ref = _expect_string(
                    clause["decision_ref"], f"{path}.decision_ref"
                )
                _require(
                    decision_ref in plan_decision_refs,
                    f"acceptance clause {clause_id} decision_ref must be registered in plan.decision_refs",
                    code="unconfirmed_acceptance_clause",
                )
            if origin_kind == "derived_proposal":
                _require(
                    "decision_ref" in clause,
                    f"derived acceptance clause {clause_id} requires an explicit decision_ref",
                    code="unconfirmed_acceptance_clause",
                )
            source_id = validate_trace_source(clause, path)
            trace_actual_by_source[source_id]["acceptance_clause"].add(clause_id)
            acceptance_clause_by_id[clause_id] = clause
            acceptance_clauses_by_requirement[requirement_id].add(clause_id)
            acceptance_verification_scope_by_requirement[requirement_id].update(
                verification_scope
            )
            acceptance_claims_by_requirement[requirement_id].update(required_claims)
        _require(
            bool(acceptance_clause_by_id),
            "strict_v2 plan.acceptance_clauses must not be empty",
        )
        for requirement_id in sorted(in_scope_requirements):
            declared_scope = acceptance_scope_by_requirement[requirement_id]
            source_scope = acceptance_verification_scope_by_requirement[requirement_id]
            _require(
                declared_scope == source_scope,
                f"requirement {requirement_id} acceptance_scope must exactly equal source-owned clause verification scopes; missing="
                + ",".join(sorted(source_scope - declared_scope))
                + " extra="
                + ",".join(sorted(declared_scope - source_scope)),
                code="acceptance_scope_drift",
            )
            declared_claims = observable_claims_by_requirement[requirement_id]
            source_claims = acceptance_claims_by_requirement[requirement_id]
            _require(
                declared_claims == source_claims,
                f"requirement {requirement_id} observable_claims must exactly equal source-owned clause claims; missing="
                + ",".join(sorted(source_claims - declared_claims))
                + " extra="
                + ",".join(sorted(declared_claims - source_claims)),
                code="acceptance_claim_drift",
            )

        covered_acceptance_clauses: set[str] = set()
        for index, clause_value in enumerate(
            _expect_list(plan["design_clauses"], "plan.design_clauses")
        ):
            path = f"plan.design_clauses[{index}]"
            clause = _expect_object(clause_value, path)
            _expect_keys(
                clause,
                required={
                    "id",
                    "statement",
                    "source_ref",
                    "source_fingerprint",
                    "acceptance_clause_ids",
                },
                optional=set(),
                path=path,
            )
            clause_id = _expect_id(clause["id"], f"{path}.id")
            _expect_string(clause["statement"], f"{path}.statement")
            _require(
                clause_id not in design_clause_by_id,
                f"duplicate design clause id: {clause_id}",
            )
            acceptance_ids = set(
                _unique_strings(
                    clause["acceptance_clause_ids"],
                    f"{path}.acceptance_clause_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                acceptance_ids <= set(acceptance_clause_by_id),
                f"design clause {clause_id} references unknown acceptance clauses: "
                + ",".join(sorted(acceptance_ids - set(acceptance_clause_by_id))),
            )
            source_id = validate_trace_source(clause, path)
            trace_actual_by_source[source_id]["design_clause"].add(clause_id)
            covered_acceptance_clauses.update(acceptance_ids)
            design_clause_by_id[clause_id] = clause
        _require(
            covered_acceptance_clauses == set(acceptance_clause_by_id),
            "acceptance clauses without design coverage: "
            + ",".join(sorted(set(acceptance_clause_by_id) - covered_acceptance_clauses)),
            code="traceability_gap",
        )

        covered_design_clauses: set[str] = set()
        for index, step_value in enumerate(
            _expect_list(plan["solution_steps"], "plan.solution_steps")
        ):
            path = f"plan.solution_steps[{index}]"
            step = _expect_object(step_value, path)
            _expect_keys(
                step,
                required={
                    "id",
                    "action",
                    "expected_result",
                    "source_ref",
                    "source_fingerprint",
                    "design_clause_ids",
                    "depends_on",
                    "must_not_depend_on",
                    "uncertainty_boundary",
                },
                optional=set(),
                path=path,
            )
            step_id = _expect_id(step["id"], f"{path}.id")
            _expect_string(step["action"], f"{path}.action")
            _expect_string(step["expected_result"], f"{path}.expected_result")
            _require(
                step_id not in solution_step_by_id,
                f"duplicate solution step id: {step_id}",
            )
            design_ids = set(
                _unique_strings(
                    step["design_clause_ids"],
                    f"{path}.design_clause_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                design_ids <= set(design_clause_by_id),
                f"solution step {step_id} references unknown design clauses: "
                + ",".join(sorted(design_ids - set(design_clause_by_id))),
            )
            _unique_strings(step["depends_on"], f"{path}.depends_on", ids=True)
            _unique_strings(
                step["must_not_depend_on"],
                f"{path}.must_not_depend_on",
                ids=True,
            )
            _validate_uncertainty_boundary(
                step["uncertainty_boundary"], f"{path}.uncertainty_boundary"
            )
            source_id = validate_trace_source(step, path)
            trace_actual_by_source[source_id]["solution_step"].add(step_id)
            covered_design_clauses.update(design_ids)
            solution_step_by_id[step_id] = step
        _require(
            covered_design_clauses == set(design_clause_by_id),
            "design clauses without solution coverage: "
            + ",".join(sorted(set(design_clause_by_id) - covered_design_clauses)),
            code="traceability_gap",
        )
        for step_id, step in solution_step_by_id.items():
            dependencies = set(step["depends_on"])
            forbidden = set(step["must_not_depend_on"])
            _require(
                dependencies <= set(solution_step_by_id),
                f"solution step {step_id} depends on unknown steps: "
                + ",".join(sorted(dependencies - set(solution_step_by_id))),
            )
            _require(
                forbidden <= set(solution_step_by_id),
                f"solution step {step_id} forbids unknown steps: "
                + ",".join(sorted(forbidden - set(solution_step_by_id))),
            )
            _require(
                step_id not in dependencies | forbidden,
                f"solution step {step_id} cannot reference itself",
            )
            _require(
                not dependencies & forbidden,
                f"solution step {step_id} both requires and forbids: "
                + ",".join(sorted(dependencies & forbidden)),
            )
        visiting_steps: set[str] = set()
        visited_steps: set[str] = set()

        def visit_solution(step_id: str) -> None:
            if step_id in visited_steps:
                return
            _require(
                step_id not in visiting_steps,
                f"solution dependency cycle includes {step_id}",
            )
            visiting_steps.add(step_id)
            for upstream_id in solution_step_by_id[step_id]["depends_on"]:
                visit_solution(upstream_id)
            visiting_steps.remove(step_id)
            visited_steps.add(step_id)

        for step_id in sorted(solution_step_by_id):
            visit_solution(step_id)

        covered_solution_steps: set[str] = set()
        solution_gap_owner: dict[str, str] = {}
        for index, gap_value in enumerate(_expect_list(plan["gap_items"], "plan.gap_items")):
            path = f"plan.gap_items[{index}]"
            gap = _expect_object(gap_value, path)
            _expect_keys(
                gap,
                required={
                    "id",
                    "finding",
                    "source_ref",
                    "source_fingerprint",
                    "solution_step_ids",
                    "status",
                },
                optional=set(),
                path=path,
            )
            gap_id = _expect_id(gap["id"], f"{path}.id")
            _expect_string(gap["finding"], f"{path}.finding")
            _require(gap_id not in gap_item_by_id, f"duplicate gap id: {gap_id}")
            solution_ids = set(
                _unique_strings(
                    gap["solution_step_ids"],
                    f"{path}.solution_step_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                solution_ids <= set(solution_step_by_id),
                f"gap {gap_id} references unknown solution steps: "
                + ",".join(sorted(solution_ids - set(solution_step_by_id))),
            )
            for solution_id in solution_ids:
                _require(
                    solution_id not in solution_gap_owner,
                    f"solution step {solution_id} is assigned to multiple gap items: "
                    f"{solution_gap_owner.get(solution_id)},{gap_id}",
                    code="traceability_gap",
                )
                solution_gap_owner[solution_id] = gap_id
            status = _expect_string(gap["status"], f"{path}.status")
            _require(status in GAP_STATUSES, f"gap {gap_id} has invalid status")
            source_id = validate_trace_source(gap, path)
            trace_actual_by_source[source_id]["gap_item"].add(gap_id)
            covered_solution_steps.update(solution_ids)
            gap_item_by_id[gap_id] = gap
        _require(
            covered_solution_steps == set(solution_step_by_id),
            "solution steps without current-state gap analysis: "
            + ",".join(sorted(set(solution_step_by_id) - covered_solution_steps)),
            code="traceability_gap",
        )

        for source_id, inventories in trace_actual_by_source.items():
            source = sources_by_id[source_id]
            for kind, (ids_field, _prefix_field) in TRACE_SOURCE_INVENTORIES.items():
                actual_ids = inventories[kind]
                declared_ids = set(source.get(ids_field, []))
                _require(
                    declared_ids == actual_ids,
                    f"source {source_id} {kind} inventory mismatch; missing="
                    + ",".join(sorted(actual_ids - declared_ids))
                    + " extra="
                    + ",".join(sorted(declared_ids - actual_ids)),
                    code="traceability_inventory_drift",
                )

        planning_audit = _expect_object(plan["planning_audit"], "plan.planning_audit")
        _expect_keys(
            planning_audit,
            required={"receipt_ref"},
            optional=set(),
            path="plan.planning_audit",
        )
        _validate_relative_path(
            _expect_string(planning_audit["receipt_ref"], "plan.planning_audit.receipt_ref"),
            "plan.planning_audit.receipt_ref",
        )

    producers = _expect_object(plan["producers"], "plan.producers")
    for producer_id, producer_value in producers.items():
        _expect_id(producer_id, f"plan.producers.{producer_id}")
        producer = _expect_object(producer_value, f"plan.producers.{producer_id}")
        _expect_keys(
            producer,
            required={
                "version",
                "source_class",
                "source_ref",
                "allowed_claims",
                "envelope_schema",
                "requires_raw_artifacts",
            },
            optional=set(),
            path=f"plan.producers.{producer_id}",
        )
        _expect_string(producer["version"], f"plan.producers.{producer_id}.version")
        source_class = _expect_string(producer["source_class"], f"plan.producers.{producer_id}.source_class")
        _require(source_class in SOURCE_CLASSES, f"plan.producers.{producer_id}.source_class is invalid")
        _expect_string(producer["source_ref"], f"plan.producers.{producer_id}.source_ref")
        _unique_strings(
            producer["allowed_claims"],
            f"plan.producers.{producer_id}.allowed_claims",
            claims=True,
            allow_empty=False,
        )
        _require(
            producer["envelope_schema"] == EVIDENCE_SCHEMA,
            f"plan.producers.{producer_id}.envelope_schema must be {EVIDENCE_SCHEMA}",
        )
        _require(
            isinstance(producer["requires_raw_artifacts"], bool),
            f"plan.producers.{producer_id}.requires_raw_artifacts must be boolean",
        )

    profiles = _expect_object(plan["evidence_profiles"], "plan.evidence_profiles")
    for profile_id, profile_value in profiles.items():
        _expect_id(profile_id, f"plan.evidence_profiles.{profile_id}")
        profile = _expect_object(profile_value, f"plan.evidence_profiles.{profile_id}")
        _expect_keys(
            profile,
            required={"required_claims", "claim_rules"},
            optional=set(),
            path=f"plan.evidence_profiles.{profile_id}",
        )
        required_claims = _unique_strings(
            profile["required_claims"],
            f"plan.evidence_profiles.{profile_id}.required_claims",
            claims=True,
            allow_empty=False,
        )
        rules = _expect_object(profile["claim_rules"], f"plan.evidence_profiles.{profile_id}.claim_rules")
        _require(set(required_claims) <= set(rules), f"profile {profile_id} lacks rules for required claims")
        for claim, rule_value in rules.items():
            _expect_claim(claim, f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}")
            rule = _expect_object(rule_value, f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}")
            _expect_keys(
                rule,
                required={"producers", "source_classes", "freshness_keys", "min_evidence"},
                optional=set(),
                path=f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}",
            )
            producer_ids_for_claim = _unique_strings(
                rule["producers"],
                f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}.producers",
                ids=True,
                allow_empty=False,
            )
            for producer_id in producer_ids_for_claim:
                _require(producer_id in producers, f"profile {profile_id} references unknown producer {producer_id}")
                _require(
                    claim in producers[producer_id]["allowed_claims"],
                    f"producer {producer_id} does not allow claim {claim}",
                )
            source_classes = _unique_strings(
                rule["source_classes"],
                f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}.source_classes",
                allow_empty=False,
            )
            _require(set(source_classes) <= SOURCE_CLASSES, f"claim {claim} has invalid source_classes")
            _require(
                "agent_context" not in source_classes,
                f"claim {claim} cannot accept agent_context as completion evidence",
            )
            for producer_id in producer_ids_for_claim:
                _require(
                    producers[producer_id]["source_class"] in source_classes,
                    f"producer {producer_id} source_class is not accepted by claim {claim}",
                )
            freshness = _unique_strings(
                rule["freshness_keys"],
                f"plan.evidence_profiles.{profile_id}.claim_rules.{claim}.freshness_keys",
                claims=True,
            )
            _require("contract" in freshness, f"claim {claim} must require contract freshness")
            _require(
                isinstance(rule["min_evidence"], int) and not isinstance(rule["min_evidence"], bool),
                f"claim {claim}.min_evidence must be an integer",
            )
            _require(rule["min_evidence"] >= 1, f"claim {claim}.min_evidence must be at least 1")

    qualifications = _expect_object(plan["test_qualifications"], "plan.test_qualifications")
    for test_id, qualification_value in qualifications.items():
        _expect_string(test_id, f"plan.test_qualifications.{test_id}")
        qualification = _expect_object(qualification_value, f"plan.test_qualifications.{test_id}")
        _expect_keys(
            qualification,
            required={
                "requirement_ids",
                "subject",
                "oracle_source",
                "baseline",
                "claim_dimensions",
                "negative_paths",
                "trust_state",
                "source_fingerprint",
            },
            optional={"observed_scopes", "evidence_shape"},
            path=f"plan.test_qualifications.{test_id}",
        )
        for requirement_id in _unique_strings(
            qualification["requirement_ids"],
            f"plan.test_qualifications.{test_id}.requirement_ids",
            ids=True,
            allow_empty=False,
        ):
            _require(requirement_id in requirement_ids, f"test {test_id} references unknown requirement {requirement_id}")
        _expect_string(qualification["subject"], f"plan.test_qualifications.{test_id}.subject")
        _expect_string(qualification["oracle_source"], f"plan.test_qualifications.{test_id}.oracle_source")
        _expect_string(qualification["baseline"], f"plan.test_qualifications.{test_id}.baseline")
        _unique_strings(
            qualification["claim_dimensions"],
            f"plan.test_qualifications.{test_id}.claim_dimensions",
            claims=True,
            allow_empty=False,
        )
        _unique_strings(qualification["negative_paths"], f"plan.test_qualifications.{test_id}.negative_paths")
        trust_state = _expect_string(qualification["trust_state"], f"plan.test_qualifications.{test_id}.trust_state")
        _require(trust_state in TRUST_STATES, f"test {test_id} has invalid trust_state")
        _expect_string(qualification["source_fingerprint"], f"plan.test_qualifications.{test_id}.source_fingerprint")
        evidence_shape = _expect_string(
            qualification.get("evidence_shape", "module"),
            f"plan.test_qualifications.{test_id}.evidence_shape",
        )
        _require(evidence_shape in EVIDENCE_SHAPES, f"test {test_id} has invalid evidence_shape")
        observed_scopes = _unique_strings(
            qualification.get("observed_scopes", []),
            f"plan.test_qualifications.{test_id}.observed_scopes",
        )
        if evidence_shape == "vertical":
            _require(bool(observed_scopes), f"vertical test {test_id} must declare observed_scopes")
        else:
            _require(
                not observed_scopes,
                f"module test {test_id} cannot declare observed_scopes",
            )

    tasks = _expect_list(plan["tasks"], "plan.tasks")
    _require(bool(tasks), "plan.tasks must not be empty")
    task_ids: set[str] = set()
    task_by_id: dict[str, dict[str, Any]] = {}
    requirement_consumers: set[str] = set()
    acceptance_clause_consumers: set[str] = set()
    gap_owner_task: dict[str, str] = {}
    solution_owner_task: dict[str, str] = {}
    for index, task_value in enumerate(tasks):
        path = f"plan.tasks[{index}]"
        task = _expect_object(task_value, path)
        _expect_keys(
            task,
            required={
                "id",
                "outcome",
                "requirement_ids",
                "depends_on",
                "context_refs",
                "mutation_scope",
                "test_scope",
                "freshness_scopes",
                "build_profile",
                "rollback_scope",
                "package_key",
                "claim_profile",
                "claim_overrides",
                "tests_first",
            },
            optional={
                "planned_test_scope",
                "completion_level",
                "claim_scope",
                "scope_enforced",
                "acceptance_clause_ids",
                "solution_step_ids",
                "gap_ids",
                "uncertainty_boundary",
            },
            path=path,
        )
        task_id = _expect_id(task["id"], f"{path}.id")
        _require(task_id not in task_ids, f"duplicate task id: {task_id}")
        task_ids.add(task_id)
        task_by_id[task_id] = task
        _expect_string(task["outcome"], f"{path}.outcome")
        if strict:
            for field in ("completion_level", "claim_scope", "scope_enforced"):
                _require(
                    field in task,
                    f"strict task {task_id} must declare {field}",
                )
        if pipeline_strict:
            for field in (
                "acceptance_clause_ids",
                "solution_step_ids",
                "gap_ids",
                "uncertainty_boundary",
            ):
                _require(field in task, f"strict_v2 task {task_id} must declare {field}")
        completion_level = _expect_string(
            task.get("completion_level", "module_ready"), f"{path}.completion_level"
        )
        _require(completion_level in COMPLETION_LEVELS, f"{path}.completion_level is invalid")
        claim_scope = set(_unique_strings(task.get("claim_scope", []), f"{path}.claim_scope"))
        scope_enforced = task.get("scope_enforced", False)
        _require(isinstance(scope_enforced, bool), f"{path}.scope_enforced must be boolean")
        if strict:
            if COMPLETION_LEVELS[completion_level] >= COMPLETION_LEVELS["integration_ready"]:
                _require(bool(claim_scope), f"strict high-level task {task_id} must have claim_scope")
                _require(
                    scope_enforced,
                    f"strict high-level task {task_id} must enable scope_enforced",
                )
        if scope_enforced and COMPLETION_LEVELS[completion_level] >= COMPLETION_LEVELS["integration_ready"]:
            _require("completion_level" in task, f"scope-enforced task {task_id} must declare completion_level")
            _require(bool(claim_scope), f"scope-enforced task {task_id} must declare claim_scope")
        task_requirements = _unique_strings(
            task["requirement_ids"], f"{path}.requirement_ids", ids=True, allow_empty=False
        )
        for requirement_id in task_requirements:
            _require(requirement_id in in_scope_requirements, f"task {task_id} references non-active requirement {requirement_id}")
            requirement_consumers.add(requirement_id)
        if pipeline_strict:
            task_acceptance_ids = set(
                _unique_strings(
                    task["acceptance_clause_ids"],
                    f"{path}.acceptance_clause_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                task_acceptance_ids <= set(acceptance_clause_by_id),
                f"task {task_id} references unknown acceptance clauses: "
                + ",".join(sorted(task_acceptance_ids - set(acceptance_clause_by_id))),
            )
            derived_requirements = {
                acceptance_clause_by_id[clause_id]["requirement_id"]
                for clause_id in task_acceptance_ids
            }
            _require(
                set(task_requirements) == derived_requirements,
                f"task {task_id} requirement_ids must exactly match its acceptance clauses; missing="
                + ",".join(sorted(derived_requirements - set(task_requirements)))
                + " extra="
                + ",".join(sorted(set(task_requirements) - derived_requirements)),
                code="task_traceability_drift",
            )
            acceptance_clause_consumers.update(task_acceptance_ids)
            task_solution_ids = set(
                _unique_strings(
                    task["solution_step_ids"],
                    f"{path}.solution_step_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                task_solution_ids <= set(solution_step_by_id),
                f"task {task_id} references unknown solution steps: "
                + ",".join(sorted(task_solution_ids - set(solution_step_by_id))),
            )
            task_gap_ids = set(
                _unique_strings(
                    task["gap_ids"],
                    f"{path}.gap_ids",
                    ids=True,
                    allow_empty=False,
                )
            )
            _require(
                task_gap_ids <= set(gap_item_by_id),
                f"task {task_id} references unknown gaps: "
                + ",".join(sorted(task_gap_ids - set(gap_item_by_id))),
            )
            gap_solution_ids = set().union(
                *(set(gap_item_by_id[gap_id]["solution_step_ids"]) for gap_id in task_gap_ids)
            )
            _require(
                task_solution_ids == gap_solution_ids,
                f"task {task_id} solution_step_ids must exactly match its gaps; missing="
                + ",".join(sorted(gap_solution_ids - task_solution_ids))
                + " extra="
                + ",".join(sorted(task_solution_ids - gap_solution_ids)),
                code="task_traceability_drift",
            )
            for gap_id in task_gap_ids:
                _require(
                    gap_item_by_id[gap_id]["status"] != "satisfied",
                    f"task {task_id} cannot implement satisfied gap {gap_id}",
                )
                _require(
                    gap_id not in gap_owner_task,
                    f"gap {gap_id} has multiple task owners: {gap_owner_task.get(gap_id)},{task_id}",
                )
                gap_owner_task[gap_id] = task_id
            for solution_id in task_solution_ids:
                _require(
                    solution_id not in solution_owner_task,
                    f"solution step {solution_id} has multiple task owners: "
                    f"{solution_owner_task.get(solution_id)},{task_id}",
                )
                solution_owner_task[solution_id] = task_id
            task_boundary = _validate_uncertainty_boundary(
                task["uncertainty_boundary"], f"{path}.uncertainty_boundary"
            )
            for solution_id in task_solution_ids:
                solution_boundary = _validate_uncertainty_boundary(
                    solution_step_by_id[solution_id]["uncertainty_boundary"],
                    f"solution step {solution_id}.uncertainty_boundary",
                )
                _require(
                    task_boundary == solution_boundary,
                    f"task {task_id} combines solution step {solution_id} from a different uncertainty boundary",
                    code="heterogeneous_work_package",
                )
            solution_acceptance_ids: set[str] = set()
            for solution_id in task_solution_ids:
                for design_id in solution_step_by_id[solution_id]["design_clause_ids"]:
                    solution_acceptance_ids.update(
                        design_clause_by_id[design_id]["acceptance_clause_ids"]
                    )
            _require(
                task_acceptance_ids <= solution_acceptance_ids,
                f"task {task_id} acceptance clauses are not justified by its solution steps: "
                + ",".join(sorted(task_acceptance_ids - solution_acceptance_ids)),
                code="task_traceability_drift",
            )
        _expect_list(task["depends_on"], f"{path}.depends_on")
        _unique_strings(task["context_refs"], f"{path}.context_refs")
        for scope_name in ("mutation_scope", "test_scope", "planned_test_scope"):
            for scope_index, scope_entry in enumerate(
                _unique_strings(task.get(scope_name, []), f"{path}.{scope_name}")
            ):
                _validate_relative_path(scope_entry, f"{path}.{scope_name}[{scope_index}]")
        freshness_scopes = _expect_object(task["freshness_scopes"], f"{path}.freshness_scopes")
        for freshness_key, scope_value in freshness_scopes.items():
            _expect_claim(freshness_key, f"{path}.freshness_scopes.{freshness_key}")
            _require(
                freshness_key not in BASE_FRESHNESS_KEYS,
                f"task {task_id} cannot redefine built-in freshness key {freshness_key}",
            )
            scope_entries = _unique_strings(
                scope_value,
                f"{path}.freshness_scopes.{freshness_key}",
                allow_empty=False,
            )
            for scope_index, scope_entry in enumerate(scope_entries):
                _validate_relative_path(
                    scope_entry,
                    f"{path}.freshness_scopes.{freshness_key}[{scope_index}]",
                )
        _expect_string(task["build_profile"], f"{path}.build_profile", nonempty=False)
        _expect_string(task["rollback_scope"], f"{path}.rollback_scope")
        _expect_string(task["package_key"], f"{path}.package_key")
        profile_id = _expect_id(task["claim_profile"], f"{path}.claim_profile")
        _require(profile_id in profiles, f"task {task_id} references unknown claim_profile {profile_id}")
        overrides = _expect_object(task["claim_overrides"], f"{path}.claim_overrides")
        _expect_keys(
            overrides,
            required={"required_claims", "automation_test_ids", "readback_subjects"},
            optional=set(),
            path=f"{path}.claim_overrides",
        )
        override_claims = _unique_strings(
            overrides["required_claims"], f"{path}.claim_overrides.required_claims", claims=True
        )
        if override_claims:
            for claim in override_claims:
                _require(
                    claim in profiles[profile_id]["claim_rules"],
                    f"task {task_id} requires claim {claim} without a profile rule",
                )
        automation_test_ids = _unique_strings(
            overrides["automation_test_ids"], f"{path}.claim_overrides.automation_test_ids"
        )
        if automation_test_ids:
            _require(
                bool(task["test_scope"] or task.get("planned_test_scope", [])),
                f"task {task_id} declares tests without test_scope or planned_test_scope",
            )
        readback_subjects = set(
            _unique_strings(
                overrides["readback_subjects"],
                f"{path}.claim_overrides.readback_subjects",
            )
        )
        if scope_enforced:
            _require(
                claim_scope <= readback_subjects,
                f"scope-enforced task {task_id} claims subjects without required readback: "
                + ", ".join(sorted(claim_scope - readback_subjects)),
            )
            if (
                COMPLETION_LEVELS[completion_level] >= COMPLETION_LEVELS["production_ready"]
                and "public_entry" in set(_required_claims(plan, task))
            ):
                _require(
                    bool(set(task_requirements) & direct_flow_requirements),
                    f"scope-enforced production task {task_id} with public_entry must own a direct_flow requirement",
                )
        tests_first = _expect_object(task["tests_first"], f"{path}.tests_first")
        _expect_keys(
            tests_first,
            required={"mode", "reason", "expected_red_producer"},
            optional=set(),
            path=f"{path}.tests_first",
        )
        mode = _expect_string(tests_first["mode"], f"{path}.tests_first.mode")
        _require(mode in TESTS_FIRST_MODES, f"task {task_id} has invalid tests_first.mode")
        _expect_string(tests_first["reason"], f"{path}.tests_first.reason", nonempty=mode != "required")
        producer_id = _expect_string(
            tests_first["expected_red_producer"],
            f"{path}.tests_first.expected_red_producer",
            nonempty=mode == "required",
        )
        if mode == "required":
            _require(producer_id in producers, f"task {task_id} has unknown expected-red producer {producer_id}")
            _require(
                bool(automation_test_ids),
                f"task {task_id} requires tests-first but declares no automation_test_ids",
            )
            _require(
                producers[producer_id]["source_class"] in {"registered_machine", "derived_machine"},
                f"task {task_id} expected-red producer must be machine evidence",
            )

    _require(
        requirement_consumers == in_scope_requirements,
        "in-scope requirements without task consumers: "
        + ", ".join(sorted(in_scope_requirements - requirement_consumers)),
    )
    if pipeline_strict:
        _require(
            acceptance_clause_consumers == set(acceptance_clause_by_id),
            "acceptance clauses without task consumers: "
            + ",".join(sorted(set(acceptance_clause_by_id) - acceptance_clause_consumers)),
            code="traceability_gap",
        )
        incomplete_gap_ids = {
            gap_id
            for gap_id, gap in gap_item_by_id.items()
            if gap["status"] != "satisfied"
        }
        _require(
            set(gap_owner_task) == incomplete_gap_ids,
            "unfinished gaps without exactly one task owner: "
            + ",".join(sorted(incomplete_gap_ids - set(gap_owner_task))),
            code="traceability_gap",
        )
    requirement_claim_coverage: dict[str, set[str]] = {
        requirement_id: set() for requirement_id in in_scope_requirements
    }
    for task in task_by_id.values():
        task_claims = set(_required_claims(plan, task))
        for requirement_id in task["requirement_ids"]:
            requirement_claim_coverage[requirement_id].update(task_claims)
    requirements_by_id = _requirement_map(plan)
    for requirement_id, covered_claims in requirement_claim_coverage.items():
        observable = set(requirements_by_id[requirement_id]["observable_claims"])
        _require(
            observable <= covered_claims,
            f"requirement {requirement_id} has unmapped claims: "
            + ", ".join(sorted(observable - covered_claims)),
        )

    for task_id, task in task_by_id.items():
        upstream_seen: set[str] = set()
        for edge_index, edge_value in enumerate(task["depends_on"]):
            path = f"task {task_id}.depends_on[{edge_index}]"
            edge = _expect_object(edge_value, path)
            _expect_keys(edge, required={"task_id", "claims"}, optional=set(), path=path)
            upstream_id = _expect_id(edge["task_id"], f"{path}.task_id")
            _require(upstream_id in task_by_id, f"task {task_id} depends on unknown task {upstream_id}")
            _require(upstream_id != task_id, f"task {task_id} cannot depend on itself")
            _require(upstream_id not in upstream_seen, f"task {task_id} repeats dependency {upstream_id}")
            upstream_seen.add(upstream_id)
            consumed_claims = _unique_strings(edge["claims"], f"{path}.claims", claims=True, allow_empty=False)
            upstream_claims = set(_required_claims(plan, task_by_id[upstream_id]))
            _require(
                set(consumed_claims) <= upstream_claims,
                f"task {task_id} consumes undeclared claims from {upstream_id}",
            )
        for test_id in task["claim_overrides"]["automation_test_ids"]:
            _require(test_id in qualifications, f"task {task_id} references unknown test qualification {test_id}")
        claims = _required_claims(plan, task)
        _require(bool(claims), f"task {task_id} has no required claims")
        for claim in claims:
            rule = _claim_rule(plan, task, claim)
            allowed_freshness = BASE_FRESHNESS_KEYS | set(task["freshness_scopes"])
            for freshness_key in rule["freshness_keys"]:
                _require(
                    freshness_key in allowed_freshness,
                    f"task {task_id} claim {claim} uses freshness key {freshness_key} "
                    "without a recomputable freshness scope",
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        _require(task_id not in visiting, f"task dependency cycle includes {task_id}")
        visiting.add(task_id)
        for edge in task_by_id[task_id]["depends_on"]:
            visit(edge["task_id"])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(task_by_id):
        visit(task_id)

    if pipeline_strict:
        dependency_closure_cache: dict[str, set[str]] = {}

        def dependency_closure(task_id: str) -> set[str]:
            if task_id in dependency_closure_cache:
                return dependency_closure_cache[task_id]
            result: set[str] = set()
            for edge in task_by_id[task_id]["depends_on"]:
                upstream_id = edge["task_id"]
                result.add(upstream_id)
                result.update(dependency_closure(upstream_id))
            dependency_closure_cache[task_id] = result
            return result

        for task_id, task in task_by_id.items():
            direct_task_dependencies = {edge["task_id"] for edge in task["depends_on"]}
            transitive_task_dependencies = dependency_closure(task_id)
            for solution_id in task["solution_step_ids"]:
                solution_step = solution_step_by_id[solution_id]
                for upstream_solution_id in solution_step["depends_on"]:
                    upstream_task_id = solution_owner_task.get(upstream_solution_id)
                    if upstream_task_id is None or upstream_task_id == task_id:
                        continue
                    _require(
                        upstream_task_id in direct_task_dependencies,
                        f"task {task_id} misses solution dependency {upstream_solution_id} owned by {upstream_task_id}",
                        code="solution_dependency_drift",
                    )
                for forbidden_solution_id in solution_step["must_not_depend_on"]:
                    forbidden_task_id = solution_owner_task.get(forbidden_solution_id)
                    if forbidden_task_id is None:
                        continue
                    _require(
                        forbidden_task_id not in transitive_task_dependencies,
                        f"task {task_id} depends on forbidden solution {forbidden_solution_id} via {forbidden_task_id}",
                        code="forbidden_solution_dependency",
                    )

    flow_ids: set[str] = set()
    mapped_direct_flow_requirements: set[str] = set()
    for index, flow_value in enumerate(
        _expect_list(plan.get("acceptance_flows", []), "plan.acceptance_flows")
    ):
        path = f"plan.acceptance_flows[{index}]"
        flow = _expect_object(flow_value, path)
        _expect_keys(
            flow,
            required={
                "id",
                "title",
                "scope",
                "requirement_ids",
                "verification_task_id",
                "required_claims",
                "direct_test_ids",
            },
            optional={"evidence_mode", "scope_coverage", "scope_claims"},
            path=path,
        )
        flow_id = _expect_id(flow["id"], f"{path}.id")
        _require(flow_id not in flow_ids, f"duplicate acceptance flow id: {flow_id}")
        flow_ids.add(flow_id)
        _expect_string(flow["title"], f"{path}.title")
        _expect_string(flow["scope"], f"{path}.scope")
        flow_requirements = set(
            _unique_strings(flow["requirement_ids"], f"{path}.requirement_ids", ids=True, allow_empty=False)
        )
        _require(
            flow_requirements <= direct_flow_requirements,
            f"acceptance flow {flow_id} may only reference in-scope direct_flow requirements",
        )
        mapped_direct_flow_requirements.update(flow_requirements)
        verification_task_id = _expect_id(flow["verification_task_id"], f"{path}.verification_task_id")
        _require(
            verification_task_id in task_by_id,
            f"acceptance flow {flow_id} references unknown verification task {verification_task_id}",
        )
        verification_task = task_by_id[verification_task_id]
        _require(
            flow_requirements <= set(verification_task["requirement_ids"]),
            f"acceptance flow {flow_id} verification task does not own all requirements",
        )
        level = verification_task.get("completion_level", "module_ready")
        _require(
            COMPLETION_LEVELS[level] >= COMPLETION_LEVELS["integration_ready"],
            f"acceptance flow {flow_id} requires integration_ready or higher verification task",
        )
        required_scope = set().union(
            *(acceptance_scope_by_requirement[requirement_id] for requirement_id in flow_requirements)
        )
        _require(
            required_scope <= set(verification_task.get("claim_scope", [])),
            f"acceptance flow {flow_id} verification task misses claim_scope: "
            + ", ".join(sorted(required_scope - set(verification_task.get("claim_scope", [])))),
        )
        required_claims = set(
            _unique_strings(flow["required_claims"], f"{path}.required_claims", claims=True, allow_empty=False)
        )
        _require(
            required_claims <= set(_required_claims(plan, verification_task)),
            f"acceptance flow {flow_id} requires claims not owned by verification task",
        )
        direct_test_ids = _unique_strings(
            flow["direct_test_ids"], f"{path}.direct_test_ids", allow_empty=False
        )
        _require(
            set(direct_test_ids) <= set(verification_task["claim_overrides"]["automation_test_ids"]),
            f"acceptance flow {flow_id} direct tests must belong to its verification task",
        )
        covered_claims: set[str] = set()
        for test_id in direct_test_ids:
            _require(test_id in qualifications, f"acceptance flow {flow_id} references unknown test {test_id}")
            qualification = qualifications[test_id]
            _require(
                flow_requirements <= set(qualification["requirement_ids"]),
                f"acceptance flow {flow_id} test {test_id} does not bind all flow requirements",
            )
            covered_claims.update(qualification["claim_dimensions"])
        _require(
            required_claims <= covered_claims,
            f"acceptance flow {flow_id} direct tests miss claims: "
            + ", ".join(sorted(required_claims - covered_claims)),
        )
        if strict:
            _require(
                "evidence_mode" in flow and "scope_coverage" in flow,
                f"strict acceptance flow {flow_id} must declare evidence_mode and scope_coverage",
            )
        if "evidence_mode" in flow or "scope_coverage" in flow:
            _require(
                "evidence_mode" in flow and "scope_coverage" in flow,
                f"acceptance flow {flow_id} must declare evidence_mode and scope_coverage together",
            )
            evidence_mode = _expect_string(flow["evidence_mode"], f"{path}.evidence_mode")
            _require(
                evidence_mode in FLOW_EVIDENCE_MODES,
                f"acceptance flow {flow_id} has invalid evidence_mode",
            )
            coverage_value = _expect_object(flow["scope_coverage"], f"{path}.scope_coverage")
            _require(
                set(coverage_value) == required_scope,
                f"acceptance flow {flow_id} scope_coverage must exactly match acceptance scope; missing="
                + ",".join(sorted(required_scope - set(coverage_value)))
                + " extra="
                + ",".join(sorted(set(coverage_value) - required_scope)),
            )
            scope_claims_by_scope: dict[str, set[str]] = {
                scope_id: set(required_claims) for scope_id in required_scope
            }
            if "scope_claims" in flow:
                scope_claims_value = _expect_object(
                    flow["scope_claims"], f"{path}.scope_claims"
                )
                _require(
                    set(scope_claims_value) == required_scope,
                    f"acceptance flow {flow_id} scope_claims must exactly match acceptance scope",
                )
                scope_claims_by_scope = {}
                for scope_id, claims_value in scope_claims_value.items():
                    scoped_claims = set(
                        _unique_strings(
                            claims_value,
                            f"{path}.scope_claims.{scope_id}",
                            claims=True,
                            allow_empty=False,
                        )
                    )
                    _require(
                        scoped_claims <= required_claims,
                        f"acceptance flow {flow_id} scope_claims for {scope_id} exceed required_claims",
                    )
                    scope_claims_by_scope[scope_id] = scoped_claims
                _require(
                    set().union(*scope_claims_by_scope.values()) == required_claims,
                    f"acceptance flow {flow_id} scope_claims must cover every required claim",
                )
            covered_test_ids: set[str] = set()
            for scope_id, mapped_value in coverage_value.items():
                _expect_string(scope_id, f"{path}.scope_coverage key")
                mapped_tests = _unique_strings(
                    mapped_value,
                    f"{path}.scope_coverage.{scope_id}",
                    allow_empty=False,
                )
                _require(
                    set(mapped_tests) <= set(direct_test_ids),
                    f"acceptance flow {flow_id} scope {scope_id} maps undeclared direct tests",
                )
                covered_test_ids.update(mapped_tests)
                for test_id in mapped_tests:
                    qualification = qualifications[test_id]
                    _require(
                        qualification.get("evidence_shape", "module") == "vertical",
                        f"acceptance flow {flow_id} requires vertical test evidence for {test_id}",
                    )
                    _require(
                        scope_id in qualification.get("observed_scopes", []),
                        f"acceptance flow {flow_id} test {test_id} does not observe scope {scope_id}",
                    )
                    _require(
                        scope_claims_by_scope[scope_id]
                        <= set(qualification["claim_dimensions"]),
                        f"acceptance flow {flow_id} scope_claims for {scope_id} are not proven by {test_id}",
                    )
            _require(
                covered_test_ids == set(direct_test_ids),
                f"acceptance flow {flow_id} has direct tests outside scope_coverage: "
                + ", ".join(sorted(set(direct_test_ids) - covered_test_ids)),
            )
            if evidence_mode == "single_receipt":
                _require(
                    len(direct_test_ids) == 1,
                    f"single_receipt flow {flow_id} must use exactly one direct test",
                )
                _require(
                    all(set(mapped) == set(direct_test_ids) for mapped in coverage_value.values()),
                    f"single_receipt flow {flow_id} must bind every scope to its one direct test",
                )
    _require(
        mapped_direct_flow_requirements == direct_flow_requirements,
        "direct_flow requirements without acceptance flow: "
        + ", ".join(sorted(direct_flow_requirements - mapped_direct_flow_requirements)),
    )
    strict_flow_verification_tasks = {
        flow["verification_task_id"]
        for flow in plan.get("acceptance_flows", [])
        if "evidence_mode" in flow and "scope_coverage" in flow
    }
    for task_id, task in task_by_id.items():
        if (
            task.get("completion_level") == "domain_complete"
            and (strict or task.get("scope_enforced", False))
        ):
            _require(
                task_id in strict_flow_verification_tasks,
                f"scope-enforced domain_complete task {task_id} must verify a strict acceptance flow",
            )
    if strict:
        high_level_tasks = {
            task["id"]
            for task in tasks
            if COMPLETION_LEVELS[task["completion_level"]]
            >= COMPLETION_LEVELS["integration_ready"]
        }
        if high_level_tasks:
            _require(
                any(
                    source.get("inventory_mode") == "exact"
                    for source in sources_by_id.values()
                ),
                "strict plan with high-level tasks requires at least one exact scope source",
            )
            _require(
                bool(direct_flow_requirements),
                "strict plan with high-level tasks requires at least one direct_flow requirement",
            )

    group_ids: set[str] = set()
    grouped_tasks: set[str] = set()
    for index, group_value in enumerate(_expect_list(plan["groups"], "plan.groups")):
        path = f"plan.groups[{index}]"
        group = _expect_object(group_value, path)
        _expect_keys(group, required={"id", "title", "task_ids"}, optional=set(), path=path)
        group_id = _expect_id(group["id"], f"{path}.id")
        _require(group_id not in group_ids, f"duplicate group id: {group_id}")
        group_ids.add(group_id)
        _expect_string(group["title"], f"{path}.title")
        for task_id in _unique_strings(group["task_ids"], f"{path}.task_ids", ids=True):
            _require(task_id in task_by_id, f"group {group_id} references unknown task {task_id}")
            _require(task_id not in grouped_tasks, f"task {task_id} appears in multiple groups")
            grouped_tasks.add(task_id)


def _new_task_state(status: str = "todo") -> dict[str, Any]:
    return {"status": status, "evidence_refs": [], "unresolved": [], "baseline_identity": {}}


def _validate_unresolved(value: Any, path: str) -> list[dict[str, Any]]:
    items = _expect_list(value, path)
    result: list[dict[str, Any]] = []
    for index, item_value in enumerate(items):
        item_path = f"{path}[{index}]"
        item = _expect_object(item_value, item_path)
        _expect_keys(
            item,
            required={"type", "subject", "next_action"},
            optional={"details"},
            path=item_path,
        )
        _expect_string(item["type"], f"{item_path}.type")
        _expect_string(item["subject"], f"{item_path}.subject")
        _expect_string(item["next_action"], f"{item_path}.next_action")
        if "details" in item:
            _expect_string(item["details"], f"{item_path}.details")
        result.append(item)
    return result


def _validate_state(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    enforce_plan_revision: bool = True,
) -> None:
    _expect_keys(
        state,
        required={"schema", "plan_id", "plan_revision", "revision", "active_package", "task_states"},
        optional=set(),
        path="state",
    )
    _require(state["schema"] == STATE_SCHEMA, f"state.schema must be {STATE_SCHEMA}")
    _require(state["plan_id"] == plan["plan_id"], "state.plan_id does not match plan")
    if enforce_plan_revision:
        _require(
            state["plan_revision"] == _plan_hash(plan),
            "plan.json changed outside taskctl amend; state revision is bound to another plan",
            code="plan_revision_mismatch",
        )
    _require(
        isinstance(state["revision"], int) and not isinstance(state["revision"], bool) and state["revision"] >= 1,
        "state.revision must be a positive integer",
    )
    task_by_id = _task_map(plan)
    task_states = _expect_object(state["task_states"], "state.task_states")
    _require(set(task_states) == set(task_by_id), "state.task_states must match plan task ids")
    for task_id, task_state_value in task_states.items():
        task_state = _expect_object(task_state_value, f"state.task_states.{task_id}")
        _expect_keys(
            task_state,
            required={"status", "evidence_refs", "unresolved", "baseline_identity"},
            optional=set(),
            path=f"state.task_states.{task_id}",
        )
        status = _expect_string(task_state["status"], f"state.task_states.{task_id}.status")
        _require(status in TASK_STATUSES, f"task {task_id} has invalid status {status}")
        _unique_strings(task_state["evidence_refs"], f"state.task_states.{task_id}.evidence_refs")
        _validate_unresolved(task_state["unresolved"], f"state.task_states.{task_id}.unresolved")
        baseline = _expect_object(task_state["baseline_identity"], f"state.task_states.{task_id}.baseline_identity")
        if baseline:
            identity_keys = BASE_FRESHNESS_KEYS | set(task_by_id[task_id]["freshness_scopes"])
            _expect_keys(
                baseline,
                required=identity_keys | {"scope_summary"},
                optional=set(),
                path=f"state.task_states.{task_id}.baseline_identity",
            )
            for identity_key in identity_keys:
                _expect_string(
                    baseline[identity_key],
                    f"state.task_states.{task_id}.baseline_identity.{identity_key}",
                )
            _expect_object(
                baseline["scope_summary"],
                f"state.task_states.{task_id}.baseline_identity.scope_summary",
            )
    active = state["active_package"]
    if active is None:
        _require(
            all(task_state["status"] != "active" for task_state in task_states.values()),
            "active task exists without active_package",
        )
        return
    active = _expect_object(active, "state.active_package")
    _expect_keys(
        active,
        required={
            "task_ids",
            "phase",
            "baseline_identity",
            "changed_paths",
            "evidence_refs",
            "unresolved",
            "next_action",
        },
        optional={"revalidation_task_ids", "controller_identity"},
        path="state.active_package",
    )
    if "controller_identity" in active:
        _expect_string(active["controller_identity"], "state.active_package.controller_identity")
    active_ids = _unique_strings(active["task_ids"], "state.active_package.task_ids", ids=True, allow_empty=False)
    revalidation_ids = _unique_strings(
        active.get("revalidation_task_ids", []),
        "state.active_package.revalidation_task_ids",
        ids=True,
    )
    _require(
        set(revalidation_ids) <= set(active_ids),
        "active revalidation task ids must be active package task ids",
    )
    for task_id in active_ids:
        _require(task_id in task_by_id, f"active_package references unknown task {task_id}")
        _require(task_states[task_id]["status"] == "active", f"active task {task_id} is not active in task_states")
    phase = _expect_string(active["phase"], "state.active_package.phase")
    _require(phase in PHASES, f"state.active_package.phase is invalid: {phase}")
    baselines = _expect_object(active["baseline_identity"], "state.active_package.baseline_identity")
    _require(set(baselines) == set(active_ids), "active baseline identities must match active task ids")
    _unique_strings(active["changed_paths"], "state.active_package.changed_paths")
    _unique_strings(active["evidence_refs"], "state.active_package.evidence_refs")
    _validate_unresolved(active["unresolved"], "state.active_package.unresolved")
    _expect_string(active["next_action"], "state.active_package.next_action")


def _dependencies_done(plan: dict[str, Any], state: dict[str, Any], task: dict[str, Any]) -> bool:
    return all(state["task_states"][edge["task_id"]]["status"] == "done" for edge in task["depends_on"])


def _dependency_closure(plan: dict[str, Any], seeds: set[str]) -> set[str]:
    tasks = _task_map(plan)
    result = set(seeds)
    queue = list(seeds)
    while queue:
        current = queue.pop()
        for edge in tasks[current]["depends_on"]:
            dependency = edge["task_id"]
            if dependency not in result:
                result.add(dependency)
                queue.append(dependency)
    return result


def _active_evidence_task_ids(plan: dict[str, Any], state: dict[str, Any]) -> set[str]:
    active = state["active_package"]
    _require(active is not None, "cannot ingest evidence without an active package")
    return _dependency_closure(plan, set(active["task_ids"]))


def _active_controller_status(state: dict[str, Any]) -> str:
    active = state.get("active_package")
    if active is None:
        return "not_active"
    expected = active.get("controller_identity")
    if not expected:
        return "unbound"
    return "verified" if expected == _controller_identity() else "drifted"


def _require_active_controller(state: dict[str, Any]) -> None:
    status = _active_controller_status(state)
    _require(
        status == "verified",
        "active work package controller changed or predates controller binding; "
        "use checkpoint --release, review the change, then begin again",
        code="controller_drift",
    )


def _recompute_ready(plan: dict[str, Any], state: dict[str, Any]) -> None:
    for task in plan["tasks"]:
        task_state = state["task_states"][task["id"]]
        if task_state["status"] not in {"todo", "ready"}:
            continue
        task_state["status"] = "ready" if _dependencies_done(plan, state, task) else "todo"


def _verify_scope_sources(plan: dict[str, Any], plan_dir: Path) -> None:
    project_root: Path | None = None
    for source in plan["scope_sources"]:
        if source.get("fingerprint_mode", "label") != "file_sha256":
            continue
        relative = _validate_relative_path(source["ref"], f"scope source {source['id']}.ref")
        if source["root"] == "task":
            root = plan_dir
        else:
            if project_root is None:
                project_root = _project_root(plan_dir, None)
            root = project_root
        source_path = (root / Path(relative)).resolve()
        _require(
            _inside(source_path, root),
            f"scope source {source['id']} escapes its {source['root']} root",
            code="source_drift",
        )
        _require(
            source_path.is_file(),
            f"scope source {source['id']} is missing: {source_path}",
            code="source_drift",
        )
        actual = _sha256_file(source_path)
        _require(
            actual == source["fingerprint"],
            f"scope source {source['id']} changed; expected {source['fingerprint']}, got {actual}; amend the requirement inventory before continuing",
            code="source_drift",
        )
        inventory_specs: list[tuple[str, str, set[str]]] = []
        inventory_prefix = source.get("inventory_prefix")
        if inventory_prefix:
            inventory_specs.append(
                ("requirement", inventory_prefix, set(source.get("requirement_ids", [])))
            )
        for kind, (ids_field, prefix_field) in TRACE_SOURCE_INVENTORIES.items():
            prefix = source.get(prefix_field)
            if prefix:
                inventory_specs.append((kind, prefix, set(source.get(ids_field, []))))
        if inventory_specs:
            try:
                source_text = source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise TaskCtlError(
                    f"scope source {source['id']} exact inventory must be UTF-8 text: {source_path}",
                    code="source_inventory_drift",
                ) from exc
        for kind, prefix, declared_ids in inventory_specs:
            token_pattern = re.compile(
                rf"(?<![A-Za-z0-9_.:-]){re.escape(prefix)}[A-Za-z0-9_.:-]*(?![A-Za-z0-9_.:-])"
            )
            observed_ids = set(token_pattern.findall(source_text))
            _require(
                observed_ids == declared_ids,
                f"scope source {source['id']} {kind} ids differ from the file; missing="
                + ",".join(sorted(observed_ids - declared_ids))
                + " extra="
                + ",".join(sorted(declared_ids - observed_ids)),
                code="source_inventory_drift",
            )


def _load_plan_state(
    plan_dir: Path,
    *,
    require_state: bool = True,
    enforce_plan_revision: bool = True,
    verify_sources: bool = True,
    enforce_source_durability: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    plan = _load_json(plan_dir / "plan.json")
    _validate_plan(plan, enforce_source_durability=enforce_source_durability)
    if verify_sources:
        _verify_scope_sources(plan, plan_dir)
    state_path = plan_dir / "state.json"
    if not state_path.is_file():
        _require(not require_state, f"missing state.json in {plan_dir}", code="missing_state")
        return plan, None
    state = _load_json(state_path)
    _validate_state(state, plan, enforce_plan_revision=enforce_plan_revision)
    return plan, state


def _evidence_filename(evidence_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", evidence_id).strip("-.") or "evidence"
    digest = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:80]}-{digest}.json"


def _artifact_snapshot_path(artifact_path: Path, artifact_hash: str) -> str:
    digest = artifact_hash.removeprefix("sha256:")
    suffix = artifact_path.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
        suffix = ".bin"
    return f"evidence/artifacts/{digest}{suffix}"


def _prepare_evidence_snapshots(
    report_path: Path,
    envelope: dict[str, Any],
    *,
    project_root: Path,
    plan_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    normalized = copy.deepcopy(envelope)
    pending_files: dict[str, bytes] = {}
    for artifact in normalized["raw_artifacts"]:
        artifact_path = _resolve_allowed_path(
            artifact["path"],
            root_kind=artifact["root"],
            project_root=project_root,
            plan_dir=plan_dir,
        )
        payload = artifact_path.read_bytes()
        _require(
            _sha256_bytes(payload) == artifact["sha256"],
            f"raw artifact changed while importing evidence: {artifact_path}",
        )
        relative = _artifact_snapshot_path(artifact_path, artifact["sha256"])
        pending_files[relative] = payload
        artifact["root"] = "plan"
        artifact["path"] = relative

    source_relative = f"evidence/sources/{_evidence_filename(envelope['evidence_id'])}"
    source_payload = report_path.read_bytes()
    pending_files[source_relative] = source_payload
    source = {
        "root": "plan",
        "path": source_relative,
        "sha256": _sha256_bytes(source_payload),
    }
    return normalized, source, pending_files


def _resolve_input_report(path_text: str, project_root: Path, plan_dir: Path) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = plan_dir / path
    resolved = path.resolve()
    _require(
        _inside(resolved, project_root) or _inside(resolved, plan_dir),
        f"evidence report is outside allowed roots: {resolved}",
    )
    _require(resolved.is_file(), f"evidence report does not exist: {resolved}", code="missing_evidence")
    return resolved


def _resolve_task_input(path_text: str, plan_dir: Path, label: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = plan_dir / path
    resolved = path.resolve()
    _require(
        _inside(resolved, plan_dir),
        f"{label} is outside task directory: {resolved}",
        code="task_input_outside_root",
    )
    _require(
        resolved.is_file(),
        f"{label} does not exist: {resolved}",
        code="missing_task_input",
    )
    return resolved


def _resolve_context_output_dir(
    path_text: str, project_root: Path, plan_dir: Path
) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = plan_dir / path
    resolved = path.resolve()
    _require(
        _inside(resolved, project_root) or _inside(resolved, plan_dir),
        f"context output directory is outside allowed roots: {resolved}",
        code="context_output_outside_root",
    )
    _require(
        resolved not in {project_root, plan_dir},
        "context output directory must be a dedicated subdirectory",
        code="context_output_too_broad",
    )
    resolved.mkdir(parents=True, exist_ok=True)
    _require(resolved.is_dir(), f"context output path is not a directory: {resolved}")
    return resolved


def _validate_evidence_envelope(
    envelope: dict[str, Any],
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
    active_only: bool,
) -> None:
    _expect_keys(
        envelope,
        required={
            "schema",
            "evidence_id",
            "plan_id",
            "plan_revision",
            "task_ids",
            "type",
            "phase",
            "source_class",
            "producer",
            "result",
            "claims",
            "subjects",
            "test_ids",
            "freshness_identity",
            "raw_artifacts",
            "started_at",
            "completed_at",
            "summary",
        },
        optional={"decision_ref"},
        path="evidence",
    )
    _require(envelope["schema"] == EVIDENCE_SCHEMA, f"evidence.schema must be {EVIDENCE_SCHEMA}")
    _expect_id(envelope["evidence_id"], "evidence.evidence_id")
    _require(envelope["plan_id"] == plan["plan_id"], "evidence.plan_id does not match plan")
    if active_only:
        _require(envelope["plan_revision"] == state["plan_revision"], "new evidence uses a stale plan revision")
    task_ids = _unique_strings(envelope["task_ids"], "evidence.task_ids", ids=True, allow_empty=False)
    _require(len(task_ids) == 1, "evidence envelope must bind claims to exactly one task")
    task_by_id = _task_map(plan)
    for task_id in task_ids:
        _require(task_id in task_by_id, f"evidence references unknown task {task_id}")
    if active_only:
        _require(
            set(task_ids) <= _active_evidence_task_ids(plan, state),
            "evidence references a task outside the active package dependency closure",
        )
    _expect_string(envelope["type"], "evidence.type")
    phase = _expect_string(envelope["phase"], "evidence.phase")
    _require(phase in {"expected_red", "verification", "decision"}, "evidence.phase is invalid")
    source_class = _expect_string(envelope["source_class"], "evidence.source_class")
    _require(source_class in SOURCE_CLASSES, "evidence.source_class is invalid")
    producer_ref = _expect_object(envelope["producer"], "evidence.producer")
    _expect_keys(producer_ref, required={"id", "version"}, optional=set(), path="evidence.producer")
    producer_id = _expect_id(producer_ref["id"], "evidence.producer.id")
    _require(producer_id in plan["producers"], f"evidence uses unregistered producer {producer_id}")
    producer = plan["producers"][producer_id]
    _require(producer_ref["version"] == producer["version"], f"producer {producer_id} version does not match plan")
    _require(source_class == producer["source_class"], f"producer {producer_id} source_class does not match plan")
    result = _expect_string(envelope["result"], "evidence.result")
    _require(result in EVIDENCE_RESULTS, "evidence.result is invalid")
    claims = _unique_strings(envelope["claims"], "evidence.claims", claims=True)
    _require(set(claims) <= set(producer["allowed_claims"]), f"producer {producer_id} emitted disallowed claims")
    if result == "expected_fail":
        _require(phase == "expected_red", "expected_fail evidence must use expected_red phase")
    if phase == "expected_red":
        _require(result == "expected_fail", "expected_red phase must use expected_fail result")
    if phase == "decision":
        _require(source_class == "human_decision", "decision evidence must use human_decision source")
        _expect_string(envelope.get("decision_ref"), "evidence.decision_ref")
    _unique_strings(envelope["subjects"], "evidence.subjects")
    _unique_strings(envelope["test_ids"], "evidence.test_ids")
    freshness = _expect_object(envelope["freshness_identity"], "evidence.freshness_identity")
    for key, value in freshness.items():
        _expect_string(key, f"evidence.freshness_identity.{key}")
        _expect_string(value, f"evidence.freshness_identity.{key}")
    raw_artifacts = _expect_list(envelope["raw_artifacts"], "evidence.raw_artifacts")
    if producer["requires_raw_artifacts"]:
        _require(bool(raw_artifacts), f"producer {producer_id} requires raw_artifacts")
    for index, artifact_value in enumerate(raw_artifacts):
        path = f"evidence.raw_artifacts[{index}]"
        artifact = _expect_object(artifact_value, path)
        _expect_keys(artifact, required={"root", "path", "sha256"}, optional=set(), path=path)
        root_kind = _expect_string(artifact["root"], f"{path}.root")
        _require(root_kind in {"project", "plan"}, f"{path}.root is invalid")
        artifact_path = _resolve_allowed_path(
            _expect_string(artifact["path"], f"{path}.path"),
            root_kind=root_kind,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        _require(artifact_path.is_file(), f"raw artifact does not exist: {artifact_path}")
        _require(_sha256_file(artifact_path) == artifact["sha256"], f"raw artifact hash mismatch: {artifact_path}")
    started_text = _expect_string(envelope["started_at"], "evidence.started_at")
    completed_text = _expect_string(envelope["completed_at"], "evidence.completed_at")
    started_at = _parse_timestamp(started_text)
    completed_at = _parse_timestamp(completed_text)
    _require(started_at is not None, "evidence.started_at must be an ISO-8601 timestamp")
    _require(completed_at is not None, "evidence.completed_at must be an ISO-8601 timestamp")
    _require(completed_at >= started_at, "evidence.completed_at must not precede started_at")
    _expect_object(envelope["summary"], "evidence.summary")


def _index_report(
    report_path: Path,
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, bytes]]:
    envelope = _load_json(report_path)
    _validate_evidence_envelope(
        envelope,
        plan=plan,
        state=state,
        project_root=project_root,
        plan_dir=plan_dir,
        active_only=True,
    )
    normalized, source, pending_files = _prepare_evidence_snapshots(
        report_path,
        envelope,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    index = {
        "schema": INDEX_SCHEMA,
        "evidence_id": normalized["evidence_id"],
        "source_envelope": source,
        "envelope": normalized,
    }
    relative = f"evidence/index/{_evidence_filename(normalized['evidence_id'])}"
    destination = plan_dir / Path(relative)
    if destination.is_file():
        existing = _load_json(destination)
        _require(existing == index, f"evidence id {normalized['evidence_id']} already exists with different content")
    return relative, index, normalized, pending_files


def _prepare_evidence_reports(
    paths: Iterable[str],
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, bytes],
    dict[str, list[str]],
    list[dict[str, Any]],
]:
    pending_indexes: dict[str, dict[str, Any]] = {}
    pending_snapshots: dict[str, bytes] = {}
    new_refs_by_task: dict[str, list[str]] = {
        task_id: [] for task_id in _active_evidence_task_ids(plan, state)
    }
    envelopes: list[dict[str, Any]] = []
    for path_text in paths:
        report_path = _resolve_input_report(path_text, project_root, plan_dir)
        relative, index, envelope, snapshots = _index_report(
            report_path,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        if relative in pending_indexes:
            _require(
                pending_indexes[relative] == index,
                f"evidence index collision: {relative}",
            )
        pending_indexes[relative] = index
        for snapshot_relative, payload in snapshots.items():
            if snapshot_relative in pending_snapshots:
                _require(
                    pending_snapshots[snapshot_relative] == payload,
                    f"evidence snapshot collision: {snapshot_relative}",
                )
            pending_snapshots[snapshot_relative] = payload
        for task_id in envelope["task_ids"]:
            new_refs_by_task[task_id].append(relative)
        envelopes.append(envelope)
    return pending_indexes, pending_snapshots, new_refs_by_task, envelopes


def _commit_evidence_reports(
    *,
    plan_dir: Path,
    state: dict[str, Any],
    pending_indexes: dict[str, dict[str, Any]],
    pending_snapshots: dict[str, bytes],
    new_refs_by_task: dict[str, list[str]],
) -> None:
    for task_id, references in new_refs_by_task.items():
        task_state = state["task_states"][task_id]
        task_state["evidence_refs"] = list(
            dict.fromkeys(task_state["evidence_refs"] + references)
        )
    for relative, payload in pending_snapshots.items():
        _write_bytes_immutable(plan_dir / Path(relative), payload)
    for relative, index in pending_indexes.items():
        _write_json_atomic(plan_dir / Path(relative), index)


def _load_index(
    relative: str,
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
) -> dict[str, Any]:
    normalized = _validate_relative_path(relative, "evidence reference")
    index_path = (plan_dir / Path(normalized)).resolve()
    _require(_inside(index_path, plan_dir), f"evidence reference escapes plan root: {relative}")
    index = _load_json(index_path)
    _expect_keys(
        index,
        required={"schema", "evidence_id", "source_envelope", "envelope"},
        optional=set(),
        path=f"index {relative}",
    )
    _require(index["schema"] == INDEX_SCHEMA, f"index {relative} has unsupported schema")
    source = _expect_object(index["source_envelope"], f"index {relative}.source_envelope")
    _expect_keys(source, required={"root", "path", "sha256"}, optional=set(), path=f"index {relative}.source_envelope")
    source_root = _expect_string(source["root"], f"index {relative}.source_envelope.root")
    _require(source_root in {"project", "plan"}, f"index {relative}.source_envelope.root is invalid")
    source_path = _resolve_allowed_path(
        _expect_string(source["path"], f"index {relative}.source_envelope.path"),
        root_kind=source_root,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    _expect_string(source["sha256"], f"index {relative}.source_envelope.sha256")
    _require(source_path.is_file(), f"source evidence report is missing: {source_path}")
    _require(_sha256_file(source_path) == source["sha256"], f"source evidence report hash mismatch: {source_path}")
    envelope = _expect_object(index["envelope"], f"index {relative}.envelope")
    _require(index["evidence_id"] == envelope.get("evidence_id"), f"index {relative} evidence id mismatch")
    _validate_evidence_envelope(
        envelope,
        plan=plan,
        state=state,
        project_root=project_root,
        plan_dir=plan_dir,
        active_only=False,
    )
    return envelope


def _load_task_evidence(
    task_state: dict[str, Any],
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
) -> list[dict[str, Any]]:
    return [
        _load_index(
            reference,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        for reference in task_state["evidence_refs"]
    ]


def _current_freshness(
    plan: dict[str, Any],
    task: dict[str, Any],
    project_root: Path,
    *,
    require_planned_tests: bool = False,
) -> dict[str, str]:
    identities = _task_identities(plan, task, project_root)
    summary = identities["scope_summary"]
    if task["claim_overrides"]["automation_test_ids"]:
        _require(
            not summary["test_missing"],
            "test_scope identity inputs are missing: " + ", ".join(summary["test_missing"]),
            code="freshness_input_missing",
        )
        if require_planned_tests:
            _require(
                not summary["planned_test_missing"],
                "planned_test_scope identity inputs are missing: "
                + ", ".join(summary["planned_test_missing"]),
                code="freshness_input_missing",
            )
    for key, custom_summary in summary["custom"].items():
        _require(
            not custom_summary["missing"],
            f"freshness scope {key} inputs are missing: "
            + ", ".join(custom_summary["missing"]),
            code="freshness_input_missing",
        )
    return {key: value for key, value in identities.items() if key != "scope_summary"}


def _parse_timestamp(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return None


def _evidence_fact_identity(record: dict[str, Any]) -> str:
    """Ignore labels and timestamps so duplicated facts cannot inflate evidence counts."""
    return _json_identity(
        {
            "type": record["type"],
            "phase": record["phase"],
            "producer": record["producer"],
            "result": record["result"],
            "claims": sorted(record["claims"]),
            "subjects": sorted(record["subjects"]),
            "test_ids": sorted(record["test_ids"]),
            "freshness_identity": record["freshness_identity"],
            "raw_artifacts": sorted(
                record["raw_artifacts"],
                key=lambda item: (item["root"], item["path"], item["sha256"]),
            ),
        }
    )


def _freshness_value_matches(
    plan: dict[str, Any],
    record: dict[str, Any],
    key: str,
    expected: str,
) -> bool:
    observed = record["freshness_identity"].get(key)
    if observed == expected:
        return True
    if key != "runner" or observed is None:
        return False
    producer_ref = record.get("producer", {})
    producer = plan["producers"].get(producer_ref.get("id"))
    return bool(
        producer
        and producer_ref.get("version") == producer.get("version")
    )


def _expected_red_records(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
    project_root: Path,
    *,
    require_planned_tests: bool = False,
) -> list[dict[str, Any]]:
    task_id = task["id"]
    required_claims = _required_claims(plan, task)
    current = _current_freshness(
        plan,
        task,
        project_root,
        require_planned_tests=require_planned_tests,
    )
    baseline = state["task_states"][task_id]["baseline_identity"]
    task_is_done = state["task_states"][task_id].get("status") == "done"
    active = state.get("active_package") or {}
    task_is_revalidation = task_id in active.get("revalidation_task_ids", [])
    red_freshness_keys = {
        key
        for claim in required_claims
        for key in _claim_rule(plan, task, claim)["freshness_keys"]
    }

    def matches(record: dict[str, Any]) -> bool:
        for key in red_freshness_keys:
            if task_is_done and key in {
                "contract",
                "production_scope",
                "runner",
                "test_scope",
            }:
                # Expected-red is a historical ordering fact once the task is
                # complete. Later implementation or consumer work may update
                # its amended contract, production, shared tests, or runners;
                # the task can only return to done after current verification
                # proves that contract. A rewritten red receipt against green
                # code would destroy the historical ordering evidence.
                continue
            if task_is_revalidation and key in {
                "contract",
                "production_scope",
                "runner",
                "test_scope",
            }:
                # audit --apply reopens a previously completed task as
                # needs_review, and begin then refreshes its production
                # baseline to the current implementation. A fresh passing
                # verification revalidates that implementation against the
                # amended contract; the sealed red remains the historical
                # ordering proof and must not be recreated against green
                # code. New tasks and first implementations never enter this
                # branch, so they still require a red sealed against their
                # current contract and begin baseline.
                continue
            expected = (
                baseline.get("production_scope")
                if key == "production_scope"
                else current.get(key)
            )
            if expected is None or not _freshness_value_matches(
                plan, record, key, expected
            ):
                return False
        return True

    required_tests = task["claim_overrides"]["automation_test_ids"]
    producer_id = task["tests_first"]["expected_red_producer"]
    return [
        record
        for record in records
        if task_id in record["task_ids"]
        and record["phase"] == "expected_red"
        and record["result"] == "expected_fail"
        and record["producer"]["id"] == producer_id
        and matches(record)
        and (not required_tests or set(required_tests) <= set(record["test_ids"]))
    ]


def _require_sealed_red_identity(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
    project_root: Path,
) -> list[dict[str, Any]]:
    if task["tests_first"]["mode"] != "required":
        return []
    matching = _expected_red_records(
        plan,
        state,
        task,
        records,
        project_root,
        require_planned_tests=True,
    )
    if matching:
        return matching
    has_red = any(
        task["id"] in record["task_ids"] and record["phase"] == "expected_red"
        for record in records
    )
    _require(
        not has_red,
        f"sealed expected-red identity changed for task {task['id']}; restore the sealed test/contract/runner identity",
        code="red_identity_changed",
    )
    raise TaskCtlError(
        f"task {task['id']} has no sealed expected-red evidence",
        code="expected_red_not_sealed",
    )


def _evaluate_task(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    task_id = task["id"]
    required_claims = _required_claims(plan, task)
    current = _current_freshness(plan, task, project_root)
    missing: list[dict[str, Any]] = []
    claim_status: dict[str, str] = {}
    valid_records_by_claim: dict[str, list[dict[str, Any]]] = {}
    stale_count = 0
    for claim in required_claims:
        rule = _claim_rule(plan, task, claim)
        valid: list[dict[str, Any]] = []
        seen_facts: set[str] = set()
        for record in records:
            if task_id not in record["task_ids"] or record["result"] != "pass" or claim not in record["claims"]:
                continue
            producer_id = record["producer"]["id"]
            if producer_id not in rule["producers"] or record["source_class"] not in rule["source_classes"]:
                continue
            freshness = record["freshness_identity"]
            stale_reasons: list[str] = []
            for key in rule["freshness_keys"]:
                if key not in freshness:
                    stale_reasons.append(f"missing:{key}")
                elif key in current and not _freshness_value_matches(
                    plan, record, key, current[key]
                ):
                    stale_reasons.append(f"stale:{key}")
            if stale_reasons:
                stale_count += 1
                continue
            fact_identity = _evidence_fact_identity(record)
            if fact_identity in seen_facts:
                continue
            seen_facts.add(fact_identity)
            valid.append(record)
        valid_records_by_claim[claim] = valid
        required_count = rule["min_evidence"]
        if len(valid) < required_count:
            claim_status[claim] = "missing"
            missing.append(
                {
                    "type": "missing_evidence",
                    "subject": claim,
                    "next_action": f"provide {required_count} valid evidence item(s) for {claim}",
                }
            )
        else:
            claim_status[claim] = "pass"

    overrides = task["claim_overrides"]
    required_tests = overrides["automation_test_ids"]
    observed_tests: set[str] = set()
    for test_id in required_tests:
        qualification = plan["test_qualifications"].get(test_id)
        if not qualification or qualification["trust_state"] != "qualified":
            missing.append(
                {
                    "type": "test_invalid",
                    "subject": test_id,
                    "next_action": "qualify, replace, or remove the invalid legacy test before implementation completion",
                }
            )
            continue
        if not set(qualification["requirement_ids"]) & set(task["requirement_ids"]):
            missing.append(
                {
                    "type": "test_invalid",
                    "subject": test_id,
                    "next_action": "map the test to a requirement consumed by this task",
                }
            )
            continue
        applicable_claims = set(qualification["claim_dimensions"]) & set(required_claims)
        if not applicable_claims:
            missing.append(
                {
                    "type": "test_invalid",
                    "subject": test_id,
                    "next_action": "correct the test claim dimensions",
                }
            )
            continue
        test_observed = any(
            test_id in record["test_ids"]
            for claim in applicable_claims
            for record in valid_records_by_claim[claim]
        )
        if test_observed:
            observed_tests.add(test_id)
        else:
            missing.append(
                {"type": "missing_test", "subject": test_id, "next_action": "run the qualified test"}
            )

    observed_subjects: set[str] = set()
    for claim_records in valid_records_by_claim.values():
        for record in claim_records:
            observed_subjects.update(record["subjects"])
    for subject in overrides["readback_subjects"]:
        if subject not in observed_subjects:
            missing.append(
                {"type": "missing_readback", "subject": subject, "next_action": "provide independent readback"}
            )

    tests_first = task["tests_first"]
    if tests_first["mode"] == "required":
        expected_red = _expected_red_records(
            plan, state, task, records, project_root
        )
        verification_times = [
            timestamp
            for record in records
            if record["result"] == "pass"
            for timestamp in [_parse_timestamp(record["started_at"])]
            if timestamp is not None
        ]
        red_times = [
            timestamp
            for record in expected_red
            for timestamp in [_parse_timestamp(record["completed_at"])]
            if timestamp is not None
        ]
        if not expected_red:
            missing.append(
                {
                    "type": "tests_first",
                    "subject": task_id,
                    "next_action": "provide expected-red evidence captured against the begin production baseline",
                }
            )
        elif verification_times and red_times and not any(
            verification_time >= red_time
            for verification_time in verification_times
            for red_time in red_times
        ):
            missing.append(
                {
                    "type": "tests_first",
                    "subject": task_id,
                    "next_action": "expected-red evidence must precede verification evidence",
                }
            )

    deduplicated: list[dict[str, Any]] = []
    seen_missing: set[tuple[str, str, str]] = set()
    for item in missing:
        key = (item["type"], item["subject"], item["next_action"])
        if key not in seen_missing:
            seen_missing.add(key)
            deduplicated.append(item)
    return {
        "task_id": task_id,
        "outcome": task["outcome"],
        "claims": claim_status,
        "required_tests": len(required_tests),
        "observed_tests": len(set(required_tests) & observed_tests),
        "required_subjects": len(overrides["readback_subjects"]),
        "observed_subjects": len(set(overrides["readback_subjects"]) & observed_subjects),
        "evidence_count": len(records),
        "stale_evidence": stale_count,
        "missing": deduplicated,
        "complete": not deduplicated,
    }


def _dependency_issues(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
    *,
    evaluation_cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Validate only the upstream claims explicitly consumed by this task."""
    cache = evaluation_cache if evaluation_cache is not None else {}
    tasks = _task_map(plan)
    issues: list[dict[str, Any]] = []
    for edge in task["depends_on"]:
        upstream_id = edge["task_id"]
        upstream_state = state["task_states"][upstream_id]
        if upstream_state["status"] != "done":
            issues.append(
                {
                    "type": "dependency_status",
                    "subject": upstream_id,
                    "next_action": f"complete or revalidate dependency {upstream_id}",
                }
            )
            continue
        if upstream_id not in cache:
            try:
                records = _load_task_evidence(
                    upstream_state,
                    plan=plan,
                    state=state,
                    project_root=project_root,
                    plan_dir=plan_dir,
                )
                cache[upstream_id] = _evaluate_task(
                    plan, state, tasks[upstream_id], records, project_root
                )
            except TaskCtlError as exc:
                cache[upstream_id] = {
                    "claims": {},
                    "missing": [
                        {
                            "type": "evidence_invalid",
                            "subject": upstream_id,
                            "next_action": str(exc),
                        }
                    ],
                    "complete": False,
                }
        upstream_evaluation = cache[upstream_id]
        for claim in edge["claims"]:
            if upstream_evaluation.get("claims", {}).get(claim) != "pass":
                issues.append(
                    {
                        "type": "dependency_claim",
                        "subject": f"{upstream_id}:{claim}",
                        "next_action": f"revalidate consumed claim {claim} on {upstream_id}",
                    }
                )
    return issues


def _blocking_dependency_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return dependency failures that cannot be repaired by the next package.

    A completed dependency whose consumed claim is stale can be revalidated through
    the active package evidence closure.  An unfinished dependency still blocks the
    package from starting.
    """
    return [item for item in issues if item["type"] != "dependency_claim"]


def _evaluate_task_with_dependencies(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
    project_root: Path,
    plan_dir: Path,
    *,
    evaluation_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evaluation = _evaluate_task(plan, state, task, records, project_root)
    dependency_issues = _dependency_issues(
        plan,
        state,
        task,
        project_root,
        plan_dir,
        evaluation_cache=evaluation_cache,
    )
    if dependency_issues:
        existing = {
            (item["type"], item["subject"], item["next_action"])
            for item in evaluation["missing"]
        }
        evaluation["missing"].extend(
            item
            for item in dependency_issues
            if (item["type"], item["subject"], item["next_action"]) not in existing
        )
        evaluation["complete"] = False
    return evaluation


def _compact_markdown_cell(value: str, *, limit: int = 72) -> str:
    text = " ".join(value.split()).replace("|", "\\|")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _render_markdown(
    plan_dir: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
    *,
    include_details: bool = False,
) -> None:
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows: list[str] = []
    details: list[str] = []
    for task in plan["tasks"]:
        task_id = task["id"]
        task_state = state["task_states"][task_id]
        dependency_detail = ", ".join(
            f"{edge['task_id']}[{'+'.join(edge['claims'])}]" for edge in task["depends_on"]
        ) or "—"
        dependencies = _compact_markdown_cell(dependency_detail)
        evidence_count = len(task_state["evidence_refs"])
        evidence = (
            f"[{evidence_count}](evidence/index/) evidence" if evidence_count else "0 evidence"
        )
        if task_state["unresolved"]:
            evidence += f" / {len(task_state['unresolved'])} missing"
        outcome = _compact_markdown_cell(task["outcome"])
        rows.append(f"| `{task_id}` | {outcome} | {dependencies} | {evidence} | `{task_state['status']}` |")
        if include_details:
            details.extend(
                [
                f"### `{task_id}`",
                "",
                f"- 交付结果：{' '.join(task['outcome'].split())}",
                f"- 完成级别：{task.get('completion_level', 'module_ready')}",
                f"- Claim scope：{', '.join(task.get('claim_scope', [])) or '—'}",
                f"- Requirements：{', '.join(task['requirement_ids'])}",
                f"- Acceptance clauses：{', '.join(task.get('acceptance_clause_ids', [])) or '—'}",
                f"- Solution steps：{', '.join(task.get('solution_step_ids', [])) or '—'}",
                f"- Gap items：{', '.join(task.get('gap_ids', [])) or '—'}",
                "- Uncertainty boundary："
                + (
                    "; ".join(
                        f"{key}={value}"
                        for key, value in sorted(
                            task.get("uncertainty_boundary", {}).items()
                        )
                    )
                    or "—"
                ),
                f"- 必需 claims：{', '.join(_required_claims(plan, task))}",
                f"- 必要依赖：{dependency_detail}",
                f"- Mutation scope：{', '.join(task['mutation_scope']) or '—'}",
                f"- Test scope：{', '.join(task['test_scope']) or '—'}",
                (
                    "- Planned test scope："
                    + (", ".join(task.get("planned_test_scope", [])) or "—")
                ),
                "- Freshness scopes："
                + (
                    "; ".join(
                        f"{key}={','.join(entries)}"
                        for key, entries in sorted(task["freshness_scopes"].items())
                    )
                    or "—"
                ),
                    "",
                ]
            )
    active = state["active_package"]
    active_text = "none"
    if active:
        active_text = f"{', '.join(active['task_ids'])} / {active['phase']} / {active['next_action']}"
    totals = {status: 0 for status in TASK_STATUSES}
    for task_state in state["task_states"].values():
        totals[task_state["status"]] += 1
    totals_text = ", ".join(f"{status}={totals[status]}" for status in sorted(totals) if totals[status])
    flow_rows: list[str] = []
    flow_details: list[str] = []
    for flow in plan.get("acceptance_flows", []):
        flow_rows.append(
            f"| `{flow['id']}` | {_compact_markdown_cell(flow['title'])} | "
            f"`{flow['verification_task_id']}` |"
        )
        if include_details:
            flow_details.extend(
                [
                    f"### `{flow['id']}`",
                    "",
                    f"- 验收结果：{flow['title']}",
                    f"- 精确范围：{' '.join(flow['scope'].split())}",
                    f"- Requirements：{', '.join(flow['requirement_ids'])}",
                    f"- 验收任务：{flow['verification_task_id']}",
                    f"- 证据绑定：{flow.get('evidence_mode', '未声明（审计失败）')}",
                    f"- 覆盖范围数：{len(flow.get('scope_coverage', {}))}",
                    f"- 必需 claims：{', '.join(flow['required_claims'])}",
                    f"- 直接测试：{', '.join(flow['direct_test_ids'])}",
                    "",
                ]
            )
    markdown = "\n".join(
        [
            "# TASK TABLE (generated)",
            "",
            "> Generated view only. `plan.json` and `state.json` are authoritative; manual edits are overwritten.",
            "",
            f"- plan: `{plan['plan_id']}`",
            f"- plan_revision: `{state['plan_revision']}`",
            f"- state_revision: `{state['revision']}`",
            f"- generated_at: `{generated_at}`",
            f"- active_package: {active_text}",
            f"- totals: {totals_text}",
            "",
            "| ID | 交付结果 | 必要依赖 | 完成证据 | 状态 |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## 验收流程",
            "",
            *(
                [
                    "| ID | 验收结果 | 验收任务 |",
                    "| --- | --- | --- |",
                    *flow_rows,
                    "",
                ]
                if flow_rows
                else ["—", ""]
            ),
            *(
                [
                    "## 验收流程详情",
                    "",
                    *flow_details,
                    "## 任务详情",
                    "",
                    *details,
                ]
                if include_details
                else []
            ),
        ]
    )
    _write_bytes_atomic(plan_dir / "TASK_TABLE.md", markdown.encode("utf-8"))


def _render_after_state_change(plan_dir: Path, plan: dict[str, Any], state: dict[str, Any]) -> list[str]:
    try:
        _render_markdown(plan_dir, plan, state)
    except OSError as exc:
        return [f"TASK_TABLE.md render failed after state update: {exc}"]
    return []


def _emit(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )


def _make_strict_candidate(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    candidate = copy.deepcopy(plan)
    candidate["enforcement_profile"] = STRICT_ENFORCEMENT_PROFILE
    inferred_fields: list[str] = []
    source_ids = [source["id"] for source in candidate["scope_sources"]]
    requirements_by_source: dict[str, list[str]] = {source_id: [] for source_id in source_ids}
    source_by_id = {source["id"]: source for source in candidate["scope_sources"]}
    task_scopes_by_requirement: dict[str, set[str]] = {}
    for task in candidate["tasks"]:
        task_scope = set(
            task.get("claim_scope")
            or task["claim_overrides"].get("readback_subjects", [])
        )
        for requirement_id in task["requirement_ids"]:
            task_scopes_by_requirement.setdefault(requirement_id, set()).update(task_scope)
    for requirement in candidate["requirements"]:
        matching_sources = [
            source_id
            for source_id in source_ids
            if requirement["source_ref"] == source_id
            or requirement["source_ref"].startswith(source_id + ":")
        ]
        _require(
            bool(matching_sources),
            f"requirement {requirement['id']} has no source for strict migration",
        )
        source_id = max(matching_sources, key=len)
        source = source_by_id[source_id]
        _require(
            bool(source.get("fingerprint")),
            f"source {source_id} needs a fingerprint before strict migration",
        )
        requirements_by_source[source_id].append(requirement["id"])
        requirement["source_fingerprint"] = source["fingerprint"]
        if requirement["status"] == "in_scope":
            if "verification_mode" not in requirement:
                requirement["verification_mode"] = "task_evidence"
                inferred_fields.append(f"requirement:{requirement['id']}:verification_mode")
            if "acceptance_scope" not in requirement:
                inferred_scope = sorted(
                    task_scopes_by_requirement.get(requirement["id"], set())
                )
                requirement["acceptance_scope"] = inferred_scope
                inferred_fields.append(f"requirement:{requirement['id']}:acceptance_scope")
    for source in candidate["scope_sources"]:
        if "inventory_mode" not in source:
            source["inventory_mode"] = "advisory"
            inferred_fields.append(f"source:{source['id']}:inventory_mode")
        if "fingerprint_mode" not in source:
            source["fingerprint_mode"] = "label"
            inferred_fields.append(f"source:{source['id']}:fingerprint_mode")
        source["requirement_ids"] = sorted(requirements_by_source[source["id"]])
    for task in candidate["tasks"]:
        if "completion_level" not in task:
            task["completion_level"] = "module_ready"
            inferred_fields.append(f"task:{task['id']}:completion_level")
        if "claim_scope" not in task:
            task["claim_scope"] = list(
                task["claim_overrides"].get("readback_subjects", [])
            )
            inferred_fields.append(f"task:{task['id']}:claim_scope")
        if "scope_enforced" not in task:
            task["scope_enforced"] = (
                COMPLETION_LEVELS[task["completion_level"]]
                >= COMPLETION_LEVELS["integration_ready"]
            )
            inferred_fields.append(f"task:{task['id']}:scope_enforced")
    _validate_plan(candidate)
    return candidate, inferred_fields


def _command_migrate_strict(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir, require_state=False)
    if state is not None:
        _require(
            state["active_package"] is None,
            "cannot prepare strict migration while a work package is active",
            code="active_package",
        )
    candidate, inferred_fields = _make_strict_candidate(plan)
    _verify_scope_sources(candidate, plan_dir)
    output_path = plan_dir / "strict-plan.candidate.json"
    _write_json_atomic(output_path, candidate)
    return {
        "ok": True,
        "candidate": str(output_path),
        "enforcement_profile": STRICT_ENFORCEMENT_PROFILE,
        "plan_revision": _plan_hash(candidate),
        "inferred_field_count": len(inferred_fields),
    }


def _planning_audit_path(plan_dir: Path, plan: dict[str, Any]) -> Path:
    planning = _expect_object(plan.get("planning_audit"), "plan.planning_audit")
    relative = _validate_relative_path(
        planning["receipt_ref"], "plan.planning_audit.receipt_ref"
    )
    base = Path(relative)
    revision_suffix = _plan_hash(plan).split(":", 1)[-1][:16]
    if base.suffix:
        receipt_name = f"{base.stem}.{revision_suffix}{base.suffix}"
        versioned = base.with_name(receipt_name)
    else:
        versioned = base / f"{revision_suffix}.json"
    path = (plan_dir / versioned).resolve()
    _require(
        _inside(path, plan_dir),
        f"planning audit receipt is outside task directory: {path}",
        code="task_input_outside_root",
    )
    return path


def _planning_audit_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PLANNING_AUDIT_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_revision": _plan_hash(plan),
        "enforcement_profile": _enforcement_profile(plan),
        "controller_identity": _controller_identity(),
        "audit_scope": "machine_structural_traceability",
        "status": "pass",
        "counts": {
            "requirements": len(plan["requirements"]),
            "acceptance_clauses": len(plan["acceptance_clauses"]),
            "design_clauses": len(plan["design_clauses"]),
            "solution_steps": len(plan["solution_steps"]),
            "gap_items": len(plan["gap_items"]),
            "tasks": len(plan["tasks"]),
            "acceptance_flows": len(plan.get("acceptance_flows", [])),
        },
    }


def _verify_planning_audit(plan_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    _require(
        _enforcement_profile(plan) == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "plan activation/completion requires enforcement_profile=strict_v2",
        code="pipeline_profile_required",
    )
    path = _planning_audit_path(plan_dir, plan)
    _require(
        path.is_file(),
        f"planning audit receipt is missing: {path}; run taskctl audit-plan first",
        code="planning_audit_required",
    )
    receipt = _load_json(path)
    _expect_keys(
        receipt,
        required={
            "schema",
            "plan_id",
            "plan_revision",
            "enforcement_profile",
            "controller_identity",
            "audit_scope",
            "status",
            "counts",
        },
        optional=set(),
        path="planning_audit_receipt",
    )
    _require(
        receipt["schema"] == PLANNING_AUDIT_SCHEMA,
        f"planning audit schema must be {PLANNING_AUDIT_SCHEMA}",
        code="planning_audit_stale",
    )
    _require(
        receipt["plan_id"] == plan["plan_id"]
        and receipt["plan_revision"] == _plan_hash(plan)
        and receipt["enforcement_profile"] == PIPELINE_STRICT_ENFORCEMENT_PROFILE
        and receipt["controller_identity"] == _controller_identity()
        and receipt["audit_scope"] == "machine_structural_traceability"
        and receipt["status"] == "pass",
        "planning audit receipt does not match the current plan/controller; run taskctl audit-plan again",
        code="planning_audit_stale",
    )
    _expect_object(receipt["counts"], "planning_audit_receipt.counts")
    return receipt


def _command_audit_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    if args.candidate:
        plan_path = _resolve_task_input(args.candidate, plan_dir, "candidate plan")
        plan = _load_json(plan_path)
        _validate_plan(plan)
        _verify_scope_sources(plan, plan_dir)
    else:
        plan, _state = _load_plan_state(plan_dir, require_state=False)
    _require(
        _enforcement_profile(plan) == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "planning audit requires enforcement_profile=strict_v2",
        code="pipeline_profile_required",
    )
    receipt = _planning_audit_payload(plan)
    path = _planning_audit_path(plan_dir, plan)
    _write_json_atomic(path, receipt)
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "plan_revision": receipt["plan_revision"],
        "enforcement_profile": receipt["enforcement_profile"],
        "audit_scope": receipt["audit_scope"],
        "receipt": path.relative_to(plan_dir).as_posix(),
        "counts": receipt["counts"],
    }


def _command_validate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir, require_state=False)
    if state is None:
        _require(
            _enforcement_profile(plan) in STRICT_ENFORCEMENT_PROFILES,
            "new plan must declare a strict enforcement profile",
            code="strict_profile_required",
        )
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "plan_revision": _plan_hash(plan),
        "enforcement_profile": _enforcement_profile(plan),
        "state": "valid" if state else "not_activated",
        "activation_allowed": _enforcement_profile(plan)
        == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "task_count": len(plan["tasks"]),
        "requirement_count": len(plan["requirements"]),
    }


def _command_activate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir, require_state=False)
    _require(state is None, f"state.json already exists in {plan_dir}", code="already_activated")
    _require(
        _enforcement_profile(plan) == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "new plan must declare enforcement_profile=strict_v2 before activation",
        code="pipeline_profile_required",
    )
    planning_audit = _verify_planning_audit(plan_dir, plan)
    task_states = {task["id"]: _new_task_state() for task in plan["tasks"]}
    state = {
        "schema": STATE_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_revision": _plan_hash(plan),
        "revision": 1,
        "active_package": None,
        "task_states": task_states,
    }
    _recompute_ready(plan, state)
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "enforcement_profile": _enforcement_profile(plan),
        "planning_audit_revision": planning_audit["plan_revision"],
        "revision": 1,
        "warnings": warnings,
    }


def _task_projection(
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
    *,
    evaluation_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_state = state["task_states"][task["id"]]
    try:
        records = _load_task_evidence(
            task_state,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        evaluation = _evaluate_task_with_dependencies(
            plan,
            state,
            task,
            records,
            project_root,
            plan_dir,
            evaluation_cache=evaluation_cache,
        )
    except TaskCtlError as exc:
        evaluation = {
            "complete": False,
            "claims": {},
            "missing": [
                {"type": "evidence_invalid", "subject": task["id"], "next_action": str(exc)}
            ],
            "stale_evidence": 0,
        }
    return {
        "id": task["id"],
        "outcome": task["outcome"],
        "requirement_ids": task["requirement_ids"],
        "depends_on": task["depends_on"],
        "context_refs": task["context_refs"],
        "mutation_scope": task["mutation_scope"],
        "test_scope": task["test_scope"],
        "planned_test_scope": task.get("planned_test_scope", []),
        "freshness_scopes": task["freshness_scopes"],
        "required_claims": _required_claims(plan, task),
        "status": task_state["status"],
        "claims": evaluation.get("claims", {}),
        "missing": evaluation.get("missing", []),
        "unresolved": task_state["unresolved"],
    }


def _command_resume(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    project_root = _project_root(plan_dir, args.project_root)
    tasks = _task_map(plan)
    evaluation_cache: dict[str, dict[str, Any]] = {}
    if state["active_package"]:
        active = state["active_package"]
        projections = [
            _task_projection(
                plan,
                state,
                tasks[task_id],
                project_root,
                plan_dir,
                evaluation_cache=evaluation_cache,
            )
            for task_id in active["task_ids"]
        ]
        return {
            "ok": True,
            "plan_id": plan["plan_id"],
            "plan_revision": state["plan_revision"],
            "state_revision": state["revision"],
            "enforcement_profile": _enforcement_profile(plan),
            "completion_allowed": _enforcement_profile(plan)
            == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
            "active_package": {
                "task_ids": active["task_ids"],
                "phase": active["phase"],
                "next_action": active["next_action"],
                "unresolved": active["unresolved"],
                "controller_status": _active_controller_status(state),
            },
            "tasks": projections,
        }
    candidate_tasks = [
        task
        for task in plan["tasks"]
        if state["task_states"][task["id"]]["status"] in {"ready", "needs_review"}
    ]
    actionable_tasks: list[dict[str, Any]] = []
    dependency_blocked: list[str] = []
    for task in candidate_tasks:
        issues = _dependency_issues(
            plan,
            state,
            task,
            project_root,
            plan_dir,
            evaluation_cache=evaluation_cache,
        )
        if _blocking_dependency_issues(issues):
            dependency_blocked.append(task["id"])
        else:
            actionable_tasks.append(task)
    packages: dict[tuple[str, str, str], list[str]] = {}
    for task in actionable_tasks:
        key = (task["package_key"], task["build_profile"], task["rollback_scope"])
        packages.setdefault(key, []).append(task["id"])
    suggestions = [
        {
            "task_ids": task_ids,
            "package_key": key[0],
            "build_profile": key[1],
            "rollback_scope": key[2],
        }
        for key, task_ids in packages.items()
    ]
    ready_ids = [
        task["id"]
        for task in actionable_tasks
        if state["task_states"][task["id"]]["status"] == "ready"
    ]
    review_ids = [
        task["id"]
        for task in actionable_tasks
        if state["task_states"][task["id"]]["status"] == "needs_review"
    ]
    recommended_package: dict[str, Any] | None = None
    if suggestions:
        recommended_package = copy.deepcopy(suggestions[0])
        recommended_ids = set(recommended_package["task_ids"])
        recommended_package["tasks"] = [
            _task_projection(
                plan,
                state,
                task,
                project_root,
                plan_dir,
                evaluation_cache=evaluation_cache,
            )
            for task in actionable_tasks
            if task["id"] in recommended_ids
        ]
    payload: dict[str, Any] = {
        "ok": True,
        "plan_id": plan["plan_id"],
        "plan_revision": state["plan_revision"],
        "state_revision": state["revision"],
        "enforcement_profile": _enforcement_profile(plan),
        "completion_allowed": _enforcement_profile(plan)
        == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "active_package": None,
        "ready_count": len(ready_ids),
        "ready_ids": ready_ids,
        "needs_review_count": len(review_ids),
        "needs_review_ids": review_ids,
        "dependency_blocked_ids": dependency_blocked,
        "recommended_package": recommended_package,
    }
    if args.all_ready:
        payload["actionable"] = [
            _task_projection(
                plan,
                state,
                task,
                project_root,
                plan_dir,
                evaluation_cache=evaluation_cache,
            )
            for task in actionable_tasks
        ]
        payload["package_suggestions"] = suggestions
    return payload


def _require_revision(state: dict[str, Any], expected_revision: int) -> None:
    _require(
        state["revision"] == expected_revision,
        f"state revision mismatch: expected {expected_revision}, actual {state['revision']}",
        code="revision_conflict",
    )


def _command_begin(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    _require_revision(state, args.expected_revision)
    _require(state["active_package"] is None, "another work package is already active")
    selected = list(dict.fromkeys(args.task))
    _require(bool(selected), "begin requires at least one --task")
    tasks = _task_map(plan)
    project_root = _project_root(plan_dir, args.project_root)
    evaluation_cache: dict[str, dict[str, Any]] = {}
    for task_id in selected:
        _require(task_id in tasks, f"unknown task: {task_id}")
        _require(
            state["task_states"][task_id]["status"] in {"ready", "needs_review"},
            f"task {task_id} is not ready or awaiting review",
        )
        dependency_issues = _dependency_issues(
            plan,
            state,
            tasks[task_id],
            project_root,
            plan_dir,
            evaluation_cache=evaluation_cache,
        )
        blocking_dependency_issues = _blocking_dependency_issues(dependency_issues)
        _require(
            not blocking_dependency_issues,
            f"task {task_id} has invalid dependency evidence: "
            + "; ".join(item["subject"] for item in blocking_dependency_issues),
            code="dependency_invalid",
        )
    compatibility = {
        (tasks[task_id]["package_key"], tasks[task_id]["build_profile"], tasks[task_id]["rollback_scope"])
        for task_id in selected
    }
    _require(len(compatibility) == 1, "selected tasks cross package/build/rollback boundaries")
    def is_preserved_revalidation(task_id: str) -> bool:
        task_state = state["task_states"][task_id]
        if task_state["status"] != "ready" or not any(
            item.get("type") == "plan_changed"
            for item in task_state.get("unresolved", [])
        ):
            return False
        records = _load_task_evidence(
            task_state,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        has_expected_red = any(
            task_id in record["task_ids"]
            and record["phase"] == "expected_red"
            and record["result"] == "expected_fail"
            for record in records
        )
        has_verification = any(
            task_id in record["task_ids"]
            and record["phase"] == "verification"
            and record["result"] == "pass"
            for record in records
        )
        return has_expected_red and has_verification

    preserved_revalidation_ids = {
        task_id for task_id in selected if is_preserved_revalidation(task_id)
    }

    def begin_baseline(task_id: str) -> dict[str, Any]:
        task = tasks[task_id]
        current = _task_identities(plan, task, project_root)
        task_state = state["task_states"][task_id]
        if (
            task_state["status"] == "needs_review"
            or task_id in preserved_revalidation_ids
            or task["tests_first"]["mode"] != "required"
        ):
            return current

        records = _load_task_evidence(
            task_state,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        required_tests = set(
            task["claim_overrides"]["automation_test_ids"]
        )
        producer_id = task["tests_first"]["expected_red_producer"]
        red_freshness_keys = {
            key
            for claim in _required_claims(plan, task)
            for key in _claim_rule(plan, task, claim)["freshness_keys"]
        }
        for record in reversed(records):
            if (
                task_id not in record["task_ids"]
                or record["phase"] != "expected_red"
                or record["result"] != "expected_fail"
                or record["producer"]["id"] != producer_id
                or not required_tests <= set(record["test_ids"])
            ):
                continue
            if any(
                key != "production_scope"
                and (
                    key not in current
                    or not _freshness_value_matches(
                        plan, record, key, current[key]
                    )
                )
                for key in red_freshness_keys
            ):
                continue
            red_production = record["freshness_identity"].get(
                "production_scope"
            )
            if red_production:
                # A released, unfinished tests-first task keeps the production
                # identity observed by its still-current sealed red. This
                # permits controller upgrades or checkpoints without treating
                # the already implemented green state as the original begin
                # baseline. Contract, test, and runner identities still have
                # to match the current plan before this recovery is allowed.
                current["production_scope"] = red_production
                return current
        return current

    baselines = {task_id: begin_baseline(task_id) for task_id in selected}
    revalidation_task_ids = [
        task_id
        for task_id in selected
        if state["task_states"][task_id]["status"] == "needs_review"
        or task_id in preserved_revalidation_ids
    ]
    for task_id in selected:
        state["task_states"][task_id]["status"] = "active"
        state["task_states"][task_id]["baseline_identity"] = baselines[task_id]
        state["task_states"][task_id]["unresolved"] = []
    state["active_package"] = {
        "task_ids": selected,
        "phase": "tests",
        "baseline_identity": baselines,
        "controller_identity": _controller_identity(),
        "changed_paths": [],
        "evidence_refs": [],
        "unresolved": [],
        "next_action": "qualify or update tests before production implementation",
        "revalidation_task_ids": revalidation_task_ids,
    }
    state["revision"] += 1
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "state_revision": state["revision"],
        "active_package": selected,
        "baseline_identity": baselines,
        "warnings": warnings,
    }


def _build_evidence_context(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    phase: str,
    project_root: Path,
    plan_dir: Path,
) -> dict[str, Any]:
    freshness = _current_freshness(
        plan, task, project_root, require_planned_tests=True
    )
    if phase == "expected_red":
        _require(
            task["tests_first"]["mode"] == "required",
            f"task {task['id']} does not require expected-red evidence",
        )
        baseline = state["task_states"][task["id"]]["baseline_identity"]
        _require(
            freshness["production_scope"] == baseline.get("production_scope"),
            "production scope changed after begin; expected-red evidence can no longer be created",
            code="tests_first_order",
        )
        producer_ids = [task["tests_first"]["expected_red_producer"]]
    else:
        records = _load_task_evidence(
            state["task_states"][task["id"]],
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        _require_sealed_red_identity(
            plan, state, task, records, project_root
        )
        producer_ids = sorted(
            {
                producer_id
                for claim in _required_claims(plan, task)
                for producer_id in _claim_rule(plan, task, claim)["producers"]
            }
        )
    claim_contracts = {
        claim: copy.deepcopy(_claim_rule(plan, task, claim))
        for claim in _required_claims(plan, task)
    }
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "plan_revision": state["plan_revision"],
        "state_revision": state["revision"],
        "task_id": task["id"],
        "phase": phase,
        "freshness_identity": freshness,
        "producer_ids": producer_ids,
        "required_claims": _required_claims(plan, task),
        "claim_contracts": claim_contracts,
        "test_ids": task["claim_overrides"]["automation_test_ids"],
        "readback_subjects": task["claim_overrides"]["readback_subjects"],
    }


def _write_evidence_context_files(
    contexts: list[dict[str, Any]], output_dir: Path
) -> list[str]:
    paths: list[str] = []
    for context in contexts:
        identity = _json_identity(context).removeprefix("sha256:")[:12]
        filename = _evidence_filename(
            f"{context['phase']}:{context['task_id']}:r{context['state_revision']}:{identity}:context"
        )
        output_path = output_dir / filename
        _write_bytes_immutable(output_path, _pretty_bytes(context))
        paths.append(str(output_path))
    return paths


def _active_dependency_issues(
    plan: dict[str, Any],
    state: dict[str, Any],
    project_root: Path,
    plan_dir: Path,
) -> list[dict[str, Any]]:
    active = state["active_package"]
    _require(active is not None, "impact requires an active package")
    tasks = _task_map(plan)
    evaluation_cache: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for task_id in active["task_ids"]:
        for item in _dependency_issues(
            plan,
            state,
            tasks[task_id],
            project_root,
            plan_dir,
            evaluation_cache=evaluation_cache,
        ):
            key = (item["type"], item["subject"], item["next_action"])
            if key not in seen:
                seen.add(key)
                issues.append(item)
    return issues


def _revalidation_task_ids(issues: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            item["subject"].split(":", 1)[0]
            for item in issues
            if item["type"] == "dependency_claim"
        }
    )


def _command_evidence_context(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    active = state["active_package"]
    _require(active is not None, "evidence context requires an active package")
    _require_active_controller(state)
    tasks = _task_map(plan)
    project_root = _project_root(plan_dir, args.project_root)
    if not args.package:
        _require(
            args.task in _active_evidence_task_ids(plan, state),
            f"task {args.task} is outside the active package dependency closure",
        )
        context = _build_evidence_context(
            plan=plan,
            state=state,
            task=tasks[args.task],
            phase=args.phase,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        if not args.output_dir:
            return context
        output_dir = _resolve_context_output_dir(
            args.output_dir, project_root, plan_dir
        )
        context_files = _write_evidence_context_files([context], output_dir)
        return {
            "ok": True,
            "plan_id": plan["plan_id"],
            "plan_revision": state["plan_revision"],
            "state_revision": state["revision"],
            "phase": args.phase,
            "task_ids": [args.task],
            "context_files": context_files,
        }

    dependency_issues = _active_dependency_issues(
        plan, state, project_root, plan_dir
    )
    revalidation_ids = _revalidation_task_ids(dependency_issues)
    if args.phase == "expected_red":
        task_ids = [
            task_id
            for task_id in active["task_ids"]
            if tasks[task_id]["tests_first"]["mode"] == "required"
        ]
        _require(bool(task_ids), "active package has no required expected-red tasks")
        revalidation_ids = []
    else:
        task_ids = sorted(set(active["task_ids"]) | set(revalidation_ids))
    contexts = [
        _build_evidence_context(
            plan=plan,
            state=state,
            task=tasks[task_id],
            phase=args.phase,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        for task_id in task_ids
    ]
    package_test_ids = sorted(
        {
            test_id
            for context in contexts
            for test_id in context["test_ids"]
        }
    )
    for context in contexts:
        context["package_test_ids"] = package_test_ids
    payload = {
        "ok": True,
        "plan_id": plan["plan_id"],
        "plan_revision": state["plan_revision"],
        "state_revision": state["revision"],
        "phase": args.phase,
        "package": True,
        "task_ids": task_ids,
        "revalidation_task_ids": revalidation_ids,
        "contexts": contexts,
    }
    if args.output_dir:
        output_dir = _resolve_context_output_dir(
            args.output_dir, project_root, plan_dir
        )
        context_files = _write_evidence_context_files(contexts, output_dir)
        payload.pop("contexts")
        payload["context_files"] = context_files
    return payload


def _command_impact(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    active = state["active_package"]
    _require(active is not None, "impact requires an active package")
    _require_active_controller(state)
    project_root = _project_root(plan_dir, args.project_root)
    tasks = _task_map(plan)
    dependency_issues = _active_dependency_issues(
        plan, state, project_root, plan_dir
    )
    active_changes: dict[str, list[str]] = {}
    red_status: dict[str, str] = {}
    for task_id in active["task_ids"]:
        task = tasks[task_id]
        current = _current_freshness(
            plan, task, project_root, require_planned_tests=True
        )
        baseline = state["task_states"][task_id]["baseline_identity"]
        active_changes[task_id] = sorted(
            key
            for key, value in current.items()
            if baseline.get(key) != value
        )
        if task["tests_first"]["mode"] != "required":
            red_status[task_id] = "not_required"
            continue
        records = _load_task_evidence(
            state["task_states"][task_id],
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        if _expected_red_records(plan, state, task, records, project_root):
            red_status[task_id] = "sealed"
        elif any(record["phase"] == "expected_red" for record in records):
            red_status[task_id] = "identity_changed"
        else:
            red_status[task_id] = "unsealed"
    revalidation_task_ids = _revalidation_task_ids(dependency_issues)
    regression_task_ids = list(
        dict.fromkeys([*active["task_ids"], *revalidation_task_ids])
    )
    test_ids_by_task = {
        task_id: list(tasks[task_id]["claim_overrides"]["automation_test_ids"])
        for task_id in regression_task_ids
    }
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "state_revision": state["revision"],
        "active_task_ids": active["task_ids"],
        "changed_freshness_keys": active_changes,
        "red_status": red_status,
        "revalidation_task_ids": revalidation_task_ids,
        "test_ids_by_task": test_ids_by_task,
        "selected_test_ids": sorted(
            {
                test_id
                for test_ids in test_ids_by_task.values()
                for test_id in test_ids
            }
        ),
        "dependency_issues": dependency_issues,
    }


def _command_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    # Release is the recovery edge that makes an active package amendable after
    # an upstream source changed.  Requiring the obsolete source fingerprint on
    # that one edge creates a deadlock: amend rejects an active package while
    # release rejects the drift that requires amendment.  Plan/state structure,
    # revision and active-package ownership remain enforced below.
    plan, state = _load_plan_state(plan_dir, verify_sources=not args.release)
    assert state is not None
    _require_revision(state, args.expected_revision)
    _require(state["active_package"] is not None, "no active package to checkpoint")
    active = state["active_package"]
    if args.phase:
        _require(args.phase in PHASES, f"invalid phase: {args.phase}")
        active["phase"] = args.phase
    active["next_action"] = args.next_action
    if args.changed_path:
        active["changed_paths"] = list(dict.fromkeys(args.changed_path))
    if args.unresolved:
        unresolved_data = _load_json(
            _resolve_task_input(args.unresolved, plan_dir, "checkpoint input")
        )
        _expect_keys(unresolved_data, required={"items"}, optional=set(), path="checkpoint input")
        active["unresolved"] = _validate_unresolved(unresolved_data["items"], "checkpoint input.items")
        for task_id in active["task_ids"]:
            state["task_states"][task_id]["unresolved"] = copy.deepcopy(active["unresolved"])
    if args.release:
        for task_id in active["task_ids"]:
            task_state = state["task_states"][task_id]
            has_prior_verification = any(
                "-verification-" in reference
                for reference in task_state["evidence_refs"]
            )
            has_expected_red = any(
                "-expected_red-" in reference
                for reference in task_state["evidence_refs"]
            )
            task_state["status"] = (
                "needs_review" if has_prior_verification else "todo"
            )
            if has_prior_verification or not has_expected_red:
                task_state["baseline_identity"] = {}
        state["active_package"] = None
        _recompute_ready(plan, state)
    state["revision"] += 1
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {"ok": True, "state_revision": state["revision"], "warnings": warnings}


def _command_invalidate_red(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    _require_revision(state, args.expected_revision)
    active = state["active_package"]
    _require(active is not None, "no active package to reopen for test correction")
    _require_active_controller(state)
    _require(
        active["phase"] in {"implementation", "verification"},
        "expected-red can be invalidated only after it has been sealed",
        code="red_not_sealed",
    )
    project_root = _project_root(plan_dir, args.project_root)
    tasks = _task_map(plan)
    invalidated: list[str] = []
    for task_id in active["task_ids"]:
        task = tasks[task_id]
        if task["tests_first"]["mode"] != "required":
            continue
        records = _load_task_evidence(
            state["task_states"][task_id],
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        _require_sealed_red_identity(plan, state, task, records, project_root)
        invalidated.append(task_id)
    _require(bool(invalidated), "active package has no sealed expected-red tasks")

    active["phase"] = "tests"
    active["next_action"] = (
        "review the full selected test harness, restore production to the begin "
        "baseline, then create and seal new expected-red evidence"
    )
    if args.changed_path:
        active["changed_paths"] = list(dict.fromkeys(args.changed_path))
    active["unresolved"] = [
        {
            "type": "test_identity_invalidated",
            "subject": task_id,
            "next_action": args.reason,
        }
        for task_id in invalidated
    ]
    for task_id in invalidated:
        state["task_states"][task_id]["unresolved"] = [
            copy.deepcopy(
                next(
                    item
                    for item in active["unresolved"]
                    if item["subject"] == task_id
                )
            )
        ]
    state["revision"] += 1
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {
        "ok": True,
        "state_revision": state["revision"],
        "invalidated_task_ids": invalidated,
        "next_action": active["next_action"],
        "warnings": warnings,
    }


def _command_seal_red(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    _require_revision(state, args.expected_revision)
    active = state["active_package"]
    _require(active is not None, "no active package to seal")
    _require_active_controller(state)
    _require(bool(args.evidence), "seal-red requires at least one --evidence")
    project_root = _project_root(plan_dir, args.project_root)
    prepared = _prepare_evidence_reports(
        args.evidence,
        plan=plan,
        state=state,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    pending_indexes, pending_snapshots, new_refs_by_task, envelopes = prepared
    active_ids = set(active["task_ids"])
    for envelope in envelopes:
        _require(
            envelope["phase"] == "expected_red"
            and envelope["result"] == "expected_fail",
            "seal-red accepts only expected_red/expected_fail evidence",
            code="seal_red_evidence_invalid",
        )
        _require(
            set(envelope["task_ids"]) <= active_ids,
            "seal-red evidence must belong to an active package task",
            code="seal_red_task_invalid",
        )

    tasks = _task_map(plan)
    sealed_task_ids: list[str] = []
    for task_id in active["task_ids"]:
        task = tasks[task_id]
        if task["tests_first"]["mode"] != "required":
            continue
        records = _load_task_evidence(
            state["task_states"][task_id],
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        ) + [
            envelope
            for envelope in envelopes
            if task_id in envelope["task_ids"]
        ]
        _require_sealed_red_identity(
            plan, state, task, records, project_root
        )
        sealed_task_ids.append(task_id)
    _require(bool(sealed_task_ids), "active package has no required expected-red tasks")

    _commit_evidence_reports(
        plan_dir=plan_dir,
        state=state,
        pending_indexes=pending_indexes,
        pending_snapshots=pending_snapshots,
        new_refs_by_task=new_refs_by_task,
    )
    active["phase"] = "implementation"
    active["evidence_refs"] = list(
        dict.fromkeys(
            reference
            for task_id in active["task_ids"]
            for reference in state["task_states"][task_id]["evidence_refs"]
        )
    )
    active["unresolved"] = []
    for task_id in sealed_task_ids:
        state["task_states"][task_id]["unresolved"] = []
    active["next_action"] = (
        "implement the production scope without changing the sealed test identity"
    )
    state["revision"] += 1
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {
        "ok": True,
        "state_revision": state["revision"],
        "sealed_task_ids": sealed_task_ids,
        "evidence_ids": [envelope["evidence_id"] for envelope in envelopes],
        "next_action": active["next_action"],
        "warnings": warnings,
    }


def _command_close(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    _require_revision(state, args.expected_revision)
    active = state["active_package"]
    _require(active is not None, "no active package to close")
    _require_active_controller(state)
    project_root = _project_root(plan_dir, args.project_root)
    prepared = _prepare_evidence_reports(
        args.evidence,
        plan=plan,
        state=state,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    pending_indexes, pending_snapshots, new_refs_by_task, _ = prepared
    _commit_evidence_reports(
        plan_dir=plan_dir,
        state=state,
        pending_indexes=pending_indexes,
        pending_snapshots=pending_snapshots,
        new_refs_by_task=new_refs_by_task,
    )

    tasks = _task_map(plan)
    cards: list[dict[str, Any]] = []
    completed: list[str] = []
    remaining: list[str] = []
    combined_unresolved: list[dict[str, Any]] = []
    evaluation_cache: dict[str, dict[str, Any]] = {}
    for task_id in active["task_ids"]:
        task_state = state["task_states"][task_id]
        records = _load_task_evidence(
            task_state,
            plan=plan,
            state=state,
            project_root=project_root,
            plan_dir=plan_dir,
        )
        evaluation = _evaluate_task_with_dependencies(
            plan,
            state,
            tasks[task_id],
            records,
            project_root,
            plan_dir,
            evaluation_cache=evaluation_cache,
        )
        task_state["unresolved"] = copy.deepcopy(evaluation["missing"])
        if evaluation["complete"]:
            task_state["status"] = "done"
            completed.append(task_id)
        else:
            task_state["status"] = "active"
            remaining.append(task_id)
            combined_unresolved.extend(evaluation["missing"])
        cards.append(evaluation)
    if remaining:
        active["task_ids"] = remaining
        active["revalidation_task_ids"] = [
            task_id
            for task_id in active.get("revalidation_task_ids", [])
            if task_id in remaining
        ]
        active["baseline_identity"] = {
            task_id: active["baseline_identity"][task_id] for task_id in remaining
        }
        active["evidence_refs"] = list(
            dict.fromkeys(
                reference
                for task_id in remaining
                for reference in state["task_states"][task_id]["evidence_refs"]
            )
        )
        active["unresolved"] = combined_unresolved
        active["phase"] = "verification"
        active["next_action"] = "satisfy the listed missing or stale evidence"
    else:
        state["active_package"] = None
    _recompute_ready(plan, state)
    state["revision"] += 1
    _validate_state(state, plan)
    _write_state(plan_dir, state)
    warnings = _render_after_state_change(plan_dir, plan, state)
    return {
        "ok": True,
        "state_revision": state["revision"],
        "completed": completed,
        "remaining": remaining,
        "completion_cards": cards,
        "warnings": warnings,
    }


def _audit_task_ids(plan: dict[str, Any], state: dict[str, Any], all_tasks: bool) -> list[str]:
    if all_tasks:
        return [task["id"] for task in plan["tasks"]]
    if state["active_package"]:
        return list(state["active_package"]["task_ids"])
    ready = [task for task in plan["tasks"] if state["task_states"][task["id"]]["status"] == "ready"]
    dependencies: set[str] = set()
    for task in ready:
        dependencies.update(edge["task_id"] for edge in task["depends_on"])
    return sorted(dependencies)


def _dependent_closure(plan: dict[str, Any], seeds: set[str]) -> set[str]:
    reverse: dict[str, set[str]] = {task["id"]: set() for task in plan["tasks"]}
    for task in plan["tasks"]:
        for edge in task["depends_on"]:
            reverse.setdefault(edge["task_id"], set()).add(task["id"])
    result = set(seeds)
    queue = list(seeds)
    while queue:
        current = queue.pop()
        for dependent in reverse.get(current, set()):
            if dependent not in result:
                result.add(dependent)
                queue.append(dependent)
    return result


def _record_satisfies_flow_receipt(
    plan: dict[str, Any],
    task: dict[str, Any],
    record: dict[str, Any],
    project_root: Path,
    *,
    required_claims: set[str],
    required_tests: set[str],
    required_subjects: set[str],
) -> bool:
    if (
        task["id"] not in record["task_ids"]
        or record["phase"] != "verification"
        or record["result"] != "pass"
        or not required_claims <= set(record["claims"])
        or not required_tests <= set(record["test_ids"])
        or not required_subjects <= set(record["subjects"])
    ):
        return False
    current = _current_freshness(plan, task, project_root)
    producer_id = record["producer"]["id"]
    for claim in required_claims:
        rule = _claim_rule(plan, task, claim)
        if producer_id not in rule["producers"] or record["source_class"] not in rule["source_classes"]:
            return False
        for key in rule["freshness_keys"]:
            if key not in record["freshness_identity"]:
                return False
            if key in current and not _freshness_value_matches(
                plan, record, key, current[key]
            ):
                return False
    return True


def _evaluate_acceptance_flow(
    plan: dict[str, Any],
    flow: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    if "evidence_mode" not in flow or "scope_coverage" not in flow:
        missing.append(
            {
                "type": "flow_contract_incomplete",
                "subject": flow["id"],
                "next_action": "declare evidence_mode and exact scope_coverage before claiming the flow",
            }
        )
    else:
        required_claims = set(flow["required_claims"])
        scope_claims = {
            scope_id: set(claims)
            for scope_id, claims in flow.get("scope_claims", {}).items()
        }
        if flow["evidence_mode"] == "single_receipt":
            subjects = set(flow["scope_coverage"])
            tests = set(flow["direct_test_ids"])
            receipt_claims = set().union(
                *(scope_claims.get(scope_id, required_claims) for scope_id in subjects)
            )
            if not any(
                _record_satisfies_flow_receipt(
                    plan,
                    task,
                    record,
                    project_root,
                    required_claims=receipt_claims,
                    required_tests=tests,
                    required_subjects=subjects,
                )
                for record in records
            ):
                missing.append(
                    {
                        "type": "missing_vertical_receipt",
                        "subject": flow["id"],
                        "next_action": "produce one fresh receipt containing every required claim, direct test, and readback scope",
                    }
                )
        else:
            for scope_id, mapped_tests in flow["scope_coverage"].items():
                receipt_claims = scope_claims.get(scope_id, required_claims)
                if any(
                    _record_satisfies_flow_receipt(
                        plan,
                        task,
                        record,
                        project_root,
                        required_claims=receipt_claims,
                        required_tests=set(mapped_tests),
                        required_subjects={scope_id},
                    )
                    for record in records
                ):
                    continue
                missing.append(
                    {
                        "type": "missing_scope_receipt",
                        "subject": scope_id,
                        "next_action": "produce one fresh vertical receipt for this exact scope and its mapped direct test(s)",
                    }
                )
    return {
        "flow_id": flow["id"],
        "verification_task_id": flow["verification_task_id"],
        "complete": not missing,
        "scope": flow["scope"],
        "evidence_mode": flow.get("evidence_mode", "unbound"),
        "missing": missing,
    }


def _write_completion_receipt(
    plan_dir: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
    audited_task_ids: list[str],
    audited_flow_ids: list[str],
    records_by_task_id: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    receipt_core = {
        "schema": COMPLETION_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_revision": state["plan_revision"],
        "state_revision": state["revision"],
        "enforcement_profile": _enforcement_profile(plan),
        "audited_task_ids": sorted(audited_task_ids),
        "audited_flow_ids": sorted(audited_flow_ids),
        "state_identity": _json_identity(state),
        "evidence_identity": _json_identity(records_by_task_id),
    }
    receipt_id = _json_identity(receipt_core)
    receipt = {**receipt_core, "receipt_id": receipt_id}
    receipt_path = (
        plan_dir
        / "evidence"
        / "completion"
        / f"{receipt_id.removeprefix('sha256:')}.json"
    )
    _write_json_atomic(receipt_path, receipt)
    return {
        "id": receipt_id,
        "path": receipt_path.relative_to(plan_dir).as_posix(),
    }


def _command_audit(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    plan, state = _load_plan_state(plan_dir)
    assert state is not None
    enforcement_profile = _enforcement_profile(plan)
    plan_failures: list[dict[str, str]] = []
    if args.all and enforcement_profile != PIPELINE_STRICT_ENFORCEMENT_PROFILE:
        plan_failures.append(
            {
                "type": "pipeline_profile_required",
                "subject": plan["plan_id"],
                "next_action": "amend the active plan to enforcement_profile=strict_v2 with a fresh planning audit",
            }
        )
    elif args.all:
        try:
            _verify_planning_audit(plan_dir, plan)
        except TaskCtlError as exc:
            plan_failures.append(
                {
                    "type": exc.code,
                    "subject": plan["plan_id"],
                    "next_action": str(exc),
                }
            )
    project_root = _project_root(plan_dir, args.project_root)
    tasks = _task_map(plan)
    audited = _audit_task_ids(plan, state, args.all)
    failures: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    records_by_task_id: dict[str, list[dict[str, Any]]] = {}
    evaluation_cache: dict[str, dict[str, Any]] = {}
    for task_id in audited:
        task_state = state["task_states"][task_id]
        try:
            records = _load_task_evidence(
                task_state,
                plan=plan,
                state=state,
                project_root=project_root,
                plan_dir=plan_dir,
            )
            records_by_task_id[task_id] = records
            card = _evaluate_task_with_dependencies(
                plan,
                state,
                tasks[task_id],
                records,
                project_root,
                plan_dir,
                evaluation_cache=evaluation_cache,
            )
        except TaskCtlError as exc:
            records_by_task_id[task_id] = []
            card = {
                "task_id": task_id,
                "complete": False,
                "claims": {},
                "missing": [
                    {"type": "evidence_invalid", "subject": task_id, "next_action": str(exc)}
                ],
                "stale_evidence": 0,
            }
        if args.all and task_state["status"] != "done":
            card["missing"].append(
                {
                    "type": "task_not_done",
                    "subject": task_id,
                    "next_action": f"finish task currently marked {task_state['status']}",
                }
            )
            card["complete"] = False
        cards.append(card)
        if not card["complete"]:
            failures.append(card)
    card_by_task_id = {card["task_id"]: card for card in cards}
    flow_cards: list[dict[str, Any]] = []
    if args.all:
        for flow in plan.get("acceptance_flows", []):
            verification_task_id = flow["verification_task_id"]
            task_card = card_by_task_id[verification_task_id]
            flow_card = _evaluate_acceptance_flow(
                plan,
                flow,
                tasks[verification_task_id],
                records_by_task_id.get(verification_task_id, []),
                project_root,
            )
            if not task_card["complete"]:
                flow_card["complete"] = False
                flow_card["missing"].append(
                    {
                        "type": "verification_task_incomplete",
                        "subject": verification_task_id,
                        "next_action": "complete the verification task and its vertical receipt contract",
                    }
                )
            flow_cards.append(flow_card)
    failed_flow_ids = [card["flow_id"] for card in flow_cards if not card["complete"]]
    changed: list[str] = []
    if args.apply and (failures or failed_flow_ids):
        _require_revision(state, args.expected_revision)
        seeds = {card["task_id"] for card in failures}
        seeds.update(
            card["verification_task_id"] for card in flow_cards if not card["complete"]
        )
        affected = _dependent_closure(plan, seeds)
        for task_id in affected:
            task_state = state["task_states"][task_id]
            if task_state["status"] == "done":
                task_state["status"] = "needs_review"
                changed.append(task_id)
            elif task_state["status"] in {"ready", "todo"}:
                task_state["status"] = "todo"
        if state["active_package"] and set(state["active_package"]["task_ids"]) & affected:
            state["active_package"]["unresolved"].append(
                {
                    "type": "evidence_stale",
                    "subject": ",".join(sorted(affected)),
                    "next_action": "review invalidated upstream evidence before continuing",
                }
            )
        _recompute_ready(plan, state)
        state["revision"] += 1
        _validate_state(state, plan)
        _write_state(plan_dir, state)
        _render_after_state_change(plan_dir, plan, state)
    audit_ok = not failures and not failed_flow_ids and not plan_failures
    completion_receipt = None
    if args.all and audit_ok:
        completion_receipt = _write_completion_receipt(
            plan_dir,
            plan,
            state,
            audited,
            [flow["id"] for flow in plan.get("acceptance_flows", [])],
            records_by_task_id,
        )
    return {
        "ok": audit_ok,
        "enforcement_profile": enforcement_profile,
        "audited": len(audited),
        "audited_flows": len(flow_cards),
        "failed": len(failures),
        "failed_task_ids": [card["task_id"] for card in failures],
        "failed_flow_ids": failed_flow_ids,
        "plan_failures": plan_failures,
        "completion_receipt": completion_receipt,
        "changed_to_needs_review": sorted(changed),
        "state_revision": state["revision"],
        "cards": cards if args.details else [],
        "flow_cards": flow_cards if args.details else [],
    }


def _without_source_fingerprints(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_source_fingerprints(child)
            for key, child in value.items()
            if key != "source_fingerprint"
        }
    if isinstance(value, list):
        return [_without_source_fingerprints(child) for child in value]
    return value


def _semantic_amendment_changed(old_value: Any, new_value: Any) -> bool:
    return _without_source_fingerprints(old_value) != _without_source_fingerprints(
        new_value
    )


def _amendment_impact(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_tasks = _task_map(old)
    new_tasks = _task_map(new)
    old_requirements = _requirement_map(old)
    new_requirements = _requirement_map(new)
    old_sources = {source["id"]: source for source in old["scope_sources"]}
    new_sources = {source["id"]: source for source in new["scope_sources"]}
    changed_sources = {
        key
        for key in set(old_sources) | set(new_sources)
        if old_sources.get(key) != new_sources.get(key)
    }
    changed_requirements = {
        key
        for key in set(old_requirements) | set(new_requirements)
        if _semantic_amendment_changed(
            old_requirements.get(key), new_requirements.get(key)
        )
    }
    changed_producers = {
        key
        for key in set(old["producers"]) | set(new["producers"])
        if _semantic_amendment_changed(
            old["producers"].get(key), new["producers"].get(key)
        )
    }
    changed_profiles = {
        key
        for key in set(old["evidence_profiles"]) | set(new["evidence_profiles"])
        if _semantic_amendment_changed(
            old["evidence_profiles"].get(key), new["evidence_profiles"].get(key)
        )
    }
    changed_tests = {
        key
        for key in set(old["test_qualifications"]) | set(new["test_qualifications"])
        if _semantic_amendment_changed(
            old["test_qualifications"].get(key),
            new["test_qualifications"].get(key),
        )
    }
    old_flow_map = {flow["id"]: flow for flow in old.get("acceptance_flows", [])}
    new_flow_map = {flow["id"]: flow for flow in new.get("acceptance_flows", [])}
    changed_flows = {
        key
        for key in set(old_flow_map) | set(new_flow_map)
        if _semantic_amendment_changed(old_flow_map.get(key), new_flow_map.get(key))
    }
    changed_tasks = {
        key
        for key in set(old_tasks) | set(new_tasks)
        if _semantic_amendment_changed(old_tasks.get(key), new_tasks.get(key))
    }
    direct: set[str] = set(changed_tasks)
    for task_id, task in new_tasks.items():
        if set(task["requirement_ids"]) & changed_requirements:
            direct.add(task_id)
        if task["claim_profile"] in changed_profiles:
            direct.add(task_id)
        if set(task["claim_overrides"]["automation_test_ids"]) & changed_tests:
            direct.add(task_id)
        for claim in _required_claims(new, task):
            if set(_claim_rule(new, task, claim)["producers"]) & changed_producers:
                direct.add(task_id)
    for flow_id in changed_flows:
        old_flow = old_flow_map.get(flow_id)
        new_flow = new_flow_map.get(flow_id)
        if old_flow and old_flow["verification_task_id"] in old_tasks:
            direct.add(old_flow["verification_task_id"])
        if new_flow and new_flow["verification_task_id"] in new_tasks:
            direct.add(new_flow["verification_task_id"])
    affected = _dependent_closure(new, direct & set(new_tasks)) | (direct - set(new_tasks))
    lowerings: list[str] = []
    if (
        _enforcement_profile(old) == PIPELINE_STRICT_ENFORCEMENT_PROFILE
        and _enforcement_profile(new) != PIPELINE_STRICT_ENFORCEMENT_PROFILE
    ):
        lowerings.append("weakened enforcement_profile from strict_v2")
    removed_decision_refs = set(old.get("decision_refs", [])) - set(new.get("decision_refs", []))
    if removed_decision_refs:
        lowerings.append(
            "removed decision refs " + ",".join(sorted(removed_decision_refs))
        )
    for source_id, old_source in old_sources.items():
        new_source = new_sources.get(source_id)
        if new_source is None:
            lowerings.append(f"removed scope source {source_id}")
            continue
        if (
            old_source.get("inventory_mode", "advisory") == "exact"
            and new_source.get("inventory_mode", "advisory") != "exact"
        ):
            lowerings.append(f"scope source {source_id} weakened exact inventory")
        removed_inventory = set(old_source.get("requirement_ids", [])) - set(
            new_source.get("requirement_ids", [])
        )
        if removed_inventory:
            lowerings.append(
                f"scope source {source_id} removed requirement inventory "
                + ",".join(sorted(removed_inventory))
            )
        if (
            old_source.get("fingerprint_mode", "label") == "file_sha256"
            and new_source.get("fingerprint_mode", "label") != "file_sha256"
        ):
            lowerings.append(f"scope source {source_id} weakened file fingerprint verification")
        if old_source.get("source_audit_ref") and not new_source.get("source_audit_ref"):
            lowerings.append(f"scope source {source_id} removed source audit reference")
        if old_source.get("inventory_prefix") and (
            old_source.get("inventory_prefix") != new_source.get("inventory_prefix")
        ):
            lowerings.append(f"scope source {source_id} changed inventory prefix")
        for field in ("ref", "root"):
            if field in old_source and old_source.get(field) != new_source.get(field):
                lowerings.append(f"scope source {source_id} changed {field}")

    def record_rule_lowering(prefix: str, old_rule: dict[str, Any], new_rule: dict[str, Any]) -> None:
        removed_freshness = set(old_rule["freshness_keys"]) - set(new_rule["freshness_keys"])
        if removed_freshness:
            lowerings.append(f"{prefix} removed freshness {','.join(sorted(removed_freshness))}")
        if new_rule["min_evidence"] < old_rule["min_evidence"]:
            lowerings.append(
                f"{prefix} reduced min_evidence {old_rule['min_evidence']}->{new_rule['min_evidence']}"
            )
        added_sources = set(new_rule["source_classes"]) - set(old_rule["source_classes"])
        if added_sources:
            lowerings.append(f"{prefix} broadened source_classes {','.join(sorted(added_sources))}")
        added_producers = set(new_rule["producers"]) - set(old_rule["producers"])
        if added_producers:
            lowerings.append(f"{prefix} broadened producers {','.join(sorted(added_producers))}")

    for requirement_id, old_requirement in old_requirements.items():
        new_requirement = new_requirements.get(requirement_id)
        if new_requirement is None:
            lowerings.append(f"removed requirement {requirement_id}")
        elif old_requirement["status"] == "in_scope" and new_requirement["status"] == "out_of_scope":
            lowerings.append(f"requirement {requirement_id} moved out_of_scope")
        elif new_requirement:
            if (
                old_requirement.get("verification_mode", "task_evidence") == "direct_flow"
                and new_requirement.get("verification_mode", "task_evidence") != "direct_flow"
            ):
                lowerings.append(f"requirement {requirement_id} weakened direct_flow verification")
            removed_scope = set(old_requirement.get("acceptance_scope", [])) - set(
                new_requirement.get("acceptance_scope", [])
            )
            if removed_scope:
                lowerings.append(
                    f"requirement {requirement_id} narrowed acceptance_scope "
                    + ",".join(sorted(removed_scope))
                )
            removed_observables = set(old_requirement["observable_claims"]) - set(
                new_requirement["observable_claims"]
            )
            if removed_observables:
                lowerings.append(
                    f"requirement {requirement_id} removed observable claims "
                    + ",".join(sorted(removed_observables))
                )

    for producer_id, old_producer in old["producers"].items():
        new_producer = new["producers"].get(producer_id)
        if new_producer is None:
            continue
        if old_producer["source_class"] != new_producer["source_class"]:
            lowerings.append(
                f"producer {producer_id} changed source_class "
                f"{old_producer['source_class']}->{new_producer['source_class']}"
            )
        added_claims = set(new_producer["allowed_claims"]) - set(old_producer["allowed_claims"])
        if added_claims:
            lowerings.append(
                f"producer {producer_id} broadened allowed claims {','.join(sorted(added_claims))}"
            )
        if old_producer["requires_raw_artifacts"] and not new_producer["requires_raw_artifacts"]:
            lowerings.append(f"producer {producer_id} stopped requiring raw artifacts")

    for profile_id, old_profile in old["evidence_profiles"].items():
        new_profile = new["evidence_profiles"].get(profile_id)
        if new_profile is None:
            continue
        removed_profile_claims = set(old_profile["required_claims"]) - set(
            new_profile["required_claims"]
        )
        if removed_profile_claims:
            lowerings.append(
                f"profile {profile_id} removed required claims "
                + ",".join(sorted(removed_profile_claims))
            )
        for claim in set(old_profile["claim_rules"]) & set(new_profile["claim_rules"]):
            record_rule_lowering(
                f"profile {profile_id} claim {claim}",
                old_profile["claim_rules"][claim],
                new_profile["claim_rules"][claim],
            )

    for test_id, old_test in old["test_qualifications"].items():
        new_test = new["test_qualifications"].get(test_id)
        if new_test is None:
            continue
        if old_test["trust_state"] != "qualified" and new_test["trust_state"] == "qualified":
            lowerings.append(f"test {test_id} promoted to qualified")
        for field in ("oracle_source", "baseline", "subject"):
            if old_test[field] != new_test[field]:
                lowerings.append(f"test {test_id} changed {field}")
        for field in ("requirement_ids", "claim_dimensions", "negative_paths"):
            removed = set(old_test[field]) - set(new_test[field])
            if removed:
                lowerings.append(f"test {test_id} removed {field} {','.join(sorted(removed))}")
        if old_test.get("evidence_shape", "module") != new_test.get("evidence_shape", "module"):
            lowerings.append(f"test {test_id} changed evidence_shape")
        if set(old_test.get("observed_scopes", [])) != set(new_test.get("observed_scopes", [])):
            lowerings.append(f"test {test_id} changed observed_scopes")

    tests_first_strength = {"not_applicable": 0, "prequalified": 1, "required": 2}
    for task_id, old_task in old_tasks.items():
        new_task = new_tasks.get(task_id)
        if new_task is None:
            lowerings.append(f"removed task {task_id}")
            continue
        if old_task["outcome"] != new_task["outcome"]:
            lowerings.append(f"task {task_id} changed outcome")
        old_level = old_task.get("completion_level", "module_ready")
        new_level = new_task.get("completion_level", "module_ready")
        if COMPLETION_LEVELS[new_level] < COMPLETION_LEVELS[old_level]:
            lowerings.append(f"task {task_id} lowered completion_level {old_level}->{new_level}")
        if old_task.get("scope_enforced", False) and not new_task.get("scope_enforced", False):
            lowerings.append(f"task {task_id} disabled scope enforcement")
        removed_claim_scope = set(old_task.get("claim_scope", [])) - set(
            new_task.get("claim_scope", [])
        )
        if removed_claim_scope:
            lowerings.append(
                f"task {task_id} narrowed claim_scope {','.join(sorted(removed_claim_scope))}"
            )
        removed_requirements = set(old_task["requirement_ids"]) - set(new_task["requirement_ids"])
        if removed_requirements:
            lowerings.append(
                f"task {task_id} removed requirements {','.join(sorted(removed_requirements))}"
            )
        removed_claims = set(_required_claims(old, old_task)) - set(_required_claims(new, new_task))
        if removed_claims:
            lowerings.append(f"task {task_id} removed claims {','.join(sorted(removed_claims))}")
        old_dependencies = {edge["task_id"]: set(edge["claims"]) for edge in old_task["depends_on"]}
        new_dependencies = {edge["task_id"]: set(edge["claims"]) for edge in new_task["depends_on"]}
        for upstream_id, old_claims in old_dependencies.items():
            if upstream_id not in new_dependencies:
                lowerings.append(f"task {task_id} removed dependency {upstream_id}")
                continue
            removed_dependency_claims = old_claims - new_dependencies[upstream_id]
            if removed_dependency_claims:
                lowerings.append(
                    f"task {task_id} removed dependency claims from {upstream_id}: "
                    + ",".join(sorted(removed_dependency_claims))
                )
        for field in ("automation_test_ids", "readback_subjects"):
            removed = set(old_task["claim_overrides"][field]) - set(
                new_task["claim_overrides"][field]
            )
            if removed:
                lowerings.append(f"task {task_id} removed {field} {','.join(sorted(removed))}")
        old_mode = old_task["tests_first"]["mode"]
        new_mode = new_task["tests_first"]["mode"]
        if tests_first_strength[new_mode] < tests_first_strength[old_mode]:
            lowerings.append(f"task {task_id} weakened tests_first {old_mode}->{new_mode}")
        if (
            old_mode == "required"
            and new_mode == "required"
            and old_task["tests_first"]["expected_red_producer"]
            != new_task["tests_first"]["expected_red_producer"]
        ):
            lowerings.append(f"task {task_id} changed expected-red producer")
        for field in ("mutation_scope",):
            removed = set(old_task.get(field, [])) - set(new_task.get(field, []))
            if removed:
                lowerings.append(f"task {task_id} narrowed {field} {','.join(sorted(removed))}")
        old_test_contract = set(old_task.get("test_scope", [])) | set(
            old_task.get("planned_test_scope", [])
        )
        new_test_contract = set(new_task.get("test_scope", [])) | set(
            new_task.get("planned_test_scope", [])
        )
        removed_test_contract = old_test_contract - new_test_contract
        if removed_test_contract:
            lowerings.append(
                f"task {task_id} narrowed test contract "
                + ",".join(sorted(removed_test_contract))
            )
        for freshness_key, old_scope in old_task["freshness_scopes"].items():
            new_scope = new_task["freshness_scopes"].get(freshness_key)
            if new_scope is None:
                lowerings.append(f"task {task_id} removed freshness scope {freshness_key}")
                continue
            removed = set(old_scope) - set(new_scope)
            if removed:
                lowerings.append(
                    f"task {task_id} narrowed freshness scope {freshness_key} "
                    + ",".join(sorted(removed))
                )
        common_claims = set(_required_claims(old, old_task)) & set(
            _required_claims(new, new_task)
        )
        for claim in common_claims:
            record_rule_lowering(
                f"task {task_id} claim {claim}",
                _claim_rule(old, old_task, claim),
                _claim_rule(new, new_task, claim),
            )
    old_flows = {flow["id"]: flow for flow in old.get("acceptance_flows", [])}
    new_flows = {flow["id"]: flow for flow in new.get("acceptance_flows", [])}
    for flow_id, old_flow in old_flows.items():
        new_flow = new_flows.get(flow_id)
        if new_flow is None:
            lowerings.append(f"removed acceptance flow {flow_id}")
            continue
        for field in ("requirement_ids", "required_claims", "direct_test_ids"):
            removed = set(old_flow[field]) - set(new_flow[field])
            if removed:
                lowerings.append(
                    f"acceptance flow {flow_id} removed {field} {','.join(sorted(removed))}"
                )
        if old_flow["verification_task_id"] != new_flow["verification_task_id"]:
            lowerings.append(f"acceptance flow {flow_id} changed verification task")
        if old_flow["scope"] != new_flow["scope"]:
            lowerings.append(f"acceptance flow {flow_id} changed scope")
        if old_flow.get("evidence_mode") != new_flow.get("evidence_mode"):
            lowerings.append(f"acceptance flow {flow_id} changed evidence_mode")
        if old_flow.get("scope_coverage") != new_flow.get("scope_coverage"):
            lowerings.append(f"acceptance flow {flow_id} changed scope_coverage")
        if old_flow.get("scope_claims") != new_flow.get("scope_claims"):
            lowerings.append(f"acceptance flow {flow_id} changed scope_claims")
    return {
        "changed_scope_sources": sorted(changed_sources),
        "changed_requirements": sorted(changed_requirements),
        "changed_producers": sorted(changed_producers),
        "changed_profiles": sorted(changed_profiles),
        "changed_test_qualifications": sorted(changed_tests),
        "changed_acceptance_flows": sorted(changed_flows),
        "changed_tasks": sorted(changed_tasks),
        "affected_tasks": sorted(affected),
        "lowered_contracts": sorted(set(lowerings)),
    }


def _command_amend(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    old_plan, state = _load_plan_state(plan_dir, verify_sources=False)
    assert state is not None
    candidate = _load_json(_resolve_task_input(args.candidate, plan_dir, "candidate plan"))
    _validate_plan(candidate)
    _require(
        _enforcement_profile(candidate) == PIPELINE_STRICT_ENFORCEMENT_PROFILE,
        "amended plan must declare enforcement_profile=strict_v2",
        code="pipeline_profile_required",
    )
    _verify_scope_sources(candidate, plan_dir)
    _require(candidate["plan_id"] == old_plan["plan_id"], "candidate plan_id must match active plan")
    impact = _amendment_impact(old_plan, candidate)
    if impact["changed_scope_sources"]:
        _require(
            candidate["design_revision"] != old_plan["design_revision"],
            "scope source changes require a new design_revision",
            code="design_revision_required",
        )
    if not args.apply:
        return {"ok": True, "preview": True, "impact": impact, "candidate_revision": _plan_hash(candidate)}
    _require_revision(state, args.expected_revision)
    _require(state["active_package"] is None, "cannot amend while a work package is active")
    if impact["lowered_contracts"]:
        _expect_string(args.decision_ref, "--decision-ref")
        _require(
            args.decision_ref in candidate.get("decision_refs", []),
            "a lowering decision must already be recorded in the audited candidate plan",
            code="decision_ref_not_audited",
        )
    _verify_planning_audit(plan_dir, candidate)
    new_tasks = _task_map(candidate)
    old_task_states = state["task_states"]
    affected = set(impact["affected_tasks"])
    new_task_states: dict[str, dict[str, Any]] = {}
    for task_id in new_tasks:
        if task_id not in old_task_states:
            new_task_states[task_id] = _new_task_state()
            continue
        task_state = copy.deepcopy(old_task_states[task_id])
        if task_id in affected:
            if task_state["status"] == "done":
                task_state["status"] = "needs_review"
            else:
                task_state["status"] = "todo"
            task_state["unresolved"] = [
                {
                    "type": "plan_changed",
                    "subject": task_id,
                    "next_action": "review changed requirements, producer, profile, or task contract",
                }
            ]
            task_state["baseline_identity"] = {}
        new_task_states[task_id] = task_state
    new_plan_revision = _plan_hash(candidate)
    new_state = {
        "schema": STATE_SCHEMA,
        "plan_id": candidate["plan_id"],
        "plan_revision": new_plan_revision,
        "revision": state["revision"] + 1,
        "active_package": None,
        "task_states": new_task_states,
    }
    _recompute_ready(candidate, new_state)
    _validate_state(new_state, candidate)
    _write_plan(plan_dir, candidate)
    _write_state(plan_dir, new_state)
    warnings = _render_after_state_change(plan_dir, candidate, new_state)
    if impact["lowered_contracts"]:
        decision = {
            "schema": DECISION_SCHEMA,
            "decision_ref": args.decision_ref,
            "plan_id": candidate["plan_id"],
            "lowered_contracts": impact["lowered_contracts"],
        }
        decision_name = hashlib.sha256(args.decision_ref.encode("utf-8")).hexdigest()[:16] + ".json"
        _write_json_atomic(plan_dir / "evidence" / "decisions" / decision_name, decision)
    return {
        "ok": True,
        "preview": False,
        "impact": impact,
        "plan_revision": new_plan_revision,
        "state_revision": new_state["revision"],
        "warnings": warnings,
    }


def _command_render(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = _task_dir(args)
    # Rendering is a read-only recovery/view operation. It still validates the
    # schema and state relationship, but source durability and live hashes are
    # execution preconditions and must not make an existing plan unreadable.
    plan, state = _load_plan_state(
        plan_dir,
        verify_sources=False,
        enforce_source_durability=False,
    )
    assert state is not None
    _render_markdown(plan_dir, plan, state, include_details=args.details)
    return {
        "ok": True,
        "path": str(plan_dir / "TASK_TABLE.md"),
        "state_revision": state["revision"],
        "view_scope": "read_only_projection",
        "execution_validity": "not_checked",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-backed long-running task state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(command: argparse.ArgumentParser, *, project_root: bool = False) -> None:
        command.add_argument(
            "--task-dir",
            "--plan-dir",
            dest="task_dir",
            required=True,
            help="absolute task working directory; --plan-dir is a compatibility alias",
        )
        if project_root:
            command.add_argument("--project-root")

    validate_parser = subparsers.add_parser("validate")
    add_common(validate_parser)
    validate_parser.set_defaults(handler=_command_validate)

    audit_plan_parser = subparsers.add_parser("audit-plan")
    add_common(audit_plan_parser)
    audit_plan_parser.add_argument("--candidate")
    audit_plan_parser.set_defaults(handler=_command_audit_plan)

    migrate_strict_parser = subparsers.add_parser("migrate-strict")
    add_common(migrate_strict_parser)
    migrate_strict_parser.set_defaults(handler=_command_migrate_strict)

    activate_parser = subparsers.add_parser("activate")
    add_common(activate_parser)
    activate_parser.set_defaults(handler=_command_activate)

    resume_parser = subparsers.add_parser("resume")
    add_common(resume_parser, project_root=True)
    resume_parser.add_argument("--all-ready", action="store_true")
    resume_parser.set_defaults(handler=_command_resume)

    begin_parser = subparsers.add_parser("begin")
    add_common(begin_parser, project_root=True)
    begin_parser.add_argument("--task", action="append", required=True)
    begin_parser.add_argument("--expected-revision", type=int, required=True)
    begin_parser.set_defaults(handler=_command_begin)

    evidence_context_parser = subparsers.add_parser("evidence-context")
    add_common(evidence_context_parser, project_root=True)
    evidence_context_target = evidence_context_parser.add_mutually_exclusive_group(
        required=True
    )
    evidence_context_target.add_argument("--task")
    evidence_context_target.add_argument("--package", action="store_true")
    evidence_context_parser.add_argument(
        "--phase", choices=("expected_red", "verification"), required=True
    )
    evidence_context_parser.add_argument(
        "--output-dir",
        help="write context JSON files to this explicit project/task subdirectory and return only paths",
    )
    evidence_context_parser.set_defaults(handler=_command_evidence_context)

    impact_parser = subparsers.add_parser("impact")
    add_common(impact_parser, project_root=True)
    impact_parser.set_defaults(handler=_command_impact)

    seal_red_parser = subparsers.add_parser("seal-red")
    add_common(seal_red_parser, project_root=True)
    seal_red_parser.add_argument("--expected-revision", type=int, required=True)
    seal_red_parser.add_argument("--evidence", action="append", required=True)
    seal_red_parser.set_defaults(handler=_command_seal_red)

    invalidate_red_parser = subparsers.add_parser("invalidate-red")
    add_common(invalidate_red_parser, project_root=True)
    invalidate_red_parser.add_argument("--expected-revision", type=int, required=True)
    invalidate_red_parser.add_argument("--reason", required=True)
    invalidate_red_parser.add_argument("--changed-path", action="append")
    invalidate_red_parser.set_defaults(handler=_command_invalidate_red)

    checkpoint_parser = subparsers.add_parser("checkpoint")
    add_common(checkpoint_parser)
    checkpoint_parser.add_argument("--expected-revision", type=int, required=True)
    checkpoint_parser.add_argument("--phase", choices=sorted(PHASES))
    checkpoint_parser.add_argument("--next-action", required=True)
    checkpoint_parser.add_argument("--changed-path", action="append")
    checkpoint_parser.add_argument(
        "--unresolved",
        help="task-directory-relative JSON file with an items array",
    )
    checkpoint_parser.add_argument("--release", action="store_true")
    checkpoint_parser.set_defaults(handler=_command_checkpoint)

    close_parser = subparsers.add_parser("close")
    add_common(close_parser, project_root=True)
    close_parser.add_argument("--expected-revision", type=int, required=True)
    close_parser.add_argument("--evidence", action="append", default=[])
    close_parser.set_defaults(handler=_command_close)

    audit_parser = subparsers.add_parser("audit")
    add_common(audit_parser, project_root=True)
    audit_parser.add_argument("--all", action="store_true")
    audit_parser.add_argument("--apply", action="store_true")
    audit_parser.add_argument("--expected-revision", type=int)
    audit_parser.add_argument("--details", action="store_true")
    audit_parser.set_defaults(handler=_command_audit)

    amend_parser = subparsers.add_parser("amend")
    add_common(amend_parser)
    amend_parser.add_argument("--candidate", required=True)
    amend_parser.add_argument("--apply", action="store_true")
    amend_parser.add_argument("--expected-revision", type=int)
    amend_parser.add_argument("--decision-ref")
    amend_parser.set_defaults(handler=_command_amend)

    render_parser = subparsers.add_parser("render")
    add_common(render_parser)
    render_parser.add_argument("--details", action="store_true")
    render_parser.set_defaults(handler=_command_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if getattr(args, "apply", False) and args.command in {"audit", "amend"}:
            _require(args.expected_revision is not None, "--apply requires --expected-revision")
        payload = args.handler(args)
        _emit(payload)
        return 0 if payload.get("ok", False) else 2
    except TaskCtlError as exc:
        _emit({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, stream=sys.stderr)
        return 2
    except KeyboardInterrupt:
        _emit({"ok": False, "error": {"code": "interrupted", "message": "interrupted"}}, stream=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
