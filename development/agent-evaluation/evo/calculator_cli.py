"""CLI integration for explicitly authorized fixed local calculators."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .calculator import calculate
from .spec import EvoError


ACTIONS = {"calculate"}


def add_commands(commands) -> None:
    parser = commands.add_parser("calculate", help="run a fingerprinted local calculator over existing artifacts")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-local-code", action="store_true")


def handle(args) -> dict:
    result = calculate(manifest_path=args.manifest, spec_path=args.spec, artifacts_path=args.artifacts,
                       output_path=args.output, allow_local_code=args.allow_local_code)
    return {"schema": result["schema"], "id": result["id"], "version": result["version"],
            "rows": len(result["rows"]), "output": str(args.output.resolve()), "calculator": result["calculator"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval evo")
    commands = parser.add_subparsers(dest="action", required=True)
    add_commands(commands)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(handle(args), ensure_ascii=False, indent=2))
        return 0
    except EvoError as exc:
        print(f"evo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
