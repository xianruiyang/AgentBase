"""One-shot evaluation consumes the same queue and scoring owners as separate CLI steps."""
from __future__ import annotations

from pathlib import Path

from .runtime import run, submit
from .runtime_review import prepare_study_reviews
from .grading import study_artifacts_with_model_grades
from .scoring import score_artifacts
from .store import Store

ACTIONS = {"evaluate"}


def add_commands(commands) -> None:
    parser = commands.add_parser("evaluate", help="submit, execute and score using the persistent queue")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--installed-codex-root", type=Path)


def handle(args) -> dict:
    store = Store(args.state_root)
    identity = submit(store, args.spec, args.project_root, args.work_root)
    status = run(store, study=identity, installed_codex_root=args.installed_codex_root)
    reviews = prepare_study_reviews(store, identity)
    return {
        "schema": "agentbase-evo-evaluation/v1",
        "study": f"s{identity}",
        "status": status,
        "reviews": reviews,
        "scores": score_artifacts(store.study(identity)["spec"], study_artifacts_with_model_grades(store, identity)),
    }
