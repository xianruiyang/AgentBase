# 开发环境与门禁治理：需求分析

## REQ-001 开发环境保持当前、可理解且不受旧路径干扰

- 状态: confirmed
- 来源: 用户要求完整治理当前开发环境中的干扰、未更新旧内容和错误安全观念遗留
- 关联: AC-001, AC-002, AC-006, UDES-001

AgentBase 的 Windows 本地开发环境只保留当前目标仍需要的正式入口、开发资产和验证职责；已经替代、没有消费者、与当前状态冲突或只为历史错误机制服务的内容退出正常路径。

## REQ-002 检查与门禁必须保护真实当前契约

- 状态: confirmed
- 来源: 用户明确要求处理垃圾检查和垃圾门禁
- 关联: AC-003, AC-004, AC-005, UDES-002

长期检查和门禁必须能够指出删除后会在哪个当前输入下破坏哪项正式契约。无法形成该因果关系的检查删除；内容质量、上游未决和普通诊断不得伪装成机械阻断。

## REQ-003 最终评测回归受信任的本地工程评价职责

- 状态: confirmed
- 来源: 用户明确指出此前“安全”观念错误并要求清理其遗留；既有最终评测目标仍需保留
- 关联: AC-002, AC-003, AC-004, AC-007, UDES-001, UDES-002

AgentBase Windows SWE 保留固定语料、候选工作区、独立 Verifier 工作区、受限 patch、资格结果和可恢复收据，但把候选视为受信任的本地开发参与者，而不是需要对宿主实施敌对隔离的安全主体。

## REQ-004 有净收益的子问题实际进入子代理执行

- 状态: confirmed
- 来源: 用户先要求通过 `AGENTS.md` 对冲，随后用原生运行时入口替代，并最终明确 root 主动、child 默认不递归的角色边界
- 关联: AC-008, AC-009, UDES-005, UDES-006

当用户没有禁止子代理，且一个子问题独立有界、可单独验收并具有委派净收益时，主代理实际创建语义匹配的子代理；用户不需要在每个任务中重复写“使用子代理”，推理档位也不改变该路由条件。子代理默认完成自己的有界任务，不把同一主动策略递归扩张到下一层。

## REQ-005 行为测试使用当前稳定 Codex CLI

- 状态: confirmed
- 来源: 用户补充要求“那个 cli 最好更新到最新版本来测试”
- 关联: AC-008, AC-010, UDES-004

主动委派行为测试使用 npm 正式 `latest` 指向的稳定 Codex CLI，而不是项目已知落后的旧 pin；项目 bootstrap 的精确版本合同与实际用户级安装保持一致，避免后续正式入口重新判旧版为目标。

## AC-001 正式入口和状态说明只有一个当前版本

- 状态: confirmed
- 关联: REQ-001

README、总计划、组件说明和正式 CLI 对当前 owner、版本、发布状态、开放项和验证入口保持一致；历史证据不继续充当当前入口或状态源。

## AC-002 退出敌对安全运行时及其派生资产

- 状态: confirmed
- 关联: REQ-001, REQ-003

最终评测不再要求或提供 elevated sandbox、UAC setup/status/check 生命周期、ACL/permission-profile deny、宿主与凭据 canary、认证 hardlink、逐工具权限证明、专用 sandbox 清理脚本或由这些机制派生的能力声明、测试和门禁。

## AC-003 保留可复现性与数据完整性的机械边界

- 状态: confirmed
- 关联: REQ-002, REQ-003

固定 corpus 与 asset 身份、工作区互斥、候选 patch 路径/数量/大小、不可覆盖结果、锁与 revision、运行超时和资源上限继续由各自 owner 保护。它们只证明自己的机器合同，不外推为模型质量或宿主安全。

## AC-004 正常本地入口不因安全前置条件阻断

- 状态: confirmed
- 关联: REQ-002, REQ-003

评测的 validate/list/check/report/prepare/oracle/run/recover 在各自动作所需输入齐备时直接工作，不依赖持久 sandbox runtime、管理员批准、权限 acceptance 或跨 owner security assessment。缺少外部源码、依赖、资格或模型结果按其真实生命周期表达为 pending、blocked 或显式缺失。

