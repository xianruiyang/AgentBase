# 统一源码查询入口迁移候选

## 1. 职责与生效边界

本文件只说明分支满足验收且用户决定采纳后，如何把现行查询职责收敛到一个正式入口。它不是迁移授权；当前正式 skill、全局规则、Codex 安装态和 `rg_receipt.py` 保持有效。实际迁移与发布必须在同一次采纳变更中完成并重新验证消费者，避免候选与旧入口长期共同决定行为。

## 2. 权威职责映射

| 当前入口 | 迁入 `source-query` 的职责 | 迁移后动作 |
| --- | --- | --- |
| `fd-usage` | 文件与目录发现、pattern/path 区分、有界原生快路径 | 删除旧 skill |
| `rg-token-safe` | 文本定位、范围与输出预算、全集和不存在证明 | 删除旧 skill 与 `rg_receipt.py` |
| `ast-grep-token-safe` | AST argv、profile、cache、process、rewrite 与安全边界 | 语义迁入按需 `references/ast.md` 后删除旧 skill；sgy AST 命令保持 |
| `symbol-structure-workflow` | 文本、AST 与 LSP 的成本升级边界 | 只保留真实符号语义、LSP 协议及修改裁决，不再重复前三类工具协议 |
| `powershell-usage` | Windows shell 语法与执行安全 | 保留；不承担源码查询路由 |

## 3. 原子迁移步骤

1. 以候选 skill 和 `sgy 0.2.0` 构建正式 payload，确认仅含运行规则、引用、二进制、许可证和来源材料。
2. 更新 `global/AGENTS.md` 的查询路由，使其只引用统一 skill 的成本升级边界；更新 `symbol-structure-workflow` 的消费者关系。
3. 删除三个被替代 skill 与 `rg_receipt.py`，同步删除触发用例、校验器和文档中的旧正式入口引用，不保留别名或兼容分支。
4. 刷新独立路由和行为证据，验证简单快路径、全集、fd tree、AST、LSP、写入安全及相近非触发。
5. 由用户确认当次发布后增量安装；读回 payload 清单与运行时版本，并在新任务中验证指令链。

任一步无法同时退出旧决定路径时，停止采纳，不把候选叠加为第二套长期规则。
