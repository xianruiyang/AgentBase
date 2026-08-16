# P10 受影响候选 v2 审计

## 身份与边界

- experiment identity: `5047af5e2afa0aa954befb683e33b518c190851d02f0f8960b5f8151edfecb61`
- capsule SHA-256: `535bf8a84b0dd347113649d1c64aeb553950df9a4b7ac0e6ba30c0df04d07a6d`
- 模型与运行：`gpt-5.6-sol`、medium、`service_tier=default`、danger-full-access、approval never
- 样本：Provider、containing、HJSON 三类各两次，只运行 candidate；P9 与冻结五-skill 历史未重跑
- 完整性：16 个原始文件和 2 个环境文件通过确定性校验；detached 审计只读 capsule，结果见 [audit-result-p10-affected-v2.json](audit-result-p10-affected-v2.json)

## 结果

| 指标 | P9 同六次只读记录 | P10 v2 | 变化 |
| --- | ---: | ---: | ---: |
| 总 Token | 771,535 | 618,630 | -152,905 / -19.82% |
| 工具命令 | 28 | 23 | -5 / -17.86% |
| 失败命令 | 0 | 0 | 0 |
| 耗时 | 220.428 s | 248.378 s | +27.950 s / +12.68% |
| 短上下文价格等价 | 212,768.4 | 213,198.6 | +0.20% |
| 长上下文价格等价 | 407,731.8 | 408,244.2 | +0.13% |
| 必需质量 / strict 质量 | 6/6 / 6/6 | 5/6 / 2/6 | 退化 |

v2 不可采纳。它达到阶段 Token 目标，但未达到质量优先和不高于 20 次命令的条件，且价格等价和耗时未形成净收益。

## 直接机制

Provider 已稳定收敛到两次查询。containing 仍在直接实现足够后追溯 README、测试或 fingerprint 上游机制，且最终回答没有把源码定位逐项绑定到三项结论。HJSON 的定义与调用内容正确，但完整性有一次未写正式源码范围，两次都未写当前已绑定快照。下一版只继续收紧请求职责层停止、结论定位和范围/快照双限定，不新增 srcq 能力。
