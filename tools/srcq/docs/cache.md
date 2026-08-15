# srcq 缓存与取回

## 模式

| 模式 | 行为 |
| --- | --- |
| `auto` | 默认；结果完整且未截断时不保留 cache，需要省略/截断时提交完整原生输出 |
| `on` | 成功处理后始终提交完整原生输出 |
| `off` | 不创建 cache；省略内容之后不能由 cache 取回 |

cache 在 Token-Safe 投影前保存原生 JSON/JSONL 字节和索引。它不是第二次 ast-grep 扫描，也不受 40/400/24 KiB 模型上下文预算影响。提交 cache 时会对已发现的引擎执行有界版本探测并记录实际 `ast-grep ...` 版本；仅在探测失败时使用 `unknown`。需要后续位置投影的源码必须在 `exec` 时显式重复 `--fingerprint-file <PATH>`；srcq 在启动引擎前取整文件哈希、提交前复核，最多 256 个文件、每个 64 MiB。

默认位置为 `%LOCALAPPDATA%\srcq\cache\v1`。

cache root 不允许位于当前 workspace 内。默认 TTL 为 7 天，总配额 1 GiB，单条上限 512 MiB；失败保留的 incomplete staging 最长 1 天。GC 按 TTL、LRU 和配额回收，不删除 active entry。

## 取回

从 model 的 `@more cache=<ID>` 或 machine 的 `_sgy.cache` 读取 26 字符 ID：

```powershell
srcq cache info 01HXXXXXXXXXXXXXXXXXXXXXXX
srcq cache query 01HXXXXXXXXXXXXXXXXXXXXXXX --limit 40
srcq cache query 01HXXXXXXXXXXXXXXXXXXXXXXX --file src/app.ts --rule-id no-console --offset 0 --limit 20
srcq cache get 01HXXXXXXXXXXXXXXXXXXXXXXX --result 12
srcq cache get 01HXXXXXXXXXXXXXXXXXXXXXXX --result 12 --field /text
```

- `query` 使用已建 file/rule 索引和分页，不重新运行 ast-grep；默认只输出 `#<result-id> file:range`、有界正文及必要规则字段，续页使用 `@more cache/after`。程序消费时加 `--output machine`。
- `get --result N` 返回完整原生 result；`--field` 使用 JSON Pointer，并且必须同时指定 result。
- cache 打开时校验 ID、metadata、hash、大小、TTL 和状态；损坏或过期不会静默返回内容。

也可直接交给安全处理器：

```powershell
srcq process count --cache-id 01HXXXXXXXXXXXXXXXXXXXXXXX
srcq process group --cache-id 01HXXXXXXXXXXXXXXXXXXXXXXX --field file
srcq process containing --cache-id 01HXXXXXXXXXXXXXXXXXXXXXXX --file src/app.ts --line 42 --column 8
srcq process group-locations --cache-id 01HXXXXXXXXXXXXXXXXXXXXXXX --file src/app.ts --limit 40
```

位置投影只接受原生 ast-grep cache，并沿用其 workspace 根和 0-based、end-exclusive range。它在返回正文或位置前复核登记文件的整文件哈希与 cache 记录；未登记 fingerprint、执行期间变化或查询前变化都必须重新执行原扫描，不能把旧 cache 当作当前结构。`containing` 与 `group-locations` 默认输出无 envelope 的定位证据；稳定结构消费者显式使用 `--output machine`。

## 维护与隐私

```powershell
srcq cache remove 01HXXXXXXXXXXXXXXXXXXXXXXX
srcq cache gc
srcq doctor
```

cache 可能包含完整源码片段、replacement、rule message 和文件路径，应按本地敏感代码处理。metadata 只保存用户 argv/effective argv 的 SHA-256 和必要审计字段，不保存敏感 argv 明文；这不等于源码脱敏。共享机器上不需要取回能力时使用 `--cache off`，任务完成后按策略执行 `remove` 或 `gc`。
