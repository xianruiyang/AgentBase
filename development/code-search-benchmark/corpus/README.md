# 版本化源码查询语料

`v1.json` 至 `v4.json` 分别绑定历史结构化、迁移、首个 srcq 直觉入口和版本无关修正身份；`v5.json` 保留调优阶段的权威源码范围反例，`v6.json` 固化第一轮 P10 调优身份，`v7.json` 至 `v9.json` 依次固化同预算闭环、内置续页和权威范围身份，`v10.json` 进一步排除“只审查规则”对高级查询 skill 的误触发。`v11.json` 是当前候选，在继承原六类任务的同时加入两个中型 C++ 与 TypeScript 真实项目：前者覆盖限定成员、typed receiver、非注释直接调用与公共/私有实现链，后者覆盖跨运行面事件注册、局部闭包身份、清理和状态过滤。两项使用各自绑定的 dirty working-tree 快照，runner 会冻结完整身份并在变化时拒绝结果。旧版本只复核已引用它们的历史结果，不作为新实验的当前 oracle。语义关系不依赖固定措辞，`IsBareKey` 的正式源码 oracle 为定义 2655、调用 648/868/2037。

每个 case 绑定直接承担 oracle 的源码文件 SHA-256。任一文件变化都会使本版本失效，应复制为新的 corpus 版本并重新审查事实，不得原位改写已被实验引用的版本。文件级绑定只证明 oracle 事实；实际实验还必须在 `experiment.json` 冻结声明的工作区 identity scope、commit、tree、该范围 dirty patch 和 snapshot hash。未声明 scope 时默认整个仓库；所有 oracle 来源必须位于声明范围内。

独立校验器接受任意 workspace role，并可只验证当前实验选择的 case；未选择的历史快照不要求在当前主机重建：

```powershell
python -X utf8 development\code-search-benchmark\corpus\validate_corpus.py development\code-search-benchmark\corpus\v11.json --workspace facecutting3d-cpp=D:\program\FaceCutting3D --workspace opencode-vs-plugin-ts=D:\program\OpencodeVsPlugin --case-id facecutting3d-raycast-chain --case-id opencode-webview-message-boundary
```

`lsp-progressive-v1.json` 单独冻结未进入 LSP、单项 LSP 和多阶段 LSP 三类语料。它用于观察渐进工具暴露、调用序列和端到端成本，不与旧五-skill 对照拼接，也不替代同 identity 的收益实验。

本目录是项目开发资产，不属于 sgy 或 Codex 发布 payload。
