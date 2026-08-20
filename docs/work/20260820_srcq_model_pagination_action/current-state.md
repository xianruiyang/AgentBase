# 当前状态与差距

## OBS-001 query cursor 与 snapshot 已能精确续页

- 状态: confirmed
- 关联: AC-002, CON-001

`tools/srcq/crates/srcq-cli/src/query_gateway.rs` 在首个未完成 model 页面持久化完整原生捕获，以 `q1.<snapshot>.<view>.<offset>` 生成 cursor。续页会先核对 backend、engine/version、cwd 与原生 argv 的 fingerprint，再从 snapshot 投影下一页；现有组件测试已覆盖 snapshot 身份和 scc 不重扫。

## OBS-002 变更前页尾只提供游标片段

- 状态: confirmed
- 关联: AC-001, AC-003

实施前 query model 页尾为 `@more shown=<N> omitted=<N> after=<cursor>`。正确续页实际需要进入 `srcq query <backend> exec` 控制面并重放原生 argv；直接入口把 backend 后所有 token 原样交给原生工具，所以 `srcq scc --after <cursor>` 会被 scc 拒绝。

## OBS-003 有效独立运行已复现错误动作

- 状态: confirmed
- 关联: AC-003

P12 v5 在 WebSocket、代理端 DNS、ALL_PROXY fanout、full access 与真实 scc preflight 均有效且零 retry/fallback 的边界下，独立 Codex 首先成功取得第一页，随后自行执行 `srcq scc --after <cursor>` 并失败；它没有取得第二页。该命令事件把差距归于模型页尾动作信息，而非评估网络、权限或后端可用性。

## GAP-001 模型必须重建未显示的控制面语法

- 状态: resolved
- 关联: REQ-001, AC-001, AC-003, OBS-002, OBS-003

旧 owner 已掌握 backend、wrapper 值、原生 argv 和 cursor，却只输出游标片段，把控制面选择和参数重建责任转嫁给模型。0.4.1 已由同一 owner 输出完整 `@next`；特殊 argv、单次扫描和独立 v6 第二页事件共同证明错误机制不再经过该路径。offset + length 没有进入实现。
