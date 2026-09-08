from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .review import export_review_package, import_review_assessments, merge_review_artifacts, review_completion
from .spec import EvoError, load_artifacts, load_spec, read_json


ACTIONS = {"review-export", "review-import", "review-status", "review-merge", "review-prepare", "review-sync"}


def add_commands(commands: argparse._SubParsersAction) -> None:
    export = commands.add_parser("review-export", help="export a frozen local human review package")
    export.add_argument("--spec", type=Path, required=True)
    export.add_argument("--artifacts", type=Path, required=True)
    export.add_argument("--state-root", type=Path, required=True)
    export.add_argument("--scoring", required=True)
    export.add_argument("--field", action="append", dest="fields", required=True)
    export.add_argument("--grain", action="append", dest="grains")
    export.add_argument("--row", action="append", dest="rows")
    export.add_argument("--blind", action="store_true")
    export.add_argument("--output", type=Path)
    imported = commands.add_parser("review-import", help="import explicit human assessments")
    imported.add_argument("--state-root", type=Path, required=True)
    imported.add_argument("--submission", type=Path, required=True)
    status = commands.add_parser("review-status", help="show missing human assessments")
    status.add_argument("--state-root", type=Path, required=True)
    status.add_argument("--package-id", required=True)
    merge = commands.add_parser("review-merge", help="merge current human assessment heads into artifacts")
    merge.add_argument("--state-root", type=Path, required=True)
    merge.add_argument("--package-id", required=True)
    merge.add_argument("--artifacts", type=Path, required=True)
    merge.add_argument("--output", type=Path)
    for name, help_text in (("review-prepare", "prepare editable packages for awaiting runtime jobs"),
                            ("review-sync", "advance jobs whose human reviews are complete")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--state-root", type=Path, required=True)
        command.add_argument("--study", required=True)


def _save(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"output": str(path), "schema": value["schema"], "id": value.get("package_id", value.get("id"))}


def _ensure_distinct(path: Path | None, inputs: list[Path]) -> None:
    if path is None:
        return
    target = os.path.normcase(str(path.resolve()))
    if any(target == os.path.normcase(str(source.resolve())) for source in inputs):
        raise EvoError("review output path must not overwrite an input")


def handle(args: argparse.Namespace) -> dict[str, Any]:
    if args.action == "review-export":
        _ensure_distinct(args.output, [args.spec, args.artifacts])
        value = export_review_package(
            load_spec(args.spec), load_artifacts(args.artifacts), args.state_root, args.scoring,
            args.fields, blind=args.blind, grains=args.grains, row_ids=args.rows,
        )
        return _save(args.output, value) if args.output else value
    if args.action == "review-import":
        return import_review_assessments(args.state_root, read_json(args.submission))
    if args.action == "review-status":
        return review_completion(args.state_root, args.package_id)
    if args.action == "review-merge":
        _ensure_distinct(args.output, [args.artifacts])
        value = merge_review_artifacts(load_artifacts(args.artifacts), args.state_root, args.package_id)
        return _save(args.output, value) if args.output else value
    if args.action in {"review-prepare", "review-sync"}:
        from .runtime_cli import study_id
        from .runtime_review import prepare_study_reviews, sync_study_reviews
        from .store import Store
        store = Store(args.state_root)
        study = study_id(args.study)
        values = prepare_study_reviews(store, study) if args.action == "review-prepare" else sync_study_reviews(store, study)
        return {"study": f"s{study}", "reviews": values}
    raise EvoError(f"unsupported review action: {args.action}")
