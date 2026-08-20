# 模型设计

## DES-001 srcq 是 scc 模型交互面的唯一 owner

- 状态: confirmed
- 关联目标: REQ-001, AC-003, UDES-001

外部 `scc.exe` 提供完整原生指标事实；srcq 负责后端发现、只读执行、规范化记录、模型预算、分页快照、稳定 machine schema 与 native/artifact 逃生口。scc 特有的参数分类、JSON 解析和指标投影位于独立 backend 模块，公共网关只维护与 rg/fd 已证明相同的执行与输出职责。

## DES-002 bootstrap 是主机工具状态唯一 owner

- 状态: confirmed
- 关联目标: AC-002, UDES-002

`development/codex-deployment/bootstrap_windows.ps1` 唯一判断 PowerShell、fd、Python、Node、ast-grep、scc 与 hyperfine 的主机安装状态并执行安装或升级；README、项目规则和部署 validator 只声明和消费该入口，不维护第二份当前状态。

## DES-003 全局规则与 source-query 分层路由

- 状态: confirmed
- 关联目标: AC-001, AC-003

`global/AGENTS.md` 只承担 `srcq scc` 与 `hyperfine` 的普通选择边界和最小语法。`source-query` skill 只在 scc 分页、machine/native/artifact、特殊格式或恢复确实需要高级合同时加载 scc 引用；普通指标任务不为工具说明支付固定 skill 成本。

## DES-004 hyperfine 保持独立外部 benchmark 工具

- 状态: confirmed
- 关联目标: REQ-001, AC-001

hyperfine 输出规模和职责不需要 srcq 级投影。模型直接使用 PATH 中的 `hyperfine.exe` 比较已界定的命令与环境；短结果读取 human 输出，需要程序消费或保存完整试验事实时写 JSON artifact。它不成为验证通过裁判，也不创建重跑许可。

## DES-005 files 复用共享路径树并在同一证据页内自适应

- 状态: confirmed
- 关联目标: REQ-002, AC-005, AC-006, UDES-004

公共 query gateway 继续唯一维护可逆、保序、合并单子链和段转义的路径树；scc backend 只提供每个文件叶子的直接指标列。`files` 对同一证据页比较带字段名扁平行、单表头扁平表与单表头目录树，以估算 Token 成本和字符数的稳定键选择严格更小的候选。三个候选随稳定文件前缀的成本单调不减，且失效目录树不能在后续前缀重新有效，因此既有二分预算入口仍能选择预算内最大证据前缀。表示选择不得改变证据单元、排序、limit、预算、cursor 或 snapshot；`hotspots` 因排名是主要关系而固定使用扁平行。规范化 machine 仍是完整稳定记录，lossless/raw/artifact 仍从原生捕获恢复。
