from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from evaluation_core import CaseLock, EvaluationError

from . import runtime
from .scoring import score_artifacts
from .spec import COMPONENT_KINDS, EvoError, load_spec
from .store import Store, canonical, fingerprint, positive


OPTIMIZATION_SCHEMA = "agentbase-evo-optimization/v1"
PROPOSAL_SCHEMA = "agentbase-evo-proposal/v1"
EXPORT_SCHEMA = "agentbase-evo-optimization-export/v1"
MAX_CONTROLLER_FILE_BYTES = 256 * 1024


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="optimization-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoError(f"cannot read optimization state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvoError(f"optimization state must be an object: {path}")
    return value


def _optimization_root(store: Store, identity: str) -> Path:
    return store.root / "optimizations" / identity


def _resolve(store: Store, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise EvoError("optimization id is required")
    roots = store.root / "optimizations"
    if reference.startswith("opt-") and len(reference) == 12:
        matches = [path for path in roots.glob("*.json") if _read(path).get("alias") == reference]
        if len(matches) != 1:
            raise EvoError(f"optimization alias must resolve uniquely: {reference}")
        return matches[0]
    path = roots / f"{reference}.json"
    if not path.is_file():
        raise EvoError(f"unknown optimization: {reference}")
    return path


def _relative_file(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvoError(f"{where} must be a non-empty forward-slash relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EvoError(f"{where} must stay inside its component")
    return value


def _metric_coordinate(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"scoring", "metric", "direction", "minimum", "maximum"}:
        raise EvoError(f"{where} must identify scoring, metric and optional direction")
    if not all(isinstance(value.get(key), str) and value[key] for key in ("scoring", "metric")):
        raise EvoError(f"{where} requires non-empty scoring and metric")
    if value.get("direction", "max") not in ("min", "max"):
        raise EvoError(f"{where}.direction must be min or max")
    return {**value, "direction": value.get("direction", "max")}


def validate_optimization(spec: dict[str, Any]) -> dict[str, Any]:
    config = spec.get("optimization")
    if not isinstance(config, dict):
        raise EvoError("optimization specification is required; Evo will not infer one")
    required = {"controller", "mutable", "rounds", "budget", "splits", "promotion", "grading"}
    missing = required - set(config)
    if missing:
        raise EvoError(f"optimization is missing required sections: {sorted(missing)}")
    combinations = {entry["id"]: entry for entry in spec["combinations"]}
    selected = spec.get("selection", {}).get("combinations", list(combinations))
    baseline = config.get("baseline_combination")
    if baseline is None:
        if len(selected) != 1:
            raise EvoError("optimization.baseline_combination is required when selection has multiple combinations")
        baseline = selected[0]
    if baseline not in selected:
        raise EvoError("optimization baseline must be one of selection.combinations")
    controller = config["controller"]
    if not isinstance(controller, dict) or controller.get("adapter") not in ("command", "codex"):
        raise EvoError("optimization.controller.adapter must be command or codex")
    positive(controller.get("timeout_seconds"), "optimization.controller.timeout_seconds", 14400)
    if controller["adapter"] == "command":
        runtime.validate_argv(controller.get("argv"))
    elif not all(isinstance(controller.get(key), str) and controller[key] for key in ("model", "reasoning_effort", "prompt")):
        raise EvoError("Codex controller requires fixed model, reasoning_effort and prompt")
    mutable = config["mutable"]
    if not isinstance(mutable, list) or not mutable:
        raise EvoError("optimization.mutable must select at least one component")
    component_map = {kind: {entry["id"]: entry for entry in spec["components"][kind]} for kind in COMPONENT_KINDS}
    baseline_members = combinations[baseline]["members"]
    seen: set[tuple[str, str, str]] = set()
    for number, entry in enumerate(mutable):
        if not isinstance(entry, dict) or entry.get("kind") not in COMPONENT_KINDS:
            raise EvoError(f"optimization.mutable[{number}] has invalid kind")
        kind, identity = entry["kind"], entry.get("id")
        if identity not in component_map[kind] or identity not in baseline_members.get(kind, []):
            raise EvoError(f"mutable component {kind}/{identity} is not selected by the baseline")
        paths = entry.get("paths")
        if not isinstance(paths, list) or not paths:
            raise EvoError(f"mutable component {kind}/{identity} requires paths")
        for index, value in enumerate(paths):
            path = _relative_file(value, f"optimization.mutable[{number}].paths[{index}]")
            key = (kind, identity, path)
            if key in seen:
                raise EvoError(f"duplicate mutable path: {kind}/{identity}/{path}")
            seen.add(key)
    rounds = config["rounds"]
    if not isinstance(rounds, dict):
        raise EvoError("optimization.rounds must be an object")
    for key in ("max", "patience", "duplicate_hypothesis_limit"):
        positive(rounds.get(key), f"optimization.rounds.{key}", 1000)
    budget = config["budget"]
    if not isinstance(budget, dict):
        raise EvoError("optimization.budget must be an object")
    positive(budget.get("max_total_tokens"), "optimization.budget.max_total_tokens")
    positive(budget.get("max_controller_tokens"), "optimization.budget.max_controller_tokens")
    groups = {entry["id"]: entry for entry in spec["evaluations"]["groups"]}
    items = {entry["id"]: entry for entry in spec["evaluations"]["items"]}
    splits = config["splits"]
    if not isinstance(splits, dict) or set(splits) != {"development", "selection", "final"}:
        raise EvoError("optimization.splits must explicitly define development, selection and final")
    family_split: dict[str, str] = {}
    for split, selected_groups in splits.items():
        if not isinstance(selected_groups, list) or (split != "development" and not selected_groups):
            raise EvoError(f"optimization.splits.{split} must be an explicit group array")
        for group in selected_groups:
            if group not in groups:
                raise EvoError(f"optimization split references unknown group: {group}")
            for item_id in groups[group]["items"]:
                family = items[item_id].get("family")
                if not isinstance(family, str) or not family:
                    raise EvoError(f"optimization evaluation item {item_id} requires family")
                prior = family_split.setdefault(family, split)
                if prior != split:
                    raise EvoError(f"evaluation family {family} leaks across {prior} and {split}")
    promotion = config["promotion"]
    if not isinstance(promotion, dict):
        raise EvoError("optimization.promotion must be an object")
    quality = promotion.get("quality_metrics")
    objectives = promotion.get("objectives")
    if not isinstance(quality, list) or not quality or not isinstance(objectives, list) or not objectives:
        raise EvoError("promotion requires quality_metrics and objectives")
    known_scores = {entry["id"]: {metric["id"] for metric in entry["metrics"]} for entry in spec["scoring"]}
    for where, entries in (("quality_metrics", quality), ("objectives", objectives)):
        for index, raw in enumerate(entries):
            coordinate = _metric_coordinate(raw, f"promotion.{where}[{index}]")
            if coordinate["metric"] not in known_scores.get(coordinate["scoring"], set()):
                raise EvoError(f"unknown promotion metric: {coordinate['scoring']}/{coordinate['metric']}")
    final_acceptance = config.get("final_acceptance")
    final_thresholds = [] if final_acceptance is None else final_acceptance.get("thresholds") if isinstance(final_acceptance, dict) else None
    if not isinstance(final_thresholds, list) or (final_acceptance is not None and not final_thresholds):
        raise EvoError("optimization.final_acceptance must contain a non-empty thresholds array")
    for index, raw in enumerate(final_thresholds):
        coordinate = _metric_coordinate(raw, f"optimization.final_acceptance.thresholds[{index}]")
        if coordinate["metric"] not in known_scores.get(coordinate["scoring"], set()):
            raise EvoError(f"unknown final threshold metric: {coordinate['scoring']}/{coordinate['metric']}")
        bounds = [key for key in ("minimum", "maximum") if key in raw]
        if not bounds or any(not isinstance(raw[key], (int, float)) or isinstance(raw[key], bool) for key in bounds):
            raise EvoError("each final threshold requires a numeric minimum or maximum")
    required_families = promotion.get("required_families")
    selection_families = {family for family, split in family_split.items() if split == "selection"}
    if not isinstance(required_families, list) or set(required_families) != selection_families:
        raise EvoError("promotion.required_families must exactly cover selection families")
    grading = config["grading"]
    if not isinstance(grading, list) or len(grading) != len(set(grading)) or any(not isinstance(value, str) or not value for value in grading):
        raise EvoError("optimization.grading must be an explicit array of unique grading ids")
    known_grading = {entry.get("id") for entry in spec.get("grading", []) if isinstance(entry, dict)}
    unknown_grading = set(grading) - known_grading
    if unknown_grading:
        raise EvoError(f"optimization references unknown grading configurations: {sorted(unknown_grading)}")
    tolerance = promotion.get("non_regression_tolerance", 0)
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
        raise EvoError("promotion.non_regression_tolerance must be a nonnegative number")
    return {**config, "baseline_combination": baseline}


def _source(project: Path, value: str) -> Path:
    import agentbase_codex
    try:
        return agentbase_codex.resolve_component_source(project, value)
    except EvaluationError as exc:
        raise EvoError(str(exc)) from exc


def _copy_component(source: Path, target: Path) -> None:
    if target.exists():
        raise EvoError(f"candidate component already exists: {target}")
    if source.is_dir():
        for path in source.rglob("*"):
            if path.is_symlink():
                raise EvoError(f"component payload contains a link: {path}")
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _candidate_sources(spec: dict[str, Any], config: dict[str, Any], project: Path, root: Path) -> dict[str, str]:
    components = {kind: {entry["id"]: entry for entry in spec["components"][kind]} for kind in COMPONENT_KINDS}
    result: dict[str, str] = {}
    for entry in config["mutable"]:
        key = f"{entry['kind']}/{entry['id']}"
        source = _source(project, components[entry["kind"]][entry["id"]]["source"])
        container = root / entry["kind"] / entry["id"]
        target = container / source.name if source.is_file() else container
        _copy_component(source, target)
        result[key] = str(target.resolve())
    return result


def start(store: Store, spec_path: Path, project: Path, work: Path) -> dict[str, Any]:
    spec = load_spec(spec_path)
    config = validate_optimization(spec)
    project, work = project.resolve(), work.resolve()
    runtime.check_roots(project, store.root, work)
    frozen = {"spec": spec, "optimization": config, "project": str(project), "work": str(work)}
    identity = fingerprint(frozen)
    path = store.root / "optimizations" / f"{identity}.json"
    if path.exists():
        state = _read(path)
        return _public(state)
    candidate = f"candidate-{fingerprint({'optimization': identity, 'baseline': True})[:12]}"
    candidate_root = store.root / "candidates" / candidate
    sources = _candidate_sources(spec, config, project, candidate_root)
    runtime.immutable_json(candidate_root / "candidate.json", {
        "candidate": candidate, "baseline": True, "source_spec": {"id": spec["id"], "version": spec["version"]},
        "sources": sources,
    })
    state = {
        "schema": OPTIMIZATION_SCHEMA, "id": identity, "alias": f"opt-{identity[:8]}", "state": "ready",
        "frozen": frozen, "baseline": candidate, "champion": candidate, "candidate_sources": {candidate: sources},
        "round": 0, "no_improvement": 0, "hypotheses": {}, "controller_studies": [], "evaluation_studies": [],
        "controller_tokens": 0, "subject_tokens": 0, "stop_reason": None, "awaiting": None, "final_study": None,
        "grader_tokens": 0, "grader_studies": [],
        "round_records": {},
        "final_acceptance": None,
    }
    _atomic_json(path, state)
    return _public(state)


def _public(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state.get(key) for key in ("schema", "id", "alias", "state", "round", "baseline", "champion",
                                             "controller_tokens", "subject_tokens", "grader_tokens", "stop_reason", "awaiting", "final_study",
                                             "final_acceptance")}


def status(store: Store, reference: str) -> dict[str, Any]:
    return _public(_read(_resolve(store, reference)))


def _controller_spec(state: dict[str, Any], round_number: int) -> dict[str, Any]:
    source = state["frozen"]["spec"]
    controller = copy.deepcopy(state["frozen"]["optimization"]["controller"])
    context = {
        "round": round_number,
        "champion": state["champion"],
        "allowed_feedback": state.get("feedback", []),
        "mutable": state["frozen"]["optimization"]["mutable"],
        "current_mutable_files": _controller_files(state),
        "required_output_schema": PROPOSAL_SCHEMA,
    }
    if controller["adapter"] == "codex":
        controller["prompt"] = controller["prompt"].rstrip() + "\n\nOptimization context (JSON):\n" + canonical(context)
    controller.setdefault("max_agents", 1)
    controller.setdefault("token_reservation", state["frozen"]["optimization"]["budget"]["max_controller_tokens"])
    return {
        "schema": source["schema"], "id": f"{source['id']}-controller-r{round_number}", "version": source["version"],
        "components": {kind: [] for kind in COMPONENT_KINDS},
        "combinations": [{"id": "controller", "members": {}}],
        "evaluations": {"items": [{"id": "propose", "family": "controller", "input_version": str(round_number),
                                     "protocol": "optimization-controller-v1", "observations": ["proposal"], "runtime": controller}],
                        "groups": [{"id": "controller", "active": True, "items": ["propose"]}]},
        "fields": [], "scoring": [],
        "selection": {"combinations": ["controller"], "groups": ["controller"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": controller["token_reservation"]},
    }


def _controller_files(state: dict[str, Any]) -> list[dict[str, str]]:
    """Project only authorized mutable text, using stable readable aliases."""
    result: list[dict[str, str]] = []
    total = 0
    sources = state["candidate_sources"][state["champion"]]
    aliases: dict[tuple[str, str], str] = {}
    for entry in state["frozen"]["optimization"]["mutable"]:
        component_key = (entry["kind"], entry["id"])
        alias = aliases.setdefault(component_key, f"component-{len(aliases) + 1}")
        source = Path(sources[f"{entry['kind']}/{entry['id']}"])
        for relative in entry["paths"]:
            path = source if source.is_file() and relative == source.name else (source / PurePosixPath(relative)).resolve()
            if path.is_symlink() or not path.is_file() or (source.is_dir() and not path.is_relative_to(source.resolve())):
                raise EvoError(f"mutable controller input is not a regular component file: {entry['kind']}/{entry['id']}/{relative}")
            raw = path.read_bytes()
            total += len(raw)
            if total > MAX_CONTROLLER_FILE_BYTES:
                raise EvoError(f"controller mutable input exceeds {MAX_CONTROLLER_FILE_BYTES} bytes")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EvoError(f"controller mutable input must be UTF-8 text: {entry['kind']}/{entry['id']}/{relative}") from exc
            result.append({"component": alias, "kind": entry["kind"], "id": entry["id"],
                           "path": relative, "content": content})
    return result


def _proposal_from_study(store: Store, study: int) -> dict[str, Any]:
    job = store.jobs(study)[0]
    if job["state"] != "completed" or not job["receipt"]:
        raise EvoError(f"controller study s{study} did not complete: {job['state']}")
    receipt = _read(store.root / job["receipt"])
    if job["runtime"]["adapter"] == "command":
        proposal = receipt.get("values")
    else:
        path = store.root / "jobs" / f"j{job['id']}" / "codex-logs" / "last-message.txt"
        try:
            proposal = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvoError(f"Codex controller did not return one JSON proposal: {exc}") from exc
    return _validate_proposal(proposal)


def _validate_proposal(proposal: Any) -> dict[str, Any]:
    if not isinstance(proposal, dict) or proposal.get("schema") != PROPOSAL_SCHEMA:
        raise EvoError(f"controller proposal schema must be {PROPOSAL_SCHEMA}")
    hypothesis = proposal.get("hypothesis")
    edits = proposal.get("edits")
    if not isinstance(hypothesis, str) or not hypothesis.strip() or not isinstance(edits, list) or not edits:
        raise EvoError("controller proposal requires a hypothesis and edits")
    if len(edits) > 100:
        raise EvoError("controller proposal exceeds 100 edits")
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict) or edit.get("kind") not in COMPONENT_KINDS:
            raise EvoError(f"proposal edit {index} has invalid kind")
        _relative_file(edit.get("path"), f"proposal.edits[{index}].path")
        if not isinstance(edit.get("id"), str) or not isinstance(edit.get("content"), str):
            raise EvoError(f"proposal edit {index} requires id and text content")
    return proposal


def _apply(state: dict[str, Any], proposal: dict[str, Any]) -> str:
    config = state["frozen"]["optimization"]
    allowed = {(entry["kind"], entry["id"], path) for entry in config["mutable"] for path in entry["paths"]}
    for edit in proposal["edits"]:
        if (edit["kind"], edit["id"], edit["path"]) not in allowed:
            raise EvoError(f"proposal edit is outside mutable scope: {edit['kind']}/{edit['id']}/{edit['path']}")
    identity = fingerprint({"parent": state["champion"], "proposal": proposal})
    candidate = f"candidate-{identity[:12]}"
    state_root = Path(state["state_root"])
    root = state_root / "candidates" / candidate
    if root.exists():
        manifest = _read(root / "candidate.json")
        if manifest != {"candidate": candidate, "parent": state["champion"], "proposal": proposal}:
            raise EvoError(f"existing candidate does not match frozen proposal: {candidate}")
        sources = {}
        for key, source_value in state["candidate_sources"][state["champion"]].items():
            kind, component = key.split("/", 1)
            prior = Path(source_value)
            target = root / kind / component / prior.name if prior.is_file() else root / kind / component
            if not target.exists() or target.is_symlink():
                raise EvoError(f"existing candidate payload is incomplete: {key}")
            sources[key] = str(target.resolve())
        state["candidate_sources"][candidate] = sources
    else:
        champion_sources = state["candidate_sources"][state["champion"]]
        sources: dict[str, str] = {}
        for key, source_value in champion_sources.items():
            kind, component = key.split("/", 1)
            source = Path(source_value)
            container = root / kind / component
            target = container / source.name if source.is_file() else container
            _copy_component(source, target)
            sources[key] = str(target.resolve())
        for edit in proposal["edits"]:
            target = Path(sources[f"{edit['kind']}/{edit['id']}"])
            if target.is_file():
                if edit["path"] != target.name:
                    raise EvoError(f"file component only permits its own filename: {target.name}")
                output = target
            else:
                output = (target / PurePosixPath(edit["path"])).resolve()
                if not output.is_relative_to(target.resolve()):
                    raise EvoError("proposal edit escapes component payload")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(edit["content"], encoding="utf-8", newline="\n")
        runtime.immutable_json(root / "candidate.json", {"candidate": candidate, "parent": state["champion"], "proposal": proposal})
        state["candidate_sources"][candidate] = sources
    return candidate


def _evaluation_spec(state: dict[str, Any], candidates: list[str], split: str, round_number: int) -> dict[str, Any]:
    spec = copy.deepcopy(state["frozen"]["spec"])
    config = state["frozen"]["optimization"]
    baseline_combo = next(entry for entry in spec["combinations"] if entry["id"] == config["baseline_combination"])
    spec["id"] = f"{spec['id']}-optimization-{split}-r{round_number}"
    spec["version"] = f"{spec['version']}+opt.{round_number}.{split}"
    spec.pop("optimization", None)
    combos = []
    original_components = {kind: {entry["id"]: entry for entry in spec["components"][kind]} for kind in COMPONENT_KINDS}
    candidate_components = {kind: [] for kind in COMPONENT_KINDS}
    for candidate in candidates:
        combo = copy.deepcopy(baseline_combo)
        combo["id"] = candidate
        for kind, members in list(combo["members"].items()):
            replaced = []
            for component_id in members:
                key = f"{kind}/{component_id}"
                if key not in state["candidate_sources"][candidate]:
                    replaced.append(component_id)
                    continue
                candidate_id = f"{component_id}@{candidate}"
                component = copy.deepcopy(original_components[kind][component_id])
                component["id"] = candidate_id
                component["source"] = state["candidate_sources"][candidate][key]
                candidate_components[kind].append(component)
                replaced.append(candidate_id)
            combo["members"][kind] = replaced
        combos.append(combo)
    spec["combinations"] = combos
    for kind in COMPONENT_KINDS:
        mutable_ids = {entry["id"] for entry in config["mutable"] if entry["kind"] == kind}
        spec["components"][kind] = [entry for entry in spec["components"][kind] if entry["id"] not in mutable_ids]
        spec["components"][kind].extend(candidate_components[kind])
    spec["selection"] = {**spec.get("selection", {}), "combinations": candidates, "groups": config["splits"][split]}
    spec.setdefault("runtime", {})["candidate_source_roots"] = [
        str((Path(state["state_root"]) / "candidates" / candidate).resolve()) for candidate in candidates
    ]
    if len(candidates) == 1:
        sources = state["candidate_sources"][candidates[0]]
        for item in spec["evaluations"]["items"]:
            item_runtime = item.get("runtime", {})
            if item_runtime.get("adapter") != "command" or "argv" not in item_runtime:
                continue
            rewritten = []
            for argument in item_runtime["argv"]:
                if argument.startswith("{component_source:") and argument.endswith("}"):
                    key = argument[len("{component_source:"):-1]
                    if key not in sources:
                        raise EvoError(f"command component placeholder is not mutable in candidate: {key}")
                    argument = sources[key]
                rewritten.append(argument)
            item_runtime["argv"] = rewritten
    return spec


def _submit_evaluation(store: Store, state: dict[str, Any], candidates: list[str], split: str, round_number: int) -> int:
    spec = _evaluation_spec(state, candidates, split, round_number)
    directory = Path(state["state_root"]) / "optimizations" / state["id"]
    candidate_key = "-vs-".join(candidate.removeprefix("candidate-") for candidate in candidates)
    path = directory / f"{split}-r{round_number}-{candidate_key}.json"
    runtime.immutable_json(path, spec)
    return runtime.submit(store, path, Path(state["frozen"]["project"]), Path(state["frozen"]["work"]))


def _study_usage(store: Store, study: int) -> tuple[int, bool]:
    jobs = store.jobs(study)
    return sum(job["usage"] or 0 for job in jobs), all(job["usage_complete"] for job in jobs)


def _study_ready(store: Store, study: int) -> tuple[bool, bool]:
    counts = store.status(study)["counts"]
    return bool(counts) and set(counts) <= {"completed"}, bool(counts.get("awaiting_human"))


def _grade_study(store: Store, state: dict[str, Any], study: int,
                 installed_codex_root: Path | None) -> tuple[bool, str | None]:
    from .grading import prepare_model_grading, run_model_grading
    selected = state["frozen"]["optimization"]["grading"]
    grading_configs = {entry["id"]: entry for entry in store.study(study)["spec"].get("grading", [])}
    reservation = sum(grading_configs[grading_id]["controller"]["token_budget"] for grading_id in selected)
    state["subject_tokens"] = sum(_study_usage(store, value)[0] for value in state["evaluation_studies"])
    state["grader_tokens"] = sum(_study_usage(store, value)[0] for value in state["grader_studies"])
    try:
        _require_budget(store, state, reservation, "selected grading")
    except EvoError as exc:
        return False, str(exc)
    for grading_id in selected:
        try:
            prepared = prepare_model_grading(store, study, grading_id)
            grader = int(prepared["grader_study"].removeprefix("s"))
            if grader not in state["grader_studies"]:
                state["grader_studies"].append(grader)
                _checkpoint(state)
            result = run_model_grading(store, grader, installed_codex_root)
            if not result["grader_usage"]["complete"] or set(result["status"]["counts"]) != {"completed"}:
                return False, f"grading {grading_id} is incomplete"
        except EvoError as exc:
            return False, f"grading {grading_id} failed: {exc}"
    states = [_study_usage(store, grader) for grader in state["grader_studies"]]
    state["grader_tokens"] = sum(value[0] for value in states)
    return True, None


def _comparison_artifacts(store: Store, studies: list[int]) -> dict[str, Any]:
    from .grading import study_artifacts_with_model_grades
    rows = []
    for study in studies:
        rows.extend(study_artifacts_with_model_grades(store, study)["rows"])
    return {"schema": "agentbase-evo-artifacts/v1", "id": "optimization-comparison",
            "version": fingerprint(rows), "rows": rows}


def _metric_values(spec: dict[str, Any], scored: dict[str, Any], candidate: str, coordinate: dict[str, Any]) -> dict[str, float] | None:
    score = next((entry for entry in scored["scores"] if entry["id"] == coordinate["scoring"]), None)
    if score is None or "combination" not in score["group_by"] or "family" not in score["group_by"]:
        return None
    result: dict[str, float] = {}
    for group in score["groups"]:
        if group["dimensions"].get("combination") != candidate:
            continue
        family = group["dimensions"].get("family")
        metric = next((value for value in group["metrics"] if value["id"] == coordinate["metric"]), None)
        if not isinstance(family, str) or metric is None or metric["status"] != "computed" or not isinstance(metric["value"], (int, float)):
            return None
        result[family] = metric["value"]
    return result


def _promote(state: dict[str, Any], spec: dict[str, Any], artifacts: dict[str, Any], champion: str, challenger: str,
             *, usage_complete: bool) -> tuple[bool, str]:
    config = state["frozen"]["optimization"]
    promotion = config["promotion"]
    if promotion.get("require_complete_cost", True) and not usage_complete:
        return False, "cost evidence is incomplete; no saving can be claimed"
    scoring_ids = sorted({entry["scoring"] for entry in promotion["quality_metrics"] + promotion["objectives"]})
    items = {entry["id"]: entry for entry in spec["evaluations"]["items"]}
    scored_artifacts = copy.deepcopy(artifacts)
    for row in scored_artifacts["rows"]:
        item = row.get("dimensions", {}).get("item")
        if item in items:
            row["dimensions"]["family"] = items[item]["family"]
    scored = score_artifacts(spec, scored_artifacts, scoring_ids)
    tolerance = promotion.get("non_regression_tolerance", 0)
    required = set(promotion["required_families"])
    for coordinate in promotion["quality_metrics"]:
        old = _metric_values(spec, scored, champion, coordinate)
        new = _metric_values(spec, scored, challenger, coordinate)
        if old is None or new is None or set(old) != required or set(new) != required:
            return False, "quality metric is missing a complete combination/family grouping"
        direction = coordinate.get("direction", "max")
        for family in required:
            if direction == "max" and new[family] + tolerance < old[family]:
                return False, f"quality regressed for family {family}"
            if direction == "min" and new[family] - tolerance > old[family]:
                return False, f"quality regressed for family {family}"
    improved = False
    for coordinate in promotion["objectives"]:
        old = _metric_values(spec, scored, champion, coordinate)
        new = _metric_values(spec, scored, challenger, coordinate)
        if old is None or new is None or set(old) != required or set(new) != required:
            return False, "objective is missing a complete combination/family grouping"
        direction = coordinate.get("direction", "max")
        if any((new[family] > old[family] if direction == "max" else new[family] < old[family]) for family in required):
            improved = True
        if any((new[family] < old[family] if direction == "max" else new[family] > old[family]) for family in required):
            return False, "objective is worse for a required family"
    return improved, "improved" if improved else "no objective improvement"


def _final_accept(store: Store, state: dict[str, Any], study: int) -> dict[str, Any]:
    config = state["frozen"]["optimization"]
    acceptance = config.get("final_acceptance")
    if acceptance is None:
        return {"status": "observed", "reason": "final evidence collected without a declared acceptance threshold"}
    thresholds = acceptance["thresholds"]
    artifacts = _comparison_artifacts(store, [study])
    spec = store.study(study)["spec"]
    items = {entry["id"]: entry for entry in spec["evaluations"]["items"]}
    for row in artifacts["rows"]:
        item = row.get("dimensions", {}).get("item")
        if item in items:
            row["dimensions"]["family"] = items[item]["family"]
    scoring_ids = sorted({entry["scoring"] for entry in thresholds})
    scored = score_artifacts(spec, artifacts, scoring_ids or None)
    final_families = {items[item]["family"] for group in spec["evaluations"]["groups"]
                      if group["id"] in config["splits"]["final"] for item in group["items"]}
    for coordinate in thresholds:
        values = _metric_values(spec, scored, state["champion"], coordinate)
        if values is None or set(values) != final_families:
            return {"status": "rejected", "reason": "final quality metric is missing a complete combination/family grouping"}
        for family, value in values.items():
            if "minimum" in coordinate and value < coordinate["minimum"]:
                return {"status": "rejected", "reason": f"final quality is below threshold for family {family}"}
            if "maximum" in coordinate and value > coordinate["maximum"]:
                return {"status": "rejected", "reason": f"final quality is above threshold for family {family}"}
    return {"status": "accepted", "reason": "all declared final thresholds passed"}


def _settle_selection(store: Store, state: dict[str, Any], studies: list[int], challenger: str, number: int,
                      installed_codex_root: Path | None) -> None:
    if state["round"] >= number:
        return
    config = state["frozen"]["optimization"]
    states = [_study_ready(store, study) for study in studies]
    if any(awaiting for _ready, awaiting in states):
        state["state"] = "awaiting_human"
        state["awaiting"] = {"studies": studies, "split": "selection", "candidate": challenger}
        state["pending"] = {"stage": "selection", "studies": studies, "challenger": challenger, "round": number}
        return
    ready = all(value[0] for value in states)
    if ready:
        for study in studies:
            graded, grading_error = _grade_study(store, state, study, installed_codex_root)
            if not graded:
                ready = False
                break
    else:
        grading_error = None
    usage_states = [_study_usage(store, value) for value in state["evaluation_studies"]]
    grader_usage = [_study_usage(store, value) for value in state["grader_studies"]]
    state["subject_tokens"] = sum(value[0] for value in usage_states)
    state["grader_tokens"] = sum(value[0] for value in grader_usage)
    if state["controller_tokens"] + state["subject_tokens"] + state["grader_tokens"] > config["budget"]["max_total_tokens"]:
        state["state"], state["stop_reason"] = "stopped", "total token budget exhausted"
        return
    if not ready:
        promote, reason = False, grading_error or "selection execution failed or remained unscored"
    else:
        selection_spec = _evaluation_spec(state, [state["champion"], challenger], "selection", number)
        promote, reason = _promote(state, selection_spec, _comparison_artifacts(store, studies), state["champion"], challenger,
                                   usage_complete=all(value[1] for value in [*usage_states, *grader_usage]))
    if promote:
        state["champion"], state["no_improvement"] = challenger, 0
    else:
        state["no_improvement"] += 1
    state["feedback"] = [{"round": number, "candidate": challenger, "promoted": promote, "reason": reason}]
    state["round"] = number
    state["pending"] = None
    state["state"] = "ready"
    if state["no_improvement"] >= config["rounds"]["patience"]:
        state["state"], state["stop_reason"] = "stopped", "no-improvement patience reached"


def _fail_round(state: dict[str, Any], number: int, challenger: str, reason: str) -> None:
    if state["round"] >= number:
        return
    state["feedback"] = [{"round": number, "candidate": challenger, "result": reason}]
    state["round"] = number
    state["no_improvement"] += 1
    if state["no_improvement"] >= state["frozen"]["optimization"]["rounds"]["patience"]:
        state["state"], state["stop_reason"] = "stopped", "no-improvement patience reached"


def _persist(path: Path, state: dict[str, Any]) -> None:
    _atomic_json(path, {key: value for key, value in state.items() if key not in {"state_root", "state_path"}})


def _checkpoint(state: dict[str, Any]) -> None:
    path = state.get("state_path")
    if path:
        _persist(Path(path), state)


def _associated_studies(state: dict[str, Any]) -> list[int]:
    values = [*state["controller_studies"], *state["evaluation_studies"], *state["grader_studies"]]
    return list(dict.fromkeys(values))


def _usage_account(store: Store, state: dict[str, Any]) -> dict[str, Any]:
    known = reserved = 0
    complete = True
    for study in _associated_studies(state):
        for job in store.jobs(study):
            if job["usage_complete"] and job["usage"] is not None:
                known += job["usage"]
            elif job["state"] in {"queued", "preparing", "running", "verifying"} and job["model_slots"] > 0:
                reserved += job["token_reservation"]
            elif job["model_slots"] > 0:
                complete = False
    return {"known": known, "reserved": reserved, "complete": complete}


def _planned_reservation(spec: dict[str, Any]) -> int:
    from .selection import build_plan
    items = {item["id"]: item for item in spec["evaluations"]["items"]}
    total = 0
    for job in build_plan(spec)["jobs"]:
        selected = {**spec.get("runtime", {}), **items[job["item"]].get("runtime", {})}
        if selected.get("adapter") == "codex":
            total += positive(selected.get("token_reservation", 100_000), "token_reservation")
    return total


def _require_budget(store: Store, state: dict[str, Any], reservation: int, label: str) -> None:
    account = _usage_account(store, state)
    if not account["complete"]:
        raise EvoError(f"cannot dispatch {label}; associated usage is unknown")
    maximum = state["frozen"]["optimization"]["budget"]["max_total_tokens"]
    if account["known"] + account["reserved"] + reservation > maximum:
        raise EvoError(f"cannot dispatch {label}; total token budget would be exceeded")


def run_optimization(store: Store, reference: str, installed_codex_root: Path | None = None) -> dict[str, Any]:
    path = _resolve(store, reference)
    try:
        with CaseLock(store.root, f"evo-optimization-{path.stem}"):
            state = _read(path)
            state["state_root"] = str(store.root)
            state["state_path"] = str(path)
            state.setdefault("round_records", {})
            config = state["frozen"]["optimization"]
            if state["state"] in ("completed", "stopped"):
                return _public(state)
            if state.get("awaiting"):
                awaiting_studies = state["awaiting"].get("studies", [state["awaiting"].get("study")])
                awaiting_states = [_study_ready(store, study) for study in awaiting_studies]
                if any(awaiting or not ready for ready, awaiting in awaiting_states):
                    return _public(state)
                state["awaiting"] = None
                state["state"] = "ready"
                state["pending"] = None
                _checkpoint(state)
            while state["state"] == "ready" and state["round"] < config["rounds"]["max"]:
                state["subject_tokens"] = sum(_study_usage(store, study)[0] for study in state["evaluation_studies"])
                state["grader_tokens"] = sum(_study_usage(store, study)[0] for study in state["grader_studies"])
                total = state["controller_tokens"] + state["subject_tokens"] + state["grader_tokens"]
                reservation = config["controller"].get("token_reservation", config["budget"]["max_controller_tokens"])
                number = state["round"] + 1
                record = state["round_records"].setdefault(str(number), {"round": number})
                if "controller_study" not in record:
                    try:
                        _require_budget(store, state, reservation, "controller")
                    except EvoError as exc:
                        state["state"], state["stop_reason"] = "stopped", str(exc)
                        _checkpoint(state)
                        break
                    if state["controller_tokens"] + reservation > config["budget"]["max_controller_tokens"]:
                        state["state"], state["stop_reason"] = "stopped", "controller token budget would be exceeded"
                        _checkpoint(state)
                        break
                    controller_spec = _controller_spec(state, number)
                    controller_path = store.root / "optimizations" / state["id"] / f"controller-r{number}.json"
                    runtime.immutable_json(controller_path, controller_spec)
                    controller_study = runtime.submit(store, controller_path, Path(state["frozen"]["project"]), Path(state["frozen"]["work"]))
                    record["controller_study"] = controller_study
                    if controller_study not in state["controller_studies"]:
                        state["controller_studies"].append(controller_study)
                    _checkpoint(state)
                controller_study = record["controller_study"]
                runtime.run(store, study=controller_study, installed_codex_root=installed_codex_root)
                _usage, complete = _study_usage(store, controller_study)
                state["controller_tokens"] = sum(_study_usage(store, study)[0] for study in state["controller_studies"])
                if not complete:
                    state["state"], state["stop_reason"] = "stopped", "controller usage is incomplete"
                    _checkpoint(state)
                    break
                if "proposal" not in record:
                    proposal = _proposal_from_study(store, controller_study)
                    hypothesis_key = fingerprint(proposal["hypothesis"].strip().casefold())
                    state["hypotheses"][hypothesis_key] = state["hypotheses"].get(hypothesis_key, 0) + 1
                    record["proposal"] = proposal
                    record["hypothesis_key"] = hypothesis_key
                    if state["hypotheses"][hypothesis_key] > config["rounds"]["duplicate_hypothesis_limit"]:
                        state["state"], state["stop_reason"] = "stopped", "duplicate hypothesis limit reached"
                    _checkpoint(state)
                    if state["state"] == "stopped":
                        break
                proposal = record["proposal"]
                if "challenger" not in record:
                    record["challenger"] = _apply(state, proposal)
                    _checkpoint(state)
                else:
                    _apply(state, proposal)
                challenger = record["challenger"]
                if config["splits"]["development"]:
                    if "development_study" not in record:
                        development_spec = _evaluation_spec(state, [challenger], "development", number)
                        try:
                            _require_budget(store, state, _planned_reservation(development_spec), "development subject")
                        except EvoError as exc:
                            state["state"], state["stop_reason"] = "stopped", str(exc)
                            _checkpoint(state)
                            break
                        development = _submit_evaluation(store, state, [challenger], "development", number)
                        record["development_study"] = development
                        if development not in state["evaluation_studies"]:
                            state["evaluation_studies"].append(development)
                        _checkpoint(state)
                    development = record["development_study"]
                    runtime.run(store, study=development, installed_codex_root=installed_codex_root)
                    ready, awaiting = _study_ready(store, development)
                    if awaiting:
                        state["state"], state["awaiting"] = "awaiting_human", {"study": development, "split": "development", "candidate": challenger}
                        state["pending"] = {"stage": "development", "study": development, "challenger": challenger, "round": number}
                        _checkpoint(state)
                        break
                    if not ready:
                        _fail_round(state, number, challenger, "development failed")
                        _checkpoint(state)
                        continue
                    graded, grading_error = _grade_study(store, state, development, installed_codex_root)
                    if not graded:
                        _fail_round(state, number, challenger, grading_error or "development grading failed")
                        _checkpoint(state)
                        continue
                selection = record.setdefault("selection_studies", [])
                for candidate in (state["champion"], challenger):
                    position = 0 if candidate == state["champion"] else 1
                    if len(selection) > position:
                        continue
                    selection_spec = _evaluation_spec(state, [candidate], "selection", number)
                    try:
                        _require_budget(store, state, _planned_reservation(selection_spec), f"selection subject {position + 1}")
                    except EvoError as exc:
                        state["state"], state["stop_reason"] = "stopped", str(exc)
                        _checkpoint(state)
                        break
                    study = _submit_evaluation(store, state, [candidate], "selection", number)
                    selection.append(study)
                    if study not in state["evaluation_studies"]:
                        state["evaluation_studies"].append(study)
                    _checkpoint(state)
                if state["state"] == "stopped":
                    break
                for study in selection:
                    runtime.run(store, study=study, installed_codex_root=installed_codex_root)
                _settle_selection(store, state, selection, challenger, number, installed_codex_root)
                record["settled"] = state["round"] >= number
                _checkpoint(state)
                if state.get("awaiting"):
                    break
            if state["state"] == "ready" and state["round"] >= config["rounds"]["max"]:
                if state["final_study"] is None:
                    final_spec = _evaluation_spec(state, [state["champion"]], "final", state["round"] + 1)
                    try:
                        _require_budget(store, state, _planned_reservation(final_spec), "final subject")
                    except EvoError as exc:
                        state["state"], state["stop_reason"] = "stopped", str(exc)
                        _checkpoint(state)
                        return _public(state)
                    final = _submit_evaluation(store, state, [state["champion"]], "final", state["round"] + 1)
                    state["evaluation_studies"].append(final)
                    state["final_study"] = final
                    _checkpoint(state)
                final = state["final_study"]
                runtime.run(store, study=final, installed_codex_root=installed_codex_root)
                ready, awaiting = _study_ready(store, final)
                if awaiting:
                    state["state"], state["awaiting"] = "awaiting_human", {"study": final, "split": "final", "candidate": state["champion"]}
                    state["pending"] = {"stage": "final", "study": final}
                elif ready:
                    graded, grading_error = _grade_study(store, state, final, installed_codex_root)
                    if graded:
                        state["final_acceptance"] = _final_accept(store, state, final)
                        state["state"], state["stop_reason"] = "completed", None
                    else:
                        state["state"], state["stop_reason"] = "stopped", grading_error
                elif not ready:
                    state["state"], state["stop_reason"] = "stopped", "final acceptance execution failed"
            _persist(path, state)
            return _public(state)
    except EvaluationError as exc:
        raise EvoError(str(exc)) from exc


def resume(store: Store, reference: str, installed_codex_root: Path | None = None) -> dict[str, Any]:
    return run_optimization(store, reference, installed_codex_root)


def export(store: Store, reference: str) -> dict[str, Any]:
    state = _read(_resolve(store, reference))
    champion_root = store.root / "candidates" / state["champion"]
    manifest = _read(champion_root / "candidate.json") if (champion_root / "candidate.json").is_file() else None
    return {"schema": EXPORT_SCHEMA, "optimization": state["id"], "state": state["state"],
            "baseline": state["baseline"], "champion": state["champion"], "candidate_root": str(champion_root),
            "candidate_manifest": manifest, "controller_tokens": state["controller_tokens"],
            "subject_tokens": state["subject_tokens"], "grader_tokens": state.get("grader_tokens", 0),
            "final_study": state["final_study"], "final_acceptance": state.get("final_acceptance"),
            "note": "Export is evidence only; it does not deploy, release, or modify the source project."}
