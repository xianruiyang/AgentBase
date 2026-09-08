from __future__ import annotations

import os
from pathlib import Path

from . import optimization
from .store import Store


ACTIONS = {"optimize", "optimize-start", "optimize-run", "optimize-resume", "optimize-status", "optimize-export"}


def add_commands(commands) -> None:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgentBase" / "evo"
    for name in sorted(ACTIONS):
        parser = commands.add_parser(name, help={
            "optimize": "freeze an explicit optimization specification and run its bounded loop",
            "optimize-start": "freeze an explicit optimization specification without invoking a controller",
            "optimize-run": "run a frozen bounded optimization",
            "optimize-resume": "resume persisted optimization work without repeating settled calls",
            "optimize-status": "show persisted optimization progress without starting work",
            "optimize-export": "export the current champion and evidence references without deployment",
        }[name])
        parser.add_argument("--state-root", type=Path, default=base / "state")
        if name in ("optimize", "optimize-start"):
            parser.add_argument("--spec", type=Path, required=True)
            parser.add_argument("--project-root", type=Path, required=True)
            parser.add_argument("--work-root", type=Path, default=base / "work")
        if name not in ("optimize", "optimize-start"):
            parser.add_argument("--optimization", required=True)
        if name in ("optimize", "optimize-run", "optimize-resume"):
            parser.add_argument("--installed-codex-root", type=Path)


def handle(args):
    store = Store(args.state_root)
    store.migrate()
    if args.action in ("optimize", "optimize-start"):
        result = optimization.start(store, args.spec, args.project_root, args.work_root)
        if args.action == "optimize":
            return optimization.run_optimization(store, result["id"], args.installed_codex_root)
        return result
    if args.action == "optimize-status":
        return optimization.status(store, args.optimization)
    if args.action == "optimize-export":
        return optimization.export(store, args.optimization)
    if args.action == "optimize-resume":
        return optimization.resume(store, args.optimization, args.installed_codex_root)
    return optimization.run_optimization(store, args.optimization, args.installed_codex_root)
