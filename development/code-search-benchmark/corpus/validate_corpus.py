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


def validate(corpus_path: Path, workspaces: dict[str, Path]) -> dict:
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
        role = case.get("workspace_role")
        root = workspaces.get(role)
        if root is None:
            failures.append(f"{case_id}: missing workspace role {role!r}")
            continue
        oracle = case.get("oracle", {})
        for source in oracle_sources(oracle):
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
    return {"ok": not failures, "case_count": len(ids), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--agentbase", type=Path, required=True)
    parser.add_argument("--large-cpp", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.corpus, {"agentbase": args.agentbase.resolve(), "large-cpp": args.large_cpp.resolve()})
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
