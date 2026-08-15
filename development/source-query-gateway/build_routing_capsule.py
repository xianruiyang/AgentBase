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
    bundle = {
        "global-route": (ROOT / "candidate-global-route.txt").read_text(encoding="utf-8").strip(),
        "SKILL.md": (skill / "SKILL.md").read_text(encoding="utf-8"),
        "references/rg-fd.md": (skill / "references" / "rg-fd.md").read_text(encoding="utf-8"),
        "references/ast.md": (skill / "references" / "ast.md").read_text(encoding="utf-8"),
    }
    cases = json.loads((ROOT / "routing-cases.json").read_text(encoding="utf-8"))["cases"]
    payload = {
        "schema": "agentbase.source-query-routing-capsule/v1",
        "isolation": "detached-capsule",
        "instructions": [
            "Only read this capsule and write the requested result; do not access the repository, conversation, other capsules, results, or hidden expectations.",
            "For every case, infer the minimum route and reference that the candidate rules require.",
            "Use only the exact route and reference labels enumerated by output_schema; do not replace labels with prose.",
            "Also report whether authorization, preview, or same-snapshot handling is required when applicable.",
            "Do not execute case requests.",
        ],
        "candidate": bundle,
        "cases": [{"id": case["id"], "prompt": case["prompt"]} for case in cases],
        "output_schema": {
            "schema": "agentbase.source-query-routing-result/v1",
            "isolation_statement": "string",
            "cases": [{
                "id": "string",
                "route": {"enum": ["native_fast", "sgy_rgfd", "sgy_ast", "lsp", "no_query", "no_skill"]},
                "reference": {"enum": ["none", "rg-fd", "ast"]},
                "authorization_required": "boolean, default false",
                "preview_required": "boolean, default false",
                "same_snapshot_required": "boolean, default false",
            }],
        },
    }
    payload["candidate_bundle_sha256"] = canonical_sha(bundle)
    payload["evaluation_input_sha256"] = canonical_sha({"cases": payload["cases"], "instructions": payload["instructions"]})
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(args.output.resolve()), "cases": len(cases), "capsule_sha256": canonical_sha(payload)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
