from __future__ import annotations

import os
import stat
from functools import wraps
from pathlib import Path
from typing import Any

from evaluation_core import PreconditionError, write_json_atomic


RUNTIME_HOME_RECORD = "codex-runtime-home.json"


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def prepare_runtime_home(*, attempt_root: Path, installed_codex_root: Path) -> tuple[Path, dict[str, Any]]:
    """Create an attempt-owned blank Codex home with a temporary auth hardlink."""

    attempt = attempt_root.resolve()
    installed = installed_codex_root.resolve()
    runtime_home = attempt / "codex-runtime-home"
    record_path = attempt / RUNTIME_HOME_RECORD
    source = installed / "auth.json"
    if installed == runtime_home or installed == attempt or installed.is_relative_to(attempt):
        raise PreconditionError("installed Codex root must be separate from the Evo attempt runtime home")
    if record_path.exists() or runtime_home.exists():
        raise PreconditionError("Evo attempt owns a pre-existing Codex runtime home")
    if not source.is_file() or source.is_symlink() or _is_reparse_point(source):
        raise PreconditionError("installed Codex auth.json must be a regular file without a reparse point")
    if source.resolve() != source:
        raise PreconditionError("installed Codex auth.json did not resolve to its declared file")
    if source.drive.casefold() != runtime_home.drive.casefold():
        raise PreconditionError("Evo runtime home must share a volume with installed Codex auth.json")
    runtime_home.mkdir()
    auth = runtime_home / "auth.json"
    try:
        os.link(source, auth)
        if not auth.is_file() or auth.is_symlink() or _is_reparse_point(auth):
            raise PreconditionError("Evo runtime authentication link is not a regular hardlink")
        if source.stat().st_ino != auth.stat().st_ino or source.stat().st_dev != auth.stat().st_dev:
            raise PreconditionError("Evo runtime authentication did not preserve file identity")
        record = {
            "schema": "agentbase.evo-codex-runtime-home/v1",
            "runtime_home": runtime_home.name,
            "authentication": "temporary-same-volume-hardlink",
            "authentication_source": "installed-codex-root/auth.json",
            "authentication_linked_at_launch": True,
        }
        write_json_atomic(record_path, record)
        return runtime_home, record
    except Exception:
        auth.unlink(missing_ok=True)
        try:
            runtime_home.rmdir()
        except OSError:
            pass
        raise


def runtime_home_from_receipt(*, attempt_root: Path, installed_codex_root: Path | None) -> Path:
    """Resolve new attempt homes while retaining legacy receipt recovery behavior."""

    attempt = attempt_root.resolve()
    record_path = attempt / RUNTIME_HOME_RECORD
    if not record_path.is_file():
        if installed_codex_root is None:
            raise PreconditionError("legacy Evo Codex recovery requires its installed Codex root")
        return installed_codex_root.resolve()
    import json

    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("schema") != "agentbase.evo-codex-runtime-home/v1" or record.get("runtime_home") != "codex-runtime-home":
        raise PreconditionError("Evo Codex runtime home receipt is invalid")
    runtime_home = (attempt / record["runtime_home"]).resolve()
    if not runtime_home.is_relative_to(attempt) or not runtime_home.is_dir():
        raise PreconditionError("Evo Codex runtime home receipt no longer resolves inside its attempt")
    return runtime_home


def remove_runtime_auth(*, attempt_root: Path) -> None:
    """Remove only the fixed attempt credential link without following a replaced home."""

    attempt = attempt_root.resolve()
    record_path = attempt / RUNTIME_HOME_RECORD
    if not record_path.is_file():
        return
    runtime_home = attempt / "codex-runtime-home"
    if runtime_home.is_symlink() or (runtime_home.exists() and _is_reparse_point(runtime_home)):
        raise PreconditionError("Evo Codex runtime home was replaced by a reparse point; authentication was not removed")
    if not runtime_home.is_dir() or runtime_home.resolve() != runtime_home:
        raise PreconditionError("Evo Codex runtime home no longer has its fixed attempt identity")
    auth = runtime_home / "auth.json"
    if auth.exists() and (auth.is_symlink() or _is_reparse_point(auth)):
        raise PreconditionError("Evo Codex runtime authentication was replaced; it was not removed")
    auth.unlink(missing_ok=True)


def cleanup_runtime_auth_after(function):
    """Guarantee cleanup for every adapter exit after a runtime receipt exists."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        attempt_root = kwargs.get("attempt_root")
        if attempt_root is None:
            raise TypeError("attempt_root must be passed by keyword")
        try:
            return function(*args, **kwargs)
        finally:
            remove_runtime_auth(attempt_root=Path(attempt_root))

    return wrapped
