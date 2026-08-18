# 验证溯源、CLI 帮助与 Git 基线：目标设计

## DES-001 正式尝试由路由证据合并入口统一接收

- 状态: confirmed
- 满足: REQ-001, AC-001, AC-002

`merge_routing_evidence.ps1` 保持唯一正式合并入口，并通过一个共享登记职责接收 Routing、Policy、References 结果。尝试历史是机器审计真源，只保存有界收据；`current.json` 继续是当前成功证据真源，二者不互相复制语义。部署 Validate 只检查当前成功阶段是否接入历史以及重试上限，不从历史反推 skill 行为正确。

## DES-002 CLI 帮助由 parser 定义唯一维护

- 状态: confirmed
- 满足: REQ-002, AC-003

参数用途、默认值和复杂命令示例由 `taskctl.py` 的 argparse parser 与参数定义直接持有；测试读取同一 parser 和真实 `--help` 输出，不建立平行命令说明表。

## DES-003 Git 提交是源码版本身份

- 状态: confirmed
- 满足: REQ-003, AC-004

项目源码和交付证据由一个职责清晰的 Git 提交固化，并通过现有上游非强制同步。Codex 发布备份与 manifest 继续只证明安装事务，不替代 Git 源码身份；本轮源码变化不隐式触发第二次 Publish。
