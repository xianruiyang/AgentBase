# Workflow CLI 运行时与模型输入输出：方案

## SOL-001 先闭合 taskctl 短句柄恢复链

- 状态: completed
- 解决: GAP-002
- 满足: AC-003, DES-002, DES-003

在现有 canonical 快照之上增加 CLI 拥有的句柄索引：model capture 返回来源句柄，complete 解析后写入原完整内容引用；model completion-context 返回复核句柄，续页先解析并验证当前完整 snapshot。先用原场景、陈旧/缺失句柄和 machine 非触发场景证明闭环，再改其余消费者。

## SOL-002 迁移到独立 workflow-cli owner

- 状态: completed
- 解决: GAP-001
- 满足: AC-001, AC-002, DES-001, DES-004
- 依赖: SOL-001

把两套源码与测试迁入 `tools/workflow-cli`，加入版本、doctor、受验证本地包和 Windows 安装器。安装器采用 staging、旧 current 回滚、状态文件与 PATH 单项幂等维护；不复制 srcq 的 Rust、ast-grep、scc、cache 或 Release 特有协议。

## SOL-003 修正 workctl 并迁移 skill 消费者

- 状态: completed
- 解决: GAP-001, GAP-002
- 满足: AC-002, AC-004, DES-001, DES-002
- 依赖: SOL-001, SOL-002

按 protect/status/context/impact/render 的真实动作移除不必要机器字段和 machine 兜底，保留直接定位与语义恢复。两个 skill 改为调用 PATH 中的命令，旧 skill scripts 退出 payload；说明、测试和项目索引只引用新的正式 owner。

## SOL-004 分层验证并安装当前主机

- 状态: completed
- 解决: GAP-001, GAP-002
- 满足: AC-001, AC-002, AC-003, AC-004, CON-001, CON-002
- 依赖: SOL-001, SOL-002, SOL-003

先运行两套 CLI 的定向组件测试与安装沙箱测试，再运行受影响 skill/部署结构合同；候选稳定后构建本地包，使用正式安装器安装到当前用户目录并从安装路径读回 Status 与真实命令。只在质量充分后比较 model 输出成本；本轮不部署 Codex payload、不发行组件。
