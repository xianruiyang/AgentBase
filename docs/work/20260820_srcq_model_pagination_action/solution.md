# 方案与执行结果

## SOL-001 将 query 续页投影为短句柄模型动作

- 状态: released
- 解决: GAP-001
- 满足: REQ-001, AC-001, AC-002, AC-003, CON-003, DES-001, DES-002, DES-003, DES-004, UDES-001

在现有 query model renderer 内以 `srcq more q<number>` 替代完整 PowerShell 命令，把 cursor、解析后的 engine/cwd、分页设置和原生 argv 放入同一 query spool owner 的不可变记录。registry 与 snapshot 共用文件锁并分别有界为 128 条与 32 份；每页新句柄、保留周期内单调不复用，缺失、损坏或 snapshot 过期时明确失败。machine cursor、显式控制面、cache/process 和原生执行职责不变；source-query skill 只执行页尾短命令。

实现已随 `srcq 0.4.2` 正式发布并安装。第一条 scc 真实路径、rg 续页、八进程并发、损坏/缺失拒绝和 36 项 query gateway 回归已通过；Windows SWE 预检中的真实分页消费者也已从旧 cursor 长命令迁移到哈希固定可执行文件上的短句柄续读。没有增加无参数“继续最后查询”、offset/length 公共模型入口、模型可编辑记录或原生重扫恢复；release、安装、skill 路由、DirectCompatibility Codex Publish 与部署读回证据见验证和完成审计。

## SOL-002 将临时句柄限制为六位循环空间

- 状态: verified
- 解决: GAP-002
- 满足: REQ-002, AC-004, AC-005, CON-004, DES-002, UDES-001

在既有 continuation registry 内增加 `999999` 的新分配上限。分配器继续在同一进程间独占锁下读取现存记录，从当前最大六位编号的下一位开始环形查找空闲编号；写入后以新编号为原点按环形年龄淘汰最旧记录，因此 `q999999` 后的 `q1` 保持为最新记录且不会覆盖活动句柄。旧版七位以上记录仍可加载，并在新写入时优先自然淘汰。实现没有新增持久 counter、tombstone、任务命名空间或第二状态源；命令、payload、machine cursor、snapshot 和错误合同不变。

0.4.3 全 workspace test/build/lint/fmt 与安装视图测试通过；回卷、128 条活动窗口、旧七位记录优先淘汰、并发分配和真实不重扫续页均由现有组件入口覆盖。全量性质测试同时暴露 YAML literal block 首行额外缩进会使后续行越出 scalar 的反例；修复位于 YAML emitter owner，新增定向回归并由原性质测试重新覆盖，不属于句柄特例。
