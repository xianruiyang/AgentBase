# 实施方案

## SOL-001 冻结并脱敏 Codex 网络投影

- 状态: implemented
- 关联: AC-001, AC-002, AC-003, DES-001

`development/code-search-benchmark/experiment.py` 新增严格 dotenv parser、固定网络 allowlist、必需键校验、有效投影 hash 和 run 时重新物化。child environment 先移除父 shell 的同类键，再注入冻结投影；`.env` 从 Codex home tree、manifest 值、日志和 capsule 中排除。SOCKS remote DNS 与 ALL_PROXY fanout 是显式、可测试、进入身份的转换。

## SOL-002 固化 transport、sandbox 与真实后端门禁

- 状态: implemented
- 关联: AC-004, DES-002, DES-003, DES-004

experiment v3 要求 `danger-full-access`、Standard、approval never 和显式 transport。HTTP-only provider 固定 ChatGPT OAuth endpoint 并禁止 extra config 覆盖；WebSocket 使用内置 provider。candidate-only 只为 candidate 消耗模型预检，但在两侧同等信任的正式 workspace 运行；预检前后所有声明 workspace identity 必须相同，不能把 full-access 预检副作用冻结成基线。srcq 预检必须取得版本与 scc doctor 的真实成功 command events；任一网络 retry/fallback 使运行无效。

## SOL-003 补齐运行身份与兼容验证

- 状态: implemented
- 关联: AC-002, AC-003, CON-001

run 复核 experiment v3、Codex 二进制、corpus、workspace、home tree、runtime projection、runner 源码与 Python 版本。新 capsule 使用 v3；只读 `verify-capsule` 继续接受历史 v2 capsule，使已完成证据仍可复核但旧 manifest 不能绕过新运行合同。

## SOL-004 运行一次正常分页行为评估

- 状态: verified-negative
- 关联: AC-005, DES-005

最终 identity `a37e3675d74dfca877f84fbccfc9814ff37cacc56fd796263c1335a3d31dc939` 使用 WebSocket、代理端 DNS、ALL_PROXY fanout、full access 和 candidate-only schedule。网络、身份和 scc 边界均有效；模型取得第一页后把 `after=<cursor>` 误接到直接入口，第二条命令失败。因此框架目标已闭合，srcq 正常续页友善度未通过，未在本任务内擅自修改产品合同。

## SOL-005 共享并冻结模型 shell 环境策略

- 状态: implemented
- 关联: AC-006, DES-001, DES-006

网络投影与 ambient sanitizer 收口到 `development/common/codex_runtime.py`，模型 shell 过滤表收口到 `development/common/codex_shell_environment_policy.json`。benchmark Codex identity 记录策略 SHA-256，每次 preflight/subject 从同一文件生成确定性 `-c` overrides，并拒绝 `extra_config` 覆盖或 prepare 后策略漂移；launcher sanitizer 同时清除 Git/SSH、云/包管理器、语言注入与 CI 控制变量。既有分页行为结论绑定旧 identity 保留为历史证据，新运行必须取得包含共享策略的新 identity。
