# AgentBase Evo

Evo 是 AgentBase 的 Windows 本地组合评测与迭代框架。正式入口为仓库根目录下的 `python.exe development/agent-evaluation/agent_eval.py evo <action>`。开发范围与完成证据见[子计划](../../../docs/work/20260909_agentbase_content_optimization/README.md)；本说明只维护实际接口、数据职责和恢复方法。

## 只评分

已有产物可直接计算分数，无需模型、队列或候选修改：

```powershell
python.exe development/agent-evaluation/agent_eval.py evo validate --spec development/agent-evaluation/tests/fixtures/evo/research-v1.json
python.exe development/agent-evaluation/agent_eval.py evo plan --spec development/agent-evaluation/tests/fixtures/evo/research-v1.json
python.exe development/agent-evaluation/agent_eval.py evo score --spec development/agent-evaluation/tests/fixtures/evo/research-v1.json --artifacts development/agent-evaluation/tests/fixtures/evo/artifacts-v1.json
```

`score --scoring <id>` 可重复选择评分配置。`--output <file>` 保存完整机器结果，随后 `report --results <file>` 生成可离线阅读的 Markdown。修改公式只重算已有数据，不自动补跑 subject、grader 或安装依赖。`--view model` 默认输出有界摘要；`--view machine` 返回完整结构，`--model-token-budget` 只影响模型读取摘要。

研究采用 `agentbase-evo-research/v1`，产物采用 `agentbase-evo-artifacts/v1`，完整合成例见[fixtures](../tests/fixtures/evo/research-v1.json)。研究包含：

- `components`：`agents_md/skills/hooks/mcp/tools/agents/codex_settings` 七个目录，各成员有稳定 `id` 和相对源码 `source`。
- `combinations`：按种类引用组件成员；空成员与当前宿主已安装内容分开，不隐式继承安装副本。
- `evaluations.items/groups`：项持有输入版本、协议与观察需求；组引用项，并由 `active` 或显式 `selection.groups` 激活。
- `selection`：选定组合、组和预声明重复次数。组重叠不重复执行，同一事实可用于不同组的分析。
- `fields`：字段声明类型、单位、粒度和来源；行内 `dimensions` 用于按组合、任务、模型、角色等筛选和分组。
- `scoring`：独立版本的计算配置；支持字段、四则运算、条件、比较、比例、权重和有界聚合。缺失默认传播为 unknown，零分母不补造分数。

输入总 Token 包含缓存子类，输出总 Token 包含推理输出，不能将总项与子项再次相加。不同粒度应先聚合；一条请求不能因关联多条工具事件被重复计费。旧 SWE 的 `reward` 和 `composite_score=null` 不变，Evo 分数是带来源的派生结果。

### 选择原始数据与重算

`fields[].extract` 从已采集的 `attempt/agent/request/event` 对象投影字段，`from` 必须等于字段的 `grain`。`path` 是点分对象路径，也可用字符串数组访问含点号的原始键；不执行表达式、数组下标或任意代码。例如：

```json
{"id":"agent_tokens","type":"integer","unit":"token","grain":"agent","source":"native usage","extract":{"from":"agent","path":"usage.total_tokens"}}
```

同一研究结束后，`results --study s1 --spec <analysis.json> --artifacts-only --output <facts.json>` 可从原收据重新投影字段，再用 `score` 计算。分析规格可以调整字段、评分和评测组选择；改变输入、组合或观察协议会被拒绝，需要另行评测。每个分数保存公式版本、字段目录和来源行。

事件字段按实际类别计数，例如 `events.tool_call_count`、`events.mcp_tool_call_count`、`events.wait_count`。`tools.attempts` 对应公开 `tool_call` 事件，不是工具内部全部动作的总数；命令与 MCP 完成事件另列，嵌套动作不要与外层调用不加区分地累计。未提供的类别或记录覆盖不足保持缺失，使用者应结合 trace coverage 选择计算口径。

评分配置的 `select` 按行的 `dimensions` 过滤，例如 `{"role":"evidence"}` 或 `{"model":["gpt-5.6-sol","gpt-5.6-luna"]}`；`group_by` 按所选维度分组。聚合表达式也可带 `select` 和基于值的 `where`。同一指标应使用同一粒度的数据，不能把 attempt 总量与 agent 分量再次相加。原生记录没有逐请求证据时只保留已知代理汇总，不把按价格分组的汇总伪装成请求。

超出声明式公式的计算使用 `calculate --manifest <calculator.json> --spec <research.json> --artifacts <facts.json> --output <derived.json> --allow-local-code`。manifest 的 `agentbase-evo-calculator/v1` 合同固定 `id/version`、代码相对路径与 SHA-256、`argv`、超时和输出上限；只有一个完整参数 `{calculator}` 被替换为代码路径。程序从标准输入读取冻结 JSON，返回声明的派生字段和 `input_rows` 来源。该入口会执行用户明确选中的本地代码。

