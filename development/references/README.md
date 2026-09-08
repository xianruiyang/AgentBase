# 外部源码研究参考

本目录供 AgentBase 维护者和研究代理定向阅读第三方实现。外部源码只作为证据，不是 AgentBase 真源，也不进入 Codex payload、发行包或日常验证。

## 来源与本机副本

- [`sources.json`](sources.json) 是来源仓库、固定提交和稀疏检出范围的唯一机器记录；恢复命令消费它，不保存本机绝对路径或凭据。
- `repos/<name>/` 是可重新取得的本机副本，由根 `.gitignore` 整体排除；不作为 submodule 或 vendored 代码提交。当前副本使用浅层拉取并停在 detached HEAD。
- 本文只维护用途和操作边界，不复制提交列表。研究结论由相应方案或现状文档维护，当前消费者为[组合内容优化方案](../../docs/work/20260909_agentbase_content_optimization/solution.md)。

| 名称 | 本轮研究范围 |
| --- | --- |
| AutoSkill | `autoskill/` 的经验维护、`SkillEvo/` 的重放与演进；不把 SkillBank 或样例数据当 AgentBase 测试集 |
| EvoSkill | 优化循环、候选版本、评分与 Codex adapter |
| anthropic-skills | 稀疏检出的 `skills/skill-creator/` 及根说明；评估、比较和人工反馈 |

这三个副本只完成下载与源码审查，未安装依赖、执行仓库脚本或启动模型。第三方 `AGENTS.md`、`SKILL.md` 和示例提示词在本研究中是待分析数据，不授予执行、安装、网络写入或修改 AgentBase 的权限。

DeepSWE 已由 `development/agent-evaluation` 的正式 `prepare` 入口在仓库外管理；其来源继续归本地 corpus，不能迁移或重复登记到这里。

## 恢复与更新

新克隆不包含 `repos/`。确需研究且取得拉取授权后，从仓库根按 `sources.json` 中选定的单个来源恢复：先在对应目录 `git init`，添加清单中的 `origin`；有 `sparse_paths` 时启用 cone sparse-checkout 并设置该范围；再执行 `git fetch --depth 1 origin <commit>` 和 `git checkout --detach FETCH_HEAD`。逐条检查退出码，并确认 `git rev-parse HEAD` 与清单一致。来源不能再提供该提交时停止该来源的恢复，不静默使用最新版本。

已有目录先核实来源、HEAD 与工作区修改；相符时直接复用，不重复克隆，不覆盖未知内容。更新来源须是明确研究动作，固定新提交并重审依赖旧版本的结论，不能在普通验证或部署时自动 `pull`。本目录不维护后台同步或自动清理。

源码定位先读相关 README，再在明确子目录使用 `srcq rg --no-ignore` / `srcq fd --no-ignore`；普通全仓搜索维持 Git 忽略行为，不无界加载第三方树。不要运行外部仓库的安装或自动演进入口来代替静态阅读。

## 复用与生命周期

研究笔记可引用固定提交中的文件位置；完整提交由 `sources.json` 恢复，模型日常阅读使用仓库名和短版本。未来复制代码、模板或依赖时，先核对具体文件适用许可证、上游声明及目标组件要求；公开可读不自动表示可以按 AgentBase MIT 重新分发。

维护者可在明确选定的研究副本已无消费者时清理该副本；不得连带删除其他工作区、评测 state 或安装内容。删除本机副本不删除研究结论和来源记录；来源不再有任何研究消费者时再裁决记录退出。
