# 代码搜索收益基准

本目录是项目内唯一的源码查询基准 owner。`analyze.py` 保留局部工具路径的模型可见 Token 后处理；`experiment.py` 负责真实 Codex 对照的身份冻结、平衡调度、外部监控、事件归档和 detached audit capsule。两者不实现查询语义，也不进入 sgy 或 Codex 发布 payload。

正式语料在 `corpus/`。真实对照先由独立配置生成 experiment，预检 control/candidate 环境差异只包含 allowlist 后才运行：

```powershell
python -X utf8 development\code-search-benchmark\experiment.py prepare --config <config.json> --output <new-output-dir>
python -X utf8 development\code-search-benchmark\experiment.py run --experiment <new-output-dir>\experiment.json
python -X utf8 development\code-search-benchmark\experiment.py capsule --experiment <new-output-dir>\experiment.json
```

每个 subject 都由新的 `codex exec --json --ephemeral --sandbox read-only` 进程执行。monitor 只捕获 stdout JSONL、stderr、退出、wall time、工具项和最后一个 `turn.completed.usage`；超时会终止该次进程树并保留失败，不静默重试。运行前后都重算 corpus、工作区 Git 快照和最小 Codex home 环境树身份。凭据不得复制进实验目录或环境树，只能通过既有安全环境提供。

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
