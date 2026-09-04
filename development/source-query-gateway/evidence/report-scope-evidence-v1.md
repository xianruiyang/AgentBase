# 搜索范围候选：发现并隔离研究材料干扰

2026-09-04。供代码阅读研究继续与用户复核；开发证据，不进入部署。最终目标仍是旧最佳批量版与候选全九题各两次、逐题至少持平且尽量全对、实际均价涨幅不超过50%，不加入题目字段提示。

## 本轮裁决

尚未认证全九题达标。原范围实验虽回答正确，但工具实际读到了历史研究资料，不能据此认证独立收益。已保存原样本；同源、无研究资料的源码工作区重测中，范围候选与真正旧最佳批量版均为3/4，均价下降0.39%，满足本题最低要求。来源剪裁消融没有提高正确率；随后[完整九题](report-scope-evidence-full-v1.md)八题最低达标，但TS少1分，故全目标未完成、不晋级。

候选保留 intent-trigger 的通用意图校准改动，只在原查询范围条款内区分“用户或正式来源确认的对象范围”与“临时使用的名称、目录、类型过滤”。后一类不是完整性依据。没有精确行号、题目文件名、语言、符号或答案提示；全局正文从4,887增至4,924 Token，其余skills、批量条款、srcq、Luna medium/low/default保持不变。三份历史报告及其直接候选的有界核对未发现同等机制已被测试；这不是对全部历史的不存在结论。

## 主仓库上的原样本：仅描述，不认证收益

根目录 `D:\AgentBaseBench\scope-evidence-v1`；control为前一轮intent-trigger候选，不是旧最佳批量版。题面与v24 oracle不变，双方各两次。对应原始 `policy-ready/audit-capsule.json` 已校验，12份原始文件、答案/usage/实际价格一致，无超时、非零退出或postflight failure；这些机械检查不证明未读取研究材料。

| 环境 | 第一次 | 第二次 | 每次均价 USD |
| --- | ---: | ---: | ---: |
| 前轮候选 control | 1/2 | 2/2 | 0.00914970 |
| 范围候选 | 2/2 | 2/2 | 0.00982520 |

原始题目费用 $0.03794980，预检 $0.01031780，共 $0.04826760。control第一次只给global/AGENTS.md，缺skills/source-query/SKILL.md；其他答案明确给出两个正式路径。该分数只描述最终文本，不能覆盖下列有效性问题。

- candidate1工具5扩大到Markdown全文搜索，输出包含 `development/source-query-gateway/evidence/report-intent-trigger-v1.md` 的研究结论、入口修复研究说明和 `candidate-skill/source-query/SKILL.md`；工具7随后直接查询实验候选skill正文。
- candidate2工具11也带入intent-trigger和入口修复研究报告。这不是假想泄漏风险，而是已发生的模型输入暴露；是否改变其最终答案不能由当前样本独立排除。
- 正式runner原本已在公共prompt禁止访问历史答案、聚合结果和隐藏oracle，但全文搜索的实际输出仍越过了这条研究隔离边界。修复对象因此转回基准的可见源码环境，不向全局规则添加题目特例或要求模型记住更多排除清单。

`inspect_tools.py --exposure` 通过正式parser投影上述来源与相邻行；原始日志仍是事实来源，不由报告补写原答案。不能把这批机械postflight通过解释为研究有效，也不因本轮反例将其他项目的全部历史样本自动判无效。

## 根源修复与当前恢复点

`prepare_source_workspace.py` 从项目Git提交导出除development外的全部根条目，生成 `D:\AgentBaseBench\source-workspaces\agentbase-v24`：965个已跟踪文件、6,317,980字节。快照保留根规则/README、docs、global、skills、tools、mcp及项目配置；不复制node_modules、缓存、凭据或原Git历史，另建仅含当前源码的本地Git快照用于正式runner身份冻结，无远端。来源与排除项保存在同目录实验根的 `source-workspace.json`，不把快照作为项目源码或部署来源。

正式 `validate_corpus_snapshot` 已确认四道AgentBase题目的目标源码指纹一致；题目、路径目标和行号oracle均未修改。排除依据是development的研究/开发资产职责，不是按正确答案筛文件。模型只读合同仍适用；这不是操作系统级访问隔离承诺。

干净重测根为 `D:\AgentBaseBench\scope-evidence-clean-v1`，准备和顺序由其中 `prepare.py`、`research-plan.md` 定义：

- control来自已冻结的真正旧最佳批量环境 `full-suite-agentbase-only-v2/external/control`，candidate来自原样scope-evidence候选；各自13个AgentBase-owned skills，双方同srcq0.7.0、CLI、Luna medium/low/default、HTTP-only。
- 双方同用源码快照，已完成原规则来源题各两次；[逐项审计](audit-scope-evidence-clean-v1.json)给出原答案定位判断。旧版2/2、1/2，候选1/2、2/2，均为3/4；均价分别$0.00963500、$0.00959768。候选在这一题达到最低持平和价格要求，但未全对，也未证明新增范围条款的净收益。其余八题尚未验证，不能把局部成绩当作目标完成。
- 原始输出在 `policy-ready/runs`，`summary.json` 和 `audit-capsule.json` 已完整生成并校验，12份原始文件一致、无postflight失败，原始答案/usage/价格匹配；已检查的工具结果无此前研究材料暴露标记。题目费用$0.03846536、预检$0.00683536，共$0.04530072。两侧各一次都以根AGENTS代替source-query正式文件，未命中R2。
- 同一干净快照的来源剪裁消融已完成，外部入口 `D:\AgentBaseBench\source-pruning-ablation-v1`。该候选退回intent-trigger基底，仅删除“最小交付来源/下级不并列”条款，不叠加范围提示或题目字段。旧最佳版也有近似条款，整套环境比较不能独立归因。双方均1/2、2/2，合计3/4；旧版均价$0.00582404、候选$0.00641764（+10.19%）。12份原始文件、答案/usage/价格校验一致，无postflight失败。删除条款没有提高正确率；本次不将它加入范围候选。
- 原消融登记自行把4/4设为扩展硬门槛，运行期间已纠正并写回：用户要求是至少持平、尽量全对，价格涨幅不超过50%。不能用自行加严的满分门槛反复停留在一题。
- `D:\AgentBaseBench\scope-evidence-full-v1` 已冻结干净范围候选并完成core/ue/external三个独立home分片，其余八题双方各两次。准备脚本沿正式home owner复制各自项目skills，不复制其他skill、认证内容、缓存或源码工程；AgentBase复用干净快照，其他工程按旧实验正式范围读原源码。分片分别保存manifest和capsule，与已有policy结果仅按同候选逐题汇总，不伪装成一个实验身份。TS候选9/14低于旧版10/14，整体不达标；新候选与原始数据入口见完整报告，不用总分覆盖局部退化。

本轮未修改或部署global/AGENTS.md、skill或srcq；仅修改开发研究说明和基准环境职责，目标保持active。
