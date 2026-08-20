# 方案与执行结果

## SOL-001 将 query 续页投影为完整模型动作

- 状态: verified
- 解决: GAP-001
- 满足: REQ-001, AC-001, AC-002, AC-003, DES-001, DES-002, DES-003, UDES-001

在现有 query model renderer 内增加单一 PowerShell 命令格式器，迁移页尾合同及正式 source-query 消费者；保留 machine、snapshot、cursor、cache/process 与原生执行职责。组件测试覆盖 rg/fd/scc 共享 renderer、特殊 argv 单行往返、连续多页和不重扫；独立 Codex 事件验收决定是否达到模型友好。

实现已进入 `srcq 0.4.1`。query 页尾输出数量 `@more` 与完整 `@next`；正式 skill 直接执行后者。全 workspace 与消费者验证通过，独立 v6 Codex 在有效网络/权限边界下第一轮就直接执行提示命令并取得第二页，因此没有为了期待不同结果追加重复采样或第二套恢复入口。
