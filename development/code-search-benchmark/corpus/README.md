# 版本化源码查询语料

`v1.json` 是六个历史 prompt 的首个正式结构化版本。它修正了旧正则 oracle 的两个关键问题：语义关系不再依赖固定措辞，`IsBareKey` 的定义与调用角色按当前源码重新核对为定义 2655、调用 648/868/2037。

每个 case 绑定直接承担 oracle 的源码文件 SHA-256。任一文件变化都会使本版本失效，应复制为新的 corpus 版本并重新审查事实，不得原位改写已被实验引用的版本。文件级绑定只证明 oracle 事实；实际实验还必须在 `experiment.json` 冻结完整只读工作区的 commit、tree、dirty patch 和 snapshot hash。

`lsp-progressive-v1.json` 单独冻结未进入 LSP、单项 LSP 和多阶段 LSP 三类语料。它用于观察渐进工具暴露、调用序列和端到端成本，不与旧五-skill 对照拼接，也不替代同 identity 的收益实验。

本目录是项目开发资产，不属于 sgy 或 Codex 发布 payload。
