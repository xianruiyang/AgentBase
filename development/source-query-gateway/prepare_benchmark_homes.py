from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
RETIRED_QUERY_SKILLS = {
    "ast-grep-token-safe",
    "fd-usage",
    "rg-token-safe",
}
MINIMAL_RELEVANT_SKILLS = RETIRED_QUERY_SKILLS | {
    "powershell-usage",
    "symbol-structure-workflow",
}
OLD_ROUTE = "should: 文本内容搜索先用受限 `rg`；文件发现使用受限 `fd`；只有文本不能可靠表达语法结构时升级 AST，只有结论依赖真实符号身份时升级 LSP"
CURRENT_ROUTE_PREFIX = "should: 源码查找先明确当前仍缺的证据；"


def config_text(lsp_server: str | None) -> str:
    lines = [
        'model = "gpt-5.6-sol"',
        'model_reasoning_effort = "medium"',
        'service_tier = "fast"',
        'project_doc_max_bytes = 65536',
        'sandbox_mode = "read-only"',
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
    return "\n".join(lines) + "\n"


def current_route() -> str:
    lines = (PROJECT_ROOT / "global" / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    matches = [line for line in lines if line.startswith(CURRENT_ROUTE_PREFIX)]
    if len(matches) != 1:
        raise SystemExit("project global/AGENTS.md must contain exactly one current source-query route")
    return matches[0]


def copy_common(installed: Path, target: Path, lsp_server: str | None, minimal: bool) -> None:
    if target.exists():
        raise SystemExit(f"target must not already exist: {target}")
    target.mkdir(parents=True)
    auth = installed / "auth.json"
    if auth.is_file():
        os.link(auth, target / "auth.json")
    agents = (installed / "AGENTS.md").read_text(encoding="utf-8")
    if agents.count(OLD_ROUTE) != 1:
        raise SystemExit("installed AGENTS.md does not contain exactly one frozen source-query route")
    (target / "AGENTS.md").write_text(agents, encoding="utf-8")
    (target / "config.toml").write_text(config_text(lsp_server), encoding="utf-8")
    skills_target = target / "skills"
    skills_target.mkdir()
    system_skills = installed / "skills" / ".system"
    if system_skills.is_dir():
        shutil.copytree(system_skills, skills_target / ".system")
    for source in sorted((installed / "skills").iterdir(), key=lambda item: item.name.lower()):
        if not source.is_dir() or source.name == ".system":
            continue
        if source.name == "source-query":
            raise SystemExit("installed control already contains source-query; select a pre-migration control home")
        if minimal and source.name not in MINIMAL_RELEVANT_SKILLS:
            continue
        shutil.copytree(source, skills_target / source.name)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-codex-home", required=True, type=Path)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--srcq-exe", required=True, type=Path)
    parser.add_argument("--vscode-lsp-server")
    parser.add_argument("--minimal", action="store_true", help="exclude unrelated installed skills from both frozen environments")
    args = parser.parse_args()
    installed = args.installed_codex_home.resolve()
    control = args.control.resolve()
    candidate = args.candidate.resolve()
    srcq_exe = args.srcq_exe.resolve()
    if not srcq_exe.is_file():
        raise SystemExit(f"srcq executable does not exist: {srcq_exe}")
    version = subprocess.run(
        [str(srcq_exe), "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if not version.startswith("srcq "):
        raise SystemExit(f"unexpected srcq executable identity: {version!r}")
    copy_common(installed, control, args.vscode_lsp_server, args.minimal)
    copy_common(installed, candidate, args.vscode_lsp_server, args.minimal)
    install_candidate_bundle(control, candidate, srcq_exe)
    candidate_agents = (candidate / "AGENTS.md").read_text(encoding="utf-8")
    candidate_route = current_route()
    (candidate / "AGENTS.md").write_text(candidate_agents.replace(OLD_ROUTE, candidate_route), encoding="utf-8")
    print(f"control={control}")
    print(f"candidate={candidate}")
    print(f"srcq={version}")
    print("retired_in_candidate=" + ",".join(sorted(RETIRED_QUERY_SKILLS)))
    print("allowed_differences=AGENTS.md,bin/srcq.exe,skills/ast-grep-token-safe/**,skills/fd-usage/**,skills/rg-token-safe/**,skills/source-query/**,skills/symbol-structure-workflow/**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
