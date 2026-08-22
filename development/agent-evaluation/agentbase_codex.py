"""Stage and invoke the real AgentBase candidate inside the Windows sandbox."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
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
    read_json,
    require_profile,
    require_task,
    run_capture,
    sha256_bytes,
    sha256_file,
    task_asset_root,
    write_text_atomic,
)


BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
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


def is_elevated_sandbox_setup_error(diagnostic: str) -> bool:
    normalized = diagnostic.casefold()
    return any(
        signature in normalized
        for signature in (
            "orchestrator_helper_launch_canceled",
            "shellexecuteexw failed to launch setup helper",
            "requires the elevated windows sandbox backend",
        )
    )


VERSION_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "srcq": ("--version",),
    "rg": ("--version",),
    "fd": ("--version",),
    "scc": ("--version",),
    "hyperfine": ("--version",),
    "ast-grep": ("--version",),
    "git": ("--version",),
    "pwsh": ("-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"),
    "python": ("--version",),
    "node": ("--version",),
}

SRCQ_SMOKE_CHECKS = (
    "ast-cache",
    "rg-pagination",
    "fd-tree",
    "scc-machine",
    "artifact",
)


def _resolved_shell_environment_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return resolve_shell_environment_policy()
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc
def candidate_capability_contract(
    project_root: Path,
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    root = project_root.resolve()
    try:
        portable_config = tomllib.loads((root / "global" / "config.toml").read_text(encoding="utf-8"))
        agent_profiles = {
            path.stem: tomllib.loads(path.read_text(encoding="utf-8"))
            for path in sorted((root / "global" / "agents").glob("*.toml"))
        }
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvaluationError(f"cannot derive candidate capability contract: {exc}") from exc
    skill_names = sorted(
        path.parent.name for path in (root / "skills").glob("*/SKILL.md") if path.is_file()
    )
    if not skill_names or not agent_profiles:
        raise EvaluationError("candidate capability surface omits skills or custom agents")
    shell_policy_descriptor, _ = _resolved_shell_environment_policy()
    agents = portable_config.get("agents", {})
    features = portable_config.get("features", {})
    if agents.get("enabled") is not True or features.get("multi_agent") is not True:
        raise EvaluationError("portable candidate config must enable custom agents and multi-agent")
    evaluator_profiles = {
        name: {
            "model": profile["model"],
            "reasoning_effort": profile["reasoning_effort"],
        }
        for name, profile in corpus["profiles"].items()
    }
    actual_profiles = {
        name: {
            "model": value.get("model"),
            "reasoning_effort": value.get("model_reasoning_effort"),
        }
        for name, value in agent_profiles.items()
    }
    package_managers = sorted(
        {
            str(task["toolchain"]["package_manager"])
            for task in corpus["tasks"]
            if task["toolchain"].get("package_manager")
        }
    )
    toolchain_kinds = sorted({str(task["toolchain"]["kind"]) for task in corpus["tasks"]})
    surface = candidate_surface_identity(root)
    return {
        "schema": "agentbase.windows-swe-candidate-capabilities/v4",
        "candidate_surface_identity_sha256": surface["identity_sha256"],
        "evaluator_profiles": evaluator_profiles,
        "projected_assets": {
            "global_rules": "global/AGENTS.md",
            "portable_config": "global/config.toml with evaluation transport overrides",
            "custom_agents": actual_profiles,
            "skills": {
                "names": skill_names,
                "count": len(skill_names),
                "discovery_root": ".agents/skills",
                "full_tree_hash_pinned": True,
                "full_tree_readable_before_model": True,
                "projection_read_only": True,
                "derived_per_attempt": True,
            },
        },
        "configured_capabilities": {
            "candidate_model_actions": {
                "target_repository_instructions": "read from the fixed task base tree",
                "workspace_read": True,
                "workspace_write": True,
                "shell": True,
                "apply_patch": True,
                "public_test_execution": True,
                "shell_environment_secret_filtered": True,
                "shell_environment_policy_sha256": shell_policy_descriptor["sha256"],
                "requires_candidate_model_evidence": True,
            },
            "sandbox": {
                "implementation": corpus["codex"]["sandbox_implementation"],
                "permission_profile": corpus["codex"]["candidate_permission_profile"],
                "network_enabled": False,
                "host_filesystem_default_denied": True,
                "minimal_runtime_readable": True,
                "project_root_denied": True,
                "state_root_denied": True,
                "installed_codex_root_denied": True,
                "attempt_tmpdir_only": True,
                "process_appdata_scoped_to_tmpdir": True,
                "skill_projection_read_only": True,
            },
            "multi_agent": {
                "configured": True,
                "runtime_exercised_by_swe": False,
                "requires_explicit_model_evidence": True,
                "default_model": agents.get("default_subagent_model"),
                "default_reasoning_effort": agents.get("default_subagent_reasoning_effort"),
            },
        },
        "runtime_identity_contract": {
            "base_cli_tools": sorted([*REQUIRED_CANDIDATE_TOOLS, "codex"]),
            "task_toolchains": {
                "kinds": toolchain_kinds,
                "package_managers": package_managers,
            },
            "base_recorded_before_candidate_model": True,
            "task_toolchain_recorded_by_dependency_identity": True,
        },
        "runtime_probe_contract": {
            "state_root_unreadable": True,
            "staged_auth_unreadable": True,
            "installed_auth_unreadable": True,
            "project_root_probe_unreadable": True,
            "skill_projection_manifest_hash_pinned": True,
            "all_skill_files_hash_readable": True,
            "skill_projection_write_denied": True,
            "workspace_write_probe": True,
            "process_temp_scoped_to_attempt_tmpdir": True,
            "process_appdata_scoped_to_attempt_tmpdir": True,
            "preflight_receipt_persisted_by_launcher": True,
            "srcq_doctor": True,
            "srcq_scc_doctor": True,
            "srcq_ast_cache_round_trip": True,
            "srcq_rg_model_pagination_round_trip": True,
            "srcq_fd_tree_projection": True,
            "srcq_scc_machine_projection": True,
            "srcq_artifact_round_trip": True,
            "base_cli_exact_identity_probes": sorted(REQUIRED_CANDIDATE_TOOLS),
            "tool_probe_manifest_hash_pinned": True,
            "task_dependency_runtime_added_per_candidate_run": True,
            "network_runtime_probe": False,
            "performed_before_candidate_model": True,
        },
        "separate_evidence_owners": [
            {
                "capability": "routing-behavior",
                "owner": "development/skill-routing",
                "reason": "behavioral evaluator is intentionally detached from SWE task execution",
            },
            {
                "capability": "vscode-lsp-mcp",
                "owner": "mcp/vscode-lsp-mcp",
                "reason": "host MCP lifecycle and runtime are not injected into the SWE sandbox",
            },
            {
                "capability": "custom-subagent-runtime-behavior",
                "owner": "development/agent-evaluation model runs",
                "reason": "configuration is projected, but behavior evidence requires an explicit token-consuming candidate run",
            },
            {
                "capability": "skill-dependent-host-services",
                "owner": "each skill component and its host integration",
                "reason": "the full skill tree is readable, while host/thread/MCP-dependent behavior remains separately qualified",
            },
            {
                "capability": "hooks-event-logging-and-qq",
                "owner": "global/hooks.template.json and their component validators",
                "reason": "hooks are disabled in the SWE transport",
            },
            {
                "capability": "plugin-packaging-and-deployment",
                "owner": "development/codex-deployment",
                "reason": "installation and publication are outside candidate authority",
            },
        ],
        "excluded_from_swe": [
            "network",
            "web-search",
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


def candidate_config_identity_descriptor(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    *,
    shell_policy_descriptor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_path = project_root.resolve() / "global" / "config.toml"
    overlay_path = (
        project_root.resolve()
        / "development"
        / "agent-evaluation"
        / str(corpus["codex"]["transport_overlay"])
    )
    if shell_policy_descriptor is None:
        shell_policy_descriptor, _ = _resolved_shell_environment_policy()
    return {
        "candidate_config_sha256": sha256_file(candidate_path),
        "transport_overlay_sha256": sha256_file(overlay_path),
        "permission_profile": corpus["codex"]["candidate_permission_profile"],
        "host_filesystem_default_denied": True,
        "minimal_runtime_readable": True,
        "project_root_denied": str(project_root.resolve()),
        "state_root_denied": str(state_root.resolve()),
        "installed_codex_root_denied": str(installed_codex_root.resolve()),
        "codex_home_under_denied_state": True,
        "attempt_tmpdir_reopened": True,
        "process_appdata_scoped_to_tmpdir": True,
        "shell_environment_secret_filtered": True,
        "shell_environment_policy_sha256": str(shell_policy_descriptor["sha256"]),
        "repository_skill_projection": ".agents/skills read-only derived copy",
        "sandbox": corpus["codex"]["sandbox_implementation"],
        "network": False,
    }


def build_candidate_config(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    candidate_path = project_root.resolve() / "global" / "config.toml"
    overlay_path = (
        project_root.resolve()
        / "development"
        / "agent-evaluation"
        / str(corpus["codex"]["transport_overlay"])
    )
    resolved_state = state_root.resolve()
    try:
        candidate = tomllib.loads(candidate_path.read_text(encoding="utf-8"))
        overlay = tomllib.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvaluationError(f"cannot build candidate Codex config: {exc}") from exc
    candidate.pop("sandbox_mode", None)
    candidate["approval_policy"] = "never"
    candidate["web_search"] = "disabled"
    candidate["default_permissions"] = str(corpus["codex"]["candidate_permission_profile"])
    shell_policy_descriptor, shell_policy = _resolved_shell_environment_policy()
    candidate["shell_environment_policy"] = shell_policy
    candidate.setdefault("windows", {})["sandbox"] = str(
        corpus["codex"]["sandbox_implementation"]
    )
    candidate.setdefault("features", {})["hooks"] = False
    candidate["permissions"] = {
        str(corpus["codex"]["candidate_permission_profile"]): {
            "filesystem": {
                ":root": "deny",
                ":minimal": "read",
                ":tmpdir": "write",
                ":workspace_roots": {
                    ".": "write",
                    ".agents/skills": "read",
                    ".codex": "read",
                    ".git": "read",
                    "**/*.env": "deny",
                },
                str(project_root.resolve()): "deny",
                str(resolved_state): "deny",
                str(installed_codex_root.resolve()): "deny",
            },
            "network": {"enabled": False},
        }
    }
    merged = _merge_without_overlap(candidate, overlay)
    if (
        merged.get("agents", {}).get("enabled") is not True
        or merged.get("features", {}).get("multi_agent") is not True
    ):
        raise EvaluationError("candidate transport must preserve custom-agent and multi-agent settings")
    text = _serialize_toml(
        merged,
        [
            "# Generated by AgentBase Windows SWE; do not edit.",
            "# Host files default to deny; only minimal runtime paths, the workspace, and the per-attempt tmpdir are usable.",
            "# Skills are a hash-pinned read-only workspace projection; state and installed Codex roots stay denied.",
        ],
    )
    descriptor = {
        "identity": candidate_config_identity_descriptor(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
            shell_policy_descriptor=shell_policy_descriptor,
        ),
        "effective_config_sha256": sha256_bytes(text.encode("utf-8")),
    }
    return text, descriptor


def build_verifier_config(corpus: Mapping[str, Any]) -> str:
    profile = str(corpus["codex"]["verifier_permission_profile"])
    value = {
        "approval_policy": "never",
        "default_permissions": profile,
        "web_search": "disabled",
        "permissions": {
            profile: {
                "extends": ":workspace",
                "network": {"enabled": False},
            }
        },
        "windows": {"sandbox": str(corpus["codex"]["sandbox_implementation"])},
        "features": {"hooks": False, "multi_agent": False},
    }
    return _serialize_toml(
        value,
        [
            "# Generated verifier sandbox config; no model is run from this home.",
        ],
    )


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


def resolve_codex_identity(
    project_root: Path,
    output_path: Path,
    explicit_path: Path | None = None,
) -> dict[str, Any]:
    helper = project_root.resolve() / "development" / "agent-evaluation" / "invoke_candidate.ps1"
    argv = [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(helper),
        "-Action",
        "Resolve",
        "-ProjectRoot",
        str(project_root.resolve()),
        "-ResultPath",
        str(output_path.resolve()),
    ]
    if explicit_path is not None:
        argv.extend(["-CodexExecutablePath", str(explicit_path.resolve())])
    run_capture(argv, timeout=120)
    value = read_json(output_path)
    if value.get("schema") != "agentbase.codex-cli-identity/v1":
        raise EvaluationError("Codex resolver returned an invalid identity")
    path = Path(str(value.get("path", "")))
    if not path.is_file() or sha256_file(path) != value.get("sha256"):
        raise EvaluationError("Codex executable identity changed after resolution")
    return dict(value)


def candidate_runtime_tools(
    project_root: Path,
    runtime_root: Path,
    explicit_codex_path: Path | None = None,
) -> dict[str, Any]:
    tools = {
        name: _tool_identity(name, _resolve_application(candidates))
        for name, candidates in REQUIRED_CANDIDATE_TOOLS.items()
    }
    codex_result = runtime_root.resolve() / "codex-identity.json"
    codex_result.parent.mkdir(parents=True, exist_ok=True)
    tools["codex"] = resolve_codex_identity(
        project_root,
        codex_result,
        explicit_codex_path,
    )
    payload = {"tools": tools}
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def candidate_tool_probe_manifest(
    runtime_tools: Mapping[str, Any],
    *,
    task: Mapping[str, Any] | None = None,
    dependency_identity: Mapping[str, Any] | None = None,
    dependency_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    tools = runtime_tools.get("tools")
    if not isinstance(tools, dict):
        raise EvaluationError("candidate runtime identity omits its tools")
    probes = []
    for name in REQUIRED_CANDIDATE_TOOLS:
        identity = tools.get(name)
        if not isinstance(identity, dict):
            raise EvaluationError(f"candidate runtime identity omits {name}")
        path = Path(str(identity.get("path", ""))).resolve()
        expected_sha256 = str(identity.get("sha256", ""))
        if not path.is_file() or sha256_file(path) != expected_sha256:
            raise EvaluationError(f"candidate runtime tool changed before probe staging: {name}")
        probes.append(
            {
                "id": name,
                "path": str(path),
                "sha256": expected_sha256,
                "argv": list(VERSION_ARGUMENTS[name]),
            }
        )
    if task is not None:
        if dependency_identity is None or dependency_values is None:
            raise EvaluationError("task tool probes require dependency identity and values")
        toolchain = task.get("toolchain")
        if not isinstance(toolchain, dict):
            raise EvaluationError("task toolchain is invalid")
        dependency_tools = dependency_identity.get("tools")
        expected_dependency_names = (
            {"python"}
            if toolchain.get("kind") == "python"
            else {"node", str(toolchain.get("package_manager") or "")}
        )
        if "" in expected_dependency_names or not isinstance(dependency_tools, dict):
            raise EvaluationError("task dependency identity omits its runtime tool")
        if set(dependency_tools) != expected_dependency_names:
            raise EvaluationError("task dependency identity has an unexpected runtime tool set")
        for dependency_name in sorted(expected_dependency_names):
            dependency_tool = dependency_tools.get(dependency_name)
            dependency_path_value = dependency_values.get(dependency_name)
            if not isinstance(dependency_tool, dict) or not dependency_path_value:
                raise EvaluationError(f"task dependency runtime omits {dependency_name}")
            dependency_path = Path(str(dependency_path_value)).resolve()
            dependency_sha256 = str(dependency_tool.get("sha256", ""))
            if not dependency_path.is_file() or sha256_file(dependency_path) != dependency_sha256:
                raise EvaluationError(
                    f"task dependency tool changed before probe staging: {dependency_name}"
                )
            base_identity = tools.get(dependency_name)
            if (
                isinstance(base_identity, dict)
                and Path(str(base_identity.get("path", ""))).resolve() == dependency_path
                and str(base_identity.get("sha256", "")) == dependency_sha256
            ):
                continue
            probes.append(
                {
                    "id": f"task-{dependency_name}",
                    "path": str(dependency_path),
                    "sha256": dependency_sha256,
                    "argv": ["--version"],
                }
            )
    probes.sort(key=lambda item: str(item["id"]))
    return {
        "schema": "agentbase.windows-swe-tool-probes/v1",
        "probes": probes,
    }


def stage_candidate_tool_probe_manifest(
    metadata_root: Path,
    runtime_tools: Mapping[str, Any],
    *,
    task: Mapping[str, Any] | None = None,
    dependency_identity: Mapping[str, Any] | None = None,
    dependency_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    manifest = candidate_tool_probe_manifest(
        runtime_tools,
        task=task,
        dependency_identity=dependency_identity,
        dependency_values=dependency_values,
    )
    path = metadata_root.resolve() / "runtime-probe" / "tool-probes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "expected_tools": {
            str(item["id"]): str(item["sha256"])
            for item in manifest["probes"]
        },
    }


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


def stage_candidate_home(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    runtime_root: Path,
    corpus: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    home = runtime_root.resolve() / "codex-home"
    if home.exists():
        raise EvaluationError(f"candidate Codex home already exists: {home}")
    home.mkdir(parents=True)
    shutil.copy2(project_root / "global" / "AGENTS.md", home / "AGENTS.md")
    shutil.copytree(project_root / "global" / "agents", home / "agents")
    config_text, descriptor = build_candidate_config(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
    )
    write_text_atomic(home / "config.toml", config_text)
    descriptor["staged_home_sha256"] = sha256_bytes(
        canonical_bytes(
            sorted(
                (str(path.relative_to(home)).replace("\\", "/"), sha256_file(path))
                for path in home.rglob("*")
                if path.is_file()
            )
        )
    )
    return home, descriptor


def stage_verifier_home(runtime_root: Path, corpus: Mapping[str, Any]) -> Path:
    home = runtime_root.resolve() / "verifier-codex-home"
    if home.exists():
        raise EvaluationError(f"verifier Codex home already exists: {home}")
    home.mkdir(parents=True)
    write_text_atomic(home / "config.toml", build_verifier_config(corpus))
    return home


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


def stage_candidate_metadata(
    project_root: Path,
    state_root: Path,
    corpus: Mapping[str, Any],
    task_id: str,
    workspace: Path,
    attempt_root: Path,
    runtime_tools: Mapping[str, Any],
    dependency_identity: Mapping[str, Any],
    dependency_values: Mapping[str, str],
) -> dict[str, Any]:
    metadata = workspace.resolve() / ".agentbase"
    metadata.mkdir(parents=True, exist_ok=False)
    instruction_source = task_asset_root(state_root, corpus, task_id) / "instruction.md"
    shutil.copy2(instruction_source, metadata / "task.md")
    preflight_source = (
        project_root.resolve()
        / "development"
        / "agent-evaluation"
        / "candidate_preflight.ps1"
    )
    shutil.copy2(preflight_source, metadata / "preflight.ps1")
    canary = attempt_root.resolve() / "held-out" / "canary.txt"
    canary.parent.mkdir(parents=True, exist_ok=True)
    canary_value = os.urandom(32).hex()
    write_text_atomic(canary, canary_value + "\n")
    output = metadata / "preflight.json"
    task = require_task(corpus, task_id)
    public_tooling = candidate_public_tooling_hint(task)
    patch_scope = candidate_patch_scope_hint(task)
    prompt = (
        "Complete the repository task described in .agentbase/task.md.\n"
        "The evaluation has already checked the AgentBase toolchain and hidden-state isolation "
        "under your exact Windows permission profile. Do not inspect paths outside this workspace.\n"
        "Use the repository instructions and AgentBase tools, implement the task, and run useful "
        "public checks.\n"
        f"{patch_scope}"
        f"{public_tooling}"
        "Finish with the working tree containing only the intended source solution; the evaluator "
        "will extract a Git patch and run held-out tests in a separate clean workspace.\n"
    )
    prompt_path = attempt_root.resolve() / "candidate-prompt.txt"
    write_text_atomic(prompt_path, prompt)
    skill_projection = stage_candidate_skill_projection(
        project_root,
        workspace,
        metadata,
    )
    tool_probe = stage_candidate_tool_probe_manifest(
        metadata,
        runtime_tools,
        task=task,
        dependency_identity=dependency_identity,
        dependency_values=dependency_values,
    )
    return {
        "metadata_root": str(metadata),
        "canary_path": str(canary),
        "preflight_output_path": str(output),
        "prompt_path": str(prompt_path),
        "skill_root_path": skill_projection["root"],
        "skill_probe_manifest_path": skill_projection["manifest_path"],
        "skill_probe_manifest_sha256": skill_projection["manifest_sha256"],
        "skill_projection_identity_sha256": skill_projection[
            "projection_identity_sha256"
        ],
        "expected_skill_file_count": skill_projection["file_count"],
        "tool_probe_manifest_path": tool_probe["path"],
        "tool_probe_manifest_sha256": tool_probe["sha256"],
        "expected_tool_probes": tool_probe["expected_tools"],
    }


def _candidate_preflight_has_valid_shape(
    preflight: Mapping[str, Any],
    *,
    expected_skill_file_count: int,
    expected_skill_probe_manifest_sha256: str,
    expected_tool_probes: Mapping[str, str],
    expected_tool_probe_manifest_sha256: str,
) -> bool:
    if (
        isinstance(expected_skill_file_count, bool)
        or expected_skill_file_count < 1
        or not re.fullmatch(r"[0-9a-f]{64}", expected_skill_probe_manifest_sha256)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_tool_probe_manifest_sha256)
        or not expected_tool_probes
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            for name, expected_sha256 in expected_tool_probes.items()
        )
    ):
        return False
    probes = preflight.get("tool_probes")
    expected_tools = dict(expected_tool_probes)
    manifest_readable = preflight.get("tool_probe_manifest_readable")
    manifest_sha256 = preflight.get("tool_probe_manifest_sha256")
    manifest_error = preflight.get("tool_probe_manifest_error_type")
    manifest_ready = (
        manifest_readable is True
        and manifest_sha256 == expected_tool_probe_manifest_sha256
        and manifest_error is None
    )
    actual_tool_names = set(probes) if isinstance(probes, dict) else set()
    expected_tool_names = set(expected_tools)
    tool_names_valid = (
        actual_tool_names == expected_tool_names if manifest_ready else not actual_tool_names
    )
    skill_manifest_sha256 = preflight.get("skill_probe_manifest_sha256")
    skill_manifest_error = preflight.get("skill_probe_manifest_error_type")
    skill_files_expected = preflight.get("skill_files_expected")
    skill_files_verified = preflight.get("skill_files_verified")
    srcq_smoke = preflight.get("srcq_smoke")

    def probe_has_valid_shape(name: str) -> bool:
        probe = probes[name]
        if not isinstance(probe, dict):
            return False
        observed_sha256 = probe.get("observed_sha256")
        return (
            probe.get("expected_sha256") == expected_tools[name]
            and (
                observed_sha256 is None
                or (isinstance(observed_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", observed_sha256))
            )
            and isinstance(probe.get("exit_code"), int)
            and not isinstance(probe.get("exit_code"), bool)
            and isinstance(probe.get("summary"), str)
        )

    def smoke_has_valid_shape(name: str) -> bool:
        if not isinstance(srcq_smoke, dict) or name not in srcq_smoke:
            return False
        item = srcq_smoke[name]
        return (
            isinstance(item, dict)
            and set(item) == {"passed", "summary"}
            and isinstance(item.get("passed"), bool)
            and isinstance(item.get("summary"), str)
        )

    return (
        preflight.get("schema") == "agentbase.windows-swe-preflight/v9"
        and isinstance(preflight.get("passed"), bool)
        and isinstance(preflight.get("canary_readable"), bool)
        and isinstance(preflight.get("auth_readable"), bool)
        and isinstance(preflight.get("installed_auth_readable"), bool)
        and isinstance(preflight.get("project_canary_readable"), bool)
        and isinstance(preflight.get("skill_probe_manifest_readable"), bool)
        and (
            skill_manifest_sha256 is None
            or (
                isinstance(skill_manifest_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", skill_manifest_sha256)
            )
        )
        and (skill_manifest_error is None or isinstance(skill_manifest_error, str))
        and isinstance(preflight.get("skill_projection_readable"), bool)
        and isinstance(preflight.get("skill_projection_write_denied"), bool)
        and (
            preflight.get("skill_projection_error_type") is None
            or isinstance(preflight.get("skill_projection_error_type"), str)
        )
        and (
            preflight.get("skill_projection_write_error_type") is None
            or isinstance(preflight.get("skill_projection_write_error_type"), str)
        )
        and isinstance(skill_files_expected, int)
        and not isinstance(skill_files_expected, bool)
        and skill_files_expected >= 0
        and isinstance(skill_files_verified, int)
        and not isinstance(skill_files_verified, bool)
        and 0 <= skill_files_verified <= skill_files_expected
        and isinstance(preflight.get("workspace_write_probe_passed"), bool)
        and isinstance(preflight.get("runtime_temp_attempt_scoped"), bool)
        and isinstance(preflight.get("runtime_appdata_attempt_scoped"), bool)
        and isinstance(preflight.get("runtime_localappdata_attempt_scoped"), bool)
        and (
            preflight.get("runtime_state_error_type") is None
            or isinstance(preflight.get("runtime_state_error_type"), str)
        )
        and isinstance(manifest_readable, bool)
        and (
            manifest_sha256 is None
            or (
                isinstance(manifest_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
            )
        )
        and (manifest_error is None or isinstance(manifest_error, str))
        and isinstance(preflight.get("srcq_doctor_exit_code"), int)
        and not isinstance(preflight.get("srcq_doctor_exit_code"), bool)
        and isinstance(preflight.get("srcq_scc_doctor_exit_code"), int)
        and not isinstance(preflight.get("srcq_scc_doctor_exit_code"), bool)
        and isinstance(probes, dict)
        and tool_names_valid
        and all(probe_has_valid_shape(name) for name in actual_tool_names)
        and isinstance(srcq_smoke, dict)
        and set(srcq_smoke) == set(SRCQ_SMOKE_CHECKS)
        and all(smoke_has_valid_shape(name) for name in SRCQ_SMOKE_CHECKS)
    )


def _candidate_preflight_is_valid(
    preflight: Mapping[str, Any],
    *,
    expected_skill_file_count: int,
    expected_skill_probe_manifest_sha256: str,
    expected_tool_probes: Mapping[str, str],
    expected_tool_probe_manifest_sha256: str,
) -> bool:
    return (
        _candidate_preflight_has_valid_shape(
            preflight,
            expected_skill_file_count=expected_skill_file_count,
            expected_skill_probe_manifest_sha256=expected_skill_probe_manifest_sha256,
            expected_tool_probes=expected_tool_probes,
            expected_tool_probe_manifest_sha256=expected_tool_probe_manifest_sha256,
        )
        and preflight.get("passed") is True
        and preflight.get("canary_readable") is False
        and preflight.get("auth_readable") is False
        and preflight.get("installed_auth_readable") is False
        and preflight.get("project_canary_readable") is False
        and preflight.get("skill_probe_manifest_readable") is True
        and preflight.get("skill_probe_manifest_sha256")
        == expected_skill_probe_manifest_sha256
        and preflight.get("skill_probe_manifest_error_type") is None
        and preflight.get("skill_projection_readable") is True
        and preflight.get("skill_projection_write_denied") is True
        and preflight.get("skill_projection_error_type") is None
        and preflight.get("skill_files_expected") == expected_skill_file_count
        and preflight.get("skill_files_verified") == expected_skill_file_count
        and preflight.get("workspace_write_probe_passed") is True
        and preflight.get("runtime_temp_attempt_scoped") is True
        and preflight.get("runtime_appdata_attempt_scoped") is True
        and preflight.get("runtime_localappdata_attempt_scoped") is True
        and preflight.get("runtime_state_error_type") is None
        and preflight.get("tool_probe_manifest_readable") is True
        and preflight.get("tool_probe_manifest_sha256")
        == expected_tool_probe_manifest_sha256
        and preflight.get("tool_probe_manifest_error_type") is None
        and preflight.get("srcq_doctor_exit_code") == 0
        and preflight.get("srcq_scc_doctor_exit_code") == 0
        and all(preflight["srcq_smoke"][name]["passed"] for name in SRCQ_SMOKE_CHECKS)
        and all(
            preflight["tool_probes"][name]["expected_sha256"] == expected_sha256
            and preflight["tool_probes"][name]["observed_sha256"] == expected_sha256
            and preflight["tool_probes"][name]["exit_code"] == 0
            and bool(preflight["tool_probes"][name]["summary"].strip())
            for name, expected_sha256 in expected_tool_probes.items()
        )
    )


def candidate_preflight_failed_checks(
    preflight: Mapping[str, Any],
    *,
    expected_skill_file_count: int,
    expected_skill_probe_manifest_sha256: str,
    expected_tool_probes: Mapping[str, str],
    expected_tool_probe_manifest_sha256: str,
) -> list[str]:
    if not _candidate_preflight_has_valid_shape(
        preflight,
        expected_skill_file_count=expected_skill_file_count,
        expected_skill_probe_manifest_sha256=expected_skill_probe_manifest_sha256,
        expected_tool_probes=expected_tool_probes,
        expected_tool_probe_manifest_sha256=expected_tool_probe_manifest_sha256,
    ):
        raise EvaluationError("candidate preflight failure receipt has an invalid shape")
    failed = []
    if preflight["canary_readable"] is not False:
        failed.append("state-root-readable")
    if preflight["auth_readable"] is not False:
        failed.append("staged-auth-readable")
    if preflight["installed_auth_readable"] is not False:
        failed.append("installed-auth-readable")
    if preflight["project_canary_readable"] is not False:
        failed.append("project-root-readable")
    skill_manifest_ready = (
        preflight["skill_probe_manifest_readable"] is True
        and preflight["skill_probe_manifest_sha256"]
        == expected_skill_probe_manifest_sha256
        and preflight["skill_probe_manifest_error_type"] is None
    )
    if preflight["skill_probe_manifest_readable"] is not True:
        failed.append("skill-probe-manifest-unavailable")
    elif preflight["skill_probe_manifest_sha256"] != expected_skill_probe_manifest_sha256:
        failed.append("skill-probe-manifest-hash")
    elif preflight["skill_probe_manifest_error_type"] is not None:
        failed.append("skill-probe-manifest-invalid")
    if skill_manifest_ready and (
        preflight["skill_projection_readable"] is not True
        or preflight["skill_files_expected"] != expected_skill_file_count
        or preflight["skill_files_verified"] != expected_skill_file_count
        or preflight["skill_projection_error_type"] is not None
    ):
        failed.append("skill-projection-unreadable")
    if skill_manifest_ready and preflight["skill_projection_write_denied"] is not True:
        failed.append("skill-projection-writable")
    if preflight["workspace_write_probe_passed"] is not True:
        failed.append("workspace-not-writable")
    if preflight["runtime_temp_attempt_scoped"] is not True:
        failed.append("runtime-temp-outside-attempt-tmpdir")
    if (
        preflight["runtime_appdata_attempt_scoped"] is not True
        or preflight["runtime_localappdata_attempt_scoped"] is not True
    ):
        failed.append("runtime-appdata-outside-attempt-tmpdir")
    manifest_ready = (
        preflight["tool_probe_manifest_readable"] is True
        and preflight["tool_probe_manifest_sha256"] == expected_tool_probe_manifest_sha256
        and preflight["tool_probe_manifest_error_type"] is None
    )
    if preflight["tool_probe_manifest_readable"] is not True:
        failed.append("tool-probe-manifest-unavailable")
    elif preflight["tool_probe_manifest_sha256"] != expected_tool_probe_manifest_sha256:
        failed.append("tool-probe-manifest-hash")
    elif preflight["tool_probe_manifest_error_type"] is not None:
        failed.append("tool-probe-manifest-invalid")
    if manifest_ready:
        failed.extend(
            f"tool:{name}"
            for name, expected_sha256 in expected_tool_probes.items()
            if preflight["tool_probes"][name]["expected_sha256"] != expected_sha256
            or preflight["tool_probes"][name]["observed_sha256"] != expected_sha256
            or preflight["tool_probes"][name]["exit_code"] != 0
            or not preflight["tool_probes"][name]["summary"].strip()
        )
    if preflight["srcq_doctor_exit_code"] != 0:
        failed.append("srcq-doctor")
    if preflight["srcq_scc_doctor_exit_code"] != 0:
        failed.append("srcq-scc-doctor")
    failed.extend(
        f"srcq-smoke:{name}"
        for name in SRCQ_SMOKE_CHECKS
        if preflight["srcq_smoke"][name]["passed"] is not True
    )
    if not failed:
        failed.append("preflight-reported-failure-without-failed-check")
    return failed


def invoke_candidate_preflight(
    *,
    project_root: Path,
    workspace: Path,
    state_root: Path,
    codex_home: Path,
    canary_path: Path,
    denied_auth_path: Path,
    installed_codex_root: Path,
    skill_root_path: Path,
    skill_probe_manifest_path: Path,
    expected_skill_probe_manifest_sha256: str,
    expected_skill_file_count: int,
    tool_probe_manifest_path: Path,
    expected_tool_probe_manifest_sha256: str,
    expected_tool_probes: Mapping[str, str],
    preflight_output_path: Path,
    result_path: Path,
    permission_profile: str,
    codex_executable_path: Path | None,
    process_environment: Mapping[str, str],
) -> dict[str, Any]:
    argv = [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(project_root.resolve() / "development" / "agent-evaluation" / "invoke_candidate.ps1"),
        "-Action",
        "Preflight",
        "-ProjectRoot",
        str(project_root.resolve()),
        "-Workspace",
        str(workspace.resolve()),
        "-StateRoot",
        str(state_root.resolve()),
        "-CodexHome",
        str(codex_home.resolve()),
        "-CanaryPath",
        str(canary_path.resolve()),
        "-DeniedAuthPath",
        str(denied_auth_path.resolve()),
        "-InstalledCodexRoot",
        str(installed_codex_root.resolve()),
        "-SkillRootPath",
        str(skill_root_path.resolve()),
        "-SkillProbeManifestPath",
        str(skill_probe_manifest_path.resolve()),
        "-ExpectedSkillProbeManifestSha256",
        expected_skill_probe_manifest_sha256,
        "-ToolProbeManifestPath",
        str(tool_probe_manifest_path.resolve()),
        "-ExpectedToolProbeManifestSha256",
        expected_tool_probe_manifest_sha256,
        "-PreflightOutputPath",
        str(preflight_output_path.resolve()),
        "-ResultPath",
        str(result_path.resolve()),
        "-PermissionProfile",
        permission_profile,
    ]
    if codex_executable_path is not None:
        argv.extend(["-CodexExecutablePath", str(codex_executable_path.resolve())])
    completed = run_capture(
        argv,
        env=process_environment,
        timeout=600,
        check=False,
    )
    if not result_path.is_file():
        diagnostic = bounded_text(
            (completed.stderr + completed.stdout).decode("utf-8", errors="replace"),
            600,
        )
        raise EvaluationError(
            f"candidate sandbox preflight produced no result ({completed.returncode}): "
            f"{diagnostic}"
        )
    value = read_json(result_path)
    preflight = value.get("preflight")
    if value.get("schema") != "agentbase.windows-swe-sandbox-check/v3" or not isinstance(
        preflight, dict
    ):
        raise EvaluationError("candidate sandbox preflight returned an invalid result")
    status = value.get("status")
    if status == "passed":
        valid = (
            completed.returncode == 0
            and value.get("passed") is True
            and _candidate_preflight_is_valid(
                preflight,
                expected_skill_file_count=expected_skill_file_count,
                expected_skill_probe_manifest_sha256=expected_skill_probe_manifest_sha256,
                expected_tool_probes=expected_tool_probes,
                expected_tool_probe_manifest_sha256=expected_tool_probe_manifest_sha256,
            )
        )
    elif status == "failed":
        valid = (
            completed.returncode == 3
            and value.get("passed") is False
            and preflight.get("passed") is False
            and _candidate_preflight_has_valid_shape(
                preflight,
                expected_skill_file_count=expected_skill_file_count,
                expected_skill_probe_manifest_sha256=expected_skill_probe_manifest_sha256,
                expected_tool_probes=expected_tool_probes,
                expected_tool_probe_manifest_sha256=expected_tool_probe_manifest_sha256,
            )
        )
        if valid:
            candidate_preflight_failed_checks(
                preflight,
                expected_skill_file_count=expected_skill_file_count,
                expected_skill_probe_manifest_sha256=expected_skill_probe_manifest_sha256,
                expected_tool_probes=expected_tool_probes,
                expected_tool_probe_manifest_sha256=expected_tool_probe_manifest_sha256,
            )
    else:
        valid = False
    if not valid:
        raise EvaluationError("candidate sandbox preflight returned an invalid result")
    return dict(value)


def invoke_candidate(
    *,
    project_root: Path,
    workspace: Path,
    state_root: Path,
    attempt_root: Path,
    codex_home: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    profile_name: str,
    metadata: Mapping[str, Any],
    process_environment: Mapping[str, str],
    codex_executable_path: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    if os.environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED") == "1":
        raise EvaluationError("candidate model evaluator is disabled by the deterministic test gate")
    profile = require_profile(corpus, profile_name)
    result_path = attempt_root.resolve() / "codex-result.json"
    argv = [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(project_root.resolve() / "development" / "agent-evaluation" / "invoke_candidate.ps1"),
        "-Action",
        "Run",
        "-ProjectRoot",
        str(project_root.resolve()),
        "-Workspace",
        str(workspace.resolve()),
        "-StateRoot",
        str(state_root.resolve()),
        "-CodexHome",
        str(codex_home.resolve()),
        "-InstalledCodexRoot",
        str(installed_codex_root.resolve()),
        "-PromptPath",
        str(Path(str(metadata["prompt_path"])).resolve()),
        "-CanaryPath",
        str(Path(str(metadata["canary_path"])).resolve()),
        "-DeniedAuthPath",
        str((codex_home.resolve() / "auth.json")),
        "-SkillRootPath",
        str(Path(str(metadata["skill_root_path"])).resolve()),
        "-SkillProbeManifestPath",
        str(Path(str(metadata["skill_probe_manifest_path"])).resolve()),
        "-ExpectedSkillProbeManifestSha256",
        str(metadata["skill_probe_manifest_sha256"]),
        "-ToolProbeManifestPath",
        str(Path(str(metadata["tool_probe_manifest_path"])).resolve()),
        "-ExpectedToolProbeManifestSha256",
        str(metadata["tool_probe_manifest_sha256"]),
        "-PreflightOutputPath",
        str(Path(str(metadata["preflight_output_path"])).resolve()),
        "-ResultPath",
        str(result_path),
        "-Model",
        str(profile["model"]),
        "-ReasoningEffort",
        str(profile["reasoning_effort"]),
        "-PermissionProfile",
        str(corpus["codex"]["candidate_permission_profile"]),
        "-TimeoutSeconds",
        str(timeout_seconds),
    ]
    if codex_executable_path is not None:
        argv.extend(["-CodexExecutablePath", str(codex_executable_path.resolve())])
    try:
        result = subprocess.run(
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
    if result.returncode != 0:
        detail = bounded_text(
            (result.stderr + result.stdout).decode("utf-8", errors="replace"),
            800,
        )
        if result_path.is_file():
            trusted_result = read_json(result_path)
            preflight = trusted_result.get("preflight")
            if (
                trusted_result.get("schema")
                != "agentbase.windows-swe-codex-run/v3"
                or trusted_result.get("status") != "blocked-precondition"
                or trusted_result.get("model_invoked") is not False
                or trusted_result.get("exit_code") is not None
                or not isinstance(preflight, dict)
                or preflight.get("passed") is not False
            ):
                raise EvaluationError("candidate launcher returned an invalid trusted failure result")
            failed_checks = candidate_preflight_failed_checks(
                preflight,
                expected_skill_file_count=int(metadata["expected_skill_file_count"]),
                expected_skill_probe_manifest_sha256=str(
                    metadata["skill_probe_manifest_sha256"]
                ),
                expected_tool_probes={
                    str(name): str(expected_sha256)
                    for name, expected_sha256 in metadata["expected_tool_probes"].items()
                },
                expected_tool_probe_manifest_sha256=str(
                    metadata["tool_probe_manifest_sha256"]
                ),
            )
            raise PreconditionError(
                "candidate sandbox preflight failed before model execution: "
                + ", ".join(failed_checks)
            )
        if is_elevated_sandbox_setup_error(detail):
            raise PreconditionError(
                "candidate sandbox requires administrator-approved elevated Windows setup"
            )
        raise EvaluationError(f"candidate launcher failed ({result.returncode}): {detail}")
    value = read_json(result_path)
    if (
        value.get("schema") != "agentbase.windows-swe-codex-run/v3"
        or value.get("status") != "completed"
        or value.get("model_invoked") is not True
    ):
        raise EvaluationError("candidate launcher returned an invalid result")
    if value.get("exit_code") != 0:
        raise EvaluationError(
            f"Codex candidate process failed: {bounded_text(str(value.get('diagnostic', '')), 800)}"
        )
    preflight = value.get("preflight")
    if (
        not isinstance(preflight, dict)
        or not _candidate_preflight_is_valid(
            preflight,
            expected_skill_file_count=int(metadata["expected_skill_file_count"]),
            expected_skill_probe_manifest_sha256=str(
                metadata["skill_probe_manifest_sha256"]
            ),
            expected_tool_probes={
                str(name): str(expected_sha256)
                for name, expected_sha256 in metadata["expected_tool_probes"].items()
            },
            expected_tool_probe_manifest_sha256=str(
                metadata["tool_probe_manifest_sha256"]
            ),
        )
    ):
        raise EvaluationError("candidate sandbox preflight did not pass")
    return dict(value)
