"""Stage and invoke the real AgentBase candidate inside the Windows sandbox."""

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
    PYTEST_ADDOPTS_ENV_KEY,
    PYTEST_DEBUG_TEMPROOT_ENV_KEY,
    PYTEST_RETENTION_ADDOPTS,
    PreconditionError,
    SandboxRuntimeInvalidError,
    SandboxSetupApprovalError,
    bounded_text,
    candidate_surface_identity,
    canonical_bytes,
    dependency_runtime_projection,
    read_json,
    require_within,
    require_profile,
    require_task,
    run_capture,
    prepare_sandbox_writable_root,
    sandbox_temp_environment,
    sandbox_runtime_home,
    sandbox_runtime_state_path,
    sha256_bytes,
    sha256_file,
    task_asset_root,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)


BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
SANDBOX_RUNNER_NAME_PATTERN = re.compile(
    r"(?:codex|codex-command-runner-[A-Za-z0-9][A-Za-z0-9._-]*)\.exe\Z",
    re.IGNORECASE,
)
WINDOWS_SID_PATTERN = re.compile(r"S-1-[0-9]+(?:-[0-9]+)+\Z")
SANDBOX_BACKEND_SCHEMA = "agentbase.windows-swe-sandbox-backend/v3"
LEGACY_SANDBOX_BACKEND_SCHEMA = "agentbase.windows-swe-sandbox-backend/v1"
CAPABILITY_SID_REGISTRY_SCHEMA = "codex.windows-capability-sid-registry/v1"
SANDBOX_RUNTIME_CONTROLLED_SCHEMA = "agentbase.windows-swe-runtime-controlled/v1"
SANDBOX_RUNTIME_STATE_SCHEMA = "agentbase.windows-swe-sandbox-runtime/v1"
SANDBOX_RUNTIME_STATUS_SCHEMA = "agentbase.windows-swe-sandbox-status/v1"
SANDBOX_RUNTIME_USE_SCHEMA = "agentbase.windows-swe-sandbox-runtime-use/v1"
SANDBOX_SETUP_RESULT_SCHEMA = "agentbase.windows-swe-sandbox-setup/v1"
CODEX_RUN_RESULT_SCHEMA = "agentbase.windows-swe-codex-run/v7"
CODEX_AGENT_USAGE_SCHEMA = "agentbase.windows-swe-agent-usage/v2"
API_PRICING_SNAPSHOT_SCHEMA = "agentbase.windows-swe-api-pricing/v1"
API_EQUIVALENT_COST_SCHEMA = "agentbase.windows-swe-api-equivalent-cost/v1"
API_PRICING_SNAPSHOT_PATH = Path(__file__).resolve().with_name("api_pricing_snapshot.json")
SANDBOX_RUNTIME_CLEANUP_SOURCE = Path(__file__).resolve().with_name(
    "sandbox_runtime_cleanup.ps1"
)
WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY = "CODEX_NETWORK_ALLOW_LOCAL_BINDING"
EVALUATION_SHELL_ENVIRONMENT_POLICY_SCHEMA = (
    "agentbase.windows-swe-shell-environment-policy/v1"
)
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


def is_sandbox_setup_approval_error(diagnostic: str) -> bool:
    normalized = diagnostic.casefold()
    return any(
        signature in normalized
        for signature in (
            "orchestrator_helper_launch_canceled",
            "shellexecuteexw failed to launch setup helper",
        )
    )


def is_elevated_sandbox_runtime_rejection(diagnostic: str) -> bool:
    return "requires the elevated windows sandbox backend" in diagnostic.casefold()


