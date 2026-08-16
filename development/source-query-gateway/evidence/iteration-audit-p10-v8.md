# P10 受影响候选 v8 预审

## 身份与边界

- experiment identity: `14341e948ba17a98507a87f015a627e1b3512b10c904277ae8cc2dcab9ac1709`
- capsule SHA-256: `287fc3a838803cf27fb1707ca2069725d86a9976e86970e0703559cd8d87f219`
- 模型与运行：`gpt-5.6-sol`、medium、default tier、danger-full-access、approval never
- 6/6 正常退出、usage 完整、postflight 无漂移；16 个原始文件和 2 个环境文件通过确定性验真。直接预审发现实验污染和 strict 失败，未运行 detached 审计

## 结果

总 Token `556,677`，其中普通输入 `119,117`、缓存输入 `431,616`、输出 `5,944`、推理输出 `2,936`、可见输出 `3,008`；22 次工具命令，耗时 `258.587 s`，短/长价格等价 `197,942.6` / `378,053.2`。相对 v7 少 `179,526` Token 和 5 次命令，距离 v3 的总 Token 目标只高 `14,019`（2.58%）。

v8 仍不可采纳。一个 containing run 的首次广域搜索命中 `development/source-query-gateway/benchmark-corpus-seed.json`，属于 `benchmark-invalid`；该 run 为 6 次命令、`147,159` Token，另一同任务 run 只有 3 次命令、`84,017` Token。两次 HJSON 最终都只写“完整：是”，没有分别写明权威源码范围和当前查询快照；containing 一次没有完整实现范围。因此 6/6 strict 前置条件不成立。

## 直接机制

- 高级 `source-query` 误触发已经退出；唯一额外 skill 是 Provider 一次为编写多行 PowerShell 按职责加载 `powershell-usage`。
- 首次搜索范围仍可写成仓库根 `.`。containing 的广域结果把 benchmark seed 带入上下文，随后需要第二次限定 `tools/srcq` 并多读三段源码；相同身份另一 run 从 `README.md tools/srcq` 定位后只读两段文件即完成。
- HJSON 两次先全项目搜索再读取策略范围；结果事实正确，但最终压缩没有执行完整性限定。工具正常退出不能替模型在答案中写出适用范围和生命周期。
- 因而下一变化不是输出预算或新命令，而是把现有根规则拆成两个短职责：搜索先限定当前职责的权威源码根；最终定位、全集与不存在结论在答案中显式保留范围/快照。拆分提高质量条款的可见性，不增加操作配方。
