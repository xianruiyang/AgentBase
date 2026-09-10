"""Stage and invoke the real AgentBase candidate in a trusted local workspace."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from codex_runtime import (  # noqa: E402
    CodexRuntimeError,
    resolve_shell_environment_policy,
)

from evaluation_core import (
    EvaluationError,
    PreconditionError,
    bounded_text,
    candidate_surface_identity,
    canonical_bytes,
    dependency_runtime_projection,
    read_json,
    require_within,
    require_profile,
    require_task,
    run_capture,
    sha256_bytes,
    sha256_file,
    task_asset_root,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)


BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
CODEX_RUN_RESULT_SCHEMA = "agentbase.windows-swe-codex-run/v8"
CODEX_AGENT_USAGE_SCHEMA = "agentbase.windows-swe-agent-usage/v2"
API_PRICING_SNAPSHOT_SCHEMA = "agentbase.windows-swe-api-pricing/v1"
API_EQUIVALENT_COST_SCHEMA = "agentbase.windows-swe-api-equivalent-cost/v1"
API_PRICING_SNAPSHOT_PATH = Path(__file__).resolve().with_name("api_pricing_snapshot.json")
CANDIDATE_COMPLETION_INSTRUCTION = (
    "Do not create Git commits. Finish with the working tree containing only the intended "
    "source solution; the evaluator will extract a Git patch and run held-out tests in a "
    "separate clean workspace.\n"
)
CODEX_USAGE_FIELDS = (
    "total_tokens",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
MAX_ATTEMPT_ROLLOUT_FILES = 128
MAX_ATTEMPT_ROLLOUT_BYTES = 256 * 1024 * 1024
MAX_ROLLOUT_LINE_BYTES = 16 * 1024 * 1024
MAX_ROLLOUT_METADATA_BYTES = 64 * 1024
MAX_COMPONENT_FILE_BYTES = 8 * 1024 * 1024
MAX_COMPONENT_PROJECTION_BYTES = 64 * 1024 * 1024
REQUIRED_CANDIDATE_TOOLS: dict[str, tuple[str, ...]] = {
    "srcq": ("srcq.exe", "srcq"),
    "rg": ("rg.exe", "rg"),
    "fd": ("fd.exe", "fd"),
    "scc": ("scc.exe", "scc"),
    "hyperfine": ("hyperfine.exe", "hyperfine"),
    "ast-grep": ("ast-grep.exe", "ast-grep.cmd", "ast-grep", "sg.exe", "sg.cmd", "sg"),
    "git": ("git.exe", "git"),
    "pwsh": ("pwsh.exe", "pwsh"),
    "python": ("python.exe", "python"),
    "node": ("node.exe", "node"),
}
VERSION_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "srcq": ("--version",),
    "rg": ("--version",),
    "fd": ("--version",),
    "scc": ("--version",),
    "hyperfine": ("--version",),
    "ast-grep": ("--version",),
    "git": ("--version",),
    "pwsh": (
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$PSVersionTable.PSVersion.ToString()",
    ),
    "python": ("--version",),
    "node": ("--version",),
    "codex": ("--version",),
}


def _resolved_shell_environment_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        source_descriptor, source_policy = resolve_shell_environment_policy()
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc
    return dict(source_descriptor), dict(source_policy)


def candidate_capability_contract(
    project_root: Path,
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the candidate surface without promoting configuration to behavior proof."""

    root = project_root.resolve()
    try:
        portable_config = tomllib.loads(
            (root / "global" / "config.toml").read_text(encoding="utf-8")
        )
        agent_profiles = {
            path.stem: tomllib.loads(path.read_text(encoding="utf-8"))
            for path in sorted((root / "global" / "agents").glob("*.toml"))
        }
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvaluationError(f"cannot derive candidate capability contract: {exc}") from exc
    skill_names = sorted(
        path.parent.name
        for path in (root / "skills").glob("*/SKILL.md")
        if path.is_file()
    )
    if not skill_names or not agent_profiles:
        raise EvaluationError("candidate capability surface omits skills or custom agents")
    agents = portable_config.get("agents", {})
    features = portable_config.get("features", {})
    if agents.get("enabled") is not True or features.get("multi_agent") is not True:
        raise EvaluationError("portable candidate config must enable custom agents and multi-agent")
    shell_policy_descriptor, _ = _resolved_shell_environment_policy()
    surface = candidate_surface_identity(root)
    return {
        "schema": "agentbase.windows-swe-candidate-capabilities/v7",
        "candidate_surface_identity_sha256": surface["identity_sha256"],
        "evaluator_profiles": {
            name: {
                "model": profile["model"],
                "reasoning_effort": profile["reasoning_effort"],
            }
            for name, profile in corpus["profiles"].items()
        },
        "projected_assets": {
            "global_rules": "global/AGENTS.md -> .codex/config.toml developer_instructions",
            "portable_config": "global/config.toml -> .codex/config.toml",
            "custom_agents": {
                name: {
                    "model": value.get("model"),
                    "reasoning_effort": value.get("model_reasoning_effort"),
                }
                for name, value in agent_profiles.items()
            },
            "custom_agent_discovery_root": ".codex/agents",
            "skills": {
                "names": skill_names,
                "count": len(skill_names),
                "discovery_root": ".agents/skills",
            },
            "derived_per_attempt": True,
            "content_hash_pinned": True,
        },
        "execution_contract": {
            "environment": "trusted-local-workspace",
            "sandbox_mode": "danger-full-access",
            "approval_policy": "never",
            "ignore_user_config": True,
            "installed_codex_root_usage": ["authentication", "session-usage-accounting"],
            "credential_copy_or_link": False,
            "hooks_enabled": False,
            "web_search": "disabled",
            "shell_environment_policy_sha256": shell_policy_descriptor["sha256"],
            "model_behavior_requires_explicit_run_evidence": True,
        },
        "runtime_identity_contract": {
            "base_cli_tools": sorted([*REQUIRED_CANDIDATE_TOOLS, "codex"]),
            "task_toolchains": sorted(
                {str(task["toolchain"]["kind"]) for task in corpus["tasks"]}
            ),
            "recorded_before_candidate_model": True,
            "task_dependency_identity_recorded": True,
        },
        "mechanical_boundaries": [
            "selected corpus and prepared source identity",
            "separate candidate and verifier workspaces",
            "patch path, file-count, size, and mode validation",
            "attempt and receipt identity with compare-and-swap updates",
            "process timeout and bounded logs",
        ],
        "separate_evidence_owners": {
            "routing_behavior": "development/skill-routing",
            "vscode_lsp_mcp": "mcp/vscode-lsp-mcp",
            "hooks_and_qq": "global/hooks.template.json and component validators",
            "plugin_and_deployment": "development/codex-deployment",
        },
        "excluded_from_swe": [
            "hooks",
            "host-apps",
            "host-plugins",
            "host-mcp",
            "installation",
            "publication",
        ],
    }


def _toml_key(value: str) -> str:
    return value if BARE_TOML_KEY.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise EvaluationError(f"unsupported generated TOML value: {type(value).__name__}")


def _emit_toml(table: Mapping[str, Any], path: tuple[str, ...], lines: list[str]) -> None:
    if path:
        if lines and lines[-1]:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
    scalar_keys = sorted(key for key, value in table.items() if not isinstance(value, dict))
    table_keys = sorted(key for key, value in table.items() if isinstance(value, dict))
    for key in scalar_keys:
        lines.append(f"{_toml_key(key)} = {_toml_value(table[key])}")
    for key in table_keys:
        _emit_toml(table[key], (*path, key), lines)


def _serialize_toml(value: Mapping[str, Any], header: Sequence[str]) -> str:
    lines = list(header)
    _emit_toml(value, (), lines)
    text = "\n".join(lines).rstrip() + "\n"
    try:
        reparsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise EvaluationError(f"generated Codex config is invalid: {exc}") from exc
    if reparsed != dict(value):
        raise EvaluationError("generated Codex config does not round-trip")
    return text


def _merge_without_overlap(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged:
            if isinstance(merged[key], dict) and isinstance(value, Mapping):
                merged[key] = _merge_without_overlap(dict(merged[key]), value)
                continue
            raise EvaluationError(f"evaluation transport conflicts with candidate config: {key}")
        merged[key] = value
    return merged


def _windows_winget_application(candidates: Sequence[str]) -> Path | None:
    if os.name != "nt":
        return None
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    alias_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Links"
    for candidate in candidates:
        if Path(candidate).suffix.casefold() != ".exe":
            continue
        alias = alias_root / candidate
        if alias.is_file():
            path = alias.resolve()
            if "\\WindowsApps\\" not in str(path):
                return path
    return None


def _resolve_application(candidates: Sequence[str]) -> Path:
    winget_path = _windows_winget_application(candidates)
    if winget_path is not None:
        return winget_path
    for candidate in candidates:
        value = shutil.which(candidate)
        if value:
            path = Path(value).resolve()
            if "\\WindowsApps\\" not in str(path):
                return path
    raise EvaluationError(f"required executable not found: {candidates[0]}")


def _tool_identity(name: str, path: Path) -> dict[str, Any]:
    result = run_capture([str(path), *VERSION_ARGUMENTS[name]], timeout=60, check=False)
    if result.returncode != 0:
        raise EvaluationError(f"cannot read {name} version: exit {result.returncode}")
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    version = bounded_text(text, 200)
    if not version:
        raise EvaluationError(f"{name} returned an empty version")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "version": version,
    }


def resolve_codex_identity(explicit_path: Path | None = None) -> dict[str, Any]:
    path = (
        explicit_path.resolve()
        if explicit_path is not None
        else _resolve_application(("codex.exe", "codex"))
    )
    if not path.is_file():
        raise EvaluationError(f"Codex executable not found: {path}")
    return {
        "schema": "agentbase.codex-cli-identity/v1",
        **_tool_identity("codex", path),
    }


