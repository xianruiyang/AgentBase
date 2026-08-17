# 模型可见工具输出合同：现状分析

## OBS-001 根需求已有渐进上下文原则但没有输出面验收

- 状态: confirmed
- 来源: `docs/requirements.md` 的 AC-005、AC-007、AC-018、AC-030
- 关联: DES-001

直接观察：项目已要求只保留改变动作与边界的信息、按当前动作渐进加载、保持视图有界和只恢复必要上下文；修改前没有条目明确区分模型与程序消费者，也没有要求同一事实形成 model/machine 投影。证据上限是项目需求文本，不证明工具行为。

## OBS-002 srcq 已实现消费者分面参考

- 状态: confirmed
- 来源: `tools/srcq/README.md`、`docs/model-output.md`、`docs/query-gateway.md` 与当前源码
- 关联: DES-003, DES-005

直接观察：srcq 已把完整事实源投影为默认 model、显式 machine 和 native/artifact；模型字段准入以是否改变判断、定位、继续查询或恢复为条件，模型预算在选择证据页前参与计算。该实现证明项目内存在可运行参考，但只直接证明源码查询领域。

## OBS-003 taskctl 当前统一输出紧凑 JSON

- 状态: confirmed
- 来源: `skills/task-table-manager/scripts/taskctl.py` 的 `emit`、`fit_payload`、`command_context`、`completion_context_locked`、`command_status` 及 tooling 合同
- 关联: DES-003, DES-004

直接观察：所有成功结果默认使用同一紧凑 JSON renderer；context 先构造完整对象，再递减所有字符串长度，仍超预算时退化为提高预算提示。completion-context 候选包含完整 source_snapshot；status 返回正常零值、空诊断和完整基线结构。当前真实工作区测量中，status 为 1,049 UTF-8 字节，默认 context 因完整对象超预算只返回 187 字节提示，提高预算后的 context 为 36,501 字节，completion-context 单目标为 15,021 字节。

## OBS-004 workctl 当前同样统一输出紧凑 JSON

- 状态: confirmed
- 来源: `skills/delivery-workflow/scripts/workctl.py` 的 `emit`、`fit_context`、`context_workspace`、`status_workspace` 及 tooling 合同
- 关联: DES-003, DES-004

直接观察：workctl 所有命令默认返回完整 JSON；context 按平均字符数裁正文并删除末尾 section，极端情况下返回提高预算或直接读文件的提示。状态、coverage、index 等模型调用与程序调用没有输出面区分。

## OBS-005 仓库内机器消费者可显式迁移

- 状态: confirmed
- 来源: 对仓库脚本、测试和正式调用文档的有界搜索
- 关联: DES-003, DES-005

直接观察：taskctl/workctl JSON 的仓库内可执行消费者主要是各自 Python 回归测试；项目验证脚本读取源码文本而不解析命令 stdout。没有发现需要保留隐式 JSON 默认值的其他当前程序调用方。此证据不证明仓库外不存在私人调用方，因此正式文档仍需给出 `machine` 选择方式，但不据此建立无限期旧默认分支。

## OBS-006 Windows 默认 Python stdout 与 Codex 解码不一致

- 状态: confirmed
- 来源: 当前 Windows 宿主直接运行 `python -c` 与 taskctl 真实中文输出
- 关联: DES-003, AC-003

直接观察：未设置 UTF-8 选项时当前 Python `sys.stdout.encoding` 为 `gbk`，Codex 终端把输出按 UTF-8 接收，taskctl 的中文标题和正文出现乱码；既有测试统一设置 `PYTHONUTF8=1`，因此没有覆盖真实宿主默认入口。该事实同时影响 model 与 machine 的中文可读性。

## GAP-001 消费者变化没有触发输出合同重判

- 状态: confirmed
- 关联: REQ-001, REQ-002, DES-001, DES-002, OBS-001, OBS-003, OBS-004

taskctl/workctl 把面向程序的完整对象继续作为模型上下文对象，仅在序列化后压缩或截断；缺少消费者识别、模型字段准入和同源双视图合同。

## GAP-002 高成本查询没有按决策优先级规划预算

- 状态: confirmed
- 关联: AC-002, AC-007, DES-003, DES-004, OBS-003, OBS-004

当前预算机制可能同时截短全部正文或完全退化为 hint，不能保证先保留任务身份、异常、直接依据和恢复入口；completion-context 还把不参与当前完成判断的完整来源指纹复制进模型页。

## GAP-003 验证保护机器结构但不证明模型决策成本

- 状态: confirmed
- 关联: AC-003, AC-008, DES-005, OBS-002, OBS-005

现有测试覆盖 JSON 字段、分页、诊断和字符预算，却没有默认 model 输出、字段准入、语义优先级、同源性与 Token 成本回归；项目中 srcq 的成熟做法尚未成为 taskctl/workctl 的正式消费者合同。

## GAP-004 CLI 输出编码依赖调用环境

- 状态: confirmed
- 关联: AC-003, DES-003, OBS-006

taskctl/workctl 没有自行固定 stdout/stderr UTF-8，直接模型调用在当前 Windows 默认代码页下不能可靠阅读中文；只在测试环境设置变量不能使正式入口成立。