def sandbox_runtime_use_is_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("schema") == SANDBOX_RUNTIME_USE_SCHEMA
        and value.get("ready") is True
        and value.get("setup_invoked") is False
        and isinstance(value.get("identity_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", str(value.get("identity_sha256")))
        is not None
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
        source_descriptor, source_policy = resolve_shell_environment_policy()
    except CodexRuntimeError as exc:
        raise EvaluationError(str(exc)) from exc
    policy = dict(source_policy)
    policy["set"] = {WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY: "1"}
    descriptor = {
        "schema": EVALUATION_SHELL_ENVIRONMENT_POLICY_SCHEMA,
        "source": source_descriptor,
        "managed_set_keys": [WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY],
        "sha256": sha256_bytes(canonical_bytes(policy)),
    }
    return descriptor, policy


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
        "schema": "agentbase.windows-swe-candidate-capabilities/v6",
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
                "shell_environment_managed_set_keys": [
                    WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY
                ],
                "shell_environment_policy_sha256": shell_policy_descriptor["sha256"],
                "requires_candidate_model_evidence": True,
            },
            "sandbox": {
                "implementation": corpus["codex"]["sandbox_implementation"],
                "permission_profile": corpus["codex"]["candidate_permission_profile"],
                "network_enabled": False,
                "external_network_enabled": False,
                "loopback_network_enabled": True,
                "host_filesystem_default_denied": True,
                "minimal_runtime_readable": True,
                "project_root_contents_denied": True,
                "state_hidden_assets_denied": True,
                "installed_codex_contents_denied": True,
                "protected_root_listing_may_be_readable": False,
                "runtime_home_minimal_read_reopened": True,
                "attempt_tmpdir_only": True,
                "process_appdata_scoped_to_tmpdir": True,
                "pytest_private_temp_cleanup": True,
                "pytest_temp_contract": {
                    "temproot_env_key": PYTEST_DEBUG_TEMPROOT_ENV_KEY,
                    "addopts_env_key": PYTEST_ADDOPTS_ENV_KEY,
                    "addopts": PYTEST_RETENTION_ADDOPTS,
                },
                "skill_projection_read_only": True,
                "persistent_backend_state": True,
                "setup_explicit_only": True,
                "normal_runs_never_request_setup": True,
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
            "process_home_scoped_to_attempt_tmpdir": True,
            "pytest_private_temp_cleanup": True,
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
            "external-network",
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


def evaluation_runtime_config_identity_descriptor(
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
        "candidate_permission_profile": corpus["codex"]["candidate_permission_profile"],
        "verifier_permission_profile": corpus["codex"]["verifier_permission_profile"],
        "host_filesystem_default_denied": True,
        "minimal_runtime_readable": True,
        "project_root_contents_denied": str(project_root.resolve()),
        "state_root_denied": str(state_root.resolve()),
        "installed_codex_contents_denied": str(installed_codex_root.resolve()),
        "protected_root_listing_may_be_readable": False,
        "runtime_home_minimal_read_reopened": True,
        "codex_home_under_denied_state": True,
        "sandbox_backend_state_persistent": True,
        "sandbox_setup_explicit_only": True,
        "attempt_tmpdir_reopened": True,
        "process_appdata_scoped_to_tmpdir": True,
        "pytest_private_temp_cleanup": True,
        "shell_environment_secret_filtered": True,
        "shell_environment_managed_set_keys": list(
            shell_policy_descriptor["managed_set_keys"]
        ),
        "shell_environment_policy_sha256": str(shell_policy_descriptor["sha256"]),
        "repository_skill_projection": ".agents/skills read-only derived copy",
        "sandbox": corpus["codex"]["sandbox_implementation"],
        "network": {
            "external_enabled": False,
            "loopback_enabled": True,
            "provisioning_env_key": WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY,
        },
    }


def _candidate_base_tool_read_rules(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
) -> dict[str, str]:
    protected_roots = (
        project_root.resolve(),
        state_root.resolve(),
        installed_codex_root.resolve(),
    )
    rules: dict[str, str] = {}
    for candidates in REQUIRED_CANDIDATE_TOOLS.values():
        path = _resolve_application(candidates)
        if any(path == root or root in path.parents for root in protected_roots):
            raise EvaluationError(
                f"candidate runtime tool overlaps a denied root: {path}"
            )
        rules[str(path)] = "read"
    return rules


def build_evaluation_runtime_config(
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
    resolved_runtime_home = sandbox_runtime_home(resolved_state)
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
    candidate["shell_environment_policy"] = {
        key: shell_policy[key]
        for key in (
            "inherit",
            "ignore_default_excludes",
            "experimental_use_profile",
            "filters",
            "set",
        )
    }
    candidate.setdefault("windows", {})["sandbox"] = str(
        corpus["codex"]["sandbox_implementation"]
    )
    candidate.setdefault("features", {})["hooks"] = False
    candidate_profile = str(corpus["codex"]["candidate_permission_profile"])
    verifier_profile = str(corpus["codex"]["verifier_permission_profile"])
    base_tool_read_rules = _candidate_base_tool_read_rules(
        project_root,
        state_root,
        installed_codex_root,
    )
    candidate["permissions"] = {
        candidate_profile: {
            "extends": ":workspace",
            "filesystem": {
                "glob_scan_max_depth": 1,
                ":root": "deny",
                ":minimal": "read",
                ":tmpdir": "write",
                ":workspace_roots": {
                    ".": "write",
                    ".agentbase": "read",
                    ".agents/skills": "read",
                    ".codex": "read",
                    ".git": "read",
                    "**/*.env": "deny",
                },
                **base_tool_read_rules,
                str(project_root.resolve()): "deny",
                str(resolved_state): "deny",
                str(resolved_runtime_home): "read",
                str(resolved_runtime_home / "auth.json"): "deny",
                str(resolved_runtime_home / ".sandbox-secrets"): "deny",
                str(installed_codex_root.resolve()): "deny",
            },
            "network": {
                "enabled": False,
                "allow_local_binding": True,
            },
        },
        verifier_profile: {
            "extends": ":workspace",
            "network": {
                "enabled": False,
                "allow_local_binding": True,
            },
        },
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
        "identity": evaluation_runtime_config_identity_descriptor(
            project_root,
            state_root,
            installed_codex_root,
            corpus,
            shell_policy_descriptor=shell_policy_descriptor,
        ),
        "effective_config_sha256": sha256_bytes(text.encode("utf-8")),
    }
    return text, descriptor


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


def invoke_sandbox_setup(
    *,
    project_root: Path,
    workspace: Path,
    state_root: Path,
    codex_home: Path,
    runtime_temp: Path,
    result_path: Path,
    codex_executable_path: Path,
    permission_profile: str,
    process_environment: Mapping[str, str],
) -> dict[str, Any]:
    if os.environ.get("AGENTBASE_AGENT_EVALUATOR_DISABLED") == "1":
        raise EvaluationError("sandbox setup is disabled by the deterministic test gate")
    prepare_sandbox_writable_root(
        workspace.parent,
        workspace,
        create_runtime_subdirs=False,
    )
    prepare_sandbox_writable_root(state_root, runtime_temp)
    marker = codex_home.resolve() / ".sandbox" / "setup_marker.json"
    marker_backup = runtime_temp.resolve() / "setup-marker-before.json"
    if marker.exists():
        if _is_reparse_point(marker) or not marker.is_file():
            raise EvaluationError("sandbox setup marker is not a regular file")
        shutil.copy2(marker, marker_backup)
        marker.unlink()

    def restore_marker() -> None:
        if not marker_backup.is_file():
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists() or marker.is_symlink():
            if marker.is_dir() and not marker.is_symlink():
                raise EvaluationError("sandbox setup replaced its marker with a directory")
            marker.unlink()
        os.replace(marker_backup, marker)

    argv = [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(project_root.resolve() / "development" / "agent-evaluation" / "invoke_candidate.ps1"),
        "-Action",
        "Setup",
        "-ProjectRoot",
        str(project_root.resolve()),
        "-Workspace",
        str(workspace.resolve()),
        "-StateRoot",
        str(state_root.resolve()),
        "-CodexHome",
        str(codex_home.resolve()),
        "-RuntimeTemp",
        str(runtime_temp.resolve()),
        "-ResultPath",
        str(result_path.resolve()),
        "-CodexExecutablePath",
        str(codex_executable_path.resolve()),
        "-PermissionProfile",
        permission_profile,
    ]
    try:
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
            if is_sandbox_setup_approval_error(diagnostic):
                raise SandboxSetupApprovalError(
                    "administrator approval for the explicit Windows sandbox setup "
                    f"was not completed: {diagnostic}"
                )
            raise EvaluationError(
                f"sandbox setup produced no result ({completed.returncode}): {diagnostic}"
            )
        value = read_json(result_path)
        if (
            completed.returncode != 0
            or value.get("schema") != SANDBOX_SETUP_RESULT_SCHEMA
            or value.get("passed") is not True
            or value.get("setup_invoked") is not True
            or value.get("model_invoked") is not False
            or value.get("exit_code") != 0
        ):
            raise EvaluationError("sandbox setup returned an invalid result")
        configured_marker = _regular_backend_file(
            codex_home,
            ".sandbox/setup_marker.json",
            256 * 1024,
        )
        _sandbox_network_provisioning_descriptor(configured_marker)
    except Exception:
        restore_marker()
        raise
    if marker_backup.exists():
        marker_backup.unlink()
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
        primary_dependency_names = (
            {"python"}
            if toolchain.get("kind") == "python"
            else {"node", str(toolchain.get("package_manager") or "")}
        )
        expected_identity_names = set(primary_dependency_names)
        if toolchain.get("kind") == "node" and toolchain.get("package_manager") == "pnpm":
            expected_identity_names.add("pnpm-runtime")
        if "" in primary_dependency_names or not isinstance(dependency_tools, dict):
            raise EvaluationError("task dependency identity omits its runtime tool")
        if set(dependency_tools) != expected_identity_names:
            raise EvaluationError("task dependency identity has an unexpected runtime tool set")
        for dependency_name in sorted(primary_dependency_names):
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
            if dependency_name == "pnpm":
                probes.append(
                    {
                        "id": "task-pnpm-workspace",
                        "path": str(dependency_path),
                        "sha256": dependency_sha256,
                        "argv": ["list", "--depth", "0", "--json"],
                    }
                )
        if "pnpm-runtime" in expected_identity_names:
            runtime_tool = dependency_tools.get("pnpm-runtime")
            runtime_path_value = dependency_values.get("pnpm_runtime")
            if not isinstance(runtime_tool, dict) or not runtime_path_value:
                raise EvaluationError("task dependency runtime omits pnpm-runtime")
            runtime_path = Path(str(runtime_path_value)).resolve()
            if (
                not runtime_path.is_file()
                or sha256_file(runtime_path) != str(runtime_tool.get("sha256", ""))
            ):
                raise EvaluationError(
                    "task dependency tool changed before probe staging: pnpm-runtime"
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


def evaluation_runtime_controlled_descriptor(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    resolved_project = project_root.resolve()
    agents_root = resolved_project / "global" / "agents"
    rules_path = resolved_project / "global" / "AGENTS.md"
    config_text, config_descriptor = build_evaluation_runtime_config(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
    )
    entries = [
        {
            "path": "AGENTS.md",
            "sha256": sha256_file(rules_path),
            "bytes": rules_path.stat().st_size,
        },
        {
            "path": "config.toml",
            "sha256": sha256_bytes(config_text.encode("utf-8")),
            "bytes": len(config_text.encode("utf-8")),
        },
        *_controlled_agent_entries(agents_root),
    ]
    identity_payload = {
        "schema": SANDBOX_RUNTIME_CONTROLLED_SCHEMA,
        "files": entries,
    }
    return config_text, {
        **identity_payload,
        "identity_sha256": sha256_bytes(canonical_bytes(identity_payload)),
        "config": config_descriptor,
    }


def evaluation_runtime_home_controlled_identity(home: Path) -> dict[str, Any]:
    resolved = home.resolve()
    if not resolved.is_dir() or _is_reparse_point(resolved):
        raise EvaluationError(f"evaluation Codex home is not a regular directory: {resolved}")
    rules = resolved / "AGENTS.md"
    config = resolved / "config.toml"
    for path in (rules, config):
        if _is_reparse_point(path) or not path.is_file():
            raise EvaluationError(f"evaluation Codex home omits controlled file: {path.name}")
    entries = [
        {
            "path": "AGENTS.md",
            "sha256": sha256_file(rules),
            "bytes": rules.stat().st_size,
        },
        {
            "path": "config.toml",
            "sha256": sha256_file(config),
            "bytes": config.stat().st_size,
        },
        *_controlled_agent_entries(resolved / "agents"),
    ]
    payload = {
        "schema": SANDBOX_RUNTIME_CONTROLLED_SCHEMA,
        "files": entries,
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def sync_evaluation_runtime_home(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    home = sandbox_runtime_home(state_root)
    if home.exists() and (not home.is_dir() or _is_reparse_point(home)):
        raise EvaluationError(f"evaluation Codex home is not a regular directory: {home}")
    home.mkdir(parents=True, exist_ok=True)
    config_text, desired = evaluation_runtime_controlled_descriptor(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
    )
    rules_source = project_root.resolve() / "global" / "AGENTS.md"
    rules_target = home / "AGENTS.md"
    if not rules_target.is_file() or sha256_file(rules_target) != sha256_file(rules_source):
        write_text_atomic(rules_target, rules_source.read_text(encoding="utf-8"))
    config_target = home / "config.toml"
    if not config_target.is_file() or config_target.read_text(encoding="utf-8") != config_text:
        write_text_atomic(config_target, config_text)
    agents_source = project_root.resolve() / "global" / "agents"
    agents_target = home / "agents"
    desired_agents = _controlled_agent_entries(agents_source)
    actual_agents: list[dict[str, Any]] | None
    try:
        actual_agents = _controlled_agent_entries(agents_target)
    except EvaluationError:
        actual_agents = None
    if actual_agents != desired_agents:
        if agents_target.exists():
            if _is_reparse_point(agents_target) or not agents_target.is_dir():
                raise EvaluationError("evaluation custom-agent target is not a regular directory")
            shutil.rmtree(agents_target)
        shutil.copytree(agents_source, agents_target)
    actual = evaluation_runtime_home_controlled_identity(home)
    if actual["identity_sha256"] != desired["identity_sha256"]:
        raise EvaluationError("evaluation Codex home differs from its controlled source")
    return home, desired


def cleanup_evaluation_runtime_transients(home: Path) -> dict[str, Any]:
    removed = 0
    for name in ("auth.json", "models-evaluation.json"):
        path = home.resolve() / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            raise EvaluationError(f"runtime transient path unexpectedly became a directory: {name}")
        path.unlink()
        removed += 1
    return {"removed": removed, "clean": True}


def evaluation_runtime_transients_absent(home: Path) -> bool:
    return all(
        not path.exists() and not path.is_symlink()
        for path in (
            home.resolve() / "auth.json",
            home.resolve() / "models-evaluation.json",
        )
    )


def _regular_backend_file(home: Path, relative: str, maximum_bytes: int) -> Path:
    resolved_home = home.resolve()
    path = resolved_home / Path(relative)
    current = path
    while current != resolved_home:
        if current.exists() and _is_reparse_point(current):
            raise EvaluationError(f"sandbox backend path is a reparse point: {relative}")
        current = current.parent
    if not path.is_file():
        raise EvaluationError(f"sandbox backend omits {relative}")
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise EvaluationError(f"sandbox backend file has an invalid size: {relative}")
    return path


def sandbox_backend_runner_files(home: Path) -> list[Path]:
    resolved = home.resolve()
    runner_root = resolved / ".sandbox-bin"
    if not runner_root.is_dir() or _is_reparse_point(runner_root):
        raise EvaluationError("sandbox backend omits its regular runner directory")
    runners: list[Path] = []
    for path in sorted(runner_root.iterdir(), key=lambda item: item.name.casefold()):
        if _is_reparse_point(path):
            raise EvaluationError("sandbox runner directory contains a reparse point")
        if not path.is_file() or SANDBOX_RUNNER_NAME_PATTERN.fullmatch(path.name) is None:
            continue
        size = path.stat().st_size
        if size <= 0 or size > 512 * 1024 * 1024:
            raise EvaluationError(f"sandbox runner has an invalid size: {path.name}")
        runners.append(path)
    if not runners:
        raise EvaluationError("sandbox backend omits a recognized command runner")
    if len(runners) > 16:
        raise EvaluationError("sandbox backend contains too many command runners")
    return runners


def _capability_sid_registry_descriptor(path: Path) -> dict[str, Any]:
    try:
        registry = read_json(path)
    except EvaluationError as exc:
        raise EvaluationError("sandbox capability SID registry is invalid JSON") from exc
    expected_fields = {
        "workspace",
        "readonly",
        "workspace_by_cwd",
        "writable_root_by_path",
    }
    if not isinstance(registry, Mapping) or set(registry) != expected_fields:
        raise EvaluationError("sandbox capability SID registry fields are invalid")
    for name in ("workspace", "readonly"):
        value = registry.get(name)
        if not isinstance(value, str) or WINDOWS_SID_PATTERN.fullmatch(value) is None:
            raise EvaluationError(f"sandbox capability SID registry has an invalid {name} SID")
    for name in ("workspace_by_cwd", "writable_root_by_path"):
        value = registry.get(name)
        if not isinstance(value, Mapping) or len(value) > 100_000:
            raise EvaluationError(f"sandbox capability SID registry has an invalid {name} map")
        for scoped_path, sid in value.items():
            if (
                not isinstance(scoped_path, str)
                or not scoped_path
                or len(scoped_path) > 32_768
                or not isinstance(sid, str)
                or WINDOWS_SID_PATTERN.fullmatch(sid) is None
            ):
                raise EvaluationError(
                    f"sandbox capability SID registry has an invalid {name} entry"
                )
    return {
        "schema": CAPABILITY_SID_REGISTRY_SCHEMA,
        "mutable": True,
        "structure_validated": True,
    }


def _sandbox_network_provisioning_descriptor(marker: Path) -> dict[str, Any]:
    value = read_json(marker)
    if not isinstance(value, Mapping):
        raise EvaluationError("sandbox setup marker is not an object")
    version = value.get("version")
    proxy_ports = value.get("proxy_ports")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise EvaluationError("sandbox setup marker has an invalid version")
    if (
        not isinstance(proxy_ports, list)
        or any(
            not isinstance(port, int)
            or isinstance(port, bool)
            or port <= 0
            or port > 65535
            for port in proxy_ports
        )
        or len(set(proxy_ports)) != len(proxy_ports)
    ):
        raise EvaluationError("sandbox setup marker has invalid proxy ports")
    if value.get("allow_local_binding") is not True:
        raise EvaluationError(
            "sandbox backend must allow loopback while retaining its non-loopback outbound block"
        )
    return {
        "schema": "agentbase.windows-swe-sandbox-network/v1",
        "offline_identity": True,
        "external_network_enabled": False,
        "loopback_network_enabled": True,
        "setup_marker_version": version,
        "proxy_ports": list(proxy_ports),
    }


def sandbox_backend_snapshot(home: Path) -> dict[str, Any]:
    resolved = home.resolve()
    marker = _regular_backend_file(resolved, ".sandbox/setup_marker.json", 256 * 1024)
    sandbox_runners = sandbox_backend_runner_files(resolved)
    capability_sid = _regular_backend_file(resolved, "cap_sid", 16 * 1024 * 1024)
    capability_sid_registry = _capability_sid_registry_descriptor(capability_sid)
    network_provisioning = _sandbox_network_provisioning_descriptor(marker)
    secrets = resolved / ".sandbox-secrets"
    if not secrets.is_dir() or _is_reparse_point(secrets):
        raise EvaluationError("sandbox backend omits its protected secret directory")
    payload = {
        "schema": SANDBOX_BACKEND_SCHEMA,
        "setup_marker_sha256": sha256_file(marker),
        "setup_marker_bytes": marker.stat().st_size,
        "sandbox_runners": [
            {
                "name": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sandbox_runners
        ],
        "capability_sid_registry": capability_sid_registry,
        "network_provisioning": network_provisioning,
        "protected_secret_directory_present": True,
    }
    return {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}


def _legacy_backend_matches_stable_core(
    recorded: object,
    current: Mapping[str, Any],
) -> bool:
    if not isinstance(recorded, Mapping):
        return False
    return (
        recorded.get("schema") == LEGACY_SANDBOX_BACKEND_SCHEMA
        and current.get("schema") == SANDBOX_BACKEND_SCHEMA
        and recorded.get("setup_marker_sha256") == current.get("setup_marker_sha256")
        and recorded.get("setup_marker_bytes") == current.get("setup_marker_bytes")
        and recorded.get("sandbox_runners") == current.get("sandbox_runners")
        and recorded.get("protected_secret_directory_present") is True
        and isinstance(recorded.get("capability_sid_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", str(recorded.get("capability_sid_sha256")))
        is not None
        and isinstance(recorded.get("capability_sid_bytes"), int)
        and not isinstance(recorded.get("capability_sid_bytes"), bool)
        and int(recorded.get("capability_sid_bytes", 0)) > 0
    )


def _runtime_identity_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if key != "identity_sha256"}


def validate_sandbox_runtime_state(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationError("sandbox runtime state is not an object")
    normalized = dict(value)
    if normalized.get("schema") != SANDBOX_RUNTIME_STATE_SCHEMA:
        raise EvaluationError("sandbox runtime state has an unsupported schema")
    expected = sha256_bytes(canonical_bytes(_runtime_identity_payload(normalized)))
    if normalized.get("identity_sha256") != expected:
        raise EvaluationError("sandbox runtime state identity mismatch")
    if normalized.get("status") not in {"ready", "invalidated"}:
        raise EvaluationError("sandbox runtime state has an invalid status")
    return normalized


def write_ready_sandbox_runtime_state(
    state_root: Path,
    codex_identity: Mapping[str, Any],
    backend: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema": SANDBOX_RUNTIME_STATE_SCHEMA,
        "status": "ready",
        "created_at": utc_now(),
        "codex": {
            "schema": str(codex_identity.get("schema", "")),
            "path": str(codex_identity.get("path", "")),
            "sha256": str(codex_identity.get("sha256", "")),
            "version": str(codex_identity.get("version", "")),
        },
        "backend": dict(backend),
    }
    value = {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}
    write_json_atomic(sandbox_runtime_state_path(state_root), value)
    return value


def invalidate_sandbox_runtime(
    state_root: Path,
    reason_code: str,
    *,
    expected_identity_sha256: str | None = None,
) -> dict[str, Any]:
    path = sandbox_runtime_state_path(state_root)
    try:
        current = validate_sandbox_runtime_state(read_json(path))
        if (
            expected_identity_sha256 is not None
            and current.get("identity_sha256") != expected_identity_sha256
        ):
            return current
        payload = _runtime_identity_payload(current)
    except EvaluationError:
        payload = {
            "schema": SANDBOX_RUNTIME_STATE_SCHEMA,
            "created_at": None,
        }
    payload.update(
        {
            "status": "invalidated",
            "invalidated_reason_code": reason_code,
        }
    )
    value = {**payload, "identity_sha256": sha256_bytes(canonical_bytes(payload))}
    write_json_atomic(path, value)
    return value


def sandbox_runtime_status(
    project_root: Path,
    state_root: Path,
    installed_codex_root: Path,
    corpus: Mapping[str, Any],
    codex_identity: Mapping[str, Any],
) -> dict[str, Any]:
    home = sandbox_runtime_home(state_root)
    _, desired = evaluation_runtime_controlled_descriptor(
        project_root,
        state_root,
        installed_codex_root,
        corpus,
    )
    reasons: list[str] = []
    try:
        actual_controlled = evaluation_runtime_home_controlled_identity(home)
        controlled_current = (
            actual_controlled["identity_sha256"] == desired["identity_sha256"]
        )
    except EvaluationError:
        actual_controlled = None
        controlled_current = False
    if not controlled_current:
        reasons.append("controlled-assets-stale")
    try:
        runtime_state = validate_sandbox_runtime_state(
            read_json(sandbox_runtime_state_path(state_root))
        )
        state_valid = True
    except EvaluationError:
        runtime_state = None
        state_valid = False
    if not state_valid:
        reasons.append("setup-state-missing-or-invalid")
    elif runtime_state.get("status") != "ready":
        reasons.append("setup-state-invalidated")
    codex_matches = bool(
        runtime_state
        and runtime_state.get("codex")
        == {
            "schema": str(codex_identity.get("schema", "")),
            "path": str(codex_identity.get("path", "")),
            "sha256": str(codex_identity.get("sha256", "")),
            "version": str(codex_identity.get("version", "")),
        }
    )
    if state_valid and not codex_matches:
        reasons.append("codex-identity-changed")
    transients_absent = evaluation_runtime_transients_absent(home)
    if not transients_absent:
        reasons.append("runtime-transient-leftover")
    try:
        backend = sandbox_backend_snapshot(home)
        backend_matches = bool(
            runtime_state
            and runtime_state.get("backend") == backend
        )
    except EvaluationError:
        backend = None
        backend_matches = False
    state_allows_refresh = bool(
        runtime_state
        and (
            runtime_state.get("status") == "ready"
            or (
                runtime_state.get("status") == "invalidated"
                and runtime_state.get("invalidated_reason_code")
                == "explicit-sandbox-setup-cleanup-failed"
            )
        )
    )
    runtime_state_refreshable = bool(
        state_valid
        and runtime_state
        and state_allows_refresh
        and controlled_current
        and codex_matches
        and transients_absent
        and backend is not None
        and (
            backend_matches
            or _legacy_backend_matches_stable_core(runtime_state.get("backend"), backend)
        )
    )
    if state_valid and not backend_matches:
        reasons.append(
            "sandbox-runtime-state-refresh-required"
            if runtime_state_refreshable
            else "sandbox-backend-missing-or-changed"
        )
    ready = not reasons
    runtime_use = None
    if ready and runtime_state is not None:
        runtime_use = {
            "schema": SANDBOX_RUNTIME_USE_SCHEMA,
            "ready": True,
            "setup_invoked": False,
            "identity_sha256": runtime_state["identity_sha256"],
            "controlled_identity_sha256": desired["identity_sha256"],
            "backend_identity_sha256": backend["identity_sha256"],
            "state_path": str(sandbox_runtime_state_path(state_root)),
        }
    return {
        "schema": SANDBOX_RUNTIME_STATUS_SCHEMA,
        "status": "ready" if ready else "setup-required",
        "ready": ready,
        "home": str(home),
        "checks": {
            "controlled_assets_current": controlled_current,
            "setup_state_valid": state_valid,
            "setup_state_ready": bool(runtime_state and runtime_state.get("status") == "ready"),
            "codex_identity_matches": codex_matches,
            "sandbox_backend_matches": backend_matches,
            "runtime_state_refreshable": runtime_state_refreshable,
            "runtime_transients_absent": transients_absent,
        },
        "reason_codes": reasons,
        "runtime_use": runtime_use,
        "setup_may_request_administrator_approval": bool(
            not ready and not runtime_state_refreshable
        ),
        "recovery_action": None if ready else "run sandbox-setup explicitly",
    }


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
        f"For Git reads in this sandbox, prefix arguments with `git.exe -c {safe_directory}`; "
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
    metadata = prepare_candidate_metadata_root(workspace)
    instruction_source = task_asset_root(state_root, corpus, task_id) / "instruction.md"
    shutil.copy2(instruction_source, metadata / "task.md")
    preflight_source = (
        project_root.resolve()
        / "development"
        / "agent-evaluation"
        / "candidate_preflight.ps1"
    )
    shutil.copy2(preflight_source, metadata / "preflight.ps1")
    if not SANDBOX_RUNTIME_CLEANUP_SOURCE.is_file():
        raise EvaluationError("sandbox runtime cleanup script is missing")
    cleanup_path = metadata / "runtime-cleanup.ps1"
    shutil.copy2(SANDBOX_RUNTIME_CLEANUP_SOURCE, cleanup_path)
    canary = attempt_root.resolve() / "held-out" / "canary.txt"
    canary.parent.mkdir(parents=True, exist_ok=True)
    canary_value = os.urandom(32).hex()
    write_text_atomic(canary, canary_value + "\n")
    output = metadata / "preflight.json"
    task = require_task(corpus, task_id)
    public_tooling = candidate_public_tooling_hint(task)
    public_checks = candidate_public_checks_hint(task, dependency_values, workspace)
    patch_scope = candidate_patch_scope_hint(task)
    windows_adapter = candidate_windows_adapter_hint(task)
    prompt = (
        "Complete the repository task described in .agentbase/task.md.\n"
        "The evaluation has already checked the AgentBase toolchain and hidden-state isolation "
        "under your exact Windows permission profile. Do not inspect paths outside this workspace.\n"
        "Use the repository instructions and AgentBase tools, implement the task, and run useful "
        "public checks.\n"
        f"{windows_adapter}"
        f"{patch_scope}"
        f"{public_tooling}"
        f"{public_checks}"
        f"{CANDIDATE_COMPLETION_INSTRUCTION}"
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
    task_runtime = dependency_runtime_projection(task, dependency_values)
    return {
        "metadata_root": str(metadata),
        "canary_path": str(canary),
        "preflight_output_path": str(output),
        "runtime_cleanup_script_path": str(cleanup_path),
        "runtime_cleanup_script_sha256": sha256_file(cleanup_path),
        "runtime_cleanup_shell_path": str(runtime_tools["tools"]["pwsh"]["path"]),
        "runtime_cleanup_shell_sha256": str(runtime_tools["tools"]["pwsh"]["sha256"]),
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
        "task_runtime": task_runtime,
    }


def cleanup_candidate_runtime_temp(
    *,
    workspace: Path,
    attempt_root: Path,
    runtime_temp: Path,
    codex_home: Path,
    codex_executable_path: Path,
    pwsh_executable_path: Path,
    expected_pwsh_sha256: str,
    cleanup_script_path: Path,
    expected_cleanup_script_sha256: str,
    permission_profile: str,
    process_environment: Mapping[str, str],
) -> dict[str, Any]:
    """Remove candidate-owned tmp children under the same restricted token."""

    started = time.perf_counter()
    resolved_workspace = workspace.resolve()
    resolved_attempt = attempt_root.resolve()
    resolved_runtime = runtime_temp.resolve()
    if (
        resolved_runtime.parent != resolved_attempt
        or resolved_runtime.name.casefold() != "runtime-temp"
    ):
        raise EvaluationError("candidate runtime cleanup target is not the exact attempt tmpdir")

    resolved_script = cleanup_script_path.resolve()
    expected_script = resolved_workspace / ".agentbase" / "runtime-cleanup.ps1"
    if resolved_script != expected_script or not resolved_script.is_file():
        raise EvaluationError("candidate runtime cleanup script is outside staged metadata")
    if sha256_file(resolved_script) != expected_cleanup_script_sha256:
        raise EvaluationError("candidate runtime cleanup script changed after staging")

    resolved_pwsh = pwsh_executable_path.resolve()
    if not resolved_pwsh.is_file() or sha256_file(resolved_pwsh) != expected_pwsh_sha256:
        raise EvaluationError("candidate runtime cleanup shell changed after staging")
    resolved_codex = codex_executable_path.resolve()
    if not resolved_codex.is_file():
        raise EvaluationError("candidate runtime cleanup Codex executable is missing")

    base = {
        "schema": "agentbase.windows-swe-runtime-cleanup/v1",
        "scope": "candidate",
        "script_sha256": expected_cleanup_script_sha256,
    }
    if not resolved_runtime.exists():
        payload = {
            **base,
            "passed": True,
            "command_invoked": False,
            "exit_code": None,
            "remaining_children": 0,
            "root_removed": True,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "diagnostic": None,
        }
        return {**payload, "receipt_sha256": sha256_bytes(canonical_bytes(payload))}
    if not resolved_runtime.is_dir() or _is_reparse_point(resolved_runtime):
        raise EvaluationError("candidate runtime cleanup target is not a regular directory")

    environment = dict(process_environment)
    for key in list(environment):
        upper = key.upper()
        if upper in {
            "ALL_PROXY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "OPENAI_API_KEY",
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
            "AZURE_OPENAI_API_KEY",
        } or upper.startswith("CODEX_"):
            environment.pop(key, None)
    environment["CODEX_HOME"] = str(codex_home.resolve())
    environment[WINDOWS_SANDBOX_LOCAL_BINDING_ENV_KEY] = "1"
    environment.update(sandbox_temp_environment(resolved_runtime))
    environment.pop("VIRTUAL_ENV", None)

    command = [
        str(resolved_codex),
        "sandbox",
        "-P",
        permission_profile,
        "-C",
        str(resolved_workspace),
        "--",
        str(resolved_pwsh),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(resolved_script),
        "-OwnerRoot",
        str(resolved_attempt),
        "-RuntimeTempPath",
        str(resolved_runtime),
        "-Scope",
        "Candidate",
    ]
    exit_code: int | None = None
    diagnostic: str | None = None
    try:
        completed = run_capture(
            command,
            cwd=resolved_workspace,
            env=environment,
            timeout=180,
            check=False,
        )
        exit_code = completed.returncode
        combined = (completed.stderr + completed.stdout).decode(
            "utf-8", errors="replace"
        )
        diagnostic = bounded_text(combined, 800) or None
    except EvaluationError as exc:
        diagnostic = bounded_text(str(exc), 800)

    remaining_children: int | None
    try:
        remaining_children = sum(1 for _ in resolved_runtime.iterdir())
    except OSError as exc:
        remaining_children = None
        detail = bounded_text(str(exc), 300)
        diagnostic = f"{diagnostic}; host inspection: {detail}" if diagnostic else detail
    passed = exit_code == 0 and remaining_children == 0
    root_removed = False
    if passed:
        try:
            resolved_runtime.rmdir()
            root_removed = True
        except OSError as exc:
            passed = False
            detail = bounded_text(str(exc), 300)
            diagnostic = f"{diagnostic}; root removal: {detail}" if diagnostic else detail

    payload = {
        **base,
        "passed": passed,
        "command_invoked": True,
        "exit_code": exit_code,
        "remaining_children": remaining_children,
        "root_removed": root_removed,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "diagnostic": diagnostic,
    }
    return {**payload, "receipt_sha256": sha256_bytes(canonical_bytes(payload))}


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
        preflight.get("schema") == "agentbase.windows-swe-preflight/v12"
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
        and isinstance(preflight.get("runtime_home_attempt_scoped"), bool)
        and isinstance(preflight.get("runtime_localappdata_attempt_scoped"), bool)
        and isinstance(preflight.get("pytest_temp_policy_ready"), bool)
        and isinstance(preflight.get("task_runtime_path_ready"), bool)
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
        and preflight.get("runtime_home_attempt_scoped") is True
        and preflight.get("runtime_localappdata_attempt_scoped") is True
        and preflight.get("pytest_temp_policy_ready") is True
        and preflight.get("task_runtime_path_ready") is True
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
    if preflight["runtime_home_attempt_scoped"] is not True:
        failed.append("runtime-home-outside-attempt-tmpdir")
    if (
        preflight["runtime_appdata_attempt_scoped"] is not True
        or preflight["runtime_localappdata_attempt_scoped"] is not True
    ):
        failed.append("runtime-appdata-outside-attempt-tmpdir")
    if preflight["pytest_temp_policy_ready"] is not True:
        failed.append("pytest-private-temp-cleanup-unavailable")
    if preflight["task_runtime_path_ready"] is not True:
        failed.append("task-runtime-path-unavailable")
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
    runtime_temp: Path,
    sandbox_runtime: Mapping[str, Any],
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
    cleanup_script_path: Path,
    expected_cleanup_script_sha256: str,
    cleanup_shell_path: Path,
    expected_cleanup_shell_sha256: str,
    process_environment: Mapping[str, str],
) -> dict[str, Any]:
    prepare_sandbox_writable_root(
        workspace.parent,
        workspace,
        create_runtime_subdirs=False,
    )
    prepare_sandbox_writable_root(state_root, runtime_temp)
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
        "-RuntimeTemp",
        str(runtime_temp.resolve()),
        "-SandboxRuntimeStatePath",
        str(Path(str(sandbox_runtime["state_path"])).resolve()),
        "-ExpectedSandboxRuntimeIdentitySha256",
        str(sandbox_runtime["identity_sha256"]),
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
    if codex_executable_path is None:
        raise EvaluationError("candidate preflight cleanup requires the resolved Codex executable")
    launch_failure: EvaluationError | None = None
    completed: subprocess.CompletedProcess[bytes] | None = None
    try:
        completed = run_capture(
            argv,
            env=process_environment,
            timeout=600,
            check=False,
        )
    except EvaluationError as exc:
        launch_failure = exc
    cleanup = cleanup_candidate_runtime_temp(
        workspace=workspace,
        attempt_root=runtime_temp.resolve().parent,
        runtime_temp=runtime_temp,
        codex_home=codex_home,
        codex_executable_path=codex_executable_path,
        pwsh_executable_path=cleanup_shell_path,
        expected_pwsh_sha256=expected_cleanup_shell_sha256,
        cleanup_script_path=cleanup_script_path,
        expected_cleanup_script_sha256=expected_cleanup_script_sha256,
        permission_profile=permission_profile,
        process_environment=process_environment,
    )
    if result_path.is_file():
        staged_value = read_json(result_path)
        staged_value["runtime_cleanup"] = cleanup
        write_json_atomic(result_path, staged_value)
    if launch_failure is not None:
        raise launch_failure
    if cleanup.get("passed") is not True:
        raise EvaluationError(
            "candidate sandbox preflight runtime cleanup failed: "
            + bounded_text(str(cleanup.get("diagnostic") or "unknown error"), 400)
        )
    assert completed is not None
    if not result_path.is_file():
        diagnostic = bounded_text(
            (completed.stderr + completed.stdout).decode("utf-8", errors="replace"),
            600,
        )
        if is_elevated_sandbox_runtime_rejection(diagnostic):
            raise SandboxRuntimeInvalidError(
                "Codex rejected the prepared sandbox runtime; run sandbox-setup explicitly"
            )
        raise EvaluationError(
            f"candidate sandbox preflight produced no result ({completed.returncode}): "
            f"{diagnostic}"
        )
    value = read_json(result_path)
    preflight = value.get("preflight")
    if value.get("schema") != "agentbase.windows-swe-sandbox-check/v5" or not isinstance(
        preflight, dict
    ):
        raise EvaluationError("candidate sandbox preflight returned an invalid result")
    runtime_use = value.get("sandbox_runtime")
    if (
        not sandbox_runtime_use_is_valid(runtime_use)
        or runtime_use.get("identity_sha256") != sandbox_runtime.get("identity_sha256")
    ):
        raise EvaluationError("candidate sandbox preflight returned an invalid runtime receipt")
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


def candidate_rollout_snapshot(codex_home: Path) -> dict[str, dict[str, Any]]:
    """Return a bounded identity map for persisted rollouts in the isolated runtime."""

    resolved_home = codex_home.resolve()
    observed: dict[str, dict[str, Any]] = {}
    for subdirectory in ("sessions", "archived_sessions"):
        root = resolved_home / subdirectory
        if not root.exists():
            continue
        if not root.is_dir() or _is_reparse_point(root):
            raise EvaluationError(f"candidate rollout root is not a regular directory: {root}")
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name
                for name in directories
                if not _is_reparse_point(current_path / name)
            ]
            for filename in filenames:
                if not (filename.endswith(".jsonl") or filename.endswith(".jsonl.zst")):
                    continue
                path = (current_path / filename).resolve()
                if _is_reparse_point(path) or not path.is_file():
                    raise EvaluationError(f"candidate rollout is not a regular file: {path}")
                relative = path.relative_to(resolved_home).as_posix()
                stat_result = path.stat()
                observed[relative.casefold()] = {
                    "path": path,
                    "relative_path": relative,
                    "bytes": stat_result.st_size,
                    "modified_ns": stat_result.st_mtime_ns,
                }
                if len(observed) > MAX_ATTEMPT_ROLLOUT_FILES * 8:
                    raise EvaluationError("evaluation runtime contains too many persisted rollouts")
    return observed


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
        raise EvaluationError(f"API pricing snapshot does not cover model {requested_model}")
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
                    group["cost_usd_nanos"] += int(priced["cost_usd_nanos"])
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
        total_cost_usd_nanos += int(group["cost_usd_nanos"])
        groups.append(
            {
                **{name: value for name, value in group.items() if name != "requested_models"},
                "requested_models": sorted(group["requested_models"]),
                "cost_usd": format_usd_nanos(int(group["cost_usd_nanos"])),
            }
        )
    return {
        "thread_id": thread_id,
        "parent_thread_id": metadata.get("parent_thread_id"),
        "forked_from_id": metadata.get("forked_from_id"),
        "agent_role": metadata.get("agent_role"),
        "agent_path": metadata.get("agent_path"),
        "agent_nickname": metadata.get("agent_nickname"),
        "turn_started_count": turn_started_count,
        "turn_terminal_count": turn_terminal_count,
        "usage_complete": usage_complete,
        "usage": usage,
        "request_count": response_count,
        "long_context_request_count": long_context_response_count,
        "pricing_complete": usage_complete,
        "api_equivalent_cost_usd_nanos": total_cost_usd_nanos,
        "api_equivalent_cost_usd": format_usd_nanos(total_cost_usd_nanos),
        "pricing_groups": groups,
        "subagent_history_start_ordinal": metadata.get("subagent_history_start_ordinal"),
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
    after = candidate_rollout_snapshot(codex_home)
    new_entries = [after[key] for key in sorted(set(after) - set(before))]
    if not new_entries:
        raise EvaluationError("Codex candidate persisted no rollout usage evidence")
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
    if pending:
        raise EvaluationError(
            "Codex candidate created rollout threads outside the root lineage: "
            + ", ".join(sorted(pending))
        )

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
        aggregate_cost_usd_nanos += int(record["api_equivalent_cost_usd_nanos"])
        request_count += int(record["request_count"])
        long_context_request_count += int(record["long_context_request_count"])
        if record["thread_id"] != root_thread_id:
            _sum_token_usage(subagent, record["usage"])
            subagent_cost_usd_nanos += int(record["api_equivalent_cost_usd_nanos"])
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
        "root_usd_nanos": aggregate_cost_usd_nanos - subagent_cost_usd_nanos,
        "subagent_usd_nanos": subagent_cost_usd_nanos,
        "total_usd": format_usd_nanos(aggregate_cost_usd_nanos),
        "root_usd": format_usd_nanos(aggregate_cost_usd_nanos - subagent_cost_usd_nanos),
        "subagent_usd": format_usd_nanos(subagent_cost_usd_nanos),
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
    return result


def invoke_candidate(
    *,
    project_root: Path,
    workspace: Path,
    state_root: Path,
    attempt_root: Path,
    codex_home: Path,
    runtime_temp: Path,
    sandbox_runtime: Mapping[str, Any],
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
    prepare_sandbox_writable_root(
        workspace.parent,
        workspace,
        create_runtime_subdirs=False,
    )
    prepare_sandbox_writable_root(attempt_root, runtime_temp)
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
        "-RuntimeTemp",
        str(runtime_temp.resolve()),
        "-SandboxRuntimeStatePath",
        str(Path(str(sandbox_runtime["state_path"])).resolve()),
        "-ExpectedSandboxRuntimeIdentitySha256",
        str(sandbox_runtime["identity_sha256"]),
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
    task_runtime = metadata.get("task_runtime")
    if not isinstance(task_runtime, Mapping):
        raise EvaluationError("candidate task runtime projection is missing")
    task_runtime_bin = task_runtime.get("bin_directory")
    if not isinstance(task_runtime_bin, str) or not task_runtime_bin:
        raise EvaluationError("candidate task runtime bin directory is missing")
    argv.extend(["-TaskRuntimeBinPath", task_runtime_bin])
    if codex_executable_path is not None:
        argv.extend(["-CodexExecutablePath", str(codex_executable_path.resolve())])
    rollouts_before = candidate_rollout_snapshot(codex_home)
    launcher_failure: EvaluationError | None = None
    result: subprocess.CompletedProcess[bytes] | None = None
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
        launcher_failure = EvaluationError(f"candidate launcher failed: {exc}")
    if result_path.is_file():
        preliminary_result = read_json(result_path)
        if (
            preliminary_result.get("schema") == CODEX_RUN_RESULT_SCHEMA
            and preliminary_result.get("model_invoked") is True
        ):
            preliminary_result = finalize_candidate_agent_usage(
                preliminary_result,
                codex_home=codex_home,
                before=rollouts_before,
            )
            write_json_atomic(result_path, preliminary_result)
    cleanup_started = time.perf_counter()
    try:
        if codex_executable_path is None:
            raise EvaluationError("candidate runtime cleanup requires the resolved Codex executable")
        cleanup = cleanup_candidate_runtime_temp(
            workspace=workspace,
            attempt_root=attempt_root,
            runtime_temp=runtime_temp,
            codex_home=codex_home,
            codex_executable_path=codex_executable_path,
            pwsh_executable_path=Path(str(metadata["runtime_cleanup_shell_path"])),
            expected_pwsh_sha256=str(metadata["runtime_cleanup_shell_sha256"]),
            cleanup_script_path=Path(str(metadata["runtime_cleanup_script_path"])),
            expected_cleanup_script_sha256=str(
                metadata["runtime_cleanup_script_sha256"]
            ),
            permission_profile=str(corpus["codex"]["candidate_permission_profile"]),
            process_environment=process_environment,
        )
    except (EvaluationError, KeyError, TypeError) as exc:
        cleanup_payload = {
            "schema": "agentbase.windows-swe-runtime-cleanup/v1",
            "scope": "candidate",
            "script_sha256": metadata.get("runtime_cleanup_script_sha256"),
            "passed": False,
            "command_invoked": False,
            "exit_code": None,
            "remaining_children": None,
            "root_removed": False,
            "duration_seconds": round(time.perf_counter() - cleanup_started, 3),
            "diagnostic": bounded_text(str(exc), 800),
        }
        cleanup = {
            **cleanup_payload,
            "receipt_sha256": sha256_bytes(canonical_bytes(cleanup_payload)),
        }
    if result_path.is_file():
        staged_result = read_json(result_path)
        staged_result["runtime_cleanup"] = cleanup
        write_json_atomic(result_path, staged_result)
    if launcher_failure is not None:
        raise launcher_failure
    assert result is not None
    if result.returncode != 0:
        detail = bounded_text(
            (result.stderr + result.stdout).decode("utf-8", errors="replace"),
            800,
        )
        if result_path.is_file():
            trusted_result = read_json(result_path)
            preflight = trusted_result.get("preflight")
            if (
                trusted_result.get("schema") != CODEX_RUN_RESULT_SCHEMA
                or trusted_result.get("status") != "blocked-precondition"
                or trusted_result.get("model_invoked") is not False
                or trusted_result.get("exit_code") is not None
                or not sandbox_runtime_use_is_valid(
                    trusted_result.get("sandbox_runtime")
                )
                or trusted_result.get("sandbox_runtime", {}).get("identity_sha256")
                != sandbox_runtime.get("identity_sha256")
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
        if is_elevated_sandbox_runtime_rejection(detail):
            raise SandboxRuntimeInvalidError(
                "Codex rejected the prepared sandbox runtime; run sandbox-setup explicitly"
            )
        raise EvaluationError(f"candidate launcher failed ({result.returncode}): {detail}")
    value = read_json(result_path)
    if (
        value.get("schema") != CODEX_RUN_RESULT_SCHEMA
        or value.get("status") != "completed"
        or value.get("model_invoked") is not True
        or not sandbox_runtime_use_is_valid(value.get("sandbox_runtime"))
        or value.get("sandbox_runtime", {}).get("identity_sha256")
        != sandbox_runtime.get("identity_sha256")
    ):
        raise EvaluationError("candidate launcher returned an invalid result")
    runtime_cleanup = value.get("runtime_cleanup")
    if (
        not isinstance(runtime_cleanup, Mapping)
        or runtime_cleanup.get("schema") != "agentbase.windows-swe-runtime-cleanup/v1"
        or runtime_cleanup.get("scope") != "candidate"
        or not isinstance(runtime_cleanup.get("passed"), bool)
        or not isinstance(runtime_cleanup.get("receipt_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", runtime_cleanup["receipt_sha256"]) is None
    ):
        raise EvaluationError("candidate launcher returned an invalid runtime cleanup receipt")
    if value.get("exit_code") != 0:
        raise EvaluationError(
            f"Codex candidate process failed: {bounded_text(str(value.get('diagnostic', '')), 800)}"
        )
    if (
        value.get("usage_scope") != "root-and-descendant-threads"
        or value.get("usage_complete") is not True
        or not isinstance(value.get("agent_usage"), list)
        or value.get("agent_thread_count") != len(value["agent_usage"])
        or not isinstance(value.get("agent_usage_receipt_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["agent_usage_receipt_sha256"])
        or not isinstance(value.get("api_equivalent_cost"), dict)
        or value["api_equivalent_cost"].get("schema") != API_EQUIVALENT_COST_SCHEMA
        or value["api_equivalent_cost"].get("complete") is not True
        or value["api_equivalent_cost"].get("actual_billing_observed") is not False
    ):
        raise EvaluationError("Codex candidate returned incomplete agent usage or API cost accounting")
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
