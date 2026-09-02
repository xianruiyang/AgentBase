# Workflow CLI 运行时与模型输入输出：需求

## REQ-001 两套流程 CLI 可作为主机工具直接调用

- 状态: confirmed
- 来源: 用户要求解决 workctl/taskctl 输入输出，并加入 PATH 或按 srcq 方式安装到电脑
- 关联: AC-001, AC-002, CON-001

`workctl` 与 `taskctl` 应从 AgentBase 项目真源形成独立 Windows 安装运行时，安装后由 PATH 直接调用；skill 只描述何时与如何使用，不再把安装副本内脚本当作运行时真源。

## REQ-002 模型输入输出不携带无意义机器身份

- 状态: confirmed
- 来源: 用户确认的模型交互面与 Token 规则，以及本轮对两套 CLI 的治理要求
- 关联: AC-003, AC-004, CON-002

默认 model 视图及模型需要回传的参数只包含当前判断、定位、动作与恢复所需的语义内容。内容哈希、内容寻址引用和其他长不透明身份留在 machine 资产；跨调用确需引用时使用可读短句柄，由 CLI 在工作区内解析。

## AC-001 Windows 安装生命周期可验证

- 状态: confirmed
- 关联: REQ-001

独立安装入口至少支持 Install、Upgrade、Status 与 Uninstall，幂等维护一个用户 PATH 项；Status 直接核对版本、受管成员、运行入口与 PATH，安装失败可恢复旧版本。

## AC-002 两个命令脱离仓库可运行

- 状态: confirmed
- 关联: REQ-001

从受验证安装目录直接执行 `workctl --version`、`taskctl --version` 及各自最小真实命令，不读取仓库内 skill 脚本，也不要求 Codex 部署先发生。

## AC-003 taskctl 的恢复链保持完整

- 状态: confirmed
- 关联: REQ-002

`context --capture`、`complete` 与 `completion-context` 分页在 model 路径上只交换工作区短句柄；CLI 能解析到同一不可变来源或复核快照，陈旧、缺失或冲突时仍由原有 gate 拒绝错误写入或混页。machine 路径继续提供完整稳定身份。

## AC-004 workctl 的模型投影按动作充分

- 状态: confirmed
- 关联: REQ-002

protect/status/coverage/context/impact/render 的 model 输出不投影无助于当前动作的确认引用、机器路径、完整身份或建议切换 machine 的兜底；必要正文、定位、诊断和精确模型恢复动作仍保留，machine 合同不退化。

## CON-001 安装不等于 Codex 部署或组件发行

- 状态: confirmed
- 来源: AgentBase 部署与发行合同；本轮用户授权安装 CLI 到电脑

本轮可构建并安装 workflow CLI 运行时，但不据此部署全局规则或 skill 到 Codex，也不创建 Git tag、Release 或分发资产。

## CON-002 不用通用后处理器猜测领域语义

- 状态: confirmed
- 关联: REQ-002

不得用正则清洗器、统一字段黑名单或事后截断替代命令 owner 的字段选择；短句柄映射是机器身份的派生索引，不成为第二语义真源。
