from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
RETIRED_QUERY_SKILLS = {
    "ast-grep-token-safe",
    "fd-usage",
    "rg-token-safe",
}
SHARED_QUERY_SKILLS = {
    "powershell-usage",
    "symbol-structure-workflow",
}
PREMIGRATION_SKILLS = RETIRED_QUERY_SKILLS | SHARED_QUERY_SKILLS
MIGRATED_SKILLS = SHARED_QUERY_SKILLS | {"source-query"}
MINIMAL_RELEVANT_SKILLS = PREMIGRATION_SKILLS | MIGRATED_SKILLS
OLD_ROUTE = "should: 文本内容搜索先用受限 `rg`；文件发现使用受限 `fd`；只有文本不能可靠表达语法结构时升级 AST，只有结论依赖真实符号身份时升级 LSP"
CURRENT_ROUTE_PREFIX = "must: 全集、不存在或唯一结论先从最近正式来源确认权威源码范围；"
PREVIOUS_SCOPE_ROUTE_PREFIX = "must: 全集、不存在或唯一结论先确认权威源码范围；源码文件与文本搜索使用 PATH 中的 `srcq fd` / `srcq rg`，"
CURRENT_EVIDENCE_ROUTE_PREFIX = "must: 源码定位在答案中保留最小可复查文件与范围；"
PREVIOUS_CONDITIONAL_ROUTE_PREFIX = "must: 源码文件与文本搜索在来源选择会改变结论时先确认权威源码范围，再使用 PATH 中的 `srcq fd` / `srcq rg`；"
PREVIOUS_ORDERED_ROUTE_PREFIX = "must: 源码文件与文本搜索先限定当前职责的权威源码根，再使用 PATH 中的 `srcq fd` / `srcq rg`；"
PREVIOUS_AUTHORITY_ROUTE_PREFIX = "must: 源码文件与文本搜索先限定当前职责的权威源码根，使用 PATH 中的 `srcq fd` / `srcq rg`；"
PREVIOUS_COMBINED_ROUTE_PREFIX = "must: 源码文件与文本搜索限定当前职责的权威源码根并使用 PATH 中的 `srcq fd` / `srcq rg`；"
PREVIOUS_DIRECT_ROUTE_PREFIX = "must: 源码文件与文本搜索使用 PATH 中的 `srcq fd` / `srcq rg`；"
PREVIOUS_COMPACT_ROUTE_PREFIX = "must: 源码查找先明确当前仍缺的直接证据和权威范围；"
PREVIOUS_DEPENDENCY_ROUTE_PREFIX = "must: 源码查询先确定"
PREVIOUS_CURRENT_ROUTE_PREFIX = "must: 模型进行源码查找时"
PREVIOUS_MIGRATED_ROUTE_PREFIX = "should: 源码查找先明确当前仍缺的证据；"
MIGRATED_ROUTE_PREFIXES = (
    CURRENT_ROUTE_PREFIX,
    PREVIOUS_SCOPE_ROUTE_PREFIX,
    PREVIOUS_CONDITIONAL_ROUTE_PREFIX,
    PREVIOUS_ORDERED_ROUTE_PREFIX,
    PREVIOUS_AUTHORITY_ROUTE_PREFIX,
    PREVIOUS_COMBINED_ROUTE_PREFIX,
    PREVIOUS_DIRECT_ROUTE_PREFIX,
    PREVIOUS_COMPACT_ROUTE_PREFIX,
    PREVIOUS_DEPENDENCY_ROUTE_PREFIX,
    PREVIOUS_CURRENT_ROUTE_PREFIX,
    PREVIOUS_MIGRATED_ROUTE_PREFIX,
)
LEGACY_AUXILIARY_ROUTE_PREFIXES = (
    CURRENT_EVIDENCE_ROUTE_PREFIX,
    "must: 全集或不存在结论先确定正式源码根；",
    "must: 已知名称先用文本定位和有界正文闭环；",
    "must: 源码结论的压缩不得删除",
)
SUPPORTED_ROUTE_PREFIXES = MIGRATED_ROUTE_PREFIXES + LEGACY_AUXILIARY_ROUTE_PREFIXES


