from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def canonical_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    skill = ROOT / "candidate-skill" / "source-query"
    skill_text = (skill / "SKILL.md").read_text(encoding="utf-8")
    skill_parts = skill_text.split("---", 2)
    if len(skill_parts) != 3:
        raise SystemExit("candidate SKILL.md frontmatter is unreadable")
    bundle = {
        "initial_selection": {
            "global-route": (ROOT / "candidate-global-route.txt").read_text(encoding="utf-8").strip(),
            "source-query-frontmatter": f"---{skill_parts[1]}---\n",
        },
        "after_source_query_selected": {
            "SKILL.md-body": skill_parts[2].lstrip(),
            "references/rg-fd.md": (skill / "references" / "rg-fd.md").read_text(encoding="utf-8"),
            "references/ast.md": (skill / "references" / "ast.md").read_text(encoding="utf-8"),
        },
    }
    cases = json.loads((ROOT / "routing-cases.json").read_text(encoding="utf-8"))["cases"]
    payload = {
        "schema": "agentbase.source-query-routing-capsule/v1",
        "isolation": "detached-capsule",
        "instructions": [
            "Only read this capsule and write the requested result; do not access the repository, conversation, other capsules, results, or hidden expectations.",
            "For every case, first infer the minimum route and whether source-query is selected using only candidate.initial_selection.",
            "Only when that first decision selects source-query may you consult candidate.after_source_query_selected to choose a reference and evaluate advanced behavior; otherwise reference must be none and selected-only content must not influence the route.",
            "Use only the exact route and reference labels enumerated by output_schema; do not replace labels with prose.",
            "Also report whether authorization, preview, or same-snapshot handling is required when applicable.",
            "Do not execute case requests.",
        ],
        "candidate": bundle,
        "cases": [{"id": case["id"], "prompt": case["prompt"]} for case in cases],
        "output_schema": {
            "schema": "agentbase.source-query-routing-result/v1",
            "isolation_statement": "string",
            "cases": "array with exactly one result for every input case",
            "case_shape": {
                "id": "string",
                "route": "string selected directly from allowed_values.route",
                "reference": "string selected directly from allowed_values.reference",
                "authorization_required": "boolean, default false",
                "preview_required": "boolean, default false",
                "same_snapshot_required": "boolean, default false",
            },
            "allowed_values": {
                "route": ["native_fast", "sgy_rgfd", "sgy_ast", "lsp", "no_query", "no_skill"],
                "reference": ["none", "rg-fd", "ast"],
            },
            "label_definitions": {
                "route": {
                    "native_fast": "bounded native fd/rg or direct read",
                    "sgy_rgfd": "sgy rg/fd, whether selected by the global route or an advanced skill protocol",
                    "sgy_ast": "sgy AST protocol",
                    "lsp": "true symbol-identity tooling",
                    "no_query": "existing evidence is already sufficient",
                    "no_skill": "request is outside source querying",
                },
                "reference": {
                    "none": "no optional source-query reference must be loaded; use this when the global route alone governs the action",
                    "rg-fd": "the advanced rg/fd protocol reference must be loaded",
                    "ast": "the AST protocol reference must be loaded",
                },
            },
            "example_case": {
                "id": "case-id",
                "route": "native_fast",
                "reference": "none",
                "authorization_required": False,
                "preview_required": False,
                "same_snapshot_required": False,
            },
        },
    }
    payload["candidate_bundle_sha256"] = canonical_sha(bundle)
    payload["evaluation_input_sha256"] = canonical_sha({"cases": payload["cases"], "instructions": payload["instructions"]})
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(args.output.resolve()), "cases": len(cases), "capsule_sha256": canonical_sha(payload)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
