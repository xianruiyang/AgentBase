# 历史源码查询基准索引

本目录只登记统一源码查询网关形成前的真实 Codex 对照。它用于约束候选方向，不把旧运行伪装成当前候选的可重复基线。

- `index.json` 保存可复算聚合、原始结果文件哈希、审计状态和证据上限。
- `verify_history.py` 在外部原始文件仍存在时校验哈希，并从逐次 usage 重新聚合；原始文件缺失时明确报告 unavailable，不把索引自身当成运行证据。
- 实际总 Token 固定为 `input_tokens + output_tokens`；cached input 是 input 子项，reasoning output 是 output 子项，均不重复相加。
- 两次历史实验没有冻结可验证的源码提交、dirty patch、完整 Codex 环境树和统一独立审计身份，因此只能作为方向性现实依据。新的收益结论必须使用版本化 corpus、只读源码快照和受监控隔离 agent 重新建立 experiment identity。

验证：

```powershell
python -X utf8 development\source-query-gateway\history\verify_history.py
```
