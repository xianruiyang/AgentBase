# 用户目标设计

## UDES-001 独立运行应像当前 Codex 一样联网

- 状态: confirmed
- 关联: REQ-001, AC-001, AC-002, AC-003

用户不应再看到因为 runner 遗漏当前 Codex `.env` 代理设置而发生的五次 WebSocket 重连。运行身份必须可审计，但不能为此暴露代理或其他敏感值。

## UDES-002 先修测试框架，再评价分页

- 状态: confirmed
- 关联: REQ-002, AC-004, AC-005

read-only 任务语义不等于把进程 sandbox 设为 `read-only`。评估需要启动真实 srcq/scc 时，先由框架证明该执行链可用；若前置失败，不把失败样本解释为分页体验。

## UDES-003 单次行为验证保持小而真实

- 状态: confirmed
- 关联: AC-005, CON-001

本次只验证正常上下文内的精确续页：一个 candidate 预检、一个 subject、一次原始查询和一次 cursor 续页。压缩后恢复、完整 A/B 收益和重复统计不在本次结论范围内。
