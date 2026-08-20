# 当前状态

## 已确认事实

- 项目正式 independent Codex owner 是 `development/code-search-benchmark/experiment.py`；`development/skill-routing` 只验证路由选择，不执行具体源码工具。
- 正式 benchmark 合同原本已经固定 `danger-full-access`，但此前临时手工运行绕过 owner 并传入 `--sandbox read-only`，导致 `srcq` 无法 canonicalize/启动 WinGet 安装的 `scc.exe`，返回 Windows `os error 5`。
- 同一次手工运行未显式读取 `C:\Users\gzxt\.codex\.env`，stderr 出现五次 WebSocket TLS 重连；该文件当前只定义非空 `ALL_PROXY`，当前 Codex 宿主进程中的同名值与其一致。
- 原 runner 的 `codex_environment()` 只复制父进程环境，因此是否获得代理取决于启动 shell；experiment identity 也没有冻结该输入。
- 原预检仅执行 `srcq.exe --version`，只能证明 wrapper 可启动，不能证明 Codex sandbox 内能启动真实 scc 后端。
- candidate-only schedule 仍固定预检 control 与 candidate，会为未调度环境消耗一次独立 Codex 运行。

## 实施中补充证据

- 单侧预检若在临时 workspace 运行，Codex 会只向该 home 的 `config.toml` 写入 trust；因此 candidate-only 不能简单跳过 control 后仍使用新临时 workspace。预检改为使用 home preparer 已在两侧同等登记的正式 workspace。
- 仅注入 `.env` 的 `ALL_PROXY=socks5://...` 仍可能让 WebSocket 发生五次 TLS retry；本机定向探针显示相同端点以本地 DNS 的 SOCKS5 超时，而代理端 DNS 的 SOCKS5H 可达。进一步把有效 ALL_PROXY 显式 fanout 到 HTTP/HTTPS 客户端后，WebSocket preflight 与 subject 都达到零 retry。
- HTTP-only custom provider 能消除 WebSocket retry，但本次两工具 subject 用时 391.046 秒；它保留为显式身份选项，不作为本机最终速度候选。最终本机候选为 WebSocket + remote DNS + HTTP/HTTPS fanout，subject 用时 82.626 秒。
- 网络和权限前置闭合后，独立 Codex 仍把第一页的 `after=<cursor>` 直觉执行为 `srcq scc --after <cursor>`，原生 scc 拒绝未知参数；这是 srcq 分页提示的真实模型交互缺口，不再归因评估框架。

## 最早失效层

失效 owner 是 benchmark runner 的子进程运行时合同和预检 oracle，不是 srcq 分页实现。修复应落在该 owner：以脱敏身份冻结 `.env` 网络投影、覆盖父 shell 同类键、保持正式 full-access sandbox，并把真实 scc backend 纳入 Codex 内预检。不得复制 `.env` 到隔离 home，也不得在 srcq 中加入权限绕行。
