# Windows sandbox 所有权修复完成审计

| 目标 | 状态 | 直接证据与边界 |
| --- | --- | --- |
| REQ-001 / AC-001 | runtime recovered；repository verified | 用户恢复后的 `unelevated` 可以启动；项目真源已删除该键，生命周期为 `transferred`，真实 Status 显示 installed 与新 source 一致 |
| AC-002 | verified | 评测 elevated 后端仍只由显式 `sandbox-setup` 与候选 runner 拥有；正式 Validate/Publish 合同不初始化它 |
| AC-003 | verified in repository | 配置、生命周期、完整部署消费者和正式 Validate 均通过，覆盖宿主值保留与不删除 |
| CON-001 | satisfied | 本轮未调用真实 Codex Publish，也未修改用户已经恢复的安装配置 |

错误 owner 与未来源码覆盖机制已经从仓库消除，当前 Codex 也保持可启动。旧发布清单尚未记录 transferred 生命周期，所以正式 publication gap 仍为 3；只有用户另行明确授权一次 Publish 后，才能把部署收据部分提升为完成并验证 gap 0。
