# 验证溯源、CLI 帮助与 Git 基线：验证

## AC-001 与 AC-002：失败收据和重试边界

- `test_routing_attempt_history.ps1` 通过：覆盖现有三阶段 baseline 导入、真实 oracle 失败收据、相同输入缺少理由时拒绝、一次带理由重试、第三次拒绝、完全相同通过结果幂等复用、正式 merge 接入以及跨阶段 evaluator ID 复用的失败分类。
- `validate_routing_attempt_history.ps1` 对仓库当前 evidence 返回 3 份有界通过收据、每组不变输入最多 2 次；三份均标记为 `baseline_import`，历史起点明确声明更早尝试未重建。
- `test_routing_capsule.ps1` 与 `test_routing_fingerprint.ps1` 通过，证明新收据没有改变 capsule 隔离与候选/输入身份计算。
- `validate_contract.ps1` 返回 93 cases、52 strict routing、10 strict references、11/11 正向与非触发覆盖。
- `manage_agentbase.ps1 -Action Validate` 返回 `valid:true`；`test_manage_agentbase.ps1` 通过，证明部署消费者要求当前成功 evidence 具有匹配通过收据。

这些证据覆盖正式登记入口及其消费者。baseline 只证明当前成功结果已接入新合同，不能重建或证明引入合同之前的失败尝试；该边界已写入机器历史和 owner README。

## AC-003：CLI 二级帮助

- `taskctl.py context --help` 直接显示 model Token 上限、machine 字符预算、完整条目上限、`--capture` 来源快照职责和最小示例。
- `taskctl.py complete --help` 直接显示 task/state CAS、结果语义文件、来源收据关系、诊断上限和最小示例。
- parser 结构回归逐个检查全部子命令的 description 及每个参数的非空 help。
- Task Table Manager 全量回归 92/92 一次通过，用时 111.904 秒；命令、存储和输出合同没有适用失败。
- 插件构建成功，新的 taskctl 与分层引用进入可重建 `agentbase-core` payload。

## AC-004 与 CON-001：Git 与真实安装边界

- 提交前 `git diff --cached --check` 通过；实现与此前完整候选形成提交 `5814dca`（`feat: strengthen agent and workflow contracts`）。
- `git fetch --prune` 后确认本地 `main` 与 `origin/main` 同为 `d07caa4`，没有远端分叉；随后非强制推送 `d07caa4..5814dca` 成功。
- 本轮未执行 Publish。`DirectCompatibility + InstallPortableSettings Status` 只读返回 `published:false`，仅报告安装 payload 与当前源码不同、旧 manifest 源码陈旧；已发布安装本身没有被修改。
