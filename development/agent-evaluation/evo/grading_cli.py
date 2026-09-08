from __future__ import annotations

from pathlib import Path

import json

from .grading import merge_model_grading_artifacts, prepare_artifact_grading, prepare_model_grading, run_model_grading
from .runtime_cli import study_id
from .spec import load_artifacts, load_spec
from .store import Store


ACTIONS = {"grade-start", "grade-run", "grade-merge"}


def add_commands(commands) -> None:
    start = commands.add_parser("grade-start", help="freeze inputs and enqueue an explicit model-grader study")
    start.add_argument("--state-root", type=Path, required=True)
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--study")
    source.add_argument("--spec", type=Path)
    start.add_argument("--artifacts", type=Path)
    start.add_argument("--project-root", type=Path)
    start.add_argument("--work-root", type=Path)
    start.add_argument("--grading", required=True)
    run = commands.add_parser("grade-run", help="explicitly run a prepared grader study")
    run.add_argument("--state-root", type=Path, required=True)
    run.add_argument("--study", required=True)
    run.add_argument("--installed-codex-root", type=Path)
    merge = commands.add_parser("grade-merge", help="write artifacts merged with one completed model grader")
    merge.add_argument("--state-root", type=Path, required=True)
    merge.add_argument("--study", required=True)
    merge.add_argument("--artifacts", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)


def handle(args):
    store = Store(args.state_root)
    if args.action == "grade-start":
        if args.study:
            if args.artifacts or args.project_root or args.work_root:
                from .spec import EvoError
                raise EvoError("--study cannot be combined with offline grading paths")
            return prepare_model_grading(store, study_id(args.study), args.grading)
        if args.artifacts is None or args.project_root is None or args.work_root is None:
            from .spec import EvoError
            raise EvoError("offline grade-start requires --spec, --artifacts, --project-root and --work-root")
        return prepare_artifact_grading(store, load_spec(args.spec), load_artifacts(args.artifacts), args.grading,
                                        args.project_root, args.work_root)
    study = study_id(args.study)
    if args.action == "grade-merge":
        if args.output.resolve() == args.artifacts.resolve():
            from .spec import EvoError
            raise EvoError("grade-merge output must not overwrite source artifacts")
        value = merge_model_grading_artifacts(load_artifacts(args.artifacts), store, study)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"output": str(args.output), "schema": value["schema"], "id": value["id"]}
    return run_model_grading(store, study, args.installed_codex_root)
