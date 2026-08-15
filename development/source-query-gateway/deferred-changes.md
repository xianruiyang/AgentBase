# 统一源码查询网关分支延后讨论项

## DCR-SQG-001 当前收益对照是否解除旧 control 冻结

- 状态: deferred
- 目标: AC-SQG-004, SOL-SQG-007, TSQG-062
- 来源: 用户前序要求五-skill 消融结果只记录、不再重跑

旧 control 与当前 Codex、工作区、候选、runner 和 corpus identity 不同，不能和当前 candidate-only 数字拼成因果收益；当前完整运行还保留了一次 TLS 超时与 usage 缺失。继续单独运行 candidate 不会改变完成结论。

后续需要用户在两种边界中裁决：允许一次当前 identity 下的 control/candidate 对照，以继续验证 `AC-SQG-004`；或维持冻结并接受本分支只保留方向性证据、不声明达到收益边缘，也不进入主线采纳与发布。该裁决不得由 CLI、历史均值或模型静默替代。
