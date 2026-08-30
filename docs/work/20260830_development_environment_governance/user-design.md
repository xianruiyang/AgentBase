# 开发环境与门禁治理：用户设计

## UDES-001 完整整理而非保留兼容垃圾

- 状态: confirmed
- 来源: 用户要求“这些你都完整整理处理下”
- 关联: REQ-001, REQ-003, AC-002, AC-006

对已经确认的干扰、未更新旧内容和错误安全机制直接修正、替代或删除，不为了形式兼容保留同责入口、旧检查或备用状态源。

## UDES-002 错误安全观念不能证明门禁必要

- 状态: confirmed
- 来源: 用户明确称此前“安全”观念错误，并要求处理其垃圾检查和垃圾门禁
- 关联: REQ-002, REQ-003, AC-002, AC-005

安全措辞、已有实现、检查数量和未来可能误用都不能成为保留理由；只有当前契约、实际消费者和直接失败证据能够证明门禁必要。

## UDES-003 用 AGENTS 正常规则对冲宿主保守默认

- 状态: superseded
- 来源: 用户要求通过 `agent.md` 实现，并明确拒绝 Hook 后期补坑
- 关联: REQ-004, AC-008, AC-009, CON-004

该候选方案曾要求在宿主允许的 AGENTS/skill 例外内对冲保守默认；用户发现 Codex 0.151.0 的原生 `multi_agent_mode_hint_text` 后明确要求改用直接入口。未提交的 AGENTS、skill 与触发合同对冲改动撤回，不再作为当前方案。

## UDES-004 先升级到 latest 再运行唯一行为探针

- 状态: confirmed
- 来源: 用户在旧版探针启动前补充要求
- 关联: REQ-005, AC-008, AC-010, CON-005

旧 CLI 输入不进入正式结果；先把项目 Codex CLI 精确基线和用户级安装更新到 npm 当前稳定 `latest` 并读回，再建立一次新的固定行为测试输入。

## UDES-005 用原生 mode policy 直接控制主动委派并提高容量

- 状态: superseded
- 来源: 用户提出 `multi_agent_mode_hint_text` 直接方案，并要求按真实官方内容确认可配置的子代理最高数量后修改
- 关联: REQ-004, AC-008, AC-009, CON-004

该候选曾把主动委派与并发容量一并交给 portable config；多轮真实反例证明 mode policy 不能绑定实际创建后，用户撤回主动 mode 与其他客户端级补偿，只保留公开的 `[agents].max_concurrent_threads_per_session = 6` 容量设置。容量只限制可同时打开的 child 数量，不决定是否委派。

## UDES-006 root 按需主动委派，child 默认不递归委派

- 状态: confirmed
- 来源: 用户明确最终目标，并允许原生入口不可行时回到 AGENTS
- 关联: REQ-004, AC-008, AC-009, DES-012

主代理 `/root` 在实际任务出现独立、有界且有净收益的子问题时主动创建合适子代理，不要求用户逐次点名；`/root/...` 子代理默认自己完成收到的任务，不再创建下一层代理，只有用户或父代理明确要求当前任务嵌套委派时例外。主动委派只由 `global/AGENTS.md` 与 `subagent-orchestration` 承担，不再保留同责的 developer mode、tool hint、Hook 或客户端门禁。

## UDES-007 只加强 AGENTS 与 skill，容量设置单独保留

- 状态: confirmed
- 来源: 用户在行为入口无法可靠闭合后明确收缩方案，并补充要求保留子代理上限
- 关联: REQ-004, AC-008, AC-009, CON-004, DES-011, DES-012

当前实现只加强 `global/AGENTS.md` 和 `subagent-orchestration` 的 root 实际创建顺序与 child 默认非递归边界；`global/config.toml` 只保留 6 个 spawned-agent 线程的容量键，不维护主动 mode 或递归策略。不得追加客户端调度器、tool hint、自由文本解析、wait 门禁、Hook 或 Stop 补偿。
