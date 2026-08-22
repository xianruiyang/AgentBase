# 方案与执行结果

## SOL-001 将 query 续页投影为短句柄模型动作

- 状态: verified
- 解决: GAP-001
- 满足: REQ-001, AC-001, AC-002, AC-003, CON-003, DES-001, DES-002, DES-003, DES-004, UDES-001

在现有 query model renderer 内以 `srcq more q<number>` 替代完整 PowerShell 命令，把 cursor、解析后的 engine/cwd、分页设置和原生 argv 放入同一 query spool owner 的不可变记录。registry 与 snapshot 共用文件锁并分别有界为 128 条与 32 份；每页新句柄、保留周期内单调不复用，缺失、损坏或 snapshot 过期时明确失败。machine cursor、显式控制面、cache/process 和原生执行职责不变；source-query skill 只执行页尾短命令。

实现已随 `srcq 0.4.2` 正式发布并安装。第一条 scc 真实路径、rg 续页、八进程并发、损坏/缺失拒绝和 36 项 query gateway 回归已通过；Windows SWE 预检中的真实分页消费者也已从旧 cursor 长命令迁移到哈希固定可执行文件上的短句柄续读。没有增加无参数“继续最后查询”、offset/length 公共模型入口、模型可编辑记录或原生重扫恢复；release、安装、skill 路由、DirectCompatibility Codex Publish 与部署读回证据见验证和完成审计。
