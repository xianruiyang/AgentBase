# 统一源码查询入口迁移候选

## 1. 职责与生效边界

本文件记录已经进入项目真源的职责迁移及尚未取得授权的 Codex 安装边界。项目正式 Skill、全局候选规则、CI 与部署合同已收敛；实际 Codex 根目录仍保持原安装态，必须在用户针对当次发布明确同意后才增量更新。

## 2. 权威职责映射

| 当前入口 | 迁入 `source-query` 的职责 | 迁移后动作 |
| --- | --- | --- |
| `fd-usage` | 文件与目录发现、pattern/path 区分、有界原生快路径 | 删除旧 skill |
| `rg-token-safe` | 文本定位、范围与输出预算、全集和不存在证明 | 删除旧 skill 与 `rg_receipt.py` |
| `ast-grep-token-safe` | AST argv、profile、cache、process、rewrite 与安全边界 | 语义迁入按需 `references/ast.md` 后删除旧 skill；`srcq` 保持既有 AST 行为 |
| skill 内置 `sgy.exe` 与运行时来源副本 | 迁移到 `tools/srcq` 维护的独立 Windows 安装生命周期 | 只允许 PATH 中的正式 `srcq.exe`；不保留私有 fallback |
| `symbol-structure-workflow` | 旧的查询与编辑混合职责 | 只保留语义重命名、Code Action、格式化、task/command 和调试等编辑器操作；只读查询归 `source-query` |
| `powershell-usage` | Windows shell 语法与执行安全 | 保留；不承担源码查询路由 |

## 3. 原子迁移步骤

1. `tools/srcq` 作为唯一运行时 owner 构建 Windows release；正式安装器覆盖全新安装、状态、升级、卸载、PATH 和新进程 `srcq --version`/`srcq doctor` 读回。
2. `source-query` payload 固定为 `SKILL.md`、metadata 与三份按需引用，不含二进制、runtime manifest、来源/许可副本或开发测试资产；只调用 PATH 中的 `srcq.exe`。
3. `global/AGENTS.md` 只保留证据层级短路由；查询协议归 `source-query`，编辑器写操作归 `symbol-structure-workflow`。
4. 删除三个被替代 skill、`rg_receipt.py` 及内置运行时；部署和插件合同必须移除受管旧副本，不保留别名、私有二进制或兼容 fallback。
5. 独立路由、行为和 LSP 渐进证据覆盖简单快路径、全集、fd tree、AST、LSP、写入安全、缺失/错误版本恢复动作及相近非触发。
6. Codex 发布仍逐次请求用户确认；发布前读回主机 `srcq` 安装态，发布后核对 payload 清单，并在新任务中验证新指令链。

任一步无法同时退出旧决定路径时，停止采纳，不把候选叠加为第二套长期规则。
