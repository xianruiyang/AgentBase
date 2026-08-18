# workctl 模型回执投影现状与证据

## OBS-001 baseline helper 读取不存在的 aligned

- 状态: confirmed
- 来源或证据: `protected_baseline_issue` 修改前读取 `value.get("aligned")`；`verify_protected_baseline` 的正式摘要只返回 `status`
- 事实/推断/未知: 事实
- 关联目标: AC-001
- 可证明上限: baseline 发生 drift/invalid 时 model 节点无法直接表达 canonical status

## OBS-002 status 异常诊断重复

- 状态: confirmed
- 来源或证据: status handler 的顶层 diagnostics 来自 index diagnostics，baseline summary 同时持有相同 diagnostics；旧 helper 两处都保留
- 事实/推断/未知: 事实
- 关联目标: AC-001
- 可证明上限: 同一 baseline 问题会在默认模型响应中复制

## OBS-003 protect/render 走通用机器形状稀疏化

- 状态: confirmed
- 来源或证据: 修改前只有 status/context 特化；protect 和 render 均走 generic projection
- 事实/推断/未知: 事实
- 关联目标: AC-002
- 可证明上限: protect 暴露 path/history 等机器 summary；render 未复用既有稀疏 status 选择并保留正常 `status:available`

## OBS-004 impact 截断总数具有真实用途

- 状态: confirmed
- 来源或证据: 真实已闭环工作区 `REQ-001` 在 `--max-items 5` 时返回 5 项、总数 31 和 `truncated:true`
- 事实/推断/未知: 事实
- 关联目标: AC-003
- 可证明上限: 只有完整列表下的重复 count 可删除；截断场景必须保留

## GAP-001 model projection 与当前 machine 合同失配

- 状态: resolved
- 来源或证据: OBS-001—OBS-004
- 事实/推断/未知: 由正式返回结构与真实输出直接推出
- 关联目标: REQ-001
- 可证明上限: 修正 owner 是 workctl model projection，不是快照格式或阶段文档
