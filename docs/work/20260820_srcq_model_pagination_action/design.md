# 模型设计

## DES-001 query model renderer 拥有可执行续页动作

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-002, CON-001, UDES-001

`query_gateway` 继续是 query model 分页、snapshot 和 cursor 的唯一 owner。只有它同时掌握精确 backend、显式 wrapper 状态、原生 argv 与新 cursor，因此由它从同一 `GatewayCommand` 生成：

```text
@more shown=<N> omitted=<N>
@next srcq query <backend> exec [必要 wrapper 选项] --after <cursor> -- <原生 argv...>
```

`@more` 只承担不完整性；`@next` 后的单行命令承担唯一下一动作。machine 继续返回结构化 `next_cursor`，cache/process 的 offset 分页继续由各自 owner 维护。

## DES-002 命令按 PowerShell 7 argv 语义无损渲染

- 状态: confirmed
- 关联目标: AC-002

固定控制 token 和生成的 cursor 使用安全裸 token。用户或路径值只有完全属于保守安全字符集时才裸写，否则使用 PowerShell 双引号字面量，并转义双引号、反引号、美元符号；控制字符使用 PowerShell 7 的 `` `u{HEX}`` 单行转义。空 argv 显式写为 `""`。不能无损表示为 UTF-8 的 model 参数局部拒绝，不以 lossy path 伪装成可执行恢复。

命令只展开改变正确性的状态：显式 engine/cwd、非默认 view/limit/max-text/model-budget、cursor 与全部原生 argv。默认值不重复；cursor 自带 snapshot 与实际 view，续页不增加第二状态源。

## DES-003 真实模型事件是友善度 oracle

- 状态: confirmed
- 关联目标: AC-003, UDES-001

确定性测试先证明文本合同、特殊 argv 往返、snapshot 身份和原生调用次数。随后用 P12 已修复的 candidate-only evaluator，在同类 scc files 场景运行一个新鲜 subject；审查其第一页、实际第二条命令、第二页首项、网络计数、postflight 身份和 scc 扫描次数。若失败，只有新的事件证据指向可修改机制时才形成下一候选，不在相同实现和环境上盲目重跑。
