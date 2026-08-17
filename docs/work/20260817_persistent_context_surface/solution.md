# 常驻模型上下文与恢复面收敛：方案设计

## SOL-001 把 handoff 收敛为当前恢复索引

- 状态: confirmed
- 解决: GAP-002
- 满足: DES-001, DES-003, AC-003

重写既有 `docs/handoff.md`，保留已发布基线、未发布候选、真实 Status、精确回滚位置、当前验证、未决候选、授权和后继入口；删除已由完成审计持有且不改变下一动作的历史展开。用恢复清单逐项验证，不新建第二 handoff 或历史摘要。

## SOL-002 逐项裁决全局规则和 skill description

- 状态: confirmed
- 解决: GAP-001
- 满足: DES-001, DES-002, AC-001, AC-002

按读取时点和 owner 审查每个候选语义：全局预加载不变量保留；只有 skill 命中后才需要的执行细节下沉到既有正文；同一 owner 内真正重复且合并后仍可独立理解的规则合并。若某项只有长度收益而没有语义冗余证据则保持不变，并把“不修改”作为审计结果而非失败。

## SOL-003 以独立路由和恢复充分性裁决候选

- 状态: confirmed
- 解决: GAP-003
- 满足: DES-003, AC-004, CON-001

更新适用静态 oracle 后构建 detached Routing、Policy 与 References capsule，由不同独立运行只读取各自 capsule 生成结果；组件回归、严格路由、完整分阶段 evidence、部署 Validate 与 handoff 恢复清单全部通过后，再比较基线与候选 tokens。质量或输入身份不成立时退出相应文本压缩，不用更短覆盖失败。

## SOL-004 更新项目索引、接手状态和发布边界

- 状态: confirmed
- 解决: GAP-002, GAP-003
- 满足: DES-004, CON-002
- 依据: OBS-004

把新交付链加入总计划，完成后将 handoff 当前状态指向候选提交和完成审计，并明确真实 Codex 只包含本轮已发布基线；Git 提交与远端同步按既有授权执行，本版本不再次 Publish。
