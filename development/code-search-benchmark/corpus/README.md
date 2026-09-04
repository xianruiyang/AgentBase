# 版本化源码查询语料

`v1.json` 至 `v4.json` 分别绑定历史结构化、迁移、首个 srcq 直觉入口和版本无关修正身份；`v5.json` 保留调优阶段的权威源码范围反例，`v6.json` 固化第一轮 P10 调优身份，`v7.json` 至 `v9.json` 依次固化同预算闭环、内置续页和权威范围身份，`v10.json` 进一步排除“只审查规则”对高级查询 skill 的误触发。`v11.json` 首次加入两个中型 C++ 与 TypeScript 项目，`v12.json` 与 `v13.json` 依次校准 TypeScript、C++ 题面和 required；`v14.json` 新增中型 C# 项目的采样、校验、缓存与分派链，`v15.json` 根据完整 Control 实测发现的源码反例补入 `TemperatureCollectorSensorReader.Test:58 -> Read` 直接调用；`v16.json` 初次把题面未明确要求的 Enabled/SlotIndex 细节降为 supporting；`v17.json` 移除 C# ExpectedUid 与 C++ root/完整参数的隐藏 required，补齐 TypeScript 宿主清理和全部消息边界，并把三个外部项目可独立漏答的事实原子化。`v18.json` 保留这些业务事实，把现有定义位置原子统一升级为完整实现文件与 1-based inclusive 起止行；`v19.json` 初次明确工作区根相对基准，但与 Codex 桌面完整绝对文件链接合同冲突；`v20.json` 以可唯一映射到工作区根 oracle 文件的完整路径身份替代固定格式，并明确实现结束行包含适用语言的闭合分隔符；`v21.json` 进一步显式化 C++ 已评分的空/非空分支和下游转发关系，并允许同一完整文件身份下分组列出多个位置。`v22.json` 校准当前源码身份、规则/DTO 位置和 UE 新增真实调用。`v23.json` 进一步修正 containing 的闭合行，明确 DTO 的两处行号、C#/TS 文件身份分组和 C# 调用完整性声明；TS 必答只保留会话过滤分类，题面未要求的状态更新动作降为 supporting。当前 `v24.json` 保留九题题面和定位事实，更新 AgentBase 规则文件快照，并把正式评分统一改为下述纯定位合同。runner 冻结各工作区声明范围内的完整身份并在变化时拒绝结果。源码行号与调用集合仅由各版 oracle 维护，不在本说明重复。旧版本只复核已引用它们的历史结果，不作为新实验的当前 oracle；旧环境也须运行相同新题，不沿用旧成绩。

## 当前正式评分与主观参考

本节由当前 corpus 的 `scoring.mode = locations-only-v1` 绑定；随 corpus 冻结的 `scoring` 使脱离仓库的 auditor 也能取得同一合同。题面仍要求解释，以保留原任务负荷，但解释不再决定正式成绩。

- `answer_contract.required` 只列题面要求的定位目标。每项核对一个路径、路径加行号，或路径加完整实现起止行，共同构成 1 分；不得把同一目标再拆成路径分、起止行分，或增设“所有路径行号准确”的重复扣分项。
- 答案位置应唯一对应指定目标。绝对路径、工作区根相对路径、路径分隔符、Markdown 链接及同文件分组可以等价；不要求固定措辞、重复路径或固定排列顺序。错误文件上的正确数字仍是错误位置。
- 起止行按 1-based inclusive，从声明第一行到实现闭合分隔符所在行，不含前置注释、属性或相邻成员；嵌套与包围实体分别核对。题面只要求路径时不额外要求行号，只要求定位行时不额外要求完整范围。
- 分母固定为当前题的 required 项数，正式得分是命中数/分母。按目标记录漏项或错项，同一目标只扣一次；针对所要求目标的额外错误位置另列，不靠堆砌行号提高得分，不扩大分母或重复扣已错项。整题正式通过须全部命中且无额外错误位置。
- 调用/引用的实际位置集合仍须完整，缺少 `Test → Read` 这类指定调用位置会失分；但未写“已穷尽”、静态边界或某个状态发布行为不扣正式分。
- `answer_contract.supporting`、其余 oracle 解释、分支/状态/错误码/类型关系、回答行数与措辞只进入“主观参考分或评语”，不与正式分相加，不影响通过判定或客观质量比较。不得从 oracle 的其他字段重新制造隐藏必答项。
- 实际越权、环境身份漂移或基础设施失败仍按运行有效性单独记录，不伪装为位置零分；这不把语义解释重新纳入正式评分。