## 使用本地 Windows SWE 题组

题组与评测配置分开维护。`swe-import` 只把既有 Windows SWE corpus 的题目身份、任务家族、固定输入版本、作答协议和 suite 映射生成独立的 `agentbase-evo-swe-catalog/v1` 目录。目录不包含模型、推理参数、组件选择、观察指标、激活状态、并发、预算或环境路径，也不复制题面、答案和补丁。

```powershell
python.exe development/agent-evaluation/agent_eval.py evo swe-import --corpus C:/local/corpus.json --output C:/local/swe-catalog.json
python.exe development/agent-evaluation/agent_eval.py evo validate --spec C:/local/swe-catalog.json
```

导入不排队、不准备源码或依赖、不运行 qualification、Verifier 或模型。输出必须是新文件；真实目录与原 corpus 一样只留本机。目录只保存 corpus 身份，不绑定生成机的绝对路径；单独 validate 检查目录结构，研究引用时再对照其环境映射的原 corpus。目录是 corpus 的派生产物，修改题目或组在原 corpus 完成，再重新导入；不把生成目录当成第二个题库维护入口。

独立的研究规格保留自己的七类组件、评分、`selection`、预算与运行参数，使用下列字段引用目录。`sha256` 填入目录文件的实际 SHA-256；相对 `source` 以研究规格所在目录为基准。只规划或对已有产物评分可省略整个 `runtime`，无需模型或本机环境映射；实际提交执行才要求完整运行配置。

```json
{
  "evaluations": {
    "catalog": {"source": "swe-catalog.json", "sha256": "<catalog SHA-256>"},
    "observations": ["quality", "usage", "timing", "public-trace"]
  },
  "selection": {"combinations": ["chosen-combination"], "groups": ["chosen-suite"], "replicates": 1},
  "runtime": {
    "adapter": "codex", "model": "<chosen model>", "reasoning_effort": "<chosen effort>",
    "max_agents": 1, "token_reservation": 1000000, "timeout_seconds": 3600,
    "swe": {
      "corpus": "C:/local/corpus.json",
      "state_root": "C:/local/swe-state", "work_root": "C:/local/swe-work",
      "work_reservation_mb": 2048
    }
  }
}
```

这是已有研究规格的字段片段；组合 ID、组 ID、模型与容量应按该次评测选择，示例数值不是所有题目的资源保证。省略 `selection.groups` 时目录没有默认激活组。`load_spec` 只读展开题目绑定，submit 再冻结完整执行身份；目录或 corpus 变化需显式更新绑定并新建研究，旧作业不追随变化。inline `items/groups` 与目录引用不能同时作为题组真源。

只有随后显式 `run` 才执行题目。SWE 扩展仍使用 Codex 组合投影、用量与公开轨迹 owner，复用原 SWE 固定来源、qualification、补丁限制与独立 Verifier；`quality.reward` 来自原固定 grader。已有源码和资格从 SWE state 复用；缺少当前资格会报前置条件，不自动执行 `prepare/oracle`。SWE state/work 与 Evo project/state/work、安装根互相分离。`work_reservation_mb` 计入每个作业的磁盘预留；工作目录仍按原 SWE owner 创建 candidate/Verifier，依赖准备和 clone 不承诺跨题复用。

SWE 的题面、允许补丁路径、公开检查和 grader 由原题目合同提供；不能用通用 `runtime.files/verifier/answer_contains` 替换，额外行为配置通过所选组件维护。模型完成后的恢复只处理已有 patch 与 Verifier 阶段，不重新调用模型。题目执行的中间状态与收据归当前 Evo attempt，历史 SWE 结果和资格不被覆盖；公开事实继续由 Evo `results/trace` 读取，分数可离线重算。实际运行兼容性须由后续明确授权的题目运行证明，静态导入和合成检查不作此保证。

## 本地队列

`init` 建立共享状态根的本机上限；`submit` 只冻结和排队；`run` 才执行作业。单研究 `budget.concurrency` 不得突破共享上限。`runtime.max_agents` 预留主代理与后代总容量，必须与选中 Codex 设置兼容，不能静默降低受测配置满足限额。

