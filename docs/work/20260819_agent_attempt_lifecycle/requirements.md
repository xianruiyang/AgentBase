# Agent 档位与验证尝试生命周期需求

## REQ-001 收敛自定义 Agent 角色

- 状态: confirmed
- 来源: 用户 2026-08-18/19 明确要求“luna 默认就是 max，terra 不要了，sol 默认 medium”
- 关联: AC-001, AC-002, AC-003, UDES-001

Codex 可移植设置只管理 Luna 与 Sol 两个自定义角色，并按用户指定的推理档位运行。

## AC-001 Luna 默认 max

- 状态: confirmed
- 关联: REQ-001

`global/config.toml` 的默认子代理为 Luna/max，`global/agents/luna.toml` 也显式声明 `max`。

## AC-002 Sol 默认 medium

- 状态: confirmed
- 关联: REQ-001

`global/agents/sol.toml` 显式声明 `medium`，部署校验拒绝其他档位。

## AC-003 Terra 完成退役

- 状态: confirmed
- 关联: REQ-001

候选源码与受管当前资产不再包含 Terra；部署生命周期把历史 `agents/terra.toml` 声明为退役资产，并且不影响目标主机的无关个人代理。

## REQ-002 正式评估失败可追溯

- 状态: confirmed
- 来源: 用户要求处理此前评审项 5，并确认每次失败应改进而不是原样重跑
- 关联: AC-004, AC-005

每次正式独立评估都必须在 evaluator 执行前取得 attempt ID，结束后明确登记通过、结果校验失败或执行失败；不存在可被后续运行覆盖的未登记失败。

## AC-004 未完成尝试阻断正式门禁

- 状态: confirmed
- 关联: REQ-002

任何 `started` 尝试都阻断正式 Validate/Publish；相同输入最多执行两次，第二次必须说明改进或重试理由。

## AC-005 尝试账本有界且可恢复

- 状态: confirmed
- 关联: REQ-002

当前评估周期最多保留六份收据；切换周期时保存上一周期身份、账本哈希和收据数，旧账本正文可通过 Git 历史恢复。

## CON-001 本轮不安装或发布

- 状态: superseded
- 来源: 当前请求没有针对本次 Publish 的明确授权，且项目要求每次 Publish 单独授权

初始实施轮只修改并验证仓库真源，不向真实 Codex 根目录 Publish，不安装软件。用户随后在独立请求中明确要求“发布”，该约束仅对初始实施轮成立，不限制已获单次授权的后继发布。

## CON-003 后继发布仅限本次授权

- 状态: superseded
- 来源: 用户 2026-08-19 明确要求“发布”

允许按当前迁移状态执行一次 `DirectCompatibility + InstallPortableSettings` Publish，并进行只读 Status 验收；该授权不继承到以后发布。它当时没有创建 Git 授权，随后用户通过独立请求授予了项目持续 Git 维护与远端同步权限。

## CON-004 持续维护项目 Git 历史

- 状态: confirmed
- 来源: 用户 2026-08-19 明确说明“这个已经说过你来全权控制的了，可能项目 agent.md 没写”，并要求完善后处理 Git

AgentBase 内已授权并验证的项目改动默认由模型自行形成职责清晰的提交并非强制推送到已配置私有远端，不再逐次请求同类 Git 授权；历史重写、强制推送、远端或仓库归属变更和破坏性删除不包含在持续授权内。

## CON-002 保留既有工作区改动

- 状态: confirmed
- 来源: 用户接手要求与项目规则

保留并合并本轮开始前 `docs/plan.md`、`docs/handoff.md` 的 dirty 内容，不回退无关改动。
