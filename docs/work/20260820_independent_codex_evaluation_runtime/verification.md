# 验证记录

## 确定性验证

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `python -X utf8 -m py_compile development/code-search-benchmark/experiment.py development/source-query-gateway/prepare_benchmark_homes.py` | pass | Python 语法与导入 |
| code-search benchmark unittest | 34/34 pass | 共享 dotenv/policy owner、ambient Git/SSH/语言注入净化、policy 身份与 override 防篡改、remote DNS、proxy fanout、transport、真实后端预检 oracle、网络降级观察、runner 身份及既有实验合同 |
| benchmark home unittest | 10/10 pass | Windows 隔离 home、full-access 配置、候选 bundle 与入口探针 |
| 主机 `srcq query scc doctor` | `ok` | 当前主机 srcq 可发现并启动真实 scc；不单独证明 Codex sandbox |

2026-08-21 额外无模型兼容探针把共享 policy 的全部 33 个 `-c` overrides 交给当前用户 npm 原生 Codex CLI；临时空 home 下 `features list` 返回 0，直接证明通配符 dotted-key 配置可被当前 CLI 解析。临时 home 已删除，未读取认证、运行 subject、安装或发布。

## 因果迭代

| 运行 | 唯一机制变化 | 结果与处置 |
| --- | --- | --- |
| v1 | candidate-only 预检 | 真实命令通过，但临时 preflight workspace 只写入 candidate trust，环境差异正确拒绝；改用两侧预登记正式 workspace |
| v2 | 显式 `.env` allowlist + 正式 workspace + full access | preflight 能启动 scc；subject 仍发生五次 WebSocket retry/HTTP fallback，样本不采纳；同时首次观察分页误用 |
| v3 | SOCKS remote DNS | preflight 仍有 TLS retry，新网络门禁直接拒绝，未启动 subject |
| v4 | ChatGPT HTTP-only transport | preflight/subject 网络干净、分页误用可复现；subject 391.046 s，作为有效诊断但不是本机速度候选 |
| v5 | WebSocket + remote DNS + ALL_PROXY fanout 到 HTTP/HTTPS | preflight 与 subject 都零连接失败、零 retry、零 fallback；成为最终身份 |

## v5 事件级结果

- experiment identity: `a37e3675d74dfca877f84fbccfc9814ff37cacc56fd796263c1335a3d31dc939`
- preflight: 60.942 s；`srcq.exe --version` 返回 `srcq 0.4.0`，`srcq query scc doctor` 返回独立 `ok` 行；网络计数全零。
- subject: 82.626 s；input `63,240`、cached input `40,448`、output `959`、reasoning output `672`；exit 0、未超时、postflight failures 为空、网络计数全零。
- v3 audit capsule 已生成并由正式 verifier 复核：capsule SHA-256 `b97bfda24dcb271aab75bf50c14bd79659410893453668cd76cc3c94b5517533`，4 个原始文件与 2 个环境文件 hash 全部通过。
- 第一条命令是指定的 `srcq scc --by-file ...`，exit 0；第一页 97 行并以 `@more shown=80 omitted=97 after=<cursor>` 结束。
- 第二条命令是模型自行形成的 `srcq scc --after <cursor>`，exit 1；stdout 明确报告原生 scc 不认识 `--after`。模型没有取得第二页，也没有报告第二页第一条文件路径。
- 结论只覆盖正常同 turn 的 scc files 续页。压缩后恢复、其他 backend、完整 A/B 收益和修改后的提示未测试。

原始运行只保存在本机可清理归档 `%LOCALAPPDATA%\AgentBase\pagination-eval-20260820-v1` 至 `v5`，不进入仓库或发布 payload；长期项目证据是本文件的有界事实、最终 identity 和适用边界。