```powershell
$EvoState = Join-Path $env:LOCALAPPDATA 'AgentBase\evo\state'
$EvoWork = Join-Path $env:LOCALAPPDATA 'AgentBase\evo\work'
python.exe development/agent-evaluation/agent_eval.py evo init --state-root $EvoState --max-concurrency 1 --model-capacity 2
# 将 <research.json> 替换为需要运行的本地研究规格。
python.exe development/agent-evaluation/agent_eval.py evo submit --state-root $EvoState --work-root $EvoWork --project-root (Get-Location).Path --spec '<research.json>'
python.exe development/agent-evaluation/agent_eval.py evo status --state-root $EvoState --study s1
python.exe development/agent-evaluation/agent_eval.py evo run --state-root $EvoState --study s1 --installed-codex-root (Join-Path $env:USERPROFILE '.codex')
python.exe development/agent-evaluation/agent_eval.py evo results --state-root $EvoState --study s1
```

研究可选择 `command` 或 `codex` runtime。前者使用显式 `argv` 并返回结构化事实；后者要求显式 `model`、`reasoning_effort` 与 prompt，仅作用于该评测进程，不操作当前对话设置。`runtime.files` 按 `{source,target}` 投影选定输入；运行前重新核对冻结来源。`evaluate` 是同一 submit/run/results 链的便捷入口，不另建执行器。

### 七类组件投影

Codex 组合的可运行示例见[七组件合成规格](../tests/fixtures/evo/components/seven-component-research.json)。AGENTS 指令选择单个文本文件，skill 选择包含 `SKILL.md` 的目录，agent 选择 TOML 文件或含 profile 的目录，Codex 设置选择 TOML 文件。多个配置声明冲突时拒绝运行，不用覆盖次序决定结果。评测进程固定无人值守与受管可写工作区，安装根仅提供已授权的运行凭据和原生会话用量来源。

hook、MCP、工具选择带 `component.json` 的源码或已准备产物目录，schema 为 `agentbase-evo-component/v1`，`kind` 与组件种类一致：

| 种类 | descriptor 内容 | 实际消费者 |
| --- | --- | --- |
| `hooks` | `hooks` 指向同目录内原生 hooks JSON；命令可引用 `{component_root}`、`{workspace}` | 受测项目 `.codex/hooks.json`；仅所选受控 hooks 获得本次进程信任 |
| `mcp` | `servers[]` 包含唯一 `id`、运行时 `command`、组件内 `entry` 与可选 `args` | 受测项目的 stdio MCP 配置；模型进程拥有 server 生命周期 |
| `tools` | `bins[]` 声明 `name` 与组件内可执行文件/脚本 `path` | 仅将选中候选的 bin 目录前置到本次进程 PATH |

路径与依赖必须属于选中组件；不复制整个安装目录、不自动安装依赖。原生产组件的编译仍走其正式入口，Evo 接收已准备、可运行的产物或脚本。投影按源码和产物身份校验；同一槽位中未变且未被污染的内容复用，变化时仅替换受管投影，必要运行产物在重置前归档。

`runtime.max_agents` 包含 root。为 1 时关闭本次进程的多代理功能；大于 1 时用后代容量配合队列总预留。显式设置与该限制冲突时先修正规格。配置文件存在只能证明投影，实际加载由本机真实场景的命令、MCP 结果、hook 产物和子代理事件证明。

`status/watch` 不启动模型，关闭监控不取消作业。`pause` 停止新派发；`cancel` 只取消本次拥有的工作。`recover` 以已持久化的执行证据对账，已完成 subject 不重跑；结果不明保持未结算。人工待评释放执行资源，必要证据与评分归档继续保留。预算预留控制作业级派发，不承诺对模型内部每个请求实施 Token 硬限。

`resources --state-root <state>` 按需查询受管 state/work 实际占用、预留、磁盘预算、卷空闲空间及 job/model 容量，`--study s1` 可限定复用统计。status/watch 只展示数据库可计算的轻量容量摘要，不每轮扫描磁盘。原生 Codex 会话账本由宿主维护，属于外部证据来源，不混入受管目录占用。

## 人工与模型评分

人工评审字段声明为 `assessment` 粒度。`review-export --spec <research.json> --artifacts <facts.json> --state-root <state> --scoring <id> --field <field-id> --output <review.json>` 导出可编辑评审包；可用 `--blind` 隐去组合绑定，`--grain/--row` 缩小待评对象。盲比只隐去框架身份，内容本身仍可能透露来源。

填写评审包中的评分后，用 `review-import --state-root <state> --submission <review.json>` 显式导入。空白保留为未评，更正通过 `supersedes` 指向当前记录，重复导入不重复累计。`review-status --package-id <review-alias>` 查看缺项，`review-merge --package-id <review-alias> --artifacts <facts.json> --output <reviewed.json>` 生成可直接评分的派生结果。

运行项可声明 `runtime.rubric={"scoring":"<id>","fields":["<assessment-field>"],"blind":true}`。完成 subject 后进入 `awaiting_human`，`review-prepare --study s1` 提供待评文件；导入后 `review-sync --study s1` 对账。恢复只推进尚缺评分阶段。

