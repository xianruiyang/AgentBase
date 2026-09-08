"""Explicit model-grader studies built on the normal Evo runtime."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from evaluation_core import CaseLock, EvaluationError
from . import runtime
from .spec import EvoError, validate_artifacts
from .store import Store, canonical, fingerprint, positive


GRADING_INPUT_SCHEMA = "agentbase-evo-model-grading-input/v1"
GRADING_BINDING_SCHEMA = "agentbase-evo-model-grading-binding/v1"


def _config(spec: dict[str, Any], grading_id: str) -> dict[str, Any]:
    entries = spec.get("grading", [])
    if not isinstance(entries, list):
        raise EvoError("spec.grading must be an array")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("id") == grading_id]
    if len(matches) != 1:
        raise EvoError(f"grading configuration must resolve uniquely: {grading_id}")
    config = matches[0]
    if not isinstance(config.get("version"), str) or not config["version"]:
        raise EvoError(f"grading {grading_id}.version must be a non-empty string")
    if not isinstance(config.get("rubric"), (str, dict)):
        raise EvoError(f"grading {grading_id}.rubric must be a fixed string or object")
    select = config.get("select")
    if not isinstance(select, dict) or set(select) - {"grains", "fields", "row_ids"}:
        raise EvoError(f"grading {grading_id}.select supports grains, fields and row_ids")
    grains, fields = select.get("grains"), select.get("fields")
    if not isinstance(grains, list) or not grains or any(not isinstance(value, str) or not value for value in grains):
        raise EvoError(f"grading {grading_id}.select.grains must contain grain names")
    if not isinstance(fields, list) or not fields or any(not isinstance(value, str) or not value for value in fields):
        raise EvoError(f"grading {grading_id}.select.fields must contain source field ids")
    row_ids = select.get("row_ids")
    if row_ids is not None and (not isinstance(row_ids, list) or len(row_ids) != len(set(row_ids)) or
                                any(not isinstance(value, str) or not value for value in row_ids)):
        raise EvoError(f"grading {grading_id}.select.row_ids must contain unique row ids")
    declared = {field["id"]: field for field in spec["fields"]}
    unknown = set(fields) - set(declared)
    if unknown:
        raise EvoError(f"grading {grading_id} selects unknown fields: {sorted(unknown)}")
    outputs = config.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise EvoError(f"grading {grading_id}.outputs must contain assessment fields")
    seen: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict) or set(output) - {"field", "minimum", "maximum"}:
            raise EvoError(f"grading {grading_id} output supports field/minimum/maximum")
        field_id = output.get("field")
        if field_id in seen or field_id not in declared or declared[field_id]["grain"] != "assessment":
            raise EvoError(f"grading output must be a unique declared assessment field: {field_id}")
        seen.add(field_id)
        if ("minimum" in output or "maximum" in output) and declared[field_id]["type"] not in {"number", "integer"}:
            raise EvoError(f"grading output {field_id} ranges require a numeric field")
        for key in ("minimum", "maximum"):
            if key in output and (not isinstance(output[key], (int, float)) or isinstance(output[key], bool)):
                raise EvoError(f"grading output {field_id}.{key} must be numeric")
        if output.get("minimum") is not None and output.get("maximum") is not None and output["minimum"] > output["maximum"]:
            raise EvoError(f"grading output {field_id} minimum exceeds maximum")
    controller = config.get("controller")
    if not isinstance(controller, dict) or controller.get("adapter") not in {"codex", "command"}:
        raise EvoError(f"grading {grading_id}.controller.adapter must be codex or command")
    positive(controller.get("token_budget"), f"grading {grading_id}.controller.token_budget")
    if controller["adapter"] == "codex" and not all(isinstance(controller.get(key), str) and controller[key] for key in ("model", "reasoning_effort")):
        raise EvoError(f"grading {grading_id} Codex controller requires model and reasoning_effort")
    if controller["adapter"] == "command":
        runtime.validate_argv(controller.get("argv"))
    return config


def _grading_input(spec: dict[str, Any], artifacts: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    select = config["select"]
    selected_ids = set(select.get("row_ids", [])) if "row_ids" in select else None
    rows = []
    for row in artifacts["rows"]:
        if row["grain"] not in select["grains"] or (selected_ids is not None and row["id"] not in selected_ids):
            continue
        values = {field: row["values"][field] for field in select["fields"] if field in row["values"]}
        rows.append({"row": row["id"], "grain": row["grain"], "dimensions": row["dimensions"],
                     "values": values, "source": row["source"], "completeness": row["completeness"]})
    if selected_ids is not None:
        missing = selected_ids - {row["row"] for row in rows}
        if missing:
            raise EvoError(f"grading selects unavailable rows: {sorted(missing)}")
    if not rows:
        raise EvoError("grading selection is empty")
    return {
        "schema": GRADING_INPUT_SCHEMA,
        "grading": {"id": config["id"], "version": config["version"], "rubric": config["rubric"]},
        "outputs": config["outputs"], "rows": rows,
        "response_contract": {"assessments": [{"row": "<selected row>", "field": "<output field>", "value": "<typed value>"}]},
    }


def _prompt(value: dict[str, Any]) -> str:
    return ("Act as an independent grader. Apply only the frozen rubric and evidence below. "
            "Return exactly one JSON object with only an assessments array. Provide exactly one value for every row/output field pair; do not return prose.\n"
            + json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


def _binding_root(store: Store, subject_study: int) -> Path:
    return store.root / "reviews" / "grading" / f"s{subject_study}"


def _write_immutable(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise EvoError(f"immutable grading binding conflicts: {path}")


def prepare_model_grading(store: Store, subject_study: int, grading_id: str) -> dict[str, Any]:
    try:
        with CaseLock(store.root, f"evo-grading-budget:s{subject_study}"):
            subject = store.study(subject_study)
            unsettled = [job for job in store.jobs(subject_study) if job["state"] in {"queued", "preparing", "running", "verifying", "uncertain"}]
            if unsettled:
                raise EvoError("model grading requires frozen subject artifacts; finish or reconcile subject jobs first")
            from .runtime_review import study_artifacts_with_reviews
            artifacts = study_artifacts_with_reviews(store, subject_study)
            config = _config(subject["spec"], grading_id)
            frozen = _grading_input(subject["spec"], artifacts, config)
            identity = fingerprint({"subject": subject_study, "config": config, "input": frozen})
            existing_path = _binding_root(store, subject_study) / "bindings" / f"{identity}.json"
            if existing_path.is_file():
                binding = json.loads(existing_path.read_text(encoding="utf-8"))
                return {"subject_study": f"s{subject_study}", "grader_study": f"s{binding['grader_study']}",
                        "grading": config["id"], "identity": identity, "reused": True}
            usage = _research_usage(store, subject_study)
            if not usage["usage_known"]:
                raise EvoError("research has unsettled subject or grader usage; reconcile it before reserving another grader")
            if usage["known_tokens"] + usage["reserved_tokens"] + config["controller"]["token_budget"] > subject["max_tokens"]:
                raise EvoError("subject plus all grader usage/reservations exceeds the research budget")
            result = _prepare_grading(store, subject["spec"], artifacts, grading_id, Path(subject["project"]),
                                      Path(subject["work"]), subject_study=subject_study,
                                      subject_usage=usage["subject_tokens"])
            result["reused"] = False
            return result
    except EvaluationError as exc:
        raise EvoError(str(exc)) from exc


def _study_usage(store: Store, study: int, *, reserve_unfinished: bool) -> dict[str, Any]:
    known = 0
    reserved = 0
    complete = True
    usage_known = True
    for job in store.jobs(study):
        if job["usage_complete"] and job["usage"] is not None:
            known += job["usage"]
        elif job["model_slots"] > 0:
            if reserve_unfinished and job["state"] in {"queued", "preparing", "running", "verifying"}:
                reserved += job["token_reservation"]
                complete = False
            else:
                complete = False
                usage_known = False
    return {"known": known, "reserved": reserved, "complete": complete, "usage_known": usage_known}


def _research_usage(store: Store, subject_study: int) -> dict[str, Any]:
    subject = _study_usage(store, subject_study, reserve_unfinished=False)
    grader_known = 0
    grader_reserved = 0
    complete = subject["complete"]
    usage_known = subject["usage_known"]
    seen: set[int] = set()
    root = _binding_root(store, subject_study) / "bindings"
    if root.exists():
        for path in root.glob("*.json"):
            binding = json.loads(path.read_text(encoding="utf-8"))
            grader = binding["grader_study"]
            if grader in seen:
                continue
            seen.add(grader)
            usage = _study_usage(store, grader, reserve_unfinished=True)
            grader_jobs = store.jobs(grader)
            if (usage["reserved"] == 0 and
                    any(job["state"] in {"queued", "preparing", "running", "verifying"} for job in grader_jobs)):
                # The command adapter is the explicit local grader/testing interface and has
                # no model_slots column reservation, but its declared grader budget still
                # participates in the owning research budget.
                usage["reserved"] = binding["config"]["controller"]["token_budget"]
            grader_known += usage["known"]
            grader_reserved += usage["reserved"]
            complete = complete and usage["complete"]
            usage_known = usage_known and usage["usage_known"]
    return {"subject_tokens": subject["known"], "grader_tokens": grader_known,
            "known_tokens": subject["known"] + grader_known, "reserved_tokens": grader_reserved,
            "complete": complete, "usage_known": usage_known}


def prepare_artifact_grading(store: Store, spec: dict[str, Any], artifacts: dict[str, Any], grading_id: str,
                             project: Path, work: Path) -> dict[str, Any]:
    """Prepare the same grader owner from explicitly supplied offline artifacts."""
    return _prepare_grading(store, spec, artifacts, grading_id, project, work, subject_study=None, subject_usage=0)


def _prepare_grading(store: Store, spec: dict[str, Any], artifacts: dict[str, Any], grading_id: str,
                     project: Path, work: Path, *, subject_study: int | None, subject_usage: int) -> dict[str, Any]:
    config = _config(spec, grading_id)
    validate_artifacts(artifacts)
    frozen = _grading_input(spec, artifacts, config)
    controller = config["controller"]
    prompt = _prompt(frozen)
    grader_runtime: dict[str, Any] = {
        "adapter": controller["adapter"], "timeout_seconds": controller.get("timeout_seconds", 300),
        "token_reservation": controller["token_budget"], "max_agents": controller.get("max_agents", 1),
    }
    if controller["adapter"] == "codex":
        grader_runtime.update(model=controller["model"], reasoning_effort=controller["reasoning_effort"], prompt=prompt)
    else:
        encoded = canonical(frozen)
        if "{grading_json}" not in controller["argv"]:
            raise EvoError("command grader argv must contain an exact {grading_json} argument")
        grader_runtime["argv"] = [encoded if arg == "{grading_json}" else arg for arg in controller["argv"]]
        if sum(len(arg) + 1 for arg in grader_runtime["argv"]) > 30_000:
            raise EvoError("frozen command grader input exceeds the bounded Windows argv; narrow grading selection")
    grader_spec = {
        "schema": "agentbase-evo-research/v1", "id": f"grader-{subject_study or 'offline'}-{grading_id}",
        "version": fingerprint({"subject": subject_study, "config": config, "input": frozen}),
        "components": {kind: [] for kind in ("agents_md", "skills", "hooks", "mcp", "tools", "agents", "codex_settings")},
        "combinations": [{"id": "fixed-grader", "members": {}}],
        "evaluations": {"items": [{"id": "grade", "input_version": fingerprint(frozen), "protocol": "model-grader-v1",
                                      "observations": ["grader-assessments"], "prompt": prompt, "runtime": grader_runtime}],
                        "groups": [{"id": "grading", "active": True, "items": ["grade"]}]},
        "fields": [], "scoring": [],
        "selection": {"combinations": ["fixed-grader"], "groups": ["grading"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": controller["token_budget"]},
    }
    identity = fingerprint({"subject": subject_study, "config": config, "input": frozen})
    binding_base = (_binding_root(store, subject_study) if subject_study is not None
                    else store.root / "reviews" / "grading" / "offline")
    spec_path = binding_base / "specs" / f"{identity}.json"
    _write_immutable(spec_path, grader_spec)
    grader_study = runtime.submit(store, spec_path, project, work)
    binding = {"schema": GRADING_BINDING_SCHEMA, "subject_study": subject_study, "grader_study": grader_study,
               "grading": {"id": config["id"], "version": config["version"]}, "identity": identity,
               "input": frozen, "config": config,
               "field_declarations": {field["id"]: field for field in spec["fields"] if field["id"] in {output["field"] for output in config["outputs"]}},
               "source_artifacts": {"id": artifacts["id"], "version": artifacts["version"]},
               "subject_usage_at_freeze": subject_usage}
    _write_immutable(binding_base / "bindings" / f"{identity}.json", binding)
    return {"subject_study": f"s{subject_study}" if subject_study is not None else None,
            "grader_study": f"s{grader_study}", "grading": config["id"], "identity": identity}


def _binding_for_grader(store: Store, grader_study: int) -> dict[str, Any]:
    root = store.root / "reviews" / "grading"
    matches = []
    if root.exists():
        for path in root.glob("*/bindings/*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("schema") == GRADING_BINDING_SCHEMA and value.get("grader_study") == grader_study:
                matches.append(value)
    if len(matches) != 1:
        raise EvoError(f"grader study s{grader_study} must have one frozen grading binding")
    return matches[0]


def _response(store: Store, grader_study: int) -> tuple[dict[str, Any], dict[str, Any]]:
    jobs = store.jobs(grader_study)
    if len(jobs) != 1 or jobs[0]["state"] != "completed" or not jobs[0]["receipt"]:
        raise EvoError(f"grader study s{grader_study} has no completed receipt")
    job = jobs[0]
    receipt_path = store.root / job["receipt"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if job["runtime"]["adapter"] == "codex":
        answer = store.root / "jobs" / f"j{job['id']}" / "codex-logs" / "last-message.txt"
        try:
            value = json.loads(answer.read_text(encoding="utf-8"),
                               parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"non-finite {token}")))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"grader final answer is not strict JSON: {exc}") from exc
    else:
        value = receipt.get("values")
    if not isinstance(value, dict) or set(value) != {"assessments"} or not isinstance(value["assessments"], list):
        raise EvoError("grader output must be exactly {assessments:[...]}")
    return value, {"job": job, "receipt": receipt, "receipt_path": receipt_path}


def _valid_type(value: Any, declaration: dict[str, Any]) -> bool:
    kind = declaration["type"]
    return ((kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool) and
             (not isinstance(value, float) or math.isfinite(value))) or
            (kind == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
            (kind == "boolean" and isinstance(value, bool)) or
            (kind == "string" and isinstance(value, str)))


def model_grading_facts(store: Store, grader_study: int) -> dict[str, Any]:
    binding = _binding_for_grader(store, grader_study)
    config = binding["config"]
    value, evidence = _response(store, grader_study)
    rows = {row["row"]: row for row in binding["input"]["rows"]}
    declarations = binding["field_declarations"]
    outputs = {output["field"]: output for output in config["outputs"]}
    expected = {(row, field) for row in rows for field in outputs}
    observed: dict[tuple[str, str], Any] = {}
    for index, assessment in enumerate(value["assessments"]):
        if not isinstance(assessment, dict) or set(assessment) != {"row", "field", "value"}:
            raise EvoError(f"grader assessment {index} must contain exactly row, field and value")
        coordinate = (assessment["row"], assessment["field"])
        if coordinate not in expected or coordinate in observed:
            raise EvoError(f"grader assessment has unknown or duplicate coordinate: {coordinate}")
        field, output = declarations[coordinate[1]], outputs[coordinate[1]]
        result = assessment["value"]
        if not _valid_type(result, field):
            raise EvoError(f"grader value for {coordinate[1]} does not match type {field['type']}")
        if output.get("minimum") is not None and result < output["minimum"]:
            raise EvoError(f"grader value for {coordinate[1]} is below minimum")
        if output.get("maximum") is not None and result > output["maximum"]:
            raise EvoError(f"grader value for {coordinate[1]} exceeds maximum")
        observed[coordinate] = result
    missing = expected - set(observed)
    if missing:
        raise EvoError(f"grader output is missing assessments: {sorted(missing)}")
    facts = []
    for row_id, source in rows.items():
        values = {field: observed[(row_id, field)] for field in outputs}
        facts.append({"id": f"grader-s{grader_study}-{row_id}", "grain": "assessment",
                      "dimensions": {**source["dimensions"], "graded_row": row_id,
                                     "grader": config["id"], "grader_version": config["version"]},
                      "values": values,
                      "source": {"kind": "model-grader-receipt", "location": str(evidence["receipt_path"].relative_to(store.root)).replace("\\", "/")},
                      "completeness": "complete"})
    return {"schema": "agentbase-evo-model-grading-facts/v1",
            "subject_study": f"s{binding['subject_study']}" if binding["subject_study"] is not None else None,
            "grader_study": f"s{grader_study}", "grading": binding["grading"], "rows": facts,
            "usage": evidence["job"]["usage"], "usage_complete": bool(evidence["job"]["usage_complete"])}


def run_model_grading(store: Store, grader_study: int, installed_codex_root: Path | None = None) -> dict[str, Any]:
    status = runtime.run(store, study=grader_study, installed_codex_root=installed_codex_root)
    if status["counts"].get("uncertain"):
        status = runtime.recover(store, grader_study, installed_codex_root)
    facts = model_grading_facts(store, grader_study)
    binding = _binding_for_grader(store, grader_study)
    grader_tokens = facts["usage"]
    research = (_research_usage(store, binding["subject_study"])
                if binding["subject_study"] is not None else None)
    return {"status": status, "facts": facts,
            "grader_usage": {"tokens": grader_tokens, "complete": facts["usage_complete"]},
            "research_usage": ({"subject_tokens": research["subject_tokens"], "grader_tokens": research["grader_tokens"],
                                "reserved_tokens": research["reserved_tokens"],
                                "total_tokens": research["known_tokens"] if research["complete"] else None,
                                "complete": research["complete"]} if research is not None else
                               {"subject_tokens": None, "grader_tokens": grader_tokens, "reserved_tokens": 0,
                                "total_tokens": grader_tokens if facts["usage_complete"] else None,
                                "complete": facts["usage_complete"]})}


def merge_model_grading_artifacts(artifacts: dict[str, Any], store: Store, grader_study: int) -> dict[str, Any]:
    """Return a new ordinary artifacts document; never modify its source file."""
    validate_artifacts(artifacts)
    binding = _binding_for_grader(store, grader_study)
    source = binding["source_artifacts"]
    if source != {"id": artifacts["id"], "version": artifacts["version"]}:
        raise EvoError("artifacts do not match the frozen model-grading input")
    facts = model_grading_facts(store, grader_study)
    rows = [*artifacts["rows"], *facts["rows"]]
    result = {**artifacts, "version": fingerprint(rows), "rows": rows}
    validate_artifacts(result)
    return result


def study_artifacts_with_model_grades(store: Store, subject_study: int,
                                      artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    if artifacts is None:
        from .runtime_review import study_artifacts_with_reviews
        base = study_artifacts_with_reviews(store, subject_study)
    else:
        validate_artifacts(artifacts)
        base = artifacts
    rows = list(base["rows"])
    spec = store.study(subject_study)["spec"]
    root = _binding_root(store, subject_study) / "bindings"
    if root.exists():
        for path in sorted(root.glob("*.json")):
            binding = json.loads(path.read_text(encoding="utf-8"))
            config = _config(spec, binding["grading"]["id"])
            current_input = _grading_input(spec, base, config)
            current_identity = fingerprint({"subject": subject_study, "config": config, "input": current_input})
            if binding["identity"] != current_identity:
                continue
            try:
                facts = model_grading_facts(store, binding["grader_study"])
            except EvoError as exc:
                if "has no completed receipt" in str(exc):
                    continue
                raise
            rows.extend(facts["rows"])
    result = {**base, "version": fingerprint(rows), "rows": rows}
    validate_artifacts(result)
    return result
