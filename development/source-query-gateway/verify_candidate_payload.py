from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "candidate-skill" / "source-query"
FORBIDDEN_PARTS = {
    "bin",
    "script",
    "scripts",
    "test",
    "tests",
    "fixture",
    "fixtures",
    "benchmark",
    "benchmarks",
    "corpus",
    "result",
    "results",
    "audit",
    "audits",
    "provenance",
}


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("candidate payload is maintained only on Windows")
    expected = {
        "SKILL.md",
        "agents/openai.yaml",
        "references/ast.md",
        "references/lsp.md",
        "references/rg-fd.md",
    }
    actual = {
        path.relative_to(PAYLOAD).as_posix()
        for path in PAYLOAD.rglob("*")
        if path.is_file()
    }
    errors: list[str] = []
    if actual != expected:
        errors.append(
            "payload file set differs: "
            + json.dumps(
                {"missing": sorted(expected - actual), "extra": sorted(actual - expected)}
            )
        )
    for relative in actual:
        path = PAYLOAD / relative
        if any(part.lower() in FORBIDDEN_PARTS for part in Path(relative).parts):
            errors.append(f"runtime or development asset leaked into payload: {relative}")
        if path.suffix.lower() in {".exe", ".dll", ".pdb", ".zip"}:
            errors.append(f"binary artifact leaked into payload: {relative}")
    combined = "\n".join(
        (PAYLOAD / relative).read_text(encoding="utf-8")
        for relative in sorted(actual)
        if (PAYLOAD / relative).suffix.lower() in {".md", ".yaml", ".yml"}
    )
    if "<skill_dir>\\scripts" in combined or "sgy.exe" in combined:
        errors.append("candidate still references a private or legacy runtime")
    if "srcq.exe" not in combined or "PATH" not in combined:
        errors.append("candidate does not declare the PATH-owned srcq runtime")
    result = {"ok": not errors, "payloadFiles": len(actual), "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