模型 grader 由独立的 `grading[]` 配置定义 `id/version/rubric/select/outputs/controller`。`select` 显式选择输入行粒度与字段，`outputs` 引用 assessment 字段并可限定数值范围；controller 固定模型、推理参数、Token 预留和超时，不继承被测候选规则。`grade-start --study s1 --grading <id>` 只冻结与排队；已有产物也可用 `--spec/--artifacts/--project-root/--work-root` 准备评分。`grade-run --study <grader-study>` 才调用 grader，要求严格结构化、完整的评分矩阵。解析失败或证据缺失不会变成零分，原 subject reward 与收据不变。

`grade-merge --state-root <state> --study <grader-study> --artifacts <original-facts.json> --output <graded.json>` 合并为标准 artifacts，随后使用原 `score`。原始版本不匹配时拒绝合并。研究的 `results` 只消费已完成且仍匹配输入身份的模型评分；调用它不会启动 grader。模型评分独立记录用量，研究预算同时结算 subject 和全部关联 grader；已有同输入结果直接复用，未知费用先对账。

## 有界自动迭代

`optimization` 必须显式声明固定 `controller`、可改 `mutable` 文件、`rounds`、总量及 controller `budget`、`splits` 和 `promotion`；需要模型评分时再列出 `grading` ID。多初始组合必须明确 `baseline_combination`。开发、选优、最终验收按任务 `family` 隔离，最终集只用于结束验收，不反馈给 controller。

`optimize-start --spec <research.json> --state-root <state> --project-root <project> --work-root <work>` 冻结基线而不调用模型。随后 `optimize-run --optimization <opt-alias> --installed-codex-root <codex>` 执行有界循环；`optimize` 合并这两步。`optimize-status` 只读状态，`optimize-resume` 接续已有工作，`optimize-export` 返回当前 champion 的候选位置与证据引用。

controller 只取得当前允许文件与开发反馈，返回 `agentbase-evo-proposal/v1` 的 `hypothesis` 和 `edits[{kind,id,path,content}]`。框架验证范围后在 state root 下冻结候选，源仓库不被改写。command 评测可用完整 argv 参数 `{component_source:<kind>/<id>}` 引用该轮实际组件。修改假设与候选身份、实际执行、评分版本和晋升理由均可追溯。

晋升先满足显式质量非退化要求和任务家族覆盖，再比较 `objectives` 的方向与值；失败、未评分、缺少可比成本的候选不晋升。达到轮次、重复假设、无改善或预算上限就停止。人工等待保留阶段并释放执行资源，恢复不重跑已经结算的 controller/subject/grader。研究总账包含三者及失败尝试；优化导出不会触发 Deploy、Release 或 Git 写入。

最终验收可声明 `optimization.final_acceptance.thresholds`，每项指定 `scoring`、`metric` 与 `minimum/maximum`。明确门槛通过或失败分别记为 `accepted/rejected`；未声明门槛则只记 `observed`。循环状态 `completed` 表示流程结束，不能单独证明质量验收通过。当前的[单轮模型合成示例](../tests/fixtures/evo/optimization/research-codex-controller.json)展示了这些字段；示例只证明框架执行能力，不是内容效果基准。

## 存储与可追溯边界

源码、state root、work root、真实 Codex 根必须彼此分离。真实题目、模型轨迹、人工评分和账户数据仅保留本机；提交内容只有框架与合成例。

| 内容 | 权威来源与生命周期 |
| --- | --- |
| 用户研究规格 | 用户按稳定 ID 维护；submit 冻结所选规格，后改不改变旧研究 |
| 调度状态 | `store.py` 的 SQLite 事务；CLI 和控制器只通过正式接口改变状态 |
| subject/Verifier 收据 | 原执行 owner 写入；恢复引用原始结果，评分不能反向修改它 |
| 用量与原生动作 | 既有 Codex 用量 owner 与仓库会话审计器；Evo 只建立当前研究关联和有界查询 |
| 人工裁决 | 不可变评审绑定与更正链；派生视图可重建，最新链头参与评分 |
| 分数与报告 | 从固定事实和评分版本重建，完整机器身份留结果文件，模型读取短别名与摘要 |
| 可写环境 | 有界独占槽位，必要差异先归档；不从真实安装反向同步源码 |

实际采集覆盖与运行完成分开报告。私有推理、工具内部未暴露动作和未取得的事件不能还原；缺失不能统计为零。使用 `trace --help` 选择调度或原生事件，先摘要再按作业、代理与事件类别展开。证据导出不等于外部上传授权，候选结果不会自动 Deploy 或 Release。
