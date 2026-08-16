# rg/fd 查询网关

## 命令边界

```text
srcq <rg|fd> <native argv...>
srcq query <rg|fd> <exec|defaults> [wrapper options] -- <native argv...>
srcq query <rg|fd> doctor [--engine PATH] [--cwd PATH]
```

普通入口把 backend 后全部 token 原样视为原生 argv；因此 `srcq rg --help`、`srcq fd exec` 或与 wrapper 同名的 pattern 都不会被 srcq 抢占。默认先执行并取得完整事实，再由内部 planner 选择输出；模型不需要预判结果格式或数量。

显式控制面中 `exec/defaults` 的 wrapper 选项是 `--engine PATH`、`--cwd PATH`、`--output model|machine`、`--view VIEW`、`--limit N`、`--max-text-chars N`、`--model-token-budget N`、`--receipt auto|full`、`--artifact-out PATH`、`--snapshot SHA256` 和 `--after CURSOR`。rg view 为 `auto|grouped|records|locations|files|summary|lossless|raw`；fd view 为 `auto|tree|flat|summary|lossless|raw`。`--max-items` 与 `--max-line-length` 是迁移别名。控制面 help 使用 `srcq query <rg|fd> exec --help`；原生 help 直接使用 `srcq <rg|fd> --help`。

`--` 后的值、顺序、重复项和空参数原样交给对应原生引擎；srcq 不用 shell 重建命令。为取得机器表示而增加的参数插在原生参数终止符之前，不能把负号开头的 pattern 或 path 重新解释成选项。`defaults` 只返回用户 argv、注入项、最终 argv、模式和处理类别，不查找或启动引擎。`exec` 按实际输出能力处理可启动后端，`doctor` 只读回当前身份；版本字符串只界定测试证据，不形成运行许可。

普通文件发现只需 `srcq fd <fd argv...>`，普通文本查询只需 `srcq rg <rg argv...>`；backend 后的 `exec`、`--view`、`--help`、`--files` 等同名 token 全部属于原生 argv。根级 `srcq files` / `srcq --files` 只返回 `srcq fd` 的一行修正，根级 AST 子命令或遗漏分隔符只返回 `srcq exec -- <ast-grep argv...>`；这些修正不执行查询、不猜 backend，也不建立兼容别名。

默认 model 只写 planner 选择的证据文本；正常成功和完整不写 schema、统计或完成回执。显式控制面的缺省页严格使用 80 个当前视图证据单元、每个正文 240 字符和 2048 个估算 Token 软预算，单个不可拆证据单元可以越过软预算。普通直接入口先用同一总预算评估；若完整结果不超过 512 个证据单元且完整渲染仍落在 2048 预算内，则越过初始 80 项上限一次返回。rg 的完整结果只有一个来源文件时，可把单行正文提高到 1024 字符重新评估，但只有整个结果仍落在同一 2048 总预算内才采用；多文件或更大结果保持原预算分页。调用方确有需要时才通过显式控制面覆盖，显式值不被上述直接入口策略改写。`--output machine` 使用单行紧凑 JSON，仍可由现有安全 YAML 读取器解析。`--receipt full` 和 `lossless` 隐含 machine。特殊模式的原生透传、产物或有界文本合同不改变。

## 处理类别

- 普通 rg 搜索追加原生 `--json --color=never`，完整事实保留 path、match/context、行、绝对偏移、submatch 和正文；model 在相同证据单元和顺序下比较逐行 locator、文件 heading、共享目录路径树与其位置/正文叶子，只选择实际更短者。投影先形成所选 view 的证据单元，再按上述有界完整闭环或分页策略处理：files 按去重匹配文件，locations 按匹配位置，grouped/records 按 match/context 记录，summary 对完整集合聚合且不产生续页。
- rg 文件列表和 fd 普通路径追加 NUL 输出，完整解析后选择 flat/tree 或 files；model 只有在类型一致、路径可逆且实际文本更短时使用合并单子链的树，混合类型回退为带最小类型标记的 flat。machine tree 为每个显式根建立稳定别名，并保留类型、内部目录结果、重复计数和无法归根的 flat 项。
- count、JSON、vimgrep 使用各自机器或稳定结构；`lossless` 保留完整原生 JSON 事件，其他 view 只投影声明的证据。显式 view 不适用于当前模式时局部拒绝，不静默换 view。
- help/version/list-details/format/hyperlink/replace/passthru/pre/stats/quiet 等文本模式返回有界行；`--view raw` 或 `--artifact-out` 请求完整原生 stdout，stderr 在显式原生通道中保持，否则只转发有界诊断。
- rg NUL/null-data/generate 与 fd print0 要求 `--artifact-out`，避免二进制进入模型或 YAML。
- fd exec/exec-batch 使用继承 stdin/stdout/stderr 的原生透传；包装器不创建副作用授权。

## 完整性与快照

结构化执行对 stdout 设置 256 MiB、stderr 设置 16 MiB 的硬捕获上限；超过上限会终止整个原生进程组并返回 wrapper 错误。成功捕获先保留在当前进程内；只有需要续页、machine full 或显式 full receipt 时才计算快照身份并持久化，最多保存 32 份。model 正常完整结果只写证据；分页追加 `@more shown=<N> omitted=<N> after=<CURSOR>`，正文或不可续读的结果/行省略追加 `@cut text|results|lines=<N>`。machine auto 保留 `sgy.query.result/v2`，full 保留 `sgy.query.result/v1`。rg 无匹配继续返回原生 exit 1 和空 stdout，原生错误不能伪装成完整空结果。raw、artifact 与 passthrough 保持原生或清单合同。

model 首个可续页结果返回自带 snapshot 身份的 after；machine 返回 `query_snapshot` 与 `next_cursor`。续页必须再次提供相同原生 argv、cwd、backend 和引擎；model 路径只需传入：

```powershell
srcq query rg exec --after <cursor> -- -n -F needle .
```

`auto` 的首个实际 view 会写入 cursor，后续页固定复用，避免页形状变化导致表示切换。snapshot 身份绑定 backend、引擎路径与版本、cwd、原生 argv、退出、stdout、stderr 和 fd 类型快照；目录、文件、reparse point、大小与哈希均读回校验。未知、损坏、跨查询或跨 view 的续点局部拒绝。

## 失败与安全

原生 stderr 不混入结构化 stdout。原生退出码原样返回；wrapper 输入/转换、进程/资源和原子产物错误使用独立错误路径。显式产物在启动引擎前固定目标指纹，完成后原子提交，防止并发覆盖。非 UTF-8 路径或正文不会伪装为空结果，而会要求显式原生产物路径。

普通 model 查询的结构化投影若不能解释实际输出，会在已有 UTF-8 文本足够时直接返回同一捕获的有界原生证据；只有注入格式导致文本不可读、且命令属于已确认只读模式时才以原始 argv 重放一次。machine、续页和可能启动外部程序、写入或改变状态的模式不自动降级或重放；转换失败使用 wrapper code 124，不得伪装成无匹配。
