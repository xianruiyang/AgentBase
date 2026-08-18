# 验证溯源、CLI 帮助与 Git 基线：现状

## OBS-001 路由证据只持久化最终成功状态

- 状态: confirmed
- 来源: `development/skill-routing/README.md`、`merge_routing_evidence.ps1`、`manage_agentbase.ps1`

修改前 `merge_routing_evidence.ps1` 只在三个阶段均通过后原子写入 `evidence/current.json`，部署 Validate 也只读取该文件；失败结果、相同输入是否重跑以及两次尝试间的身份变化没有正式收据。

## OBS-002 taskctl 参数缺少二级说明

- 状态: confirmed
- 来源: `taskctl.py complete --help`、`taskctl.py context --help` 与 parser 实现

修改前顶层子命令摘要为中文，但进入子命令后参数只有名称，没有用途、单位、默认行为、CAS 或来源收据关系。

## OBS-003 真实安装领先于 Git、落后于本轮源码

- 状态: confirmed
- 来源: 发布后 Status、`git status --short`

真实 Codex 已安装上一轮完整 dirty 候选，HEAD 与上游仍是 `d07caa4`。本轮新增验证溯源和 CLI 帮助后，仓库源码将再次不同于安装 payload；用户授权提交与同步，没有授权再次 Publish。

## GAP-001 正式失败链不可审计

- 状态: confirmed
- 关联: DES-001, OBS-001

现有最终证据无法证明失败后改变了输入或只进行一次明确、有界的非确定性重试。

## GAP-002 子命令帮助不能独立组成安全调用

- 状态: confirmed
- 关联: DES-002, OBS-002

CLI 的发现面在顶层摘要后中断，用户仍需查实现或外部文档理解关键参数关系。

## GAP-003 发布源码缺少不可变 Git 身份

- 状态: confirmed
- 关联: DES-003, OBS-003

安装 manifest 有内容哈希和回滚路径，但当前完整源码尚无对应提交与私有远端历史，恢复与比较成本偏高。