## AC-005 门禁与诊断分层

- 状态: confirmed
- 关联: REQ-002

路径越界、破坏性覆盖、并发冲突、资源无界、固定身份不一致和会混用两个快照的错误可以阻断当前命令；状态、owner、上游未决、覆盖度、测试充分性、文档陈旧和没有结果只形成可恢复诊断或待办，不成为通用失败。

## AC-006 旧资产按消费者和生命周期处理

- 状态: confirmed
- 关联: REQ-001

已证被替代且无当前消费者的源码、脚本、测试、文档入口和本地可重建状态删除；仍被当前 benchmark、部署、路由、MCP、srcq 或 hook 消费的资产保留并更新 owner 说明。历史审计只在具有追溯价值时保留为非当前证据。

## AC-007 首个真实闭环不再经过错误安全机制

- 状态: confirmed
- 关联: REQ-003

先让一个代表性的本地评测入口从当前 corpus 和源码走到可读结果，并用其直接验证 CLI、状态和错误分类；该闭环不得经过 sandbox setup、权限 canary 或同一实现生成的安全布尔量。成立后才扩展其余等价命令和清理范围。

## AC-008 非 ultra 独立 CLI 产生真实代理创建事件

- 状态: confirmed
- 关联: REQ-004

在不包含“子代理、委派、并行或 ultra”提示词的代表性只读取证任务中，独立 Codex CLI 以非 `ultra` 档位运行时，JSONL 必须在最终回答前包含至少一个真实代理创建事件；最终文字声称“已委派”、静态路由标签或 skill 被选中都不能替代该事件。

## AC-009 主动委派保留明确负向边界

- 状态: confirmed
- 关联: REQ-004

用户明确禁止、一次便宜定向循环即可闭合、没有独立边界、可直接可靠脚本化或交接复核成本不低于收益时，不强制创建子代理；主代理不转移目标、设计、正式验收、Git、发布和交付责任。
子代理只有在用户、父代理或适用 AGENTS/skill 明确要求嵌套委派时才创建下一层代理；一般的复杂、深入、研究或并行机会本身不构成嵌套委派要求。

## AC-010 Codex CLI 版本 owner、安装与能力一致

- 状态: confirmed
- 关联: REQ-005

执行测试前，npm `latest`、`bootstrap_windows.ps1` 的精确 package/version、部署说明、确定性测试和用户 npm 原生 `codex.exe --version` 指向同一稳定版本；该 CLI 继续提供 routing runner 所需的 `exec` 隔离、JSONL 与工作目录选项。

## CON-001 只维护 Windows 本地环境

- 状态: confirmed
- 来源: 项目根约束

不新增远程 CI、Linux/macOS runner、容器兼容路线或远端 required check。

## CON-002 本轮不执行 Codex Publish

- 状态: confirmed
- 来源: 当前对话已经明确上次 Publish 授权已消耗

可以修改、删除、验证、提交并非强制推送项目源码；未经用户针对当次操作明确同意，不向实际 Codex 根目录 Publish。

## CON-003 受信任开发不取消外部授权与秘密边界

- 状态: confirmed
- 来源: 项目授权和安全边界

评测安全层退出不授权提取或提交凭据，不允许未经授权的外部写入、发布或破坏性宿主操作，也不把秘密放入仓库、日志或结果。该边界由外部系统和用户授权直接消费，不属于本次要删除的推测性门禁。

## CON-004 不用 Hook 或 Stop 门禁补偿主动委派

- 状态: confirmed
- 来源: 用户明确否决 `PreToolUse`/`Stop` Hook 方案

本次使用 Codex 原生 multi-agent mode 配置和直接行为证据；不新增阻断模型工作的 Hook、Stop 检查、重试包装或发布前门禁，也不把单次行为测试升级为常驻执行许可。

## CON-005 不用预发布 Codex CLI 充当 latest

- 状态: confirmed
- 来源: 用户要求“最新版本”与 npm dist-tag 的直接区分

只采用 npm `latest` 稳定 dist-tag；`alpha`、平台 alpha、beta 或 native 历史 tag 不进入 AgentBase 主机基线或本次行为结论。
