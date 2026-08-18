# Agent 与 Skill 指令面收敛：完成审计

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| Custom agent 角色语义由唯一真源维护 | `global/agents/*.toml` 持有中文角色差异与升级边界；`portable_agents.ps1` 只验证结构、身份、中文、差异和敏感边界，不复制正文 | 满足 |
| taskctl 引用按当前动作渐进加载 | 共享 `tooling.md` 与 authoring/query/execution/completion 四个动作族分离；跨命令族才组合 | 满足 |
| References evaluator 覆盖 Task Table Manager | 26 个 References 案例通过，authoring、执行、最终复核和跨 query/execution feedback 均绑定当前候选 | 满足 |
| taskctl 最小发现面完整 | 全部子命令具有中文用途摘要；`next`、`completion-context`、`complete` 的建议、完成与 CAS/来源边界进入测试 | 满足 |
| Skill 触发与非触发边界稳定 | 93/93 Routing、93/93 Policy 和 26/26 References 通过；反复漏选或误选已回到 description、正文或案例契约修正 | 满足 |
| 默认子代理组合不被无证据改写 | `global/config.toml` 的 Luna/max 保持不变；真实宿主质量与成本继续作为未来重开条件 | 满足 |

## 约束与影响闭合

- custom agent 自然语言不再由部署脚本复制；validator 的模型身份允许同角色后缀下的版本演进，不形成第二版本 owner。
- Task Table Manager 的共享 CLI 不变量仍只在 `tooling.md`，命令族细则各有单一 owner；`SKILL.md` 明确当前请求跨族时才组合。
- Delivery Workflow 的公共 artifact contract 现在覆盖建立、修改与最终复核，最终复核的公共、目标、执行和 iteration 引用与 oracle 一致。
- `change-governance`、`codex-qq-hook`、`task-table-manager` 和 `reasoning-governor` 的 description 正/负边界已由现有严格案例覆盖；`validate_contract.ps1` 同时固定关键边界片段。
- 三阶段 detached evidence 由不同只读 ephemeral 运行生成，正式 merge 校验哈希与未访问声明；旧 candidate evidence 未被复用。
- 正式部署 `Validate` 已通过；插件 payload、PowerShell 语法、custom agent 合同与 taskctl 92 项回归均已通过。
- 2026-08-18 已在用户针对当次操作明确同意后，以 `DirectCompatibility + InstallPortableSettings` 向真实 Codex 根目录发布；正式入口报告 18 个受管理项改变并生成可回滚备份，随后同范围 `Status` 读回 `published:true`。

## 完成判定

当前范围作为未提交但已发布的仓库候选已完成：角色语义 owner、渐进引用、CLI 发现面、触发边界、独立路由证据、部署验证和真实安装状态均闭合，没有适用验证失败或开放实施项。真实 custom agent 质量与成本比较属于明确保留的未来证据边界，不影响本次候选完成；取得足以改变默认 Luna/max 的直接证据时再重开。本次发布授权已经消耗，任何再次 `Publish` 仍需用户针对当次操作重新明确同意。
