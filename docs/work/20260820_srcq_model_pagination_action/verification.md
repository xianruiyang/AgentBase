# 验证记录

## 0.4.3 六位环形句柄候选证据

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| continuation focused tests | pass | canonical `q1`—`q999999`、旧七位句柄可读、`q999999 → q1 → q2` 回卷、活动记录不覆盖、环形年龄窗口和旧记录优先淘汰 |
| `cargo ci-test` | pass | 全 workspace；57 项 CLI 单元测试、36 项真实 query gateway 及 cache/codec/property/stress 等合同通过；依赖真实 ast-grep/PTY 的既有专项保持 ignored |
| YAML 定向与性质回归 | pass | 首个多行内容行带额外缩进且后续含 private-use 字符时改用安全 quoted scalar；原 `token_safe_budget_is_deterministic_bounded_and_unicode_safe` 与新增定向回归均通过 |
| `cargo ci-build` / `cargo lint` / `cargo fmt-check` | pass | 0.4.3 workspace build、严格 Clippy 与 Rust 格式合同 |
| `scripts/test-install-srcq-views.ps1` | pass | Release 安装脚本 model/machine 视图合同 |
| source-query quick validation | pass | 临时句柄生命周期与 `srcq more` 渐进恢复说明结构、引用有效 |

首次完整 `cargo ci-test` 的 YAML 反例直接覆盖产品 emitter，修正实现与输入后本次完整 suite 通过；没有对未变输入原样重跑。私有 Release、可重复 archive、真实 Upgrade/doctor 和已安装回卷读回在实现提交后取得，不由候选测试提前替代。

## 0.4.3 发布、安装与部署证据

- source revision 为 `f4e35707fcb69e69ed9583bf108a96727f8d5087`；以该提交时间固定 `SOURCE_DATE_EPOCH` 的两次 clean Windows archive SHA-256 均为 `9d0b9569a4c19e6e1c20cc5e9625d882a5e9acfeabde93e6ee89533fdcc9e52c`，manifest 固定 `x86_64-pc-windows-msvc`、Rust 1.85.0 与同一 revision。
- `cargo audit 0.22.2 --no-fetch` 使用本机当前 1225 条 RustSec advisory 扫描 127 个依赖，无漏洞；Release 安装合同覆盖资产集合、认证下载边界、状态读回、缺失 checksum 拒绝和 0.4.3 版本。
- 私有 [GitHub Release srcq-v0.4.3](https://github.com/xianruiyang/AgentBase/releases/tag/srcq-v0.4.3) 指向该 revision，包含 archive、checksum、manifest、SPDX SBOM、第三方许可证和两份安装脚本；通过 Release 下载的 wrapper 真实 Upgrade 后，machine Status 为 `ready:true`、完整性 verified、PATH 条目 1，`srcq 0.4.3`、`srcq doctor` 与 `srcq query scc doctor` 均通过。
- 已安装二进制从 `srcq query rg exec --limit 1` 返回 `@next srcq more q921`，直接执行后取得下一页并返回 `q922`；六位上限回卷由同一发布源码的 focused/full tests 直接覆盖，不用伪造真实用户 spool 冒充安装读回。
- 同轮 `DirectCompatibility + InstallPortableSettings` Publish 通过 67/67 evaluator-disabled 基础设施检查，返回 `published:true`、`changed:10`；发布后 Status 为 `published:true`，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-211434-11afc187`。

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
| Windows SWE 哈希固定分页消费者 | focused pass；正式 Validate/Publish 各 67 tests pass | 预检验证 `@next srcq more q<number>`，再以清单中同一绝对路径和哈希固定的 `srcq.exe` 完成三页续读；没有退回 PATH 命令名或旧 `--after` 重建 |

第一条纵向路径在扩量前单独通过。全量首次失败中的旧长命令断言与未捕获并发 stdout 都没有覆盖产品机制；修正测试 oracle 后先重跑两项，再运行完整 36 项。除此之外没有对未变输入盲目重跑。

## 0.4.1 历史证据边界

独立 Codex v6 曾证明完整 `@next srcq query ... --after <cursor> -- <argv>` 能成功取得第二页并保持一次 scc 扫描；2026-08-22 的真实使用反例推翻了“该模型动作已经足够友善”的完成结论，但不推翻 snapshot、cursor、参数保真和不重扫证据。v6 的网络、Token、capsule 与 postflight 细节仍只属于历史 0.4.1 方案，不作为 0.4.2 短句柄行为证据。

## 0.4.2 发布、安装与部署证据

- source revision 为 `ef65946f23f0e1036b675b43e6e471f8237f9c04`，两次 clean release build 的 Windows archive SHA-256 均为 `8f246fe832fe0b5524566be1d770f55155de927160fae09699bf0877f6f60484`；manifest 固定 `x86_64-pc-windows-msvc`、Rust 1.85 与同一 revision。
- release 安装合同和 view 测试通过；`cargo-audit 0.22.2 --no-fetch` 消费本轮已经获取的当前 advisory database，127 个依赖未发现漏洞。私有 [GitHub Release srcq-v0.4.2](https://github.com/xianruiyang/AgentBase/releases/tag/srcq-v0.4.2) 已包含 archive、checksum、manifest、SPDX SBOM、第三方许可和两份安装脚本。
- 通过该私有 Release 的安装脚本从 0.4.1 Upgrade 到 0.4.2；安装后 machine Status 为 `ready=true`、完整性 verified、PATH 条目 1，`srcq doctor` 与 `srcq query scc doctor` 均通过。已安装二进制真实输出 `@next srcq more q2`，直接执行取得下一页并返回新句柄 `q3`。
- 正式部署前 Status 只报告 `installed_payload_differs_from_source` 与 `published_manifest_source_is_stale`；Validate 通过后，以 `DirectCompatibility + InstallPortableSettings` Publish，变更 3 个受管对象。发布后 source、installed 与 manifest 指纹一致，`managed_payload_formally_published=true`、gap 0；回滚点为 `C:\Users\gzxt\.codex\backups\AgentBase-20260822-153600-61708e97`。
