# 模型交互面真实审计

## 审计边界

- 环境：2026-08-17 当前 Windows 宿主，仓库源码候选，未向实际 Codex 根目录发布。
- 范围：模型直接读取的工具返回与机器日志、模型直接维护的阶段文档、程序消费但由模型决策写入的任务合同，以及相应生成视图；不改变 `source_snapshot` 表示和插件分发模式。
- 方法：先从正式 owner 确认唯一真源、消费者、读取或修改责任和生成关系，再分别验证模型读取充分性、模型修改入口、machine 稳定性、派生物边界和真实 Token。格式或字段变少不单独构成通过。
- Token：本机 `tiktoken 0.13.0` 的 `o200k_base`；数字只证明本轮真实输入的相对成本，不外推为固定比例或未来模型精确账单。

## Owner 与交互面

| Owner | 唯一真源与机器职责 | 模型读取面 | 模型修改面 | 生成物边界 |
| --- | --- | --- | --- | --- |
| 根需求与全局内核 | `docs/requirements.md` 定义长期目标，`global/AGENTS.md` 定义跨项目判断顺序 | 先确认事实 owner、消费者、当前责任和生命周期，再决定是否进入上下文 | 只规定稳定局部、可验证和唯一决定位置，不替代领域 owner | 不建立统一 hook、摘要器或第二状态源 |
| Delivery Workflow | 阶段 Markdown 是模型/人维护的语义真源；`workflow.json`、保护快照和任务合同各守结构职责 | 按稳定 ID 和实际关系渐进读取 | 修改所属阶段条目，合入新事实并删除失效重复 | `.work-cache/index.json`、`WORK_STATUS.md`、`TASK_TABLE.md` 可重建，不作为语义编辑入口 |
| Task Table Manager | 任务、状态和结果 JSON 是程序消费的结构化真源 | 默认 model 投影；完整身份与字段只由显式 machine 消费 | 语义由模型决定，通过 `draft/add/update` 和带 revision/CAS 的状态命令写入 | 生成任务表、状态摘要和 completion-context 只读，不反向同步 |
| Codex Event Logger | `conversation.json`、`file-operations.jsonl` 保持逐条完整机器日志 | 默认恢复投影只保留 prompt、assistant、goal、净文件操作、异常和恢复入口 | 日志没有模型直接编辑入口 | 同一文件重复修改合并，创建后删除的临时文件退出模型面；machine 仍保留每条记录 |

## 真实 Event Logger 读回

审计读取当前真实 turn `20260817_125027_768__01a00e0e-6f68-70a3-b36f-45075177c9d2`。machine 结果包含完整有界信封和 51 条原始文件操作；model 结果保留本轮用户请求、最近助手结论、公共项目基准和 20 个最终受影响文件。正常路径中的 session 目录、文件大小、限制、时间戳、hook 来源、重复修改和三个创建后删除的临时任务输入均未进入模型面。

| 同一次有界读取 | 字符数 | `o200k_base` tokens | 质量结论 |
| --- | ---: | ---: | --- |
| 显式 `--view machine` | 34,981 | 8,736 | 完整 JSON、逐条记录、状态、限制和诊断均保留，程序可解析 |
| 默认 model | 1,555 | 489 | 恢复当前需求、上一结论和全部最终文件仍充分；Token 减少 94.4% |

该比例来自当前真实 turn，不作为统一压缩目标。低预算 fixture 另外证明 `--model-token-budget 256` 时仍返回 turn 身份、预算原因和提高预算或显式 machine 的恢复入口；过大 conversation、部分 JSONL 和跳过记录只返回适用异常，不泄露被拒绝正文。

## 修改质量与派生验证

- 阶段文档通过稳定 ID 局部定位；同一目标、设计、现状或方案事实只进入所属条目，逐轮日志和可重建摘要不写回语义真源。
- 任务 JSON 虽由程序消费，但模型不手工绕过路径、CAS revision 和原子写入；真实 T001—T004 的 `start/reopen/update/complete` 操作验证了正式语义入口。
- 后继审计把同一合同落实到 `taskctl` 的 authoring、completion、写入回执、查询和 Markdown render，以及 `workctl` 的 protect/status/impact/render；显式 machine 和永久资产继续由原 canonical handler 生成，没有第二 renderer 或状态源。
- 横向复核覆盖 taskctl 全部注册命令、workctl 的专用与通用 model 路径、Event Logger model/machine 恢复视图和 srcq 已有模型输出合同。语义零、正常机器默认值、完整页、截断页和异常诊断分别裁决，不由通用稀疏函数猜测。
- Event Logger 10 项回归通过，1 项目录链接用例因当前主机不支持该能力按既有条件跳过；最新累计 Delivery Workflow 39 项、Task Table Manager 92 项回归通过。
- 最新候选的静态 76-case 合同、Routing 76、Policy 76、References 19 和正式部署 `Validate` 均通过，没有输入、格式、漏选、禁选、严格路由或严格引用失败。

## 结论与限制

本轮验证支持的根本做法是：内容 owner 先按消费者与生命周期选择唯一真源、模型读取面、模型修改入口和机器面，再比较表示成本。HJSON 风格只用于当前模型投影的低标点表达，不是通用真源格式，也不是质量证明。当前正式 owner 内未再发现有直接证据支持的同类明显缺口；该结论不外推到未来命令或未知消费者。`source_snapshot` 的事实表示、插件迁移和当前安装状态不由本审计改写；任何实际 Codex `Publish` 仍需用户针对当次操作明确同意。
