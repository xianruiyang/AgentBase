# 模型设计

## DES-001 runner 持有临时网络投影

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-002, AC-003

`experiment.py` 从配置显式指定的 Codex `.env` 读取固定网络 allowlist。原值只存在于 prepare/run 进程内存和传给 Codex 的 child environment；manifest 保存来源路径、键集合、显式转换选项和规范化有效投影哈希。`proxy_dns=remote` 只把 SOCKS5 scheme 改为 SOCKS5H，`all_proxy_fanout=http-and-https` 只在专用键缺失时从有效 ALL_PROXY 派生它们。run 重新读取并校验同一有效投影，变化时在启动 subject 前失败。

runner 先从父环境移除 allowlist 的所有大小写变体，再注入冻结投影，避免父 shell 成为未记录的第二网络状态源。认证仍由既有隔离 home 的安全链接承担；API key 等非 allowlist `.env` 项不进入投影。

## DES-006 服务 launcher 与模型 shell 分层

- 状态: confirmed
- 关联目标: REQ-001, REQ-002, AC-006

`development/common/codex_runtime.py` 唯一维护 launcher 的网络投影和 ambient 环境净化，`development/common/codex_shell_environment_policy.json` 唯一维护模型 shell 过滤表。benchmark 在解析 Codex 身份时固定策略 SHA-256，并把同一策略序列化为每次 CLI 的 `-c` 参数；runner config 不能覆盖。服务保留连接所需 proxy，模型执行真实工具时看不到这些键或宿主 Git/SSH/语言注入状态。

## DES-002 sandbox 解除进程阻断，身份读回约束副作用

- 状态: confirmed
- 关联目标: REQ-002, AC-004, UDES-002

正式 subject 固定 `danger-full-access`，使 srcq 可以启动 PATH/WinGet 中的真实后端；这不是写入授权。只读 prompt、`approval_policy=never`、工作区与 Codex home 的前后身份校验共同发现越界副作用，其他 sandbox 在 prepare 与 run 均被拒绝。

## DES-003 预检覆盖真实后端且只作用于调度环境

- 状态: confirmed
- 关联目标: AC-004, CON-001, UDES-003

srcq 环境的一次预检 Codex 依次执行版本命令和 `srcq query scc doctor`。validator 必须从成功 command event 的真实 stdout 看到版本标识与独立 `ok` 行，不能从模型最终回答推断成功。预检使用两侧已经同等信任的正式 workspace，避免单侧生成 trust 状态。candidate-only schedule 只预检 candidate；完整 A/B 仍预检两侧。

## DES-004 transport 与网络健康属于正式身份

- 状态: confirmed
- 关联目标: REQ-001, AC-003, AC-004

config 必须显式选择内置 ChatGPT `websocket` 或 runner 固定的 ChatGPT OAuth `http-only` provider；自由 extra config 不得覆盖 provider 身份。preflight 与 subject 都从 stderr 统计 WebSocket 连接失败、sampling retry 和 HTTP fallback：前者非零直接拒绝 prepare，后者非零进入 postflight failure。runner 源码 hash 与 Python 完整版本也在 run 前复核。

## DES-005 分页体验使用事件级 oracle

- 状态: confirmed
- 关联目标: AC-005, UDES-003

本次验证使用一个新鲜 candidate subject。审查命令序列、第一页 `@more`、续页命令的 cursor 与原 argv、第二页正文和 scc 原生扫描次数；任何框架、网络、权限或事件完整性失败都单独归类，不进入分页友善结论。
