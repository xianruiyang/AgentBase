# 生成式模型导航摘要设计

## DES-001 render generator 是唯一文件表示 owner

- 状态: confirmed
- 关联: REQ-001, UDES-001

taskctl/workctl 继续从同一 canonical 存储与索引计算 machine summary；Markdown renderer 只选择面向复核导航的行，不形成第二份计数、状态或完成判断。

## DES-002 Task 导航按分母与异常投影

- 状态: confirmed
- 关联: AC-001, AC-002, AC-003

状态统计只列非零状态。结果引用为零时显示一句空结论；存在结果时显示引用数和带验证数，其他未决/诊断/陈旧/快照问题只在非零时显示。上游始终保留保护状态，未决和 DCR 只在非零时增加。任务存在时保留完整明细表，无任务时只显示空结论。

## DES-003 Work 导航复用相同语义边界

- 状态: confirmed
- 关联: AC-001, AC-002

语义前缀计数保留；未决、未知引用和 DCR 只显示非零。任务摘要只列非零状态，并保留 partial/unavailable；结果引用为零或未知分别明确表达。未决 ID 章节继续以“无”区分已读取的空集合。
