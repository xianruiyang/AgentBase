# 现状与差距

## OBS-001 两个工具已真实安装但项目未声明

- 状态: confirmed
- 证据: 2026-08-19 winget 安装与真实运行；仓库正式来源全文查询
- 关联: GAP-001, GAP-002

当前主机已安装 `scc 3.7.0` 与 `hyperfine 1.20.0`，但本轮开始时 README、全局规则、skill、bootstrap、部署 validator 和 srcq 均没有两者的正式身份或路由。当前 Codex 进程尚未继承安装后的 PATH，证明宿主重启提示仍是必要安装合同。

## OBS-002 scc 逐文件输出需要模型治理

- 状态: confirmed
- 证据: AgentBase 真实试运行
- 关联: GAP-001

默认汇总输出约 3 KiB，`--by-file --format json` 对 1107 个文件产生约 456 KiB；原生人类输出还包含不适合作为源码事实的 COCOMO 估算。汇总可直接压缩，逐文件记录需要完整事实后的有界投影、分页和精确恢复。

## OBS-003 srcq 已有可复用网关合同

- 状态: confirmed
- 证据: `tools/srcq/docs/query-gateway.md`、`model-output.md` 与 `query_gateway.rs`
- 关联: GAP-001

srcq 已拥有后端发现、argv 保真、model/machine/native、资源上限、分页快照、artifact 和诊断合同；rg/fd 专用解析集中于 query gateway，实现新 backend 时必须保留指标语义而不能套用匹配行或路径树语义。

## GAP-001 缺少受治理的源码指标 backend

- 状态: confirmed
- 关联: OBS-001, OBS-002, OBS-003, DES-001, AC-003

模型当前只能直接调用 scc 并承担大型、含机器信封或带推测性字段的原生输出，也没有统一续页、machine schema 和恢复入口。

## GAP-002 主机安装与模型选择均不可发现

- 状态: confirmed
- 关联: OBS-001, DES-002, DES-003, DES-004, AC-001, AC-002

新 Windows 主机不能由正式 bootstrap 获得这两个工具，模型的常驻路由和按需 skill 也无法知道何时使用它们。

## OBS-004 files 扁平行重复路径和字段名

- 状态: confirmed
- 证据: 0.4.0 候选在 AgentBase 当前源码快照上的完整 `files` model 投影与真实 `o200k_base` 试验
- 关联: GAP-003

现有 `files` model 为每个文件重复完整目录前缀和七个字段名。相同 1165 文件快照的格式试验中，现有扁平标注为 43835 个 `o200k_base` Token，目录树加单份列定义为 26082 个，减少 40.4996%；这只证明候选格式的静态 Token 差距，尚不证明正式实现、分页或模型行为。

## GAP-003 files 缺少按实际成本选择的目录树投影

- 状态: confirmed
- 关联: OBS-004, DES-005, AC-005, AC-006

共享网关已经具备可逆保序路径树，但 scc backend 尚未消费它；逐文件 model 因而保留可消除的目录和字段标签重复，同时不能把试验格式直接当作已实现合同。
