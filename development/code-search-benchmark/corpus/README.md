# 版本化源码查询语料

`v1.json` 至 `v4.json` 分别绑定历史结构化、迁移、首个 srcq 直觉入口和版本无关修正身份；`v5.json` 保留调优阶段的权威源码范围反例，`v6.json` 固化第一轮 P10 调优身份，`v7.json` 至 `v9.json` 依次固化同预算闭环、内置续页和权威范围身份，`v10.json` 进一步排除“只审查规则”对高级查询 skill 的误触发。`v11.json` 首次加入两个中型 C++ 与 TypeScript 项目，`v12.json` 与 `v13.json` 依次校准 TypeScript、C++ 题面和 required；`v14.json` 新增中型 C# 项目的采样、校验、缓存与分派链，`v15.json` 根据完整 Control 实测发现的源码反例补入 `TemperatureCollectorSensorReader.Test:58 -> Read` 直接调用；`v16.json` 初次把题面未明确要求的 Enabled/SlotIndex 细节降为 supporting；`v17.json` 移除 C# ExpectedUid 与 C++ root/完整参数的隐藏 required，补齐 TypeScript 宿主清理和全部消息边界，并把三个外部项目可独立漏答的事实原子化。`v18.json` 保留这些业务事实，把现有定义位置原子统一升级为完整实现文件与 1-based inclusive 起止行；`v19.json` 初次明确工作区根相对基准，但与 Codex 桌面完整绝对文件链接合同冲突；`v20.json` 以可唯一映射到工作区根 oracle 文件的完整路径身份替代固定格式，并明确实现结束行包含适用语言的闭合分隔符；`v21.json` 进一步显式化 C++ 已评分的空/非空分支和下游转发关系，并允许同一完整文件身份下分组列出多个位置。`v22.json` 校准当前源码身份、规则/DTO 位置和 UE 新增真实调用。当前 `v23.json` 进一步修正 containing 的闭合行，明确 DTO 的两处行号、C#/TS 文件身份分组和 C# 调用完整性声明；TS 必答只保留会话过滤分类，题面未要求的状态更新动作降为 supporting。runner 冻结各工作区声明范围内的完整身份并在变化时拒绝结果。源码行号与调用集合仅由各版 oracle 维护，不在本说明重复。旧版本只复核已引用它们的历史结果，不作为新实验的当前 oracle；旧环境也须运行相同新题，不沿用旧成绩。

`answer_contract.required` 只保存题面明确要求，或为完成题面目标在结构上不可缺少的语义；删除任一 required 都必须能指出哪个题面目标会失败。有价值但题面未要求的源码事实放入 `supporting`，不得让隐藏补充项把符合题面的答案判为质量失败。历史 corpus 已被 experiment identity 绑定后不原位修订，oracle 语义校准通过新版本向前生效。评分前按 required 的实际数组编号，逐项记录未通过编号和原答案证据，分母与总分机械计算；同一完整文件身份下的分组位置不因省略重复路径扣分，调用者与被调用者不得混淆，静态边界与完整性按题面语义而非固定措辞判定。

校验器检查结构、文件身份和唯一路径，不证明题面与标准答案语义一致或实现范围包含闭合行；这些语义须在模型运行前对照源码人工核验。每个 case 绑定直接承担 oracle 的源码文件 SHA-256。任一文件变化都会使本版本失效，应复制为新的 corpus 版本并重新审查事实，不得原位改写已被实验引用的版本。文件级绑定只证明 oracle 事实；实际实验还必须在 `experiment.json` 冻结声明的工作区 identity scope、commit、tree、该范围 dirty patch 和 snapshot hash。未声明 scope 时默认整个仓库；所有 oracle 来源必须位于声明范围内。

独立校验器接受任意 workspace role，并可只验证当前实验选择的 case；未选择的历史快照不要求在当前主机重建：

```powershell
python -X utf8 development\code-search-benchmark\corpus\validate_corpus.py development\code-search-benchmark\corpus\v23.json --workspace facecutting3d-cpp=D:\program\FaceCutting3D --workspace opencode-vs-plugin-ts=D:\program\OpencodeVsPlugin --workspace vmtsinglemachine-csharp=D:\program\AIFile\VMTSingleMachine --case-id facecutting3d-raycast-chain --case-id opencode-webview-message-boundary --case-id vmt-temperature-collector-sampling-chain
```

`lsp-progressive-v1.json` 单独冻结未进入 LSP、单项 LSP 和多阶段 LSP 三类语料。它用于观察渐进工具暴露、调用序列和端到端成本，不与旧五-skill 对照拼接，也不替代同 identity 的收益实验。

本目录是项目开发资产，不属于 sgy 或 Codex 发布 payload。
