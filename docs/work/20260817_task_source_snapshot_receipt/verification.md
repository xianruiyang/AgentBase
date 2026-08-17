# Task 来源快照收据验证

## 验证范围

本记录只验证仓库候选中的来源快照 owner、模型/机器交互面、结果写入、历史兼容和当前消费者；不表示实际 Codex 已安装本候选。

## 直接行为

| 验证对象 | 直接证据 | 结果 |
| --- | --- | --- |
| 最终投影后捕获 | `test_captured_snapshot_matches_final_budgeted_model_upstream` 对多个模型预算寻找真实部分裁剪场景，并逐项比较最终 `upstream` ID 与快照资产成员 | 通过 |
| 模型最小收据 | 默认模型视图只返回 `ref/count/complete` 或捕获提示，不包含完整 SHA 映射；极低预算仍保留可恢复响应 | 通过 |
| 机器完整映射 | machine `context --capture` 返回引用与完整映射；结果读取和 completion-context 从同一资产展开映射 | 通过 |
| 内容寻址与去重 | 相同来源集合连续捕获只产生一个 `snapshots/<sha256>.json`，引用相同 | 通过 |
| 结果写入职责 | 模型语义结果不含来源映射，`complete --source-snapshot-ref` 在唯一写入口附加引用；双重来源输入触发 `TASK-SNAPSHOT-CONFLICT` | 通过 |
| 诊断分层 | 缺失资产、不可读资产、身份不匹配、覆盖不完整和逐来源陈旧保持不同 kind，且 show/status 不重复计数 | 通过 |
| 单向兼容 | 历史内联结果仍可读取；旧式内联完成输入由 `complete` 外部化；缺少 `snapshot_dir` 的旧工作区可首次捕获 | 通过 |
| 消费者 | Delivery Workflow 初始化新建 `snapshots/` 并登记固定目录，状态摘要继续消费 taskctl 的结果诊断 | 通过 |

## 回归结果

- `python -X utf8 skills/task-table-manager/tests/test_taskctl.py`：78 项通过。
- `python -X utf8 skills/delivery-workflow/tests/test_workctl.py`：35 项通过。
- `development/skill-routing/validate_contract.ps1`：76 个路由场景、34 个严格路由、5 个严格引用、11/11 个 skill 正向与非触发覆盖通过。

## 证据边界

本轮没有把结构性缩减换算成固定 Token 比例。直接证据覆盖的是：模型输出不再随来源数量复制完整指纹映射，预算裁剪后的收据身份与实际可见来源严格一致，machine 合同和诊断能力未退化。正式部署候选 `Validate` 仍须先刷新与当前 skill bundle 一致的 detached Routing、Policy、References 证据；任何 `Publish` 仍需用户针对当次操作明确同意。