def config_text(lsp_server: str | None, trusted_projects: tuple[Path, ...] = ()) -> str:
    lines = [
        'model = "gpt-5.6-sol"',
        'model_reasoning_effort = "medium"',
        'service_tier = "default"',
        'project_doc_max_bytes = 65536',
        'sandbox_mode = "danger-full-access"',
        '',
        '[features]',
        'hooks = false',
        'multi_agent = false',
        'plugins = false',
        'remote_plugin = false',
        'recommended_plugins = false',
        'apps = false',
        'browser_use = false',
    ]
    if lsp_server:
        escaped = lsp_server.replace("\\", "\\\\").replace('"', '\\"')
        lines.extend([
            '',
            '[mcp_servers.vscode-lsp-mcp]',
            'command = "node"',
            f'args = ["{escaped}"]',
            'startup_timeout_sec = 10',
            'tool_timeout_sec = 120',
            'enabled = true',
        ])
    for project in trusted_projects:
        key = str(project.resolve()).lower()
        if "'" in key:
            raise SystemExit(f"trusted project path cannot be encoded safely in TOML: {project}")
        lines.extend([
            '',
            f"[projects.'{key}']",
            'trust_level = "trusted"',
        ])
    return "\n".join(lines) + "\n"


def agentbase_skill_names() -> set[str]:
    """Ownership comes from deployment history; content comes from the selected home."""
    lifecycle = json.loads(
        (PROJECT_ROOT / "development" / "codex-deployment" / "managed_asset_lifecycle.json")
        .read_text(encoding="utf-8")
    )
    return {
        item["path"].split("/", 1)[1]
        for state in ("present", "retired")
        for item in lifecycle["paths"][state]
        if item["id"].startswith("skill:") and item["path"].startswith("skills/")
    }


def copy_agentbase_skills(source: Path, target: Path) -> None:
    target.mkdir()
    for name in sorted(agentbase_skill_names()):
        skill = source / name
        if (skill / "SKILL.md").is_file():
            shutil.copytree(skill, target / name)


def copy_current_control(
    installed: Path,
    target: Path,
    srcq_exe: Path,
    lsp_server: str | None,
    trusted_projects: tuple[Path, ...],
) -> None:
    if target.exists():
        raise SystemExit(f"target must not already exist: {target}")
    target.mkdir(parents=True)
    auth = installed / "auth.json"
    if auth.is_file():
        os.link(auth, target / "auth.json")
    shutil.copy2(installed / "AGENTS.md", target / "AGENTS.md")
    copy_agentbase_skills(installed / "skills", target / "skills")
    (target / "config.toml").write_text(
        config_text(lsp_server, trusted_projects), encoding="utf-8",
    )
    (target / "bin").mkdir()
    shutil.copy2(srcq_exe, target / "bin" / "srcq.exe")


def clone_current_control(control: Path, candidate: Path, installed: Path) -> None:
    if candidate.exists():
        raise SystemExit(f"target must not already exist: {candidate}")
    candidate.mkdir(parents=True)
    for name in ("AGENTS.md", "config.toml"):
        shutil.copy2(control / name, candidate / name)
    copy_agentbase_skills(control / "skills", candidate / "skills")
    (candidate / "bin").mkdir()
    shutil.copy2(control / "bin" / "srcq.exe", candidate / "bin" / "srcq.exe")
    auth = installed / "auth.json"
    if auth.is_file():
        os.link(auth, candidate / "auth.json")


