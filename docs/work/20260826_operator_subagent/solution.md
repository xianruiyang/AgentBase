# 第三语义执行子代理方案

## 目标与边界

在既有 `evidence` 与 `experiment` 之间没有职责缺口的前提下，新增 `operator` 处理“未知已经消除、只剩难以脚本化的有界实际执行”。该角色减少主代理等待和机械操作成本，但不转移目标、设计、授权、正式验收、完成、Git、发布或外部写入责任。

等待时长不决定角色：

```text
事实未知，读取或观察既有状态即可回答
└─ evidence
路径、错误或约束未知，必须实际操作才能裁决
└─ experiment
目标、规则、范围、允许动作和 oracle 已确认
└─ operator
目标、owner、设计、验收或完成仍需裁决
└─ 主代理
```

## Owner 与消费者

```text
global/agents/operator.toml
├─ 唯一维护 operator 的模型、推理档位和角色指令
├─ global/AGENTS.md 只维护抽象三路分流
├─ subagent-orchestration 维护 capsule、执行闭环、停止和接纳合同
├─ portable deployment 维护文件集、生命周期、安装和回滚
└─ skill-routing 维护正向、近邻反例与条件引用证据
```

`operator` 当前配置为 `gpt-5.6-luna`、`max`。这是首次部署的能力安全选择：任务虽然规则确定，仍需识别非等价对象、第一处反例和 dirty 边界；现有证据没有证明 medium 在这些职责上等价。模型和档位只存在于代理配置，后续可据真实质量与 API 成本替换，不改语义路由。

## 执行合同

- 派发必须包含冻结输入、精确对象集、正式规则、允许/禁止动作、单项 oracle、dirty 所有权、恢复依据和成本边界。
- 先完成并验收一个代表项；仅扩展同合同、同副作用边界和同 oracle 的等价对象。
- 可以启动、等待并分析已知正式构建；只观察已经启动的构建仍交给 `evidence`，修改后反复构建以发现路径仍交给 `experiment`。
- 第一处失败、非等价、未知、输入变化、dirty 冲突或授权缺口立即停止，不自行设计、修复、绕过或重跑。
- 返回只含状态、实际对象、oracle 结果、第一处例外、产物定位和恢复状态；主代理逐项接纳。

## 验证与迁移

新增资产以 `agent:operator` 进入 managed lifecycle，和另外两个语义角色一起由 portable-agent 合同、部署 Validate、Publish/Status 与回滚消费者管理。路由 evidence 覆盖既有执行观察、难脚本化确定执行、已知长构建、可脚本化批处理非触发，以及现有 evidence/experiment 正反例。此次不运行 Windows SWE 九题；规则产物验证不能替代后续真实任务行为观察。
