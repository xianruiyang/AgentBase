from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCHEMA = "agentbase.source-query-corpus/v1"
REBUILDABLE_PARTS = {".git", ".codex", "dist", "target", "node_modules", "__pycache__"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_sources(oracle: dict) -> list[dict]:
    if "source" in oracle:
        return [oracle["source"]]
    return list(oracle.get("sources", []))


def validate_case_contract(case: dict, failures: list[str]) -> None:
    case_id = case.get("id", "<unknown>")
    if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
        failures.append(f"{case_id}: prompt must be a non-empty string")
    answer_contract = case.get("answer_contract")
    required = answer_contract.get("required") if isinstance(answer_contract, dict) else None
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, str) and item.strip() for item in required)
    ):
        failures.append(f"{case_id}: answer_contract.required must contain non-empty strings")
    oracle = case.get("oracle")
    if not isinstance(oracle, dict) or not isinstance(oracle.get("kind"), str) or not oracle["kind"]:
        failures.append(f"{case_id}: oracle.kind must be a non-empty string")
        return
    sources = oracle_sources(oracle)
    if oracle["kind"] != "unique-path" and not sources:
        failures.append(f"{case_id}: oracle must declare source evidence")
    if "semantic_boundary" in oracle:
        boundary = oracle["semantic_boundary"]
        valid_boundary = (isinstance(boundary, str) and bool(boundary.strip())) or (
            isinstance(boundary, list)
            and bool(boundary)
            and all(isinstance(item, str) and item.strip() for item in boundary)
        )
        if not valid_boundary:
            failures.append(f"{case_id}: oracle.semantic_boundary must contain non-empty strings")


def validate(
    corpus_path: Path,
    workspaces: dict[str, Path],
    case_ids: set[str] | None = None,
) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if corpus.get("schema") != SCHEMA:
        failures.append(f"schema must equal {SCHEMA}")
    ids: set[str] = set()
    for case in corpus.get("cases", []):
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            failures.append(f"invalid or duplicate case id: {case_id!r}")
            continue
        ids.add(case_id)
    if case_ids is not None:
        unknown = sorted(case_ids - ids)
        if unknown:
            failures.append(f"unknown case ids: {unknown}")
    validated_case_count = 0
    for case in corpus.get("cases", []):
        case_id = case.get("id")
        if not isinstance(case_id, str) or case_id not in ids:
            continue
        if case_ids is not None and case_id not in case_ids:
            continue
        validated_case_count += 1
        validate_case_contract(case, failures)
        role = case.get("workspace_role")
        root = workspaces.get(role)
        if root is None:
            failures.append(f"{case_id}: missing workspace role {role!r}")
            continue
        oracle = case.get("oracle", {})
        for source in oracle_sources(oracle):
            if (
                not isinstance(source, dict)
                or not isinstance(source.get("path"), str)
                or not isinstance(source.get("sha256"), str)
            ):
                failures.append(f"{case_id}: invalid oracle source")
                continue
            candidate = (root / source["path"]).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                failures.append(f"{case_id}: source escapes workspace")
                continue
            if not candidate.is_file():
                failures.append(f"{case_id}: missing {source['path']}")
            elif digest(candidate) != source["sha256"]:
                failures.append(f"{case_id}: stale source {source['path']}")
        if oracle.get("kind") == "unique-path":
            matches = [
                path
                for path in root.rglob(Path(oracle["path"]).name)
                if path.is_file() and not REBUILDABLE_PARTS.intersection(path.relative_to(root).parts)
            ]
            relative = {path.relative_to(root).as_posix() for path in matches}
            if relative != {oracle["path"]}:
                failures.append(f"{case_id}: path is not unique: {sorted(relative)}")
            elif digest(root / oracle["path"]) != oracle["sha256"]:
                failures.append(f"{case_id}: stale source {oracle['path']}")
    return {
        "ok": not failures,
        "case_count": len(ids),
        "validated_case_count": validated_case_count,
        "failures": failures,
    }


def parse_workspaces(values: list[str]) -> dict[str, Path]:
    workspaces: dict[str, Path] = {}
    for value in values:
        role, separator, raw_path = value.partition("=")
        if not separator or not role or not raw_path:
            raise ValueError(f"workspace must use ROLE=PATH: {value!r}")
        if role in workspaces:
            raise ValueError(f"duplicate workspace role: {role!r}")
        workspaces[role] = Path(raw_path).resolve()
    return workspaces


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--agentbase", type=Path)
    parser.add_argument("--large-cpp", type=Path)
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="workspace role and root; repeat for every selected role",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="validate only this case; repeat to validate a subset",
    )
    args = parser.parse_args()
    try:
        workspaces = parse_workspaces(args.workspace)
        for role, root in (("agentbase", args.agentbase), ("large-cpp", args.large_cpp)):
            if root is None:
                continue
            if role in workspaces:
                raise ValueError(f"duplicate workspace role: {role!r}")
            workspaces[role] = root.resolve()
    except ValueError as error:
        parser.error(str(error))
    if not workspaces:
        parser.error("at least one --workspace or legacy workspace option is required")
    selected = set(args.case_id) if args.case_id is not None else None
    result = validate(args.corpus, workspaces, selected)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
