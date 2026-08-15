# 版本化源码查询语料

`v1.json` 至 `v4.json` 分别绑定历史结构化、迁移、首个 srcq 直觉入口和版本无关修正身份；`v5.json` 保留调优阶段的权威源码范围反例，`v6.json` 是当前候选，显式把原有行数验收写入被测 prompt，并绑定收敛后的普通文本与高级证据触发边界。旧版本只复核已引用它的历史结果，不作为新实验的当前 oracle。语义关系不依赖固定措辞，`IsBareKey` 的正式源码 oracle 为定义 2655、调用 648/868/2037。

每个 case 绑定直接承担 oracle 的源码文件 SHA-256。任一文件变化都会使本版本失效，应复制为新的 corpus 版本并重新审查事实，不得原位改写已被实验引用的版本。文件级绑定只证明 oracle 事实；实际实验还必须在 `experiment.json` 冻结声明的工作区 identity scope、commit、tree、该范围 dirty patch 和 snapshot hash。未声明 scope 时默认整个仓库；所有 oracle 来源必须位于声明范围内。

`lsp-progressive-v1.json` 单独冻结未进入 LSP、单项 LSP 和多阶段 LSP 三类语料。它用于观察渐进工具暴露、调用序列和端到端成本，不与旧五-skill 对照拼接，也不替代同 identity 的收益实验。

本目录是项目开发资产，不属于 sgy 或 Codex 发布 payload。
