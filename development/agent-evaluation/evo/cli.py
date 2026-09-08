from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .report import build_report
from .scoring import score_artifacts
from .selection import build_plan
from .spec import EvoError, load_artifacts, load_spec, read_json


def command_modules():
    from . import calculator_cli, evaluate_cli, grading_cli, optimization_cli, review_cli, runtime_cli
    return (runtime_cli, evaluate_cli, review_cli, calculator_cli, grading_cli, optimization_cli)


def _write(value: str, output: Path | None) -> None:
    if output is None:
        print(value)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(value + ("" if value.endswith("\n") else "\n"), encoding="utf-8")


def _json(value: dict[str, Any], output: Path | None) -> None:
    _write(json.dumps(value, indent=2, ensure_ascii=False), output)


def _emit(value: dict[str, Any], args, *, already_written: bool = False) -> None:
    output = None if already_written else getattr(args, "output", None)
    if output is not None or args.view == "machine":
        _json(value, output)
    else:
        from .view import render_model
        print(render_model(value, limit=args.model_token_budget))


def _ensure_distinct_output(output: Path | None, inputs: list[Path]) -> None:
    if output is None:
        return
    target = os.path.normcase(str(output.resolve()))
    if any(target == os.path.normcase(str(path.resolve())) for path in inputs):
        raise EvoError("output path must not overwrite an input")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="agent-eval evo", description="AgentBase Evo local evaluation and scoring")
    commands = result.add_subparsers(dest="action", required=True)
    for module in command_modules():
        module.add_commands(commands)
    validate = commands.add_parser("validate", help="validate a versioned Evo specification")
    validate.add_argument("--spec", type=Path, required=True)
    plan = commands.add_parser("plan", help="build a read-only de-duplicated evaluation plan")
    plan.add_argument("--spec", type=Path, required=True)
    plan.add_argument("--output", type=Path)
    score = commands.add_parser("score", help="score existing artifacts without running a model")
    score.add_argument("--spec", type=Path, required=True)
    score.add_argument("--artifacts", type=Path, required=True)
    score.add_argument("--scoring", action="append", dest="scoring_ids")
    score.add_argument("--output", type=Path)
    report = commands.add_parser("report", help="render a report from saved offline score results")
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--output", type=Path)
    for command in commands.choices.values():
        command.add_argument("--view", choices=("model", "machine"), default="model")
        command.add_argument("--model-token-budget", type=int, default=1200)
        if "--output" not in command._option_string_actions and command.prog.split()[-1] != "watch":
            command.add_argument("--output", type=Path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = getattr(args, "output", None)
        inputs = [getattr(args, name) for name in ("spec", "artifacts", "manifest", "submission", "results")
                  if isinstance(getattr(args, name, None), Path)]
        _ensure_distinct_output(output, inputs)
        if output and getattr(args, "state_root", None) and output.resolve().is_relative_to(args.state_root.resolve()):
            raise EvoError("CLI output must stay outside managed state; choose a separate report directory")
        for module in command_modules():
            if args.action in module.ACTIONS:
                value = module.handle(args)
                if value is not None:
                    # These owners already write their explicit output artifact.
                    _emit(value, args, already_written=args.action in {"calculate", "review-export", "review-merge", "grade-merge"})
                return 0
        if args.action == "validate":
            spec = load_spec(args.spec)
            _emit({"valid": True, "schema": spec["schema"], "id": spec["id"], "version": spec["version"]}, args)
        elif args.action == "plan":
            _ensure_distinct_output(args.output, [args.spec])
            _emit(build_plan(load_spec(args.spec)), args)
        elif args.action == "score":
            _ensure_distinct_output(args.output, [args.spec, args.artifacts])
            _emit(score_artifacts(load_spec(args.spec), load_artifacts(args.artifacts), args.scoring_ids), args)
        elif args.action == "report":
            _ensure_distinct_output(args.output, [args.results])
            _write(build_report(read_json(args.results)), args.output)
        return 0
    except EvoError as exc:
        print(f"evo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
