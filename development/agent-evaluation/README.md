# AgentBase Windows 评测框架

本目录维护 Windows 主机上的评测框架：[Evo](evo/README.md) 负责指定组件组合、分组评测与自定义评分；原 SWE 入口负责真实仓库任务及独立 Verifier。真实题目、题库配置和题目专用 Windows patch 只保留在本机，不属于 Git 跟踪的框架资产。评测不是发布门禁、远程 CI 或官方 leaderboard，也不证明未运行的模型行为。

Evo 通过 `agent_eval.py evo <action>` 使用，实际接口与数据生命周期见其说明。以下章节维护原 SWE 合同，Evo 不继承其中仅针对 SWE 的全组件默认投影、关闭 hooks 和逐题资格要求；共享投影、启动与用量仍归原 owner。

已有本地 SWE corpus 可通过 [`evo swe-import`](evo/README.md#使用本地-windows-swe-题组) 生成独立题组目录，再由研究规格引用。题组不定义模型、组件或运行参数；Evo 真正执行 SWE 题目时仍须消费原 SWE qualification 与独立 Verifier。导入和静态检查不会运行题目。

## 职责与真源

- `corpus/schema.json`：本地 corpus 的结构合同；不定义真实题目集合。
- `tests/fixtures/synthetic-corpus.json`：只供框架基础验证的最小合成 corpus，不含真实题目、仓库或答案。
- `corpus/final-v1.json`：既有本机真实 corpus 的默认路径；文件缺失时可通过 `--corpus <local-json>` 显式选择另一份本地 corpus。
- `agent_eval.py`：CLI、逐题状态机、资格、尝试、恢复和报告。
- `evo/`：组合规格、队列、资源与恢复、评分和人工评审；真实数据和状态位于本机独立根目录。
- `evo/swe_catalog.py`：本地 SWE 题组目录的静态投影与研究引用展开；原 corpus 继续持有题目权威，运行选择归研究规格。
- `agentbase_codex.py` 与 `invoke_candidate.ps1`：候选题目提示和依赖运行时、工作区组件投影、Codex CLI 调用、JSONL 使用量和 API 等价成本收据。
- `windows_verifier.py`：依赖准备、Windows adapter、patch 应用、检查、报告转换和固定 grader。
- `evaluation_core.py`：路径边界、身份、锁、不可变收据、Git 工作区和通用状态。
- `windows-adapters/`：本机 corpus 可引用的逐题、哈希固定 Windows fixture patch；真实 patch 不由 Git 分发。
- `test_agent_evaluation_infrastructure.ps1`：模型禁用时的确定性组件验证。

安装 Codex 根只提供现有 `auth.json` 和 session 使用量账本，不是项目真源。候选配置、全局规则、自定义 agents 和 skills 每次从本仓库真源投影；不复制或链接凭据，不维护独立 Codex home、权限画像或宿主后端状态。

## 当前执行模型

候选和 Verifier 都作为受信任的本地开发进程运行，但使用两个从同一固定 base 创建的独立工作区：

```text
固定 task/base/assets
├─ candidate workspace
│  ├─ .codex/config.toml       <- global/config.toml + global/AGENTS.md
│  ├─ .codex/agents/           <- global/agents/
│  ├─ .agents/skills/          <- skills/
│  ├─ 已准备的题目依赖
│  └─ 只输出受限 Git patch
└─ verifier workspace
   ├─ 独立安装同一题目依赖
   ├─ Windows adapter 基线
   ├─ candidate patch
   ├─ hidden tests
   └─ CTRF/reward/identity receipts
```

候选通过 `codex exec` 启动，显式使用 `--ignore-user-config`、`sandbox_mode=danger-full-access`、`approval_policy=never`、`--ignore-rules` 和当前 workspace 的 trusted project override。`danger-full-access` 在这里表示不再用 Codex Windows sandbox 模拟敌对租户；工作区、patch、状态与资源边界仍由 evaluator 自己的机械合同负责。

保留的边界均有当前消费者：

- 固定 corpus、上游提交、adapter 和依赖身份；
- candidate/verifier 工作区分离；
- patch 路径、文件数、大小和 Git mode 校验；
- attempt、qualification、framework、dependency 与 receipt 身份；
- per-case lock、compare-and-swap 状态更新和死进程锁回收；
- 命令超时、后代进程树终止和有界日志；
- `recover` 只复用已有 candidate patch/receipt 并重跑 Verifier，绝不重跑模型。

已退出且没有兼容入口的旧机制包括 elevated setup/status/check、permission profile、ACL/deny/canary 探针、认证 hardlink、model catalog projection、无模型 preflight、专用 sandbox runtime 与专用清理脚本。不要在调用方重新实现这些机制。

## 候选投影与环境

候选 `.codex/config.toml` 是每次运行可重建的派生物。它嵌入 `global/AGENTS.md` 为 `developer_instructions`，复制 portable config 的适用键，强制关闭 hooks 和 web search，并保持 multi-agent/custom agents 可用。候选仓库若已经占用 `.codex` 或 `.agents/skills` 保留路径，运行在模型启动前失败，避免覆盖仓库自有内容。

模型 shell 使用 `development/common/codex_shell_environment_policy.json` 的共享过滤合同；连接环境和题目依赖环境由各自入口显式投影。认证只由 Codex CLI 从指定安装根读取，不进入仓库、prompt、patch 或结构化收据。Web search 被禁用不等于网络隔离；需要网络安全保证的任务必须由相应网络 owner 单独提供和验证，不能把本评测器当作网络沙箱。

## 本地语料与资格

本地 corpus 决定具体 Python/TypeScript 任务。每题包含精确上游提交、六个哈希固定资产、允许修改路径、工具链、Windows adapter（如需）、公开/隐藏检查和 grader 配置。框架不内置题目数量、题名、目标仓库或参考答案。

`oracle` 不运行模型。它在独立工作区至少重复两次验证：

- no-op 必须得到 reward `0`；
- reference patch 必须得到 reward `1`；
- 重复运行的 dependency 和 Verifier runtime identity 必须一致。

`run` 只消费与当前 corpus/framework/task/dependency 身份匹配的 qualification。没有当前资格属于前置条件，不是候选失败。候选越界或有效零分不自动重跑；没有可恢复产物的基础设施失败只允许按状态合同进行一次有理由重试。

## CLI

以下命令均从仓库根执行：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py validate --corpus C:\path\to\local-corpus.json --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py list --corpus C:\path\to\local-corpus.json --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py next --corpus C:\path\to\local-corpus.json --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py check --corpus C:\path\to\local-corpus.json --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py report --corpus C:\path\to\local-corpus.json --suite smoke --view machine
```

这些只读入口不启动模型。外部动作必须逐题显式执行：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py prepare --corpus C:\path\to\local-corpus.json --task <task-id>
python.exe -X utf8 development\agent-evaluation\agent_eval.py oracle --corpus C:\path\to\local-corpus.json --task <task-id>
python.exe -X utf8 development\agent-evaluation\agent_eval.py run --corpus C:\path\to\local-corpus.json --task <task-id> --profile <profile>
python.exe -X utf8 development\agent-evaluation\agent_eval.py recover --attempt-id <attempt-id>
```

省略 `--corpus` 时使用本机默认路径 `development\agent-evaluation\corpus\final-v1.json`。该文件不存在时，CLI 会提示恢复到默认路径或显式传入本地 corpus；不会下载、生成或运行题目。

`prepare` 可能克隆固定外部源码；`oracle` 和 `run` 可能安装题目依赖并执行 Verifier；只有 `run` 调用模型。`run` 的 `--installed-codex-root` 默认取 `CODEX_HOME`，未设置时取 `%USERPROFILE%\.codex`。使用非默认根时，相关 `run` 必须传入同一值；`recover` 不需要安装根，也不调用模型。

state root 保存准备好的源码、资产、资格、attempt 和不可变收据；work root 只保存可重建工作区。两者必须互不包含，也不得与项目仓库或安装 Codex 根重叠。`.codex/`、`.agents/skills/` 和 `.agentbase/` 投影被排除于候选 patch。

## 评分与证据边界

Verifier 先准备独立依赖，再应用 Windows adapter、候选或 reference patch、hidden tests，执行 corpus 命令并转换报告，最后调用固定 grader。报告分别保留任务 reward、资格、覆盖、耗时、候选及子代理 token、按官方 API 单价计算的等价成本和基础设施健康；不合成整体质量分，不把 API 等价成本说成订阅实际账单。

配置和资产存在只证明静态投影。真实候选行为、子代理使用、检查结果和 reward 只有对应运行收据能够证明。没有运行本地 corpus 中的真实题目时，不得把确定性基础设施测试外推为真实评测完成。

## 确定性验证

最终评测合同或实现发生变化且候选稳定后运行一次：

```powershell
& (Join-Path (Get-Location).Path 'development\agent-evaluation\test_agent_evaluation_infrastructure.ps1') -ProjectRoot (Get-Location).Path
```

该入口设置 `AGENTBASE_AGENT_EVALUATOR_DISABLED=1`，只用 `tests/fixtures/synthetic-corpus.json` 做 PowerShell 语法、静态 schema/corpus 和单元测试验证；新克隆无需私有题库或题目 patch 即可执行。它不克隆源码、不安装题目依赖、不运行 oracle/Verifier/model，也不部署或发行。