def candidate_runtime_tools(
    project_root: Path,
    runtime_root: Path,
    explicit_codex_path: Path | None = None,
    *,
    include_codex: bool = True,
) -> dict[str, Any]:
    tools = {
        name: _tool_identity(name, _resolve_application(candidates))
        for name, candidates in REQUIRED_CANDIDATE_TOOLS.items()
    }
    if include_codex:
        tools["codex"] = resolve_codex_identity(explicit_codex_path)
    payload = {"tools": tools}
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def verifier_runtime_tools(task: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve only the local tools that participate in verifier execution."""

    names = ["git", "pwsh"]
    names.append("python" if task["toolchain"]["kind"] == "python" else "node")
    tools = {
        name: _tool_identity(name, _resolve_application(REQUIRED_CANDIDATE_TOOLS[name]))
        for name in names
    }
    payload = {"tools": tools}
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _skill_tree_entries(root: Path) -> list[dict[str, Any]]:
    resolved = root.resolve()
    if not resolved.is_dir() or _is_reparse_point(resolved):
        raise EvaluationError(f"skill source must be a regular directory: {resolved}")
    entries: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if _is_reparse_point(path):
            raise EvaluationError(f"skill tree contains a reparse point: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvaluationError(f"skill tree contains an unsupported entry: {path}")
        relative = path.relative_to(resolved).as_posix()
        entries.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    skill_documents = {
        entry["path"].split("/", 1)[0]
        for entry in entries
        if entry["path"].count("/") == 1 and entry["path"].endswith("/SKILL.md")
    }
    if not entries or not skill_documents:
        raise EvaluationError("skill tree projection is empty")
    return entries


def _regular_tree_entries(root: Path) -> list[dict[str, Any]]:
    resolved = root.resolve()
    if not resolved.is_dir() or _is_reparse_point(resolved):
        raise EvaluationError(f"component source must be a regular directory: {resolved}")
    entries: list[dict[str, Any]] = []
    total = 0
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if _is_reparse_point(path):
            raise EvaluationError(f"component tree contains a reparse point: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvaluationError(f"component tree contains an unsupported entry: {path}")
        size = path.stat().st_size
        if size > MAX_COMPONENT_FILE_BYTES:
            raise PreconditionError(f"component file exceeds {MAX_COMPONENT_FILE_BYTES} bytes: {path}")
        total += size
        if total > MAX_COMPONENT_PROJECTION_BYTES:
            raise PreconditionError(
                f"component projection exceeds {MAX_COMPONENT_PROJECTION_BYTES} bytes"
            )
        entries.append({"path": path.relative_to(resolved).as_posix(), "bytes": size})
    if not entries:
        raise PreconditionError("selected component tree is empty")
    return entries


def _projection_file_entries(workspace: Path, roots: Sequence[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        if _is_reparse_point(root) or not root.resolve().is_relative_to(workspace.resolve()):
            raise EvaluationError(f"projected component root is unsafe: {root}")
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if _is_reparse_point(path):
                raise EvaluationError(f"projected component contains a reparse point: {path}")
            if path.is_file():
                entries.append(
                    {
                        "path": path.relative_to(workspace).as_posix(),
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                    }
                )
    return sorted(entries, key=lambda entry: str(entry["path"]).casefold())


def stage_candidate_skill_projection(
    project_root: Path,
    workspace: Path,
    metadata_root: Path,
) -> dict[str, Any]:
    source = project_root.resolve() / "skills"
    destination = workspace.resolve() / ".agents" / "skills"
    metadata = metadata_root.resolve()
    if destination.exists():
        raise PreconditionError(
            "candidate repository already owns reserved evaluator path .agents/skills"
        )
    agents_root = destination.parent
    if agents_root.exists() and _is_reparse_point(agents_root):
        raise PreconditionError("candidate repository .agents path is a reparse point")
    source_entries = _skill_tree_entries(source)
    agents_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    projected_entries = _skill_tree_entries(destination)
    if projected_entries != source_entries:
        raise EvaluationError("candidate skill projection differs from its source")
    projection_identity = sha256_bytes(canonical_bytes(source_entries))
    manifest = {
        "schema": "agentbase.windows-swe-skill-probes/v1",
        "projection_root": ".agents/skills",
        "projection_identity_sha256": projection_identity,
        "files": source_entries,
    }
    path = metadata / "runtime-probe" / "skill-probes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "root": str(destination),
        "manifest_path": str(path),
        "manifest_sha256": sha256_file(path),
        "projection_identity_sha256": projection_identity,
        "file_count": len(source_entries),
    }


def stage_candidate_codex_projection(
    project_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    """Project the repository-owned Codex config and custom agents into a candidate."""

    resolved_project = project_root.resolve()
    resolved_workspace = workspace.resolve()
    source_config = resolved_project / "global" / "config.toml"
    source_rules = resolved_project / "global" / "AGENTS.md"
    source_agents = resolved_project / "global" / "agents"
    destination = resolved_workspace / ".codex"
    if destination.exists() or destination.is_symlink():
        raise PreconditionError(
            "candidate repository already owns reserved evaluator path .codex"
        )
    try:
        config = tomllib.loads(source_config.read_text(encoding="utf-8"))
        developer_instructions = source_rules.read_text(encoding="utf-8")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvaluationError(f"cannot project candidate Codex settings: {exc}") from exc
    config.pop("desktop", None)
    config["approval_policy"] = "never"
    config["sandbox_mode"] = "danger-full-access"
    config["web_search"] = "disabled"
    config["developer_instructions"] = developer_instructions
    config.setdefault("agents", {})["enabled"] = True
    features = config.setdefault("features", {})
    features["hooks"] = False
    features["multi_agent"] = True
    shell_policy_descriptor, shell_policy = _resolved_shell_environment_policy()
    config["shell_environment_policy"] = {
        key: shell_policy[key]
        for key in (
            "inherit",
            "ignore_default_excludes",
            "experimental_use_profile",
            "filters",
        )
    }
    config_text = _serialize_toml(
        config,
        [
            "# Generated by AgentBase Windows SWE; do not edit.",
            "# The candidate runs as a trusted local developer with repository-owned settings.",
        ],
    )
    destination.mkdir(parents=True, exist_ok=False)
    config_path = destination / "config.toml"
    write_text_atomic(config_path, config_text)
    agents_target = destination / "agents"
    shutil.copytree(source_agents, agents_target)
    source_entries = _controlled_agent_entries(source_agents)
    target_entries = _controlled_agent_entries(agents_target)
    if target_entries != source_entries:
        raise EvaluationError("candidate custom-agent projection differs from its source")
    files = [
        {
            "path": ".codex/config.toml",
            "sha256": sha256_file(config_path),
            "bytes": config_path.stat().st_size,
        },
        *[
            {
                **entry,
                "path": ".codex/" + str(entry["path"]),
            }
            for entry in target_entries
        ],
    ]
    identity = {
        "schema": "agentbase.windows-swe-codex-projection/v1",
        "files": files,
        "shell_environment_policy": shell_policy_descriptor,
    }
    return {
        "root": str(destination),
        "config_path": str(config_path),
        "files": files,
        "identity_sha256": sha256_bytes(canonical_bytes(identity)),
        "shell_environment_policy_sha256": shell_policy_descriptor["sha256"],
    }


def stage_codex_component_projection(
    *,
    project_root: Path,
    workspace: Path,
    selected: Mapping[str, Sequence[Mapping[str, Any]]],
    max_agents: int | None = None,
    candidate_source_roots: Sequence[Path] = (),
    skill_cache_root: Path | None = None,
    cache_cancel_check=None,
) -> dict[str, Any]:
    """Project only the Codex-facing assets selected by an Evo combination."""

    resolved_project = project_root.resolve()
    resolved_workspace = workspace.resolve()
    destination = resolved_workspace / ".codex"
    skill_destination = resolved_workspace / ".agents" / "skills"
    component_root = resolved_workspace / ".agentbase" / "components"
    manifest_path = resolved_workspace / ".agentbase" / "evo-codex-projection.json"
    pending_path = resolved_workspace / ".agentbase" / "evo-codex-projection.pending.json"
    def source_path(entry: Mapping[str, Any]) -> Path:
        raw = entry.get("source")
        if not isinstance(raw, str) or not raw:
            raise EvaluationError("selected component source is invalid")
        return resolve_component_source(
            resolved_project,
            raw,
            candidate_source_roots=candidate_source_roots,
        )

    skill_cache = None
    skill_bundle = None
    if skill_cache_root is not None:
        from evo.skill_cache import SkillCache
        lexical_cache = skill_cache_root.absolute()
        skill_cache = SkillCache(resolved_project, lexical_cache.parent, cancel_check=cache_cancel_check)
        if skill_cache.root.absolute() != lexical_cache:
            raise PreconditionError("managed skill cache root must be state-root/skill-cache")
    if selected.get("skills") and skill_cache is None:
        raise PreconditionError("selected Evo skills require an explicit managed skill cache root")
    if selected.get("skills"):
        named_sources: dict[str, Path] = {}
        for entry in selected["skills"]:
            source = source_path(entry)
            if source.name in named_sources:
                raise PreconditionError(f"selected skill target conflicts: {source.name}")
            named_sources[source.name] = source
        skill_bundle = skill_cache.materialize_bundle(named_sources)
    recipe_entries: list[dict[str, Any]] = []
    for kind in sorted(selected):
        for entry in selected[kind]:
            source = source_path(entry)
            if kind == "skills":
                files = skill_bundle["skills"][source.name]["files"]
            else:
                files = (
                [{"path": source.name, "sha256": sha256_file(source), "bytes": source.stat().st_size}]
                if source.is_file()
                else [
                    {"path": item["path"], "sha256": sha256_file(source / item["path"]), "bytes": item["bytes"]}
                    for item in _regular_tree_entries(source)
                ]
                )
            recipe_entries.append({"kind": kind, "id": entry.get("id"), "source": str(source), "files": files,
                                   **({"payload_identity_sha256": skill_bundle["identity_sha256"]} if kind == "skills" else {})})
    recipe = {"schema": "agentbase.evo-codex-projection-recipe/v1", "max_agents": max_agents, "sources": recipe_entries}
    recipe_identity = sha256_bytes(canonical_bytes(recipe))
    managed_roots = [destination, skill_destination, component_root]
    replaced = False
    if any(path.exists() or path.is_symlink() for path in managed_roots):
        if not manifest_path.is_file() or manifest_path.is_symlink():
            if not pending_path.is_file() or skill_cache is None:
                raise PreconditionError("workspace owns projection paths without an Evo managed manifest")
            pending = read_json(pending_path)
            if pending.get("schema") != "agentbase.evo-codex-projection-pending/v1":
                raise PreconditionError("workspace projection recovery marker is invalid")
            references = skill_cache.references_for_workspace(resolved_workspace)
            if references:
                skill_cache.recover_workspace_references(resolved_workspace)
            for path in managed_roots:
                if path.exists():
                    if _is_reparse_point(path) or any(_is_reparse_point(item) for item in path.rglob("*")):
                        raise PreconditionError("incomplete projection contains an unmanaged reparse point")
                    shutil.rmtree(path)
            pending_path.unlink()
            replaced = True
        if not manifest_path.is_file():
            pass
        else:
            previous = read_json(manifest_path)
            previous_files = previous.get("files")
            previous_result = previous.get("result")
            if previous.get("schema") != "agentbase.evo-codex-projection-manifest/v1" or not isinstance(previous_result, Mapping):
                raise PreconditionError("workspace projection manifest is not owned by this adapter")
            if previous.get("recipe_identity_sha256") == recipe_identity and isinstance(previous_files, list):
                if previous_result.get("skill_references"):
                    skill_cache.validate_workspace_references(resolved_workspace, previous_result["skill_references"])
                elif skill_destination.exists() and any(skill_destination.iterdir()):
                    # Legacy copied projections remain valid only through replacement below.
                    pass
                actual = _projection_file_entries(resolved_workspace, [destination, component_root])
                actual.extend(previous_result.get("skill_files", []))
                actual = sorted(actual, key=lambda row: str(row["path"]).casefold())
                if actual == previous_files and (previous_result.get("skill_references") or not skill_destination.exists()):
                    result = dict(previous_result)
                    result["disposition"] = "reused"
                    return result
            if previous_result.get("skill_references"):
                skill_cache.validate_workspace_references(resolved_workspace, previous_result["skill_references"], content=False)
            for reference in previous_result.get("skill_references", []):
                skill_cache.remove_reference(reference)
            if skill_destination.exists() and any(_is_reparse_point(item) for item in skill_destination.rglob("*")):
                raise PreconditionError("managed projection replacement encountered an unregistered skill reference")
            for path in managed_roots:
                if not path.exists():
                    continue
                if path.is_symlink() or _is_reparse_point(path) or not path.resolve().is_relative_to(resolved_workspace):
                    raise PreconditionError("managed projection replacement encountered an unsafe path")
                shutil.rmtree(path)
            manifest_path.unlink()
            replaced = True

    config: dict[str, Any] = {}
    component_copies: list[tuple[Path, Path]] = []
    tool_paths: list[str] = []
    hooks_by_event: dict[str, list[Any]] = {}
    mcp_servers: dict[str, Any] = {}
    tool_names: set[str] = set()
    for kind in ("hooks", "mcp", "tools"):
        for entry in selected.get(kind, ()):
            source = source_path(entry)
            descriptor = _component_descriptor(source, kind)
            identity = entry.get("id")
            if not isinstance(identity, str) or not identity:
                raise EvaluationError(f"selected {kind} component id is invalid")
            target = component_root / kind / identity
            component_copies.append((source, target))
            if kind == "hooks":
                hooks_path = _component_relative_file(source, descriptor.get("hooks"), "hooks.hooks")
                hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
                if not isinstance(hooks, dict) or not isinstance(hooks.get("hooks"), dict):
                    raise EvaluationError("hooks component payload must contain a hooks object")
                rendered = _replace_component_placeholders(
                    hooks["hooks"], component_root=target, workspace=resolved_workspace
                )
                for event, bindings in rendered.items():
                    if not isinstance(event, str) or not isinstance(bindings, list):
                        raise EvaluationError("hooks component event bindings are invalid")
                    hooks_by_event.setdefault(event, []).extend(bindings)
            elif kind == "mcp":
                servers = descriptor.get("servers")
                if not isinstance(servers, list):
                    raise EvaluationError("MCP component servers must be an array")
                for server in servers:
                    if not isinstance(server, dict) or not isinstance(server.get("id"), str):
                        raise EvaluationError("MCP component server entry is invalid")
                    server_id = server["id"]
                    if server_id in mcp_servers:
                        raise EvaluationError(f"selected MCP server id conflicts: {server_id}")
                    entry_path = _component_relative_file(source, server.get("entry"), "mcp entry")
                    command = server.get("command")
                    if not isinstance(command, str) or not command or any(mark in command for mark in ("/", "\\", "{")):
                        raise EvaluationError("mcp command must name an explicit runtime executable")
                    value = {key: item for key, item in server.items() if key not in {"id", "entry"}}
                    value["args"] = [str(target / entry_path.relative_to(source)), *value.get("args", [])]
                    mcp_servers[server_id] = _replace_component_placeholders(
                        value, component_root=target, workspace=resolved_workspace
                    )
            else:
                bins = descriptor.get("bins")
                if not isinstance(bins, list) or not bins:
                    raise EvaluationError("tools component bins must be a non-empty array")
                for binary in bins:
                    if not isinstance(binary, dict) or not isinstance(binary.get("name"), str):
                        raise EvaluationError("tools component bin entry is invalid")
                    if binary["name"].casefold() in tool_names:
                        raise EvaluationError(f"tools component bin name conflicts: {binary['name']}")
                    tool_names.add(binary["name"].casefold())
                    path = _component_relative_file(source, binary.get("path"), "tool bin path")
                    tool_paths.append(str((target / path.relative_to(source)).parent))
    if mcp_servers:
        config = _merge_without_overlap(config, {"mcp_servers": mcp_servers})
    for entry in selected.get("codex_settings", ()):
        path = source_path(entry)
        if not path.is_file() or path.suffix.casefold() != ".toml":
            raise PreconditionError("selected Codex setting must be a regular TOML file")
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise EvaluationError(f"cannot read selected Codex setting: {exc}") from exc
        config = _merge_without_overlap(config, value)

    instructions: list[str] = []
    for entry in selected.get("agents_md", ()):
        path = source_path(entry)
        if not path.is_file():
            raise PreconditionError("selected AGENTS source must be a regular file")
        instructions.append(path.read_text(encoding="utf-8"))
    if instructions:
        config["developer_instructions"] = "\n\n".join(text.rstrip() for text in instructions) + "\n"
    config.pop("desktop", None)
    config["approval_policy"] = "never"
    config["sandbox_mode"] = "danger-full-access"
    agents_config = config.setdefault("agents", {})
    features = config.setdefault("features", {})
    if hooks_by_event:
        configured_hooks = config["features"].get("hooks")
        if configured_hooks is False:
            raise EvaluationError("selected Codex settings disable selected hooks")
        config["features"]["hooks"] = True
    if max_agents is not None:
        agents = agents_config
        configured = agents.get("max_concurrent_threads_per_session")
        configured_enabled = agents.get("enabled")
        if max_agents == 1:
            if selected.get("agents"):
                raise PreconditionError("selected agent profiles conflict with single-root max_agents=1")
            if configured_enabled is True:
                raise PreconditionError("selected agents.enabled=true conflicts with single-root max_agents=1")
            if configured is not None:
                raise PreconditionError(
                    "selected agents.max_concurrent_threads_per_session conflicts with single-root max_agents=1"
                )
            if features.get("multi_agent") is True:
                raise PreconditionError("selected features.multi_agent=true conflicts with single-root max_agents=1")
            agents["max_concurrent_threads_per_session"] = 1
            agents["enabled"] = False
            features["multi_agent"] = False
        else:
            child_capacity = max_agents - 1
            if configured_enabled is False:
                raise PreconditionError("selected agents.enabled=false conflicts with max_agents greater than one")
            if configured is not None and configured != child_capacity:
                raise PreconditionError(
                    "selected agents.max_concurrent_threads_per_session="
                    f"{configured} conflicts with reserved root-plus-descendant max_agents={max_agents}"
                )
            if features.get("multi_agent") is False:
                raise PreconditionError("selected features.multi_agent=false conflicts with max_agents greater than one")
            agents["max_concurrent_threads_per_session"] = child_capacity
            agents["enabled"] = True
            features["multi_agent"] = True
    else:
        agents_config["enabled"] = True

    pending_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(pending_path, {"schema": "agentbase.evo-codex-projection-pending/v1",
                                     "recipe_identity_sha256": recipe_identity})
    destination.mkdir(parents=True, exist_ok=False)
    config_path = destination / "config.toml"
    write_text_atomic(
        config_path,
        _serialize_toml(config, ["# Generated by AgentBase Evo; do not edit."]),
    )
    projected_files: list[dict[str, Any]] = []

    for entry in selected.get("agents", ()):
        source = source_path(entry)
        sources = [source] if source.is_file() else sorted(source.glob("*.toml"))
        if not sources:
            raise PreconditionError("selected agents source has no TOML profiles")
        target_root = destination / "agents"
        target_root.mkdir(exist_ok=True)
        for item in sources:
            if not item.is_file() or _is_reparse_point(item):
                raise PreconditionError("selected agent profile is not a regular file")
            target = target_root / item.name
            if target.exists():
                raise EvaluationError(f"selected agent profile target conflicts: {item.name}")
            shutil.copy2(item, target)

    skill_references: list[dict[str, Any]] = []
    skill_files: list[dict[str, Any]] = []
    for entry in selected.get("skills", ()):
        source = source_path(entry)
        if not source.is_dir():
            raise PreconditionError("selected skill source must be a regular directory")
        entries = _regular_tree_entries(source)
        if not any(item["path"] == "SKILL.md" for item in entries):
            raise PreconditionError("selected skill source omits SKILL.md")
        target = skill_destination / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise EvaluationError(f"selected skill target conflicts: {source.name}")
        reference = skill_cache.create_reference(resolved_workspace, source.name, skill_bundle)
        skill_references.append(reference)
        skill_files.extend({**item, "path": (Path(".agents/skills") / source.name / item["path"]).as_posix()}
                           for item in skill_bundle["skills"][source.name]["files"])

    for source, target in component_copies:
        if target.exists():
            raise EvaluationError(f"selected component target conflicts: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    hooks_path = destination / "hooks.json"
    if hooks_by_event:
        write_text_atomic(
            hooks_path,
            json.dumps({"hooks": hooks_by_event}, ensure_ascii=False, indent=2) + "\n",
        )

    projected_files = _projection_file_entries(resolved_workspace, [destination, component_root])
    projected_files = sorted([*projected_files, *skill_files], key=lambda entry: str(entry["path"]).casefold())
    if skill_references:
        skill_cache.validate_workspace_references(resolved_workspace, skill_references)
    payload = {"schema": "agentbase.evo-codex-projection/v1", "files": projected_files}
    result = {
        "root": str(destination),
        "config_path": str(config_path),
        "files": projected_files,
        "identity_sha256": sha256_bytes(canonical_bytes(payload)),
        "managed_paths": [
            ".codex",
            ".agents/skills",
            ".agentbase/components",
            ".agentbase/evo-codex-projection.json",
        ],
        "hooks_enabled": bool(hooks_by_event),
        "tool_paths": sorted(set(tool_paths), key=str.casefold),
        "skill_references": skill_references,
        "skill_files": skill_files,
        "disposition": "replaced" if replaced else "created",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        manifest_path,
        {
            "schema": "agentbase.evo-codex-projection-manifest/v1",
            "recipe_identity_sha256": recipe_identity,
            "files": projected_files,
            "result": result,
        },
    )
    pending_path.unlink()
    return result


def _path_is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_component_source(
    project_root: Path,
    source: str,
    candidate_source_roots: Sequence[Path] = (),
) -> Path:
    """Resolve a selected component under the project or registered candidate roots."""

    if not isinstance(source, str) or not source:
        raise EvaluationError("selected component source is invalid")
    resolved_project = project_root.resolve()
    allowed_roots = [resolved_project, *(path.resolve() for path in candidate_source_roots)]
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = resolved_project / candidate
    absolute = candidate.absolute()
    resolved = candidate.resolve()
    lexical_roots = [root for root in allowed_roots if _path_is_within(root, absolute)]
    if not lexical_roots or not any(_path_is_within(root, resolved) for root in lexical_roots):
        raise PreconditionError(f"selected component source is outside allowed roots: {source}")
    for root in lexical_roots:
        cursor = root
        for part in absolute.relative_to(root).parts:
            cursor = cursor / part
            if cursor.exists() and _is_reparse_point(cursor):
                raise PreconditionError(
                    f"selected component source traverses a reparse point: {source}"
                )
    if not resolved.exists() or _is_reparse_point(resolved):
        raise PreconditionError(f"selected component source is unavailable: {source}")
    if resolved.is_file() and resolved.stat().st_size > MAX_COMPONENT_FILE_BYTES:
        raise PreconditionError(
            f"component file exceeds {MAX_COMPONENT_FILE_BYTES} bytes: {resolved}"
        )
    return resolved


def _component_descriptor(source: Path, kind: str) -> dict[str, Any]:
    if not source.is_dir():
        raise PreconditionError(f"selected {kind} component must be a directory")
    _regular_tree_entries(source)
    path = source / "component.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read {kind} component descriptor: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != "agentbase-evo-component/v1" or value.get("kind") != kind:
        raise EvaluationError(f"selected {kind} component descriptor has an invalid schema or kind")
    return value


def _component_relative_file(root: Path, value: Any, where: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise EvaluationError(f"{where} must be a component-relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file() or _is_reparse_point(path):
        raise EvaluationError(f"{where} is unavailable in the component tree")
    return path


def _replace_component_placeholders(value: Any, *, component_root: Path, workspace: Path) -> Any:
    if isinstance(value, str):
        rendered = value.replace("{component_root}", str(component_root)).replace("{workspace}", str(workspace))
        if "{" in rendered or "}" in rendered:
            raise EvaluationError("component descriptor contains an unsupported placeholder")
        return rendered
    if isinstance(value, list):
        return [_replace_component_placeholders(item, component_root=component_root, workspace=workspace) for item in value]
    if isinstance(value, dict):
        return {key: _replace_component_placeholders(item, component_root=component_root, workspace=workspace) for key, item in value.items()}
    return value


def _controlled_agent_entries(root: Path) -> list[dict[str, Any]]:
    resolved = root.resolve()
    if not resolved.is_dir() or _is_reparse_point(resolved):
        raise EvaluationError(f"custom-agent source must be a regular directory: {resolved}")
    entries: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if _is_reparse_point(path):
            raise EvaluationError(f"custom-agent tree contains a reparse point: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvaluationError(f"custom-agent tree contains an unsupported entry: {path}")
        entries.append(
            {
                "path": "agents/" + path.relative_to(resolved).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    if not entries:
        raise EvaluationError("custom-agent tree is empty")
    return entries


def candidate_public_tooling_hint(task: Mapping[str, Any]) -> str:
    toolchain = task.get("toolchain")
    if not isinstance(toolchain, Mapping):
        raise EvaluationError("candidate task toolchain is invalid")
    kind = toolchain.get("kind")
    if kind == "python":
        return (
            "Use .agentbase-venv\\Scripts\\python.exe for Python and pytest so public checks "
            "use the prepared, identity-pinned dependencies.\n"
        )
    if kind == "node":
        package_manager = toolchain.get("package_manager")
        if not isinstance(package_manager, str) or not package_manager:
            raise EvaluationError("candidate Node task omits its package manager")
        return (
            f"Dependencies are prepared under node_modules; use {package_manager} scripts for "
            "public checks.\n"
        )
    raise EvaluationError(f"unsupported candidate task toolchain: {kind!r}")


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def candidate_public_checks_hint(
    task: Mapping[str, Any],
    dependency_values: Mapping[str, str],
    workspace: Path,
) -> str:
    checks = [
        check
        for check in task.get("checks", [])
        if isinstance(check, Mapping) and check.get("bucket") == "base"
    ]
    if not checks:
        raise EvaluationError("candidate task omits a public base check")
    replacements = {str(key): str(value) for key, value in dependency_values.items()}
    replacements["workspace"] = str(workspace.resolve())
    commands: list[str] = []
    for check in checks:
        argv = check.get("argv")
        if not isinstance(argv, list) or not argv or any(
            not isinstance(argument, str) or not argument for argument in argv
        ):
            raise EvaluationError("candidate public base check argv is invalid")
        projected: list[str] = []
        for argument in argv:
            if "{report}" in argument or "{raw_report}" in argument:
                continue
            if argument in {"--json", "--reporter=junit"}:
                continue
            if argument.startswith(
                ("--ignore=", "--exclude=", "--testPathIgnorePatterns=")
            ):
                continue
            try:
                expanded = argument.format_map(replacements)
            except KeyError as exc:
                raise EvaluationError(
                    f"candidate public base check uses an unknown placeholder: {exc}"
                ) from exc
            projected.append(expanded)
        if not projected:
            raise EvaluationError("candidate public base check became empty")
        commands.append("& " + " ".join(_powershell_literal(item) for item in projected))
    safe_directory = _powershell_literal(
        f"safe.directory={workspace.resolve().as_posix()}"
    )
    rendered = "\n".join(f"- `{command}`" for command in commands)
    return (
        "Known public regression command(s), derived from the corpus base bucket with "
        "hidden-test filters and report-only flags removed:\n"
        f"{rendered}\n"
        f"For Git reads in this workspace, prefix arguments with `git.exe -c {safe_directory}`; "
        "do not retry the same Git command without that prefix.\n"
        "After one direct behavior check, run each relevant listed regression command once when "
        "the candidate is stable. Do not probe unprepared linters, type checkers, or broader test "
        "suites unless new output identifies a directly relevant uncovered mechanism.\n"
    )


def candidate_patch_scope_hint(task: Mapping[str, Any]) -> str:
    allowed = task.get("allowed_patch_paths")
    if not isinstance(allowed, list) or not allowed or any(
        not isinstance(path, str) or not path for path in allowed
    ):
        raise EvaluationError("candidate task patch scope is invalid")
    return (
        "Keep the final solution patch within these task-approved paths: "
        f"{', '.join(allowed)}. Do not modify .agentbase or any test, dependency, or lockfile "
        "outside this list.\n"
    )


def candidate_windows_adapter_hint(task: Mapping[str, Any]) -> str:
    if task.get("windows_adapter") is None:
        return ""
    return (
        "A hash-pinned Windows test-fixture adapter is already committed in this workspace "
        "baseline. Treat it as read-only environment support; do not amend, reset, or include "
        "it in the solution patch.\n"
    )


def prepare_candidate_metadata_root(workspace: Path) -> Path:
    """Reserve evaluator metadata beside the optional task-local runtime."""

    workspace_root = workspace.resolve()
    metadata = workspace_root / ".agentbase"
    if metadata.exists():
        resolved = require_within(workspace_root, metadata)
        if resolved != metadata or metadata.is_symlink() or not metadata.is_dir():
            raise EvaluationError("candidate metadata root is not a managed directory")
        unexpected = sorted(
            child.name for child in metadata.iterdir() if child.name != "task-runtime"
        )
        if unexpected:
            raise EvaluationError(
                "candidate metadata root contains unexpected pre-existing content"
            )
    else:
        metadata.mkdir(parents=True, exist_ok=False)
    return metadata


def stage_candidate_task_context(
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    workspace: Path,
    dependency_values: Mapping[str, str],
    *,
    prompt_path: Path | None = None,
) -> dict[str, Any]:
    """Stage the shared SWE task prompt and dependency runtime for any candidate surface."""
    metadata = prepare_candidate_metadata_root(workspace)
    instruction_source = task_asset_root(state_root, corpus, task_id) / "instruction.md"
    shutil.copy2(instruction_source, metadata / "task.md")
    task = require_task(corpus, task_id)
    public_tooling = candidate_public_tooling_hint(task)
    public_checks = candidate_public_checks_hint(task, dependency_values, workspace)
    patch_scope = candidate_patch_scope_hint(task)
    windows_adapter = candidate_windows_adapter_hint(task)
    prompt = (
        "Complete the repository task described in .agentbase/task.md.\n"
        "Work as a trusted local developer in this candidate workspace. Use the repository "
        "instructions and AgentBase tools, implement the task, and run useful public checks.\n"
        f"{windows_adapter}"
        f"{patch_scope}"
        f"{public_tooling}"
        f"{public_checks}"
        f"{CANDIDATE_COMPLETION_INSTRUCTION}"
    )
    if prompt_path is not None:
        write_text_atomic(prompt_path.resolve(), prompt)
    task_runtime = dependency_runtime_projection(task, dependency_values)
    return {
        "metadata_root": str(metadata),
        "prompt": prompt,
        "prompt_path": str(prompt_path.resolve()) if prompt_path is not None else None,
        "task_runtime": task_runtime,
    }


def stage_candidate_metadata(
    project_root: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    workspace: Path,
    attempt_root: Path,
    dependency_values: Mapping[str, str],
) -> dict[str, Any]:
    task_context = stage_candidate_task_context(
        state_root, corpus, task_id, workspace, dependency_values,
        prompt_path=attempt_root.resolve() / "candidate-prompt.txt",
    )
    task_context.pop("prompt", None)
    metadata = Path(task_context["metadata_root"])
    skill_projection = stage_candidate_skill_projection(
        project_root,
        workspace,
        metadata,
    )
    codex_projection = stage_candidate_codex_projection(project_root, workspace)
    return {
        **task_context,
        "codex_projection": codex_projection,
        "skill_root_path": skill_projection["root"],
        "skill_probe_manifest_path": skill_projection["manifest_path"],
        "skill_probe_manifest_sha256": skill_projection["manifest_sha256"],
        "skill_projection_identity_sha256": skill_projection[
            "projection_identity_sha256"
        ],
        "expected_skill_file_count": skill_projection["file_count"],
    }


def candidate_rollout_snapshot(codex_home: Path) -> dict[str, Any]:
    """Capture a constant-size cursor without enumerating a user's rollout history."""

    resolved_home = codex_home.resolve()
    roots: dict[str, bool] = {}
    for subdirectory in ("sessions", "archived_sessions"):
        root = resolved_home / subdirectory
        roots[subdirectory] = root.exists()
        if root.exists() and (not root.is_dir() or _is_reparse_point(root)):
            raise EvaluationError(f"candidate rollout root is not a regular directory: {root}")
    return {
        "schema": "agentbase.codex-rollout-cursor/v1",
        "codex_home": str(resolved_home),
        "started_ns": time.time_ns(),
        "roots_existed": roots,
    }


def _candidate_rollouts_after_cursor(
    codex_home: Path,
    before: Mapping[str, Any],
) -> list[dict[str, Any]]:
    resolved_home = codex_home.resolve()
    if before.get("schema") != "agentbase.codex-rollout-cursor/v1":
        after = _legacy_candidate_rollout_inventory(resolved_home)
        return [after[key] for key in sorted(set(after) - set(before))]
    if before.get("codex_home") != str(resolved_home):
        raise EvaluationError("candidate rollout cursor belongs to another Codex home")
    started_ns = before.get("started_ns")
    roots_existed = before.get("roots_existed")
    if isinstance(started_ns, bool) or not isinstance(started_ns, int) or not isinstance(roots_existed, Mapping):
        raise EvaluationError("candidate rollout cursor is invalid")
    # Filesystems can report timestamps slightly before the Python clock boundary.
    earliest_ns = started_ns - 2_000_000_000
    now = time.time()
    cursor_day = started_ns / 1_000_000_000 - 86400
    end_value = now + 86400
    day_keys: set[tuple[int, int, int]] = set()
    while cursor_day <= end_value and len(day_keys) < 4:
        value = time.gmtime(cursor_day)
        day_keys.add((value.tm_year, value.tm_mon, value.tm_mday))
        cursor_day += 86400
    files: list[Path] = []
    for subdirectory in ("sessions", "archived_sessions"):
        root = resolved_home / subdirectory
        if not root.exists():
            continue
        if not roots_existed.get(subdirectory, False):
            for current, directories, filenames in os.walk(root, followlinks=False):
                current_path = Path(current)
                directories[:] = [name for name in directories if not _is_reparse_point(current_path / name)]
                files.extend(current_path / name for name in filenames)
            continue
        files.extend(root.glob("*.jsonl"))
        files.extend(root.glob("*.jsonl.zst"))
        for year, month, day in day_keys:
            bucket = root / f"{year:04d}" / f"{month:02d}" / f"{day:02d}"
            if bucket.is_dir() and not _is_reparse_point(bucket):
                files.extend(bucket.glob("*.jsonl"))
                files.extend(bucket.glob("*.jsonl.zst"))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in files:
        path = candidate.resolve()
        if not path.is_relative_to(resolved_home) or _is_reparse_point(candidate) or not path.is_file():
            raise EvaluationError(f"candidate rollout is not a regular file: {candidate}")
        stat_result = path.stat()
        if stat_result.st_mtime_ns < earliest_ns:
            continue
        relative = path.relative_to(resolved_home).as_posix()
        key = relative.casefold()
        if key in seen:
            continue
        seen.add(key)
        entries.append({"path": str(path), "relative_path": relative, "bytes": stat_result.st_size, "modified_ns": stat_result.st_mtime_ns})
    return sorted(entries, key=lambda entry: str(entry["relative_path"]).casefold())


def _legacy_candidate_rollout_inventory(resolved_home: Path) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for subdirectory in ("sessions", "archived_sessions"):
        root = resolved_home / subdirectory
        if not root.exists():
            continue
        for path in (*root.rglob("*.jsonl"), *root.rglob("*.jsonl.zst")):
            resolved = path.resolve()
            relative = resolved.relative_to(resolved_home).as_posix()
            info = resolved.stat()
            observed[relative.casefold()] = {"path": str(resolved), "relative_path": relative, "bytes": info.st_size, "modified_ns": info.st_mtime_ns}
    return observed


def _candidate_rollout_identity(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read only a bounded session_meta line for lineage discovery."""

    path = Path(str(entry["path"]))
    if path.suffix.casefold() == ".zst":
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.readline(MAX_ROLLOUT_METADATA_BYTES + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_ROLLOUT_METADATA_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("type") != "session_meta":
        return None
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return None
    thread_id = payload.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        return None
    return {
        "thread_id": thread_id,
        "parent_thread_id": _rollout_parent_thread_id(payload),
        "forked_from_id": payload.get("forked_from_id"),
        "entry": entry,
    }


def _rollout_parent_thread_id(metadata: Mapping[str, Any]) -> Any:
    direct = metadata.get("parent_thread_id")
    if isinstance(direct, str) and direct:
        return direct
    source = metadata.get("source")
    subagent = source.get("subagent") if isinstance(source, Mapping) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, Mapping) else None
    return spawn.get("parent_thread_id") if isinstance(spawn, Mapping) else None


def _candidate_rollout_lineage_entries(
    entries: Sequence[Mapping[str, Any]],
    root_thread_id: str,
) -> list[Mapping[str, Any]]:
    indexed = [identity for entry in entries if (identity := _candidate_rollout_identity(entry))]
    roots = [identity for identity in indexed if identity["thread_id"] == root_thread_id]
    if not roots:
        raise EvaluationError("Codex candidate root thread is absent from persisted rollouts")
    if len(roots) != 1:
        raise EvaluationError("Codex candidate root thread has ambiguous rollout evidence")
    selected = {root_thread_id}
    pending = list(indexed)
    changed = True
    while changed:
        changed = False
        for identity in pending:
            if identity["thread_id"] in selected:
                continue
            if identity.get("parent_thread_id") in selected or identity.get("forked_from_id") in selected:
                selected.add(identity["thread_id"])
                changed = True
    result: list[Mapping[str, Any]] = [roots[0]["entry"]]
    for thread_id in sorted(selected - {root_thread_id}):
        matches = [identity for identity in indexed if identity["thread_id"] == thread_id]
        if len(matches) != 1:
            raise EvaluationError(f"Codex candidate persisted duplicate thread rollouts: {thread_id}")
        result.append(matches[0]["entry"])
    return result


def _nonnegative_token_usage(value: object, *, context: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{context} must be an object")
    usage: dict[str, int] = {}
    for field in CODEX_USAGE_FIELDS:
        token_value = value.get(field)
        if isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0:
            raise EvaluationError(f"{context}.{field} must be a non-negative integer")
        usage[field] = token_value
    if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise EvaluationError(f"{context}.total_tokens disagrees with input plus output")
    if (
        usage["cached_input_tokens"] + usage["cache_write_input_tokens"]
        > usage["input_tokens"]
    ):
        raise EvaluationError(
            f"{context} cached plus cache-write input exceeds input_tokens"
        )
    if usage["reasoning_output_tokens"] > usage["output_tokens"]:
        raise EvaluationError(f"{context}.reasoning_output_tokens exceeds output_tokens")
    return usage


def _zero_token_usage() -> dict[str, int]:
    return {field: 0 for field in CODEX_USAGE_FIELDS}


def _sum_token_usage(target: dict[str, int], source: Mapping[str, int]) -> None:
    for field in CODEX_USAGE_FIELDS:
        target[field] += int(source[field])


def _token_usage_delta(
    current: Mapping[str, int],
    previous: Mapping[str, int],
    *,
    context: str,
) -> dict[str, int]:
    delta: dict[str, int] = {}
    for field in CODEX_USAGE_FIELDS:
        value = int(current[field]) - int(previous[field])
        if value < 0:
            raise EvaluationError(f"{context}.{field} decreased")
        delta[field] = value
    return _nonnegative_token_usage(delta, context=context)


def _positive_integer(value: object, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationError(f"{context} must be a positive integer")
    return value


def _pricing_ratio(value: object, *, context: str) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{context} must be an object")
    return (
        _positive_integer(value.get("numerator"), context=f"{context}.numerator"),
        _positive_integer(value.get("denominator"), context=f"{context}.denominator"),
    )


def api_pricing_snapshot() -> dict[str, Any]:
    value = read_json(API_PRICING_SNAPSHOT_PATH)
    if (
        value.get("schema") != API_PRICING_SNAPSHOT_SCHEMA
        or value.get("basis") != "official-openai-standard-api-text-token-pricing"
        or value.get("currency") != "USD"
        or value.get("actual_billing_observed") is not False
        or value.get("cost_unit") != "usd_nanos"
        or not isinstance(value.get("observed_at"), str)
    ):
        raise EvaluationError("API pricing snapshot has an invalid top-level contract")
    long_context = value.get("long_context")
    if not isinstance(long_context, Mapping):
        raise EvaluationError("API pricing snapshot omits long_context")
    _positive_integer(
        long_context.get("input_threshold_tokens_exclusive"),
        context="long_context.input_threshold_tokens_exclusive",
    )
    _pricing_ratio(long_context.get("input_multiplier"), context="long_context.input_multiplier")
    _pricing_ratio(long_context.get("output_multiplier"), context="long_context.output_multiplier")
    _pricing_ratio(value.get("cache_write_multiplier"), context="cache_write_multiplier")
    aliases = value.get("aliases")
    models = value.get("models")
    if not isinstance(aliases, Mapping) or not isinstance(models, Mapping) or not models:
        raise EvaluationError("API pricing snapshot aliases/models are invalid")
    for alias, target in aliases.items():
        if not isinstance(alias, str) or not alias or not isinstance(target, str) or target not in models:
            raise EvaluationError("API pricing snapshot contains an invalid model alias")
    for model, rates in models.items():
        if not isinstance(model, str) or not model or not isinstance(rates, Mapping):
            raise EvaluationError("API pricing snapshot contains an invalid model entry")
        source = rates.get("source")
        if not isinstance(source, str) or not source.startswith(
            "https://developers.openai.com/api/docs/models/"
        ):
            raise EvaluationError(f"API pricing source is invalid for {model}")
        for field in (
            "input_usd_nanos_per_token",
            "cached_input_usd_nanos_per_token",
            "output_usd_nanos_per_token",
        ):
            _positive_integer(rates.get(field), context=f"models.{model}.{field}")
    return {**value, "identity_sha256": sha256_file(API_PRICING_SNAPSHOT_PATH)}


def _multiply_ratio_exact(value: int, ratio: tuple[int, int], *, context: str) -> int:
    numerator, denominator = ratio
    scaled = value * numerator
    if scaled % denominator != 0:
        raise EvaluationError(f"{context} cannot be represented as whole USD nanos")
    return scaled // denominator


def format_usd_nanos(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationError("USD nanos must be a non-negative integer")
    return f"{value // 1_000_000_000}.{value % 1_000_000_000:09d}"


def _price_response(
    pricing: Mapping[str, Any],
    requested_model: str,
    usage: Mapping[str, int],
) -> dict[str, Any]:
    aliases = pricing["aliases"]
    canonical_model = str(aliases.get(requested_model, requested_model))
    rates = pricing["models"].get(canonical_model)
    if not isinstance(rates, Mapping):
        # Token evidence is independent of coverage in a dated price table.
        return {
            "requested_model": requested_model,
            "priced_model": canonical_model,
            "long_context": int(usage["input_tokens"]) > int(
                pricing["long_context"]["input_threshold_tokens_exclusive"]),
            "cost_usd_nanos": None,
        }
    ordinary_input_tokens = (
        int(usage["input_tokens"])
        - int(usage["cached_input_tokens"])
        - int(usage["cache_write_input_tokens"])
    )
    input_cost = (
        ordinary_input_tokens * int(rates["input_usd_nanos_per_token"])
        + int(usage["cached_input_tokens"])
        * int(rates["cached_input_usd_nanos_per_token"])
    )
    cache_write_rate = _multiply_ratio_exact(
        int(rates["input_usd_nanos_per_token"]),
        _pricing_ratio(pricing["cache_write_multiplier"], context="cache_write_multiplier"),
        context=f"{canonical_model} cache-write rate",
    )
    input_cost += int(usage["cache_write_input_tokens"]) * cache_write_rate
    output_cost = int(usage["output_tokens"]) * int(rates["output_usd_nanos_per_token"])
    long_context = pricing["long_context"]
    long_request = int(usage["input_tokens"]) > int(
        long_context["input_threshold_tokens_exclusive"]
    )
    if long_request:
        input_cost = _multiply_ratio_exact(
            input_cost,
            _pricing_ratio(long_context["input_multiplier"], context="long_context.input_multiplier"),
            context=f"{canonical_model} long-context input cost",
        )
        output_cost = _multiply_ratio_exact(
            output_cost,
            _pricing_ratio(long_context["output_multiplier"], context="long_context.output_multiplier"),
            context=f"{canonical_model} long-context output cost",
        )
    return {
        "requested_model": requested_model,
        "priced_model": canonical_model,
        "long_context": long_request,
        "cost_usd_nanos": input_cost + output_cost,
    }


def _parse_candidate_rollout(
    path: Path,
    relative_path: str,
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    size = path.stat().st_size
    if size <= 0 or size > MAX_ATTEMPT_ROLLOUT_BYTES:
        raise EvaluationError(f"candidate rollout size is outside the bounded contract: {relative_path}")
    metadata: dict[str, Any] | None = None
    inherited_total_usage: dict[str, int] | None = None
    previous_raw_total: dict[str, int] | None = None
    usage = _zero_token_usage()
    current_model: str | None = None
    pricing_groups: dict[tuple[str, bool], dict[str, Any]] = {}
    turn_started_count = 0
    turn_terminal_count = 0
    response_count = 0
    requests: list[dict[str, Any]] = []
    expected_child_thread_ids: set[str] = set()
    long_context_response_count = 0
    own_start_ordinal = 1
    ordinal = -1
    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if len(raw_line) > MAX_ROLLOUT_LINE_BYTES:
                raise EvaluationError(
                    f"candidate rollout line is oversized: {relative_path}:{line_number}"
                )
            if not raw_line.strip():
                continue
            ordinal += 1
            try:
                item = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvaluationError(
                    f"candidate rollout contains invalid JSON: {relative_path}:{line_number}"
                ) from exc
            if not isinstance(item, dict):
                raise EvaluationError(
                    f"candidate rollout line is not an object: {relative_path}:{line_number}"
                )
            item_type = item.get("type")
            payload = item.get("payload")
            if item_type == "session_meta":
                if metadata is not None or ordinal != 0 or not isinstance(payload, dict):
                    raise EvaluationError(
                        f"candidate rollout has an invalid session_meta: {relative_path}"
                    )
                metadata = dict(payload)
                boundary = metadata.get("subagent_history_start_ordinal")
                if boundary is not None:
                    if (
                        isinstance(boundary, bool)
                        or not isinstance(boundary, int)
                        or boundary < 1
                    ):
                        raise EvaluationError(
                            f"candidate rollout has an invalid subagent history boundary: {relative_path}"
                        )
                    own_start_ordinal = boundary
                continue
            if metadata is None:
                raise EvaluationError(f"candidate rollout does not begin with session_meta: {relative_path}")
            if ordinal < own_start_ordinal:
                if item_type == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                    info = payload.get("info")
                    if isinstance(info, dict):
                        inherited_total_usage = _nonnegative_token_usage(
                            info.get("total_token_usage"),
                            context=f"{relative_path}.inherited_total_token_usage",
                        )
                continue
            if item_type == "turn_context":
                if not isinstance(payload, dict) or not isinstance(payload.get("model"), str) or not payload["model"]:
                    raise EvaluationError(f"candidate rollout turn_context omits model: {relative_path}")
                current_model = str(payload["model"])
            elif item_type == "event_msg" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type == "item_completed" and isinstance(payload.get("item"), dict):
                    completed_item = payload["item"]
                    if completed_item.get("type") == "SubAgentActivity":
                        child_id = completed_item.get("agent_thread_id")
                        if isinstance(child_id, str) and child_id:
                            expected_child_thread_ids.add(child_id)
                if event_type in {"task_started", "turn_started"}:
                    turn_started_count += 1
                elif event_type in {"task_complete", "turn_complete", "turn_aborted"}:
                    turn_terminal_count += 1
                elif event_type == "token_count":
                    info = payload.get("info")
                    if info is None:
                        continue
                    if not isinstance(info, dict):
                        raise EvaluationError(
                            f"candidate rollout token_count info is invalid: {relative_path}"
                        )
                    total_usage = _nonnegative_token_usage(
                        info.get("total_token_usage"),
                        context=f"{relative_path}.total_token_usage",
                    )
                    last_usage = _nonnegative_token_usage(
                        info.get("last_token_usage"),
                        context=f"{relative_path}.last_token_usage",
                    )
                    if previous_raw_total is None:
                        if inherited_total_usage is not None and total_usage == inherited_total_usage:
                            previous_raw_total = total_usage
                            continue
                        candidates = [_zero_token_usage()]
                        if inherited_total_usage is not None:
                            candidates.insert(0, inherited_total_usage)
                        matching = [
                            candidate
                            for candidate in candidates
                            if all(total_usage[field] >= candidate[field] for field in CODEX_USAGE_FIELDS)
                            and _token_usage_delta(
                                total_usage,
                                candidate,
                                context=f"{relative_path}.first_usage_delta",
                            )
                            == last_usage
                        ]
                        if not matching:
                            raise EvaluationError(
                                f"candidate rollout first owned usage disagrees with its cumulative total: {relative_path}"
                            )
                    else:
                        if total_usage == previous_raw_total:
                            continue
                        if _token_usage_delta(
                            total_usage,
                            previous_raw_total,
                            context=f"{relative_path}.usage_delta",
                        ) != last_usage:
                            raise EvaluationError(
                                f"candidate rollout last usage disagrees with its cumulative total: {relative_path}"
                            )
                    previous_raw_total = total_usage
                    if last_usage["total_tokens"] == 0:
                        continue
                    if current_model is None:
                        raise EvaluationError(
                            f"candidate rollout usage has no owning turn_context model: {relative_path}"
                        )
                    _sum_token_usage(usage, last_usage)
                    priced = _price_response(pricing, current_model, last_usage)
                    response_count += 1
                    if response_count > 10_000:
                        raise EvaluationError("candidate rollout contains too many model responses")
                    requests.append(
                        {
                            "ordinal": response_count,
                            "model": priced["priced_model"],
                            "requested_model": priced["requested_model"],
                            "usage": last_usage,
                            "time": item.get("timestamp"),
                            "source_line": line_number,
                            "complete": True,
                        }
                    )
                    if priced["long_context"]:
                        long_context_response_count += 1
                    group_key = (str(priced["priced_model"]), bool(priced["long_context"]))
                    group = pricing_groups.setdefault(
                        group_key,
                        {
                            "model": priced["priced_model"],
                            "long_context": priced["long_context"],
                            "request_count": 0,
                            "cost_usd_nanos": 0,
                            "usage": _zero_token_usage(),
                            "requested_models": set(),
                        },
                    )
                    group["request_count"] += 1
                    group["cost_usd_nanos"] = (
                        None if group["cost_usd_nanos"] is None or priced["cost_usd_nanos"] is None
                        else group["cost_usd_nanos"] + int(priced["cost_usd_nanos"]))
                    _sum_token_usage(group["usage"], last_usage)
                    group["requested_models"].add(priced["requested_model"])
    if metadata is None:
        raise EvaluationError(f"candidate rollout omits session_meta: {relative_path}")
    thread_id = metadata.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise EvaluationError(f"candidate rollout session_meta omits id: {relative_path}")
    if turn_terminal_count > turn_started_count:
        raise EvaluationError(f"candidate rollout has impossible turn lifecycle: {relative_path}")
    usage_complete = turn_started_count == turn_terminal_count and (
        response_count > 0 or turn_started_count == 0
    )
    groups = []
    total_cost_usd_nanos = 0
    for key in sorted(pricing_groups):
        group = pricing_groups[key]
        total_cost_usd_nanos = (
            None if total_cost_usd_nanos is None or group["cost_usd_nanos"] is None
            else total_cost_usd_nanos + int(group["cost_usd_nanos"]))
        groups.append(
            {
                **{name: value for name, value in group.items() if name != "requested_models"},
                "requested_models": sorted(group["requested_models"]),
                "cost_usd": (format_usd_nanos(int(group["cost_usd_nanos"]))
                             if group["cost_usd_nanos"] is not None else None),
            }
        )
    return {
        "thread_id": thread_id,
        "parent_thread_id": _rollout_parent_thread_id(metadata),
        "forked_from_id": metadata.get("forked_from_id"),
        "agent_role": metadata.get("agent_role"),
        "agent_path": metadata.get("agent_path"),
        "agent_nickname": metadata.get("agent_nickname"),
        "turn_started_count": turn_started_count,
        "turn_terminal_count": turn_terminal_count,
        "usage_complete": usage_complete,
        "usage": usage,
        "request_count": response_count,
        "requests": requests,
        "long_context_request_count": long_context_response_count,
        "pricing_complete": usage_complete and total_cost_usd_nanos is not None,
        "api_equivalent_cost_usd_nanos": total_cost_usd_nanos,
        "api_equivalent_cost_usd": (format_usd_nanos(total_cost_usd_nanos)
                                    if total_cost_usd_nanos is not None else None),
        "pricing_groups": groups,
        "subagent_history_start_ordinal": metadata.get("subagent_history_start_ordinal"),
        "expected_child_thread_ids": sorted(expected_child_thread_ids),
        "rollout": {
            "path": relative_path,
            "sha256": sha256_file(path),
            "bytes": size,
        },
    }


def candidate_agent_usage_receipt(
    *,
    codex_home: Path,
    before: Mapping[str, Mapping[str, Any]],
    root_thread_id: str,
    root_usage: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate exact cumulative usage for the fresh root thread and every descendant."""

    pricing = api_pricing_snapshot()
    candidates = _candidate_rollouts_after_cursor(codex_home, before)
    if not candidates:
        raise EvaluationError("Codex candidate persisted no rollout usage evidence")
    new_entries = _candidate_rollout_lineage_entries(candidates, root_thread_id)
    if len(new_entries) > MAX_ATTEMPT_ROLLOUT_FILES:
        raise EvaluationError("Codex candidate created too many rollout files")
    if sum(int(entry["bytes"]) for entry in new_entries) > MAX_ATTEMPT_ROLLOUT_BYTES:
        raise EvaluationError("Codex candidate rollouts exceeded the aggregate byte bound")
    compressed = [entry["relative_path"] for entry in new_entries if str(entry["path"]).endswith(".zst")]
    if compressed:
        raise EvaluationError(
            "new Codex candidate rollouts were compressed before usage capture: "
            + ", ".join(compressed)
        )
    records = [
        _parse_candidate_rollout(
            Path(entry["path"]),
            str(entry["relative_path"]),
            pricing,
        )
        for entry in new_entries
    ]
    by_thread: dict[str, dict[str, Any]] = {}
    for record in records:
        thread_id = str(record["thread_id"])
        if thread_id in by_thread:
            raise EvaluationError(f"Codex candidate persisted duplicate thread rollouts: {thread_id}")
        by_thread[thread_id] = record
    root = by_thread.get(root_thread_id)
    if root is None:
        raise EvaluationError("Codex candidate root thread is absent from persisted rollouts")
    expected_root_usage = _nonnegative_token_usage(root_usage, context="root_usage")
    if root["usage"] != expected_root_usage:
        raise EvaluationError("persisted root usage disagrees with codex exec JSONL usage")

    descendants = {root_thread_id}
    pending = set(by_thread) - descendants
    while pending:
        discovered = {
            thread_id
            for thread_id in pending
            if by_thread[thread_id].get("parent_thread_id") in descendants
            or by_thread[thread_id].get("forked_from_id") in descendants
        }
        if not discovered:
            break
        descendants.update(discovered)
        pending.difference_update(discovered)
    expected_children = {
        child_id
        for thread_id in descendants
        for child_id in by_thread[thread_id].get("expected_child_thread_ids", [])
    }
    missing_children = expected_children - set(by_thread)
    if missing_children:
        raise EvaluationError(
            "Codex candidate child rollout evidence is missing: "
            + ", ".join(sorted(missing_children))
        )
    # Concurrent unrelated sessions may share the authenticated Codex home. They are
    # ignored after lineage selection and never enter this attempt's usage receipt.

    ordered_records = [root] + [by_thread[thread_id] for thread_id in sorted(descendants - {root_thread_id})]
    aggregate = _zero_token_usage()
    subagent = _zero_token_usage()
    aggregate_cost_usd_nanos = 0
    subagent_cost_usd_nanos = 0
    request_count = 0
    subagent_request_count = 0
    long_context_request_count = 0
    for record in ordered_records:
        _sum_token_usage(aggregate, record["usage"])
        record_cost = record["api_equivalent_cost_usd_nanos"]
        aggregate_cost_usd_nanos = (
            None if aggregate_cost_usd_nanos is None or record_cost is None
            else aggregate_cost_usd_nanos + int(record_cost))
        request_count += int(record["request_count"])
        long_context_request_count += int(record["long_context_request_count"])
        if record["thread_id"] != root_thread_id:
            _sum_token_usage(subagent, record["usage"])
            subagent_cost_usd_nanos = (
                None if subagent_cost_usd_nanos is None or record_cost is None
                else subagent_cost_usd_nanos + int(record_cost))
            subagent_request_count += int(record["request_count"])
    usage_complete = all(bool(record["usage_complete"]) for record in ordered_records)
    pricing_complete = usage_complete and all(
        bool(record["pricing_complete"]) for record in ordered_records
    )
    cost = {
        "schema": API_EQUIVALENT_COST_SCHEMA,
        "basis": pricing["basis"],
        "currency": pricing["currency"],
        "actual_billing_observed": False,
        "scope": "root-and-descendant-model-requests",
        "pricing_snapshot_sha256": pricing["identity_sha256"],
        "pricing_observed_at": pricing["observed_at"],
        "complete": pricing_complete,
        "request_count": request_count,
        "subagent_request_count": subagent_request_count,
        "long_context_request_count": long_context_request_count,
        "total_usd_nanos": aggregate_cost_usd_nanos,
        "root_usd_nanos": root["api_equivalent_cost_usd_nanos"],
        "subagent_usd_nanos": subagent_cost_usd_nanos,
        "total_usd": (format_usd_nanos(aggregate_cost_usd_nanos) if aggregate_cost_usd_nanos is not None else None),
        "root_usd": root["api_equivalent_cost_usd"],
        "subagent_usd": (format_usd_nanos(subagent_cost_usd_nanos) if subagent_cost_usd_nanos is not None else None),
        "unpriced_models": sorted({group["model"] for record in ordered_records
                                    for group in record["pricing_groups"] if group["cost_usd_nanos"] is None}),
    }
    payload = {
        "schema": CODEX_AGENT_USAGE_SCHEMA,
        "scope": "root-and-descendant-threads",
        "root_thread_id": root_thread_id,
        "thread_count": len(ordered_records),
        "subagent_thread_count": len(ordered_records) - 1,
        "usage_complete": usage_complete,
        "usage": aggregate,
        "subagent_usage": subagent,
        "api_equivalent_cost": cost,
        "threads": ordered_records,
    }
    return {**payload, "receipt_sha256": sha256_bytes(canonical_bytes(payload))}


def finalize_candidate_agent_usage(
    value: Mapping[str, Any],
    *,
    codex_home: Path,
    before: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    result = dict(value)
    if result.get("model_invoked") is not True:
        return result
    root_thread_id = result.get("root_thread_id")
    root_usage = result.get("root_usage")
    if not isinstance(root_thread_id, str) or not root_thread_id:
        raise EvaluationError("Codex candidate result omits root_thread_id")
    if not isinstance(root_usage, Mapping):
        raise EvaluationError("Codex candidate result omits root_usage")
    receipt = candidate_agent_usage_receipt(
        codex_home=codex_home,
        before=before,
        root_thread_id=root_thread_id,
        root_usage=root_usage,
    )
    result.update(
        {
            "usage_scope": receipt["scope"],
            "usage_complete": receipt["usage_complete"],
            "usage": receipt["usage"],
            "subagent_usage": receipt["subagent_usage"],
            "agent_thread_count": receipt["thread_count"],
            "subagent_thread_count": receipt["subagent_thread_count"],
            "agent_usage": receipt["threads"],
            "agent_usage_receipt_sha256": receipt["receipt_sha256"],
            "api_equivalent_cost": receipt["api_equivalent_cost"],
        }
    )
    if result["usage_complete"]:
        result.pop("usage_collection_error", None)
    return result


def _candidate_transport_overrides(
    project_root: Path,
    corpus: Mapping[str, Any],
) -> list[str]:
    overlay_path = (
        project_root.resolve()
        / "development"
        / "agent-evaluation"
        / str(corpus["codex"]["transport_overlay"])
    )
    try:
        overlay = tomllib.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvaluationError(f"cannot read candidate transport overlay: {exc}") from exc
    provider_id = overlay.get("model_provider")
    providers = overlay.get("model_providers")
    if (
        not isinstance(provider_id, str)
        or not provider_id
        or not isinstance(providers, Mapping)
        or set(providers) != {provider_id}
        or not isinstance(providers[provider_id], Mapping)
    ):
        raise EvaluationError("candidate transport overlay has an invalid provider shape")
    overrides = [f"model_provider={_toml_value(provider_id)}"]
    for key, value in sorted(providers[provider_id].items()):
        if isinstance(value, Mapping):
            raise EvaluationError("candidate transport overlay contains a nested provider table")
        overrides.append(
            f"model_providers.{_toml_key(provider_id)}.{_toml_key(str(key))}="
            + _toml_value(value)
        )
    return overrides


def _validate_candidate_projection(
    workspace: Path,
    metadata: Mapping[str, Any],
) -> None:
    resolved_workspace = workspace.resolve()
    projection = metadata.get("codex_projection")
    if not isinstance(projection, Mapping):
        raise EvaluationError("candidate Codex projection is missing")
    files = projection.get("files")
    if not isinstance(files, list) or not files:
        raise EvaluationError("candidate Codex projection has no files")
    for entry in files:
        if not isinstance(entry, Mapping):
            raise EvaluationError("candidate Codex projection file entry is invalid")
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative.startswith(".codex/"):
            raise EvaluationError("candidate Codex projection path is invalid")
        path = require_within(resolved_workspace, resolved_workspace / relative)
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != entry.get("sha256")
            or path.stat().st_size != entry.get("bytes")
        ):
            raise EvaluationError(f"candidate Codex projection changed: {relative}")
    skill_root = Path(str(metadata.get("skill_root_path", ""))).resolve()
    expected_skill_root = resolved_workspace / ".agents" / "skills"
    if skill_root != expected_skill_root:
        raise EvaluationError("candidate skill projection root changed")
    skill_entries = _skill_tree_entries(skill_root)
    if (
        len(skill_entries) != metadata.get("expected_skill_file_count")
        or sha256_bytes(canonical_bytes(skill_entries))
        != metadata.get("skill_projection_identity_sha256")
    ):
        raise EvaluationError("candidate skill projection changed before launch")


def invoke_candidate(
    *,
    project_root: Path,
    workspace: Path,
    attempt_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    profile_name: str,
    metadata: Mapping[str, Any],
    process_environment: Mapping[str, str],
    codex_executable_path: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a candidate as a normal trusted local Codex process."""

    if os.environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED") == "1":
        raise EvaluationError("candidate model evaluator is disabled by the deterministic test gate")
    if codex_executable_path is None:
        raise EvaluationError("candidate runtime requires the resolved Codex executable")
    _validate_candidate_projection(workspace, metadata)
    profile = require_profile(corpus, profile_name)
    result_path = attempt_root.resolve() / "codex-result.json"
    task_runtime = metadata.get("task_runtime")
    if not isinstance(task_runtime, Mapping):
        raise EvaluationError("candidate task runtime projection is missing")
    task_runtime_bin = task_runtime.get("bin_directory")
    if not isinstance(task_runtime_bin, str) or not Path(task_runtime_bin).is_dir():
        raise EvaluationError("candidate task runtime bin directory is missing")
    argv = [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(project_root.resolve() / "development" / "agent-evaluation" / "invoke_candidate.ps1"),
        "-ProjectRoot",
        str(project_root.resolve()),
        "-Workspace",
        str(workspace.resolve()),
        "-InstalledCodexRoot",
        str(installed_codex_root.resolve()),
        "-PromptPath",
        str(Path(str(metadata["prompt_path"])).resolve()),
        "-ResultPath",
        str(result_path),
        "-Model",
        str(profile["model"]),
        "-ReasoningEffort",
        str(profile["reasoning_effort"]),
        "-CodexExecutablePath",
        str(codex_executable_path.resolve()),
        "-TaskRuntimeBinPath",
        str(Path(task_runtime_bin).resolve()),
        "-TimeoutSeconds",
        str(timeout_seconds),
        "-ConfigOverride",
        *_candidate_transport_overrides(project_root, corpus),
    ]
    rollouts_before = candidate_rollout_snapshot(installed_codex_root)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(workspace.resolve()),
            env=dict(process_environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds + 300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvaluationError(f"candidate launcher failed: {exc}") from exc
    if result_path.is_file():
        preliminary = read_json(result_path)
        if (
            preliminary.get("schema") == CODEX_RUN_RESULT_SCHEMA
            and preliminary.get("model_invoked") is True
        ):
            preliminary = finalize_candidate_agent_usage(
                preliminary,
                codex_home=installed_codex_root,
                before=rollouts_before,
            )
            write_json_atomic(result_path, preliminary)
    if completed.returncode != 0:
        detail = bounded_text(
            (completed.stderr + completed.stdout).decode("utf-8", errors="replace"),
            800,
        )
        raise EvaluationError(f"candidate launcher failed ({completed.returncode}): {detail}")
    value = read_json(result_path)
    if (
        value.get("schema") != CODEX_RUN_RESULT_SCHEMA
        or value.get("status") != "completed"
        or value.get("model_invoked") is not True
        or value.get("exit_code") != 0
        or value.get("execution_environment") != "trusted-local-workspace"
        or not isinstance(value.get("agent_usage"), list)
        or value.get("agent_thread_count") != len(value["agent_usage"])
        or not isinstance(value.get("agent_usage_receipt_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["agent_usage_receipt_sha256"])
        or not isinstance(value.get("api_equivalent_cost"), dict)
        or value["api_equivalent_cost"].get("schema") != API_EQUIVALENT_COST_SCHEMA
        or value["api_equivalent_cost"].get("complete") is not True
        or value["api_equivalent_cost"].get("actual_billing_observed") is not False
    ):
        raise EvaluationError("candidate launcher returned an invalid trusted-local result")
    return dict(value)
