from __future__ import annotations

import argparse
from pathlib import Path
import re
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
    text = data.decode("utf-8").replace("\r\n", "\n")
    return "\n".join(line.rstrip(" \t") for line in text.split("\n"))


def project_top_level_ast_help(text: str) -> str:
    lines = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        if index == 0:
            lines.append("Token-safe YAML adapter for ast-grep\n")
            continue
        if re.match(r"^  (?:rg|fd|scc|query)\s", line):
            continue
        if line.startswith(("Text/file syntax:", "Source syntax:", "Explicit query controls:")):
            continue
        lines.append(line)
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srcq", required=True, type=Path)
    parser.add_argument(
        "--expected-version",
        help="allow only the release version line to differ from the frozen AST baseline",
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("the Source Query Gateway AST baseline is maintained only on Windows")
    executable = args.srcq.resolve()
    if not executable.is_file():
        raise SystemExit(f"srcq executable does not exist: {executable}")
    differences = []
    for filename, command in COMMANDS.items():
        completed = subprocess.run(
            [str(executable), *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        expected = normalized_text((ROOT / filename).read_bytes())
        expected = expected.replace("sgy.exe", "srcq.exe").replace(".sgy.yml", ".srcq.yml")
        expected = expected.replace("SGY_", "SRCQ_")
        expected = re.sub(r"(?<!_)\bsgy\b(?!\.)", "srcq", expected)
        if filename == "version.txt" and args.expected_version:
            expected = f"srcq {args.expected_version}\n"
        if filename == "capabilities.yaml" and args.expected_version:
            expected = re.sub(
                r'(?m)^(  "version": )"[^"]+"$',
                rf'\1"{args.expected_version}"',
                expected,
                count=1,
            )
        actual = normalized_text(completed.stdout)
        if filename == "help.txt":
            actual = project_top_level_ast_help(actual)
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
    version = args.expected_version or "0.1.2"
    print(f'{{"ok":true,"baseline":"sgy-0.1.2-ast","subject":"srcq","subjectVersion":"{version}"}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
