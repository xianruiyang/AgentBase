from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "version.txt": ["--version"],
    "help.txt": ["--help"],
    "exec-help.txt": ["exec", "--help"],
    "defaults-help.txt": ["defaults", "--help"],
    "cache-help.txt": ["cache", "--help"],
    "process-help.txt": ["process", "--help"],
    "doctor-help.txt": ["doctor", "--help"],
    "schema.yaml": ["schema"],
    "capabilities.yaml": ["capabilities"],
}


def normalized_text(data: bytes) -> str:
    return data.decode("utf-8").replace("\r\n", "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sgy", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("the sgy AST baseline is maintained only on Windows")
    executable = args.sgy.resolve()
    if not executable.is_file():
        raise SystemExit(f"sgy executable does not exist: {executable}")
    differences = []
    for filename, command in COMMANDS.items():
        completed = subprocess.run(
            [str(executable), *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        expected = normalized_text((ROOT / filename).read_bytes())
        actual = normalized_text(completed.stdout)
        if completed.returncode != 0 or completed.stderr or actual != expected:
            differences.append(
                {
                    "file": filename,
                    "argv": command,
                    "exitCode": completed.returncode,
                    "stderr": completed.stderr.decode("utf-8", errors="replace"),
                    "stdoutMatches": actual == expected,
                }
            )
    if differences:
        import json

        print(json.dumps({"ok": False, "differences": differences}, ensure_ascii=False, indent=2))
        return 1
    print('{"ok":true,"baseline":"sgy-0.1.2-ast"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
