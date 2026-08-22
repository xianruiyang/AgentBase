# 验证记录

## 0.4.2 当前周期候选证据

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| scc 首屏—`srcq more`—第二页纵向路径 | pass | PowerShell 7 直接执行短命令；空参数、空白、美元、引号、反引号与换行从不可变记录恢复；fixture 原生调用次数为 1 |
| query gateway focused/full | 1/1、36/36 pass | rg 预算续页、scc 短句柄、machine cursor、snapshot、输出副作用与错误边界；首次全量只暴露两条旧测试 oracle/capture，修正后受影响项与全量通过 |
| 句柄生命周期 | pass | 八个并发进程分配八个不同句柄；128 条有界淘汰后编号继续单调；snapshot prune 不误删 continuation namespace |
| 缺失/损坏句柄 | pass | code 125 明确返回过期/不可用与重跑原查询；payload hash 失败不启动后端，invocation log 保持 1 |
| `cargo ci-test` | pass | 全 workspace tests 通过；真实 ast-grep 专项按既有环境要求保持 ignored，未外推为其行为通过 |
| `cargo ci-build` | pass | 0.4.2 全 workspace build 合同 |
| `cargo lint` | pass | 严格 Clippy；首次有效失败要求锁文件显式 `truncate(false)`，修正后并发单项重验通过 |
| `cargo fmt-check` | pass | Rust 格式合同 |
| source-query quick validate | pass | UTF-8 模式下 skill frontmatter、结构与引用有效；初次失败仅为 Python 3.14 在中文 Windows 默认 GBK 读取 UTF-8 文件 |
| `validate_contract.ps1` | pass；96 cases、55 strict routing、10 strict references、12/12 skills | source-query 短句柄行为、引用和静态合同自洽 |
| 路由 evidence planner/refresh | 0 evaluate、3 reuse；`already-current` | generation `C27D84237B4B8944905C34E1C452D5F460229C81DB76FDFB9922D8437A07F066` 的现有阶段身份与 oracle 仍有效；没有模型重采样 |

第一条纵向路径在扩量前单独通过。全量首次失败中的旧长命令断言与未捕获并发 stdout 都没有覆盖产品机制；修正测试 oracle 后先重跑两项，再运行完整 36 项。除此之外没有对未变输入盲目重跑。

## 0.4.1 历史证据边界

独立 Codex v6 曾证明完整 `@next srcq query ... --after <cursor> -- <argv>` 能成功取得第二页并保持一次 scc 扫描；2026-08-22 的真实使用反例推翻了“该模型动作已经足够友善”的完成结论，但不推翻 snapshot、cursor、参数保真和不重扫证据。v6 的网络、Token、capsule 与 postflight 细节仍只属于历史 0.4.1 方案，不作为 0.4.2 短句柄行为证据。

## 待完成外部门禁

正式 0.4.2 source revision、可重复 Windows archive、安装生命周期、私有 GitHub Release 下载、真实安装 Status/doctor，以及 AgentBase Validate/Publish/Status 尚未在本记录截点执行。完成前不得把仓库候选提升为已发布状态。
