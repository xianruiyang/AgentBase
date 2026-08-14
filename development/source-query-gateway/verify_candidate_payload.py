from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "candidate-skill" / "source-query"
FORBIDDEN_PARTS = {
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
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("candidate payload is maintained only on Windows")
    manifest_path = PAYLOAD / "scripts" / "provenance" / "release-record.json"
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = record["targets"][0]
    binary = PAYLOAD / "scripts" / target["binary"]["path"]
    errors: list[str] = []
    if binary.stat().st_size != target["binary"]["bytes"]:
        errors.append("binary byte length differs from release record")
    if sha256(binary) != target["binary"]["sha256"]:
        errors.append("binary hash differs from release record")
    version = subprocess.run(
        [str(binary), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if version.returncode != 0 or version.stderr or version.stdout.strip() != "sgy 0.2.0":
        errors.append("binary version readback failed")
    for path in PAYLOAD.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PAYLOAD)
        if any(part.lower() in FORBIDDEN_PARTS for part in relative.parts):
            errors.append(f"development asset leaked into payload: {relative.as_posix()}")
    expected = {
        "SKILL.md",
        "references/ast.md",
        "references/rg-fd.md",
        "scripts/bin/windows-x86_64/sgy.exe",
        "scripts/runtime-manifest.yml",
        "scripts/provenance/release-record.json",
        "scripts/provenance/sgy-source-snapshot.json",
        "scripts/provenance/windows-x86_64.manifest.json",
        "scripts/legal/LICENSE",
        "scripts/legal/LICENSE-APACHE",
        "scripts/legal/LICENSE-MIT",
        "scripts/legal/NOTICE",
        "scripts/legal/THIRD_PARTY_LICENSES-windows-x86_64.txt",
        "scripts/legal/sbom-windows-x86_64.spdx.json",
    }
    actual = {
        path.relative_to(PAYLOAD).as_posix()
        for path in PAYLOAD.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        errors.append(
            "payload file set differs: "
            + json.dumps(
                {"missing": sorted(expected - actual), "extra": sorted(actual - expected)}
            )
        )
    result = {
        "ok": not errors,
        "payloadFiles": len(actual),
        "binarySha256": sha256(binary),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
