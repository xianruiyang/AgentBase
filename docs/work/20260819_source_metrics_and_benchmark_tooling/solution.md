# 方案

## SOL-001 增加 srcq scc backend

- 状态: verified
- 解决: GAP-001
- 关联: DES-001, AC-003, AC-004

扩展直接入口、控制面、engine doctor、参数分类、JSON 规范化、指标视图、模型预算、machine schema、snapshot/cursor 和特殊模式；以真实 scc 与固定 fixture 覆盖正常、边界、错误和未来版本身份，并保持 rg/fd/AST 非回退。

## SOL-002 扩展 Windows 主机 bootstrap

- 状态: verified
- 解决: GAP-002
- 关联: DES-002, AC-002

增加精确 winget 包、版本状态、Check/Install 恢复和部署静态校验，更新 README、安装说明与 bootstrap 回归；release 和沙箱安装消费新依赖，但发布 payload 不包含工具二进制。

## SOL-003 接入模型路由与高级合同

- 状态: verified
- 解决: GAP-002
- 关联: DES-003, DES-004, AC-001, AC-003

在全局 AGENTS 写入最短普通路由，扩展 source-query description、主文和按需 scc 引用，同步 routing validator 与正向/非触发/禁选案例。按用户约束不运行独立 Codex，静态证据不得冒充行为验证。

## SOL-004 完成受影响消费者和本地验证闭环

- 状态: verified
- 解决: GAP-001, GAP-002
- 关联: AC-004, CON-001, CON-003

更新 srcq、部署、发布、文档、skill 和路由消费者，运行确定性、真实工具、tokenizer、release/installer 沙箱和部署 Validate；有效失败修正后重验。确定性与真实本地范围已经验证；正式 Validate 正确拒绝过期的独立路由证据，独立 Codex 留作额度可用后的采纳验证，本轮不 Publish。
