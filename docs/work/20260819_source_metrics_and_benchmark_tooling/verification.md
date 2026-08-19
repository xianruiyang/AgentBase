# 验证记录

## 1. 直接证据

| ID | 范围 | 入口与结果 |
| --- | --- | --- |
| VER-001 | srcq workspace | `cargo ci-test` 全部非 ignored workspace/all-targets/all-features 套件通过；受影响定向为 srcq-cli lib 45/45、真实 query gateway 32/32。`cargo ci-build`、`cargo lint`、`cargo fmt-check` 通过，release helper 6/6 通过。 |
| VER-002 | 真实引擎与非回退 | `scc 3.7.0` 的 summary、languages、files、hotspots、json2、空目录、513 文件分页、cursor、未来/变化协议、错误退出和输出副作用通过；backend 合同 6/6、36 个模式与 9 个原生 oracle 通过。AST 0.4.0 基线通过；此前同一源码影响面的 ast-grep 0.44.1 CLI 3/3、core 1/1、integration 4/4 真实 ignored 套件通过。 |
| VER-003 | 主机与部署 | bootstrap 回归通过，正式只读 Check 返回 `ready:true`、7 个工具全部 supported，并读回 `scc 3.7.0`、`hyperfine 1.20.0`。portable config、agent 与 managed-asset lifecycle 回归通过；0.4.0 发布包烟测证明部署脚本使用的 safe-YAML doctor 解析、版本、summary、files 和 manifest scc 身份均成立。 |
| VER-004 | 路由与插件 | 静态路由合同通过：96 cases、55 strict routing、10 strict references、11/11 skills 具备正向与非触发覆盖；插件正式构建通过，payload 未包含外部二进制或开发资产。 |
| VER-005 | 模型读取面 | AgentBase 真实快照含 16 种语言、1149 个文件；o200k 的完整 languages 投影由 1008 降至 457 Token（54.6627%），完整 files 投影由 124642 降至 43248 Token（65.3022%）。结果由真实 tokenizer 取得，只证明完整静态投影，不证明端到端模型行为。 |
| VER-006 | hyperfine | `hyperfine 1.20.0` 在固定 release 二进制、cwd、shell、1 次预热和 5 次记录下运行；`srcq --version` 均值 24.934 ms、标准差 8.804 ms、范围 16.987–38.400 ms。该结果只验证工具合同和本次命令分布，不是正确性或采纳裁决。 |
| VER-007 | release 与安装 | 源码快照 `sha256:c7795a6bc25ed6a2ccc477de60a76fad5d9723f9395784f521e5aceabebde300`；归档 `srcq-0.4.0-x86_64-pc-windows-msvc.zip` 为 2725761 bytes，SHA-256 `65734560168a3471c6f907e156ab61ef68fcb88db7a1add93d0014e28648d942`。同输入两次 clean build 哈希一致；manifest 声明 `scc.exe`/3.7.0。0.3.1→0.4.0 隔离安装、幂等、完整性、修复、回滚、恶意包/state、PATH、配置/cache 与卸载边界全部通过。 |

## 2. 失败归因与修正

- release 烟测最初把 safe YAML 当 JSON 读取，暴露部署 preflight 的同一解析缺陷；改为验证固定 schema/backend/ok 行并只用 JSON parser 解码根级引用标量，最终发布二进制通过。
- 差异审计发现 release manifest 遗漏 scc 消费者；新增唯一 release helper 字段与回归，重新生成源码快照、连续两次 clean build、安装生命周期和发布包烟测后闭合。
- scc 首个语言页只有一项时曾遗漏全局 totals；改为依据完整捕获的语言总数判断，并新增局部回归。
- 两次真实测试启动前分别因当前 Codex 宿主未继承 winget/npm 的新 PATH 而失败；在已读回的正式安装路径上改变测试环境后通过，没有对未变化输入盲目重跑。
- 一次烟测使用了不存在的 fixture 目录，改为已确认存在的 Rust 源目录后通过；一次 rustfmt 检查给出确定格式差异，机械格式化后通过。

## 3. 证据边界

- 按 `CON-001` 未启动、未重试任何独立 Codex、control/candidate 或 detached evaluator。现有 `development/skill-routing/evidence/current.json` 属于旧 bundle，正式 `manage_agentbase.ps1 -Action Validate` 因此以“Routing result belongs to a different candidate bundle”拒绝当前候选；静态合同不冒充模型采纳证据。
- 本机未安装 `cargo-audit`，本轮未扩大工具安装范围；workspace 自有依赖、许可证、SBOM、构建与测试门禁均已执行，但没有新的 advisory scan 结论。
- 实际用户级 srcq 安装仍为 0.3.1；0.4.0 只在隔离安装与发布沙箱验证。按 `CON-003` 未对真实 Codex 根目录执行 Publish。
- 所有可重建烟测沙箱已删除；`dist/`、`target/` 和 benchmark JSON 仍是忽略的本地构建资产，不进入项目真源。
