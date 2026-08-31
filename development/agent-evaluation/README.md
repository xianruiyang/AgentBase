# AgentBase Windows SWE 最终评测集

本目录维护固定 DeepSWE 语料在 Windows 主机上的派生评测入口。它验证候选能否在真实仓库中完成任务，并由独立 Verifier 工作区复核 patch；它不是发布门禁、远程 CI、官方 DeepSWE leaderboard，也不证明未运行的模型行为。

## 职责与真源

- `corpus/final-v1.json` 与 `corpus/schema.json`：九题、上游提交、允许修改范围、依赖、检查和评分资产合同。
- `agent_eval.py`：CLI、逐题状态机、资格、尝试、恢复和报告。
- `agentbase_codex.py` 与 `invoke_candidate.ps1`：候选工作区投影、Codex CLI 调用、JSONL 使用量和 API 等价成本收据。
- `windows_verifier.py`：依赖准备、Windows adapter、patch 应用、检查、报告转换和固定 grader。
- `evaluation_core.py`：路径边界、身份、锁、不可变收据、Git 工作区和通用状态。
- `windows-adapters/`：逐题、哈希固定且进入 framework identity 的 Windows fixture patch。
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

## 固定语料与资格

语料固定九个 Python/TypeScript 任务。每题包含精确上游提交、六个哈希固定资产、允许修改路径、工具链、Windows adapter（如需）、公开/隐藏检查和 grader 配置。

`oracle` 不运行模型。它在独立工作区至少重复两次验证：

- no-op 必须得到 reward `0`；
- reference patch 必须得到 reward `1`；
- 重复运行的 dependency 和 Verifier runtime identity 必须一致。

`run` 只消费与当前 corpus/framework/task/dependency 身份匹配的 qualification。没有当前资格属于前置条件，不是候选失败。候选越界或有效零分不自动重跑；没有可恢复产物的基础设施失败只允许按状态合同进行一次有理由重试。

## CLI

以下命令均从仓库根执行：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py validate --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py list --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py next --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py check --suite smoke --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py report --suite smoke --view machine
```

这些只读入口不启动模型。外部动作必须逐题显式执行：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py prepare --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py oracle --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py run --task returns-validated-error-accumulation --profile sol
python.exe -X utf8 development\agent-evaluation\agent_eval.py recover --attempt-id <attempt-id>
```

`prepare` 可能克隆固定外部源码；`oracle` 和 `run` 可能安装题目依赖并执行 Verifier；只有 `run` 调用模型。`run` 的 `--installed-codex-root` 默认取 `CODEX_HOME`，未设置时取 `%USERPROFILE%\.codex`。使用非默认根时，相关 `run` 必须传入同一值；`recover` 不需要安装根，也不调用模型。

state root 保存准备好的源码、资产、资格、attempt 和不可变收据；work root 只保存可重建工作区。两者必须互不包含，也不得与项目仓库或安装 Codex 根重叠。`.codex/`、`.agents/skills/` 和 `.agentbase/` 投影被排除于候选 patch。

## 评分与证据边界

Verifier 先准备独立依赖，再应用 Windows adapter、候选或 reference patch、hidden tests，执行 corpus 命令并转换报告，最后调用固定 grader。报告分别保留任务 reward、资格、覆盖、耗时、候选及子代理 token、按官方 API 单价计算的等价成本和基础设施健康；不合成整体质量分，不把 API 等价成本说成订阅实际账单。

配置和资产存在只证明静态投影。真实候选行为、子代理使用、检查结果和 reward 只有对应运行收据能够证明。没有运行九题时不得把确定性基础设施测试外推为九题完成。

## 确定性验证

最终评测合同或实现发生变化且候选稳定后运行一次：

```powershell
& (Join-Path (Get-Location).Path 'development\agent-evaluation\test_agent_evaluation_infrastructure.ps1') -ProjectRoot (Get-Location).Path
```

该入口设置 `AGENTBASE_AGENT_EVALUATOR_DISABLED=1`，只做 PowerShell 语法、静态 corpus 和单元测试验证；不克隆源码、不安装题目依赖、不运行 oracle/Verifier/model，也不 Publish。
