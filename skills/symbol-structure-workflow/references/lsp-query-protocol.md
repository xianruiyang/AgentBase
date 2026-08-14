# LSP 查询协议

## 工具成本与准入

| 工具 | 成本 | 使用条件 |
| --- | --- | --- |
| `list_workspaces` | 很低 | 本轮确定需要 LSP；调用一次并复用 |
| `health_check` | 低 | 首次激活或故障诊断，不在每次查询前调用 |
| `get_capabilities` | 中 | 兼容性调查；结果仅作弱提示 |
| `document_symbols` | 低-中 | 已知文件，需要可复用的语义大纲或嵌套路径 |
| `symbol_info` | 中 | 需要 hover、定义、类型、实现或签名；只请求所需 kind |
| `get_diagnostics` | 低-中 | 读取已发布诊断；指定文件 |
| `workspace_symbols` | 环境敏感，中-高 | 名称已知但文件未知，低成本候选无法消歧，且当前 Provider 与索引成本可接受 |
| call/type hierarchy | 高 | 用户问题本身要求调用或继承关系 |
| `get_references` | 很高 | 必须取得同一符号的精确影响范围 |
| `rename_preview` | 很高 | 用户确实要求语义重命名 |

集合默认取 1–20 项、`contextLines: 0`。大型工作区排除 Saved、Binaries、缓存和源码镜像；不要删除或阻断 UE 编译所需的 Intermediate 生成内容。

名称已知但文件未知时，通常先用受限 rg/AST 缩小候选；项目较小、索引已就绪或当前语言 Provider 的实测成本可接受，且语义候选能减少消歧时，可以直接或升级使用 `workspace_symbols`。它是条件性低优先级入口，不是全局禁用项；当前环境一旦超时、不可用或成本明显失衡，本任务内降级且不重复探测。单个已知声明的正文不默认请求全文件 `document_symbols`，只有大纲能被后续判断复用时才承担其成本。

## 精确引用

调用 `get_references` 前必须满足：

1. 已读取源码并确认精确符号位置；名称常见时先用 rg/AST 了解候选和合理源码根。
2. 结论确实要求同一符号的精确引用，而不是同名候选、调用形状或有限影响估计。
3. C++ 优先提供固定目录前缀的 `includeGlobs`，排除生成物和副本，保持小窗口和零上下文。

C++ 首次调用不显式设置 `timeoutMs`，让 MCP 尝试 scoped identity fallback；只有返回 `references_scoped_identity_fallback` 才表示候选已逐项验证。显式 `timeoutMs: 90000` 仅用于确需全局完整结果、索引稳定且默认预算不足的情况。

## 语义重命名

1. 用源码、rg/AST 和必要的 `symbol_info` 确认目标及安全目录；不要例行先跑昂贵 references。
2. `rename_preview` 必须提供 `includeGlobs`，按需排除镜像、Saved、Pak、缓存和无关插件。
3. 只有预览完整、未截断、每个文件与 edit 都属于同一目标时，调用一次 `rename_apply`。
4. `RENAME_SCOPE_VIOLATION`、`RENAME_IDENTITY_UNVERIFIED`、`RENAME_NO_EDITS` 或 `PREVIEW_TOO_LARGE` 表示没有可安全应用的预览，不得放宽范围绕过。

## 超时与恢复

Provider 默认预算为 60 秒，显式慢查询上限为 90 秒。超时不是空结果，也不提供可依赖的部分语义结果。

| 状态 | 处理 |
| --- | --- |
| capabilities timedOut/unknown | 忽略门禁含义；确有需要时做一次精确定向调用 |
| symbols / hierarchy 超时 | 降级到 rg、AST、源码和定点 definition；不原样重试 |
| references / rename 超时 | 停止高成本链；不得并发或连续重试 |
| 超时后 `PROVIDER_UNAVAILABLE` | 等待明确恢复证据，最多再试一次 |
| `WORKSPACE_DISCONNECTED` / NOT_FOUND | 重新 `list_workspaces` 一次，仍失败则降级 |
| `DOCUMENT_CHANGED` | 重读源码并重新预览 |
| apply/command 超时或断线 | 先检查实际状态，确认未执行前不得重放 |

低成本证据足以完成安全范围内工作时继续；任务必须依赖缺失语义时明确报告限制。