| 现行九题 | 正式定位项 |
| --- | ---: |
| 文件发现 | 1 |
| 正式规则来源 | 2 |
| ProviderObservation 与 DTO 字段 | 2 |
| containing 实现文件 | 1 |
| Submit 完整实现 | 1 |
| IsBareKey 定义与四处调用 | 5 |
| C++ RayCast 实现与调用链 | 5 |
| TypeScript 消息处理位置 | 7 |
| C# 采样实现与调用链 | 13 |
| 合计 | 37 |

评分报告分别列出正式位置得分、漏/错目标、额外错误位置，以及仅供参考的主观评价。质量比较只使用前者及客观位置错误，不以主观项抵消或否决。

## 历史答案与参考答案

旧 corpus 和已绑定 experiment 的 audit/result 不原位改写；旧的核心/严格/混合分数只解释当时裁决，不是当前纯定位成绩。重新使用历史答案时保留原始答案、用量、旧分数和实验身份，另记新评分版本及逐项位置结果；只变评分且题面、目标和冻结源码中的定位事实相同或经直接核实等价，可同时给双方原答案重新评分，无需运行模型。题面或定位目标发生实质变化，则新旧环境必须运行同一新题，不借重评分补造原答案没有被要求提供的内容。

路径、定位行号和实现范围的标准答案仍由各 case 的结构化 `oracle` 唯一维护，required 只标明要核对的目标；supporting 不是另一份位置答案。没有源码反例时不为降低主观性改写行号。v24 没有重评或覆盖历史实验，也不能据它直接宣称某个旧候选已经通过。

校验器检查结构、文件身份和唯一路径，不证明题面与标准答案语义一致或实现范围包含闭合行；这些语义须在模型运行前对照源码人工核验。每个 case 绑定直接承担 oracle 的源码文件 SHA-256。任一文件变化都会使本版本失效，应复制为新的 corpus 版本并重新审查事实，不得原位改写已被实验引用的版本。文件级绑定只证明 oracle 事实；实际实验还必须在 `experiment.json` 冻结声明的工作区 identity scope、commit、tree、该范围 dirty patch 和 snapshot hash。未声明 scope 时默认整个仓库；所有 oracle 来源必须位于声明范围内。

独立校验器接受任意 workspace role，并可只验证当前实验选择的 case；未选择的历史快照不要求在当前主机重建：

```powershell
python -X utf8 development\code-search-benchmark\corpus\validate_corpus.py development\code-search-benchmark\corpus\v24.json --workspace facecutting3d-cpp=D:\program\FaceCutting3D --workspace opencode-vs-plugin-ts=D:\program\OpencodeVsPlugin --workspace vmtsinglemachine-csharp=D:\program\AIFile\VMTSingleMachine --case-id facecutting3d-raycast-chain --case-id opencode-webview-message-boundary --case-id vmt-temperature-collector-sampling-chain
```

`lsp-progressive-v1.json` 仅保留未进入 LSP、单项 LSP 和多阶段 LSP 三类历史冻结语料；没有现行默认实验消费者，不属于当前九题。其历史语义分不能冒充纯定位成绩；将来重开也须按本节纯定位合同创建新版本，不能直接复用旧评分。

本目录是项目开发资产，不属于 sgy 或 Codex 发布 payload。
