# 模型设计

## DES-001 query model renderer 拥有短句柄续页动作

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-002, CON-003, UDES-001

`query_gateway` 继续是 query model 分页、snapshot、cursor 和模型续读句柄的唯一 owner。只有它同时掌握精确 backend、已解析 engine/cwd、wrapper 状态、原生 argv 与新 cursor，因此由它从同一 `GatewayCommand` 生成：

```text
@more shown=<N> omitted=<N>
@next srcq more q<number>
```

`@more` 只承担不完整性；`@next` 后的短命令承担唯一模型动作。machine 继续返回结构化 `next_cursor`，cache/process 的 offset 分页继续由各自 owner 维护。

## DES-002 不可变句柄记录原子绑定完整续读状态

- 状态: confirmed
- 关联目标: AC-002

句柄记录与 snapshot 同属用户 LocalAppData 下的 query spool，通过同一进程间文件锁分配。每条记录不可变，保存完整 cursor、backend、已解析 engine/cwd、view、limit、正文预算和原生 argv；每页新建句柄，不维护可变“最后查询”或当前 offset。句柄从 `q1` 开始按十进制单调增长，最多保留 128 条，受管保留周期内不复用。

记录使用完整 payload hash 检测损坏；加载后仍由既有 snapshot fingerprint 复核 backend、engine/version、cwd 与 argv。句柄或 snapshot 过期、损坏或不匹配时返回 wrapper code 125 和重跑原查询的恢复动作，不调用原生后端。完整 cursor 仍是程序化续页身份，短记录只是同一 owner 为模型维护的有界索引，不建立可由模型编辑的第二真源。

## DES-003 machine cursor 与旧消费者保持兼容

- 状态: confirmed
- 关联目标: AC-002, CON-003

`srcq query` 的 machine `query_snapshot`、`next_cursor` 与显式 `--snapshot/--after` 不改 schema 或含义；rg/fd/scc 的投影和 cache/process 分页也不通过短句柄反向改写。模型执行 `srcq more` 后重新进入既有 query gateway，并由内部 cursor 固定首屏选择的实际 view。

## DES-004 真实 CLI 事件与并发/失败边界共同组成 oracle

- 状态: confirmed
- 关联目标: AC-001, AC-002, AC-003, UDES-001

第一条纵向路径必须证明 scc files 首屏只显示短命令、PowerShell 7 直接执行后取得第二页、特殊 argv 完整恢复且 fixture 原生调用次数保持 1。成立后再验证 rg 共享 renderer、并发首屏分配互不重复、句柄损坏/缺失不启动后端、machine cursor 和完整 workspace 非回退；相同实现与环境失败不得盲目重跑。
