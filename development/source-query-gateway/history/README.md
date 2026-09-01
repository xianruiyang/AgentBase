# 历史源码查询基准索引

本目录登记真实 Codex 对照实验及其证据上限。它用于约束候选方向，不把旧运行或不同 experiment identity 的结果伪装成当前候选的可重复基线。

- `index.json` 保存可复算聚合、原始结果文件哈希、审计状态和证据上限。
- `verify_history.py` 对仍存在的旧 summary 和当前 capsule summary 校验哈希并从逐次 usage 重新聚合，对仓库内独立审计与 capsule 校验产物校验登记哈希；外部原始文件缺失时明确报告 unavailable，不把索引自身当成运行证据。
- 实际总 Token 固定为 `input_tokens + output_tokens`；cached input 是 input 子项，reasoning output 是 output 子项，均不重复相加。
- 每条记录的 `status` 和 `identity_limits` 决定可用范围；新的收益结论必须使用版本化 corpus、只读源码快照和受监控隔离 agent 建立 experiment identity，同身份 A/B、答案合同审计和价格折算缺一不可。

验证：

```powershell
python -X utf8 development\source-query-gateway\history\verify_history.py
```
