from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
OLD_ROUTE = "should: 文本内容搜索先用受限 `rg`；直接读取正文时，多文件显式使用 `--heading`、单个已知文件显式使用 `--no-filename`，`--no-heading` 只用于不进入模型上下文的逐行机器消费；文件发现使用受限 `fd`；只有文本不能可靠表达语法结构时升级 AST，只有结论依赖真实符号身份时升级 LSP"
SECURE_LINKS = {"auth.json", ".env"}


def ignore_secure(_: str, names: list[str]) -> set[str]:
    return set(names) & SECURE_LINKS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-control", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    control = args.frozen_control.resolve()
    candidate = args.candidate.resolve()
    if candidate.exists():
        raise SystemExit(f"candidate must not already exist: {candidate}")
    shutil.copytree(control, candidate, symlinks=True, ignore=ignore_secure)
    for name in SECURE_LINKS:
        source = control / name
        if source.exists():
            os.link(source, candidate / name)
    agents_path = candidate / "AGENTS.md"
    agents = agents_path.read_text(encoding="utf-8")
    new_route = (ROOT / "candidate-global-route.txt").read_text(encoding="utf-8").strip()
    if agents.count(OLD_ROUTE) != 1:
        raise SystemExit("frozen control does not contain exactly one expected route line")
    agents_path.write_text(agents.replace(OLD_ROUTE, new_route), encoding="utf-8")
    shutil.copytree(ROOT / "candidate-skill" / "source-query", candidate / "skills" / "source-query")
    print(f"control={control}")
    print(f"candidate={candidate}")
    print("secure_runtime_entries=hardlink:auth.json,.env")
    print("allowed_differences=AGENTS.md,skills/source-query/**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
