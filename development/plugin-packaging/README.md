# AgentBase plugin packaging

本目录把仓库中的受管 skill 构建为可重建的 `agentbase-core` 本地插件包。它只负责过滤、组装、生成清单和插件结构校验；不安装或启用插件，不发布全局 `AGENTS.md`、可移植设置、MCP 或 PATH 中的 `srcq.exe`。

## 输入与输出

- [`template/agentbase-core`](template/agentbase-core/)：经官方脚手架建立的插件模板和以 `${PLUGIN_ROOT}` 定位的 hooks。
- [`build_plugin.ps1`](build_plugin.ps1)：唯一构建入口。
- [`../common/payload_contract.ps1`](../common/payload_contract.ps1)：插件和直接兼容发布共用的 payload 过滤合同。
- [`../../.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)：仓库级 `agentbase-local` marketplace，只指向忽略的 `dist/agentbase-core` 产物。

构建器从路由合同读取所需 skill，过滤测试、fixture、benchmark、缓存、日志、覆盖率、依赖树、构建目录、临时文件和 reparse point，并生成逐文件哈希与来源指纹清单。构建产物不是项目真源，不得直接编辑或提交。

## 正式构建

默认构建写入 marketplace 所指向的 `dist/agentbase-core`，并调用当前 Codex 安装提供的官方插件校验器：

```powershell
& '.\development\plugin-packaging\build_plugin.ps1' -ProjectRoot (Get-Location).Path
```

`-SkipOfficialValidation` 只允许配合显式、隔离的 `-OutputRoot` 用于 CI 检查可移植复制和清单合同，不能写入默认 `dist`，也不能作为正式可安装产物的证据。

插件和 `DirectCompatibility` 的同名 skill/hook 不得同时启用。插件安装、Codex payload 发布、主机前置条件、状态读回和回滚见[部署说明](../codex-deployment/README.md)；每次正式 `Publish` 仍需用户针对当次操作明确同意。
