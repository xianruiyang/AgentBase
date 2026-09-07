# AgentBase Windows 发行

本目录只拥有 AgentBase 主包的发行组装，不接管组件构建、安装、部署或回滚。
主包版本来自 `development/plugin-packaging/template/agentbase-core/.codex-plugin/plugin.json`；
tag 为 `agentbase-v<version>`。srcq、workflow-cli、MCP 的版本和资产仍由各组件所有。

## 构建与发布

用户授权 Release 后，先完成受影响组件的正式验证并提交审查过的源码，再执行：

```powershell
& .\development\release\build_agentbase_release.ps1
```

构建器要求已跟踪内容与 HEAD 一致，从 Git 导出已提交文件；不从工作区递归打包，
不携带 Git 历史、忽略的真实题库、用户配置、安装备份、缓存或主机状态。
主包包含可独立开发/部署的源码与合成框架测试；真正进入 Codex 的 plugin/直接部署
payload 继续由既有过滤合同排除所有开发资产。

它从导出的正式源码调用现有插件构建器和官方校验器，再调用恢复包构建器，产生：

- `agentbase-<version>-windows.zip`：源码/部署入口，以及预构建插件和恢复入口；
- `agentbase-core-<version>.zip`：已验证插件，可独立分发；
- `agentbase-recovery-<version>-windows.zip`：无 Codex/CLI/Python 运行依赖的 PowerShell 7 恢复工具；
- `manifest.json` 与 `SHA256SUMS`：组件版本、Git 来源和所有归档的大小与校验值。

产物位于忽略的 `development/release/dist/<version>/`。manifest 是机器生成的单一来源；
发布操作消费完整 hash，模型仅报告版本、资产名、验证结论和 Release 链接，不手工编辑
生成物。修改来源后重新构建；已存在输出目录会拒绝覆盖，使用新的输出目录审查重建。

将对应 tag 指向 manifest 的 commit，创建 GitHub Release 草稿并上传该批精确资产；
核查草稿 tag、资产名和字节数后发布，实际下载并校验 hash。失败时保留草稿供恢复，
不覆盖已发布 tag/资产。不得通过 Release 自动执行主机安装、Deploy 或修改仓库可见性。
该合同只用 Windows 本地入口验证，不创建远程 CI。

## 用户安装

解压主包后先阅读根 README 和 `development/codex-deployment/README.md`。
先通过各自发行资产安装 srcq 与 workflow-cli，再按部署说明准备其他 Windows 前置条件。
新安装使用 Plugin；尚未完成插件迁移的旧安装继续 DirectCompatibility，两者不得并行启用。
插件预构建目录仍是仓库级 marketplace 指向的正式路径，无需把安装副本拷回源码。

首次部署前的原配置恢复点只在用户本机产生，随附的 `recovery/restore.ps1` 默认只预览。
原始备份不会因下载恢复工具而从服务器出现；已有安装继续其既有 Rollback。
具体冲突、Plugin 停用与恢复边界以部署 owner 文档为准。
