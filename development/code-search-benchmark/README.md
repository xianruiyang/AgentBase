# 代码搜索收益基准

本入口只核算已经完成的真实搜索运行，不执行搜索命令。这样可把不同工具、MCP 调用和失败回退统一记录，同时避免 benchmark 形成第二套搜索执行入口。

每个 manifest 使用 `agentbase.code-search-benchmark/v1`，`runs` 中每项记录：

- `caseId/route/language`：同一质量目标与实际路径；
- `temperature`：`cold` 或 `warm`；
- `elapsedMs`：从该路径开始到取得足够证据的总耗时，包含失败与回退；
- `evidenceComplete: true`：结果已覆盖同一验收目标；不完整窗口不得进入收益比较；
- `targetCount`：同一中间结果实际服务的目标数；
- `resultFiles`：按调用顺序保存的所有模型可见结果，包括失败结果；
- `skillFiles`：该路径首次需要加载的完整 skill/引用；同一文件在单项内只列一次；
- `command`：模型可见的实际命令或 MCP 参数文本。

文件路径相对 manifest，必须保持在该目录内，单文件上限 1 MiB。分析器使用 `o200k_base` 精确统计，输出每次运行及按 route 汇总的 Token、每目标 Token 和耗时中位数：

```powershell
python.exe -X utf8 development\code-search-benchmark\analyze.py <manifest.json>
```

至少覆盖 C++、Python、TypeScript 的短/中/长定义，单目标/同文件多目标、重载或嵌套项，以及 `rg` 的 0/1/N/N+1 和 LSP 的快/慢/空/失败状态。比较时先保证 `evidenceComplete` 和目标语义一致，再比较总 Token，最后比较耗时；不得用不完整固定窗口作为低成本胜者，也不得忽略首次 skill、失败或回退。
