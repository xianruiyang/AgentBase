from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
REMOVED_SEARCH_SKILLS = {
    "ast-grep-token-safe",
    "fd-usage",
    "powershell-usage",
    "rg-token-safe",
    "symbol-structure-workflow",
}
OLD_ROUTE = "should: 文本内容搜索先用受限 `rg`；文件发现使用受限 `fd`；只有文本不能可靠表达语法结构时升级 AST，只有结论依赖真实符号身份时升级 LSP"


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


def copy_common(installed: Path, target: Path, lsp_server: str | None, include_other_skills: bool) -> None:
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
    if include_other_skills:
        for source in sorted((installed / "skills").iterdir(), key=lambda item: item.name.lower()):
            if not source.is_dir() or source.name == ".system" or source.name in REMOVED_SEARCH_SKILLS or source.name == "source-query":
                continue
            shutil.copytree(source, skills_target / source.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-codex-home", required=True, type=Path)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--vscode-lsp-server")
    parser.add_argument("--minimal", action="store_true", help="exclude unrelated installed skills from both frozen environments")
    args = parser.parse_args()
    installed = args.installed_codex_home.resolve()
    control = args.control.resolve()
    candidate = args.candidate.resolve()
    copy_common(installed, control, args.vscode_lsp_server, not args.minimal)
    copy_common(installed, candidate, args.vscode_lsp_server, not args.minimal)
    candidate_agents = (candidate / "AGENTS.md").read_text(encoding="utf-8")
    candidate_route = (ROOT / "candidate-global-route.txt").read_text(encoding="utf-8").strip()
    (candidate / "AGENTS.md").write_text(candidate_agents.replace(OLD_ROUTE, candidate_route), encoding="utf-8")
    shutil.copytree(ROOT / "candidate-skill" / "source-query", candidate / "skills" / "source-query")
    print(f"control={control}")
    print(f"candidate={candidate}")
    print("removed=" + ",".join(sorted(REMOVED_SEARCH_SKILLS)))
    print("allowed_differences=AGENTS.md,skills/source-query/**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