def validate_benchmark_home_location(path: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError:
        return
    raise SystemExit(
        f"benchmark Codex home must not be under the system temp directory: {resolved}; "
        "use a stable isolated root such as %LOCALAPPDATA%\\AgentBase\\benchmark-homes"
    )


def current_route() -> str:
    lines = (PROJECT_ROOT / "global" / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    matches = [line for line in lines if line.startswith(CURRENT_ROUTE_PREFIX)]
    if len(matches) != 1:
        raise SystemExit("project global/AGENTS.md must contain exactly one current source-query route")
    return matches[0]


def current_route_block() -> str:
    return current_route()


def migrated_route(text: str) -> str:
    matches = [line for line in text.splitlines() if line.startswith(MIGRATED_ROUTE_PREFIXES)]
    if len(matches) != 1:
        raise SystemExit("installed AGENTS.md must contain exactly one supported migrated source-query route")
    return matches[0]


def replace_migrated_route(text: str) -> str:
    migrated_route(text)
    lines = text.splitlines()
    for prefix in SUPPORTED_ROUTE_PREFIXES:
        if sum(line.startswith(prefix) for line in lines) > 1:
            raise SystemExit(f"installed AGENTS.md contains duplicate source-query route: {prefix}")
    output: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith(SUPPORTED_ROUTE_PREFIXES):
            if not inserted:
                output.append(current_route())
                inserted = True
            continue
        if not line and output and not output[-1]:
            continue
        output.append(line)
    while output and not output[-1]:
        output.pop()
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def copy_common(
    installed: Path,
    target: Path,
    lsp_server: str | None,
    full_installed_skills: bool,
    baseline_mode: str,
    trusted_projects: tuple[Path, ...] = (),
) -> None:
    if target.exists():
        raise SystemExit(f"target must not already exist: {target}")
    target.mkdir(parents=True)
    auth = installed / "auth.json"
    if auth.is_file():
        os.link(auth, target / "auth.json")
    agents = (installed / "AGENTS.md").read_text(encoding="utf-8")
    if baseline_mode == "premigration":
        if agents.count(OLD_ROUTE) != 1:
            raise SystemExit("installed AGENTS.md does not contain exactly one frozen source-query route")
    else:
        migrated_route(agents)
    (target / "AGENTS.md").write_text(agents, encoding="utf-8")
    (target / "config.toml").write_text(config_text(lsp_server, trusted_projects), encoding="utf-8")
    skills_target = target / "skills"
    skills_target.mkdir()
    owned_skills = agentbase_skill_names()
    for source in sorted((installed / "skills").iterdir(), key=lambda item: item.name.lower()):
        if not source.is_dir() or source.name not in owned_skills:
            continue
        if source.name == "source-query" and baseline_mode == "premigration":
            raise SystemExit("installed control already contains source-query; select a pre-migration control home")
        selected_skills = PREMIGRATION_SKILLS if baseline_mode == "premigration" else MIGRATED_SKILLS
        if not full_installed_skills and source.name not in selected_skills:
            continue
        shutil.copytree(source, skills_target / source.name)


def verify_srcq_ingress(srcq_exe: Path) -> str:
    version = subprocess.run(
        [str(srcq_exe), "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if not version.startswith("srcq "):
        raise SystemExit(f"unexpected srcq executable identity: {version!r}")
    sentinel = "SRCQ_INGRESS_SENTINEL_7F39"
    with tempfile.TemporaryDirectory(prefix="AgentBase-srcq-ingress-") as raw:
        root = Path(raw)
        source = root / "probe.rs"
        source.write_text(f"const VALUE: &str = \"{sentinel}\";\n", encoding="utf-8")
        completed = subprocess.run(
            [str(srcq_exe), "rg", "--fixed-strings", sentinel, source.name],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    if completed.returncode != 0 or sentinel not in completed.stdout or source.name not in completed.stdout:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(f"srcq executable does not support intuitive rg ingress: {detail}")
    return version


def install_candidate_bundle(control: Path, candidate: Path, srcq_exe: Path) -> None:
    for skill_name in RETIRED_QUERY_SKILLS:
        shutil.rmtree(candidate / "skills" / skill_name, ignore_errors=True)
    for skill_name in ("symbol-structure-workflow", "source-query"):
        destination = candidate / "skills" / skill_name
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(PROJECT_ROOT / "skills" / skill_name, destination)
    for home in (control, candidate):
        (home / "bin").mkdir()
    shutil.copy2(srcq_exe, candidate / "bin" / "srcq.exe")


def install_incremental_bundle(
    control: Path,
    candidate: Path,
    baseline_srcq_exe: Path,
    candidate_srcq_exe: Path,
) -> None:
    destination = candidate / "skills" / "source-query"
    shutil.rmtree(destination)
    shutil.copytree(PROJECT_ROOT / "skills" / "source-query", destination)
    for home in (control, candidate):
        (home / "bin").mkdir()
    shutil.copy2(baseline_srcq_exe, control / "bin" / "srcq.exe")
    shutil.copy2(candidate_srcq_exe, candidate / "bin" / "srcq.exe")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-codex-home", required=True, type=Path)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--srcq-exe", required=True, type=Path)
    parser.add_argument("--vscode-lsp-server")
    parser.add_argument(
        "--trusted-project",
        action="append",
        default=[],
        type=Path,
        help="existing benchmark workspace to pre-register as trusted; repeat for every workspace",
    )
    parser.add_argument(
        "--full-installed-skills",
        action="store_true",
        help="copy all installed AgentBase-owned skills; default copies only the query experiment's causal skill set",
    )
    parser.add_argument("--minimal", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--baseline-mode",
        choices=("premigration", "migrated", "current-control"),
        default="premigration",
        help="compare a query migration, or freeze current AGENTS and AgentBase-owned installed skills",
    )
    parser.add_argument(
        "--baseline-srcq-exe",
        type=Path,
        help="required with --baseline-mode migrated; copied only into the control home",
    )
    args = parser.parse_args()
    installed = args.installed_codex_home.resolve()
    control = args.control.resolve()
    candidate = args.candidate.resolve()
    validate_benchmark_home_location(control)
    validate_benchmark_home_location(candidate)
    trusted_projects = tuple(project.resolve() for project in args.trusted_project)
    missing_projects = [str(project) for project in trusted_projects if not project.is_dir()]
    if missing_projects:
        raise SystemExit(f"trusted benchmark project does not exist: {missing_projects}")
    srcq_exe = args.srcq_exe.resolve()
    if not srcq_exe.is_file():
        raise SystemExit(f"srcq executable does not exist: {srcq_exe}")
    version = verify_srcq_ingress(srcq_exe)
    baseline_srcq_exe = args.baseline_srcq_exe.resolve() if args.baseline_srcq_exe else None
    if args.baseline_mode == "migrated" and (
        baseline_srcq_exe is None or not baseline_srcq_exe.is_file()
    ):
        raise SystemExit("--baseline-mode migrated requires an existing --baseline-srcq-exe")
    if args.minimal and args.full_installed_skills:
        raise SystemExit("--minimal and --full-installed-skills cannot be combined")
    if args.baseline_mode == "current-control":
        if args.full_installed_skills or args.minimal or baseline_srcq_exe is not None:
            raise SystemExit("current-control fixes the AgentBase-owned installed skill set and accepts no skill-scope flags")
        copy_current_control(
            installed, control, srcq_exe, args.vscode_lsp_server, trusted_projects,
        )
        clone_current_control(control, candidate, installed)
        allowed = ""
    else:
        copy_common(
            installed, control, args.vscode_lsp_server, args.full_installed_skills, args.baseline_mode,
            trusted_projects,
        )
        copy_common(
            installed, candidate, args.vscode_lsp_server, args.full_installed_skills, args.baseline_mode,
            trusted_projects,
        )
    if args.baseline_mode == "premigration":
        install_candidate_bundle(control, candidate, srcq_exe)
        candidate_agents = (candidate / "AGENTS.md").read_text(encoding="utf-8")
        candidate_route = current_route()
        (candidate / "AGENTS.md").write_text(
            candidate_agents.replace(OLD_ROUTE, current_route_block()), encoding="utf-8"
        )
        allowed = "AGENTS.md,bin/srcq.exe,skills/ast-grep-token-safe/**,skills/fd-usage/**,skills/rg-token-safe/**,skills/source-query/**,skills/symbol-structure-workflow/**"
    elif args.baseline_mode == "migrated":
        install_incremental_bundle(control, candidate, baseline_srcq_exe, srcq_exe)
        candidate_agents = (candidate / "AGENTS.md").read_text(encoding="utf-8")
        (candidate / "AGENTS.md").write_text(replace_migrated_route(candidate_agents), encoding="utf-8")
        allowed = "AGENTS.md,bin/srcq.exe,skills/source-query/**"
    print(f"control={control}")
    print(f"candidate={candidate}")
    print(f"srcq={version}")
    if args.baseline_mode == "premigration":
        print("retired_in_candidate=" + ",".join(sorted(RETIRED_QUERY_SKILLS)))
    print(f"baseline_mode={args.baseline_mode}")
    if args.baseline_mode == "current-control":
        print("skill_scope=agentbase-owned; external_plugins=disabled")
    print(f"allowed_differences={allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
