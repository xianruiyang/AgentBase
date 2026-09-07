# 本机源码查询语料合同

本目录在 Git 中只保留 `schema.json`、`validate_corpus.py` 和本说明。真实题面、标准答案、源码指纹、题库版本以及由它们派生的评分资料是操作者本机私有输入，不发布到仓库，也不复制成示例或测试 fixture。

真实语料使用 `agentbase.source-query-corpus/v1`。顶层包含稳定的 `schema`、`version`、`created_utc`、`workspace_roles` 和 `cases`；评分语义需要脱离仓库复核时，可在 `scoring` 中随语料冻结。每个 case 至少声明唯一 `id`、`workspace_role`、非空 `prompt`、非空 `answer_contract.required` 以及带源码证据的 `oracle`。`experiment.py` 还要求正整数 `answer_max_lines`，并检查 `required` 与可选 `supporting` 不重复、不交叉。

`oracle.source` 或 `oracle.sources` 中的路径必须相对相应工作区根，且以 SHA-256 绑定文件身份。`unique-path` oracle 还会排除 `.git`、`.codex`、`dist`、`target`、`node_modules` 和 `__pycache__` 后检查文件名在工作区内唯一。校验器只证明声明结构、路径边界、文件身份和唯一路径；题面是否准确覆盖目标、答案事实与源码语义是否一致仍须在运行模型前人工审查。

实验 config 的 `corpus` 字段是唯一语料选择入口。它必须显式指向本机现有 JSON 文件；框架没有默认真实版本，也不会下载、还原或合成私有题库。新克隆无需真实语料即可运行合成单元测试。需要恢复实验时，从操作者自己的受控本机备份恢复语料，并保持已有配置路径，或修改 config 指向恢复后的路径。

可独立校验全部 case，也可重复 `--case-id` 只校验当前实验选择的子集。每个被选 case 的角色必须通过重复的 `--workspace ROLE=PATH` 显式提供；未选 case 的历史工作区不需要重建：

```powershell
python -X utf8 development\code-search-benchmark\corpus\validate_corpus.py <local-corpus.json> --workspace <role>=<workspace-root> --case-id <case-id>
```

语料文件一旦被 experiment 引用便不原位改写。题面、oracle、源码身份或评分合同变化时，在本机创建新版本并重新审查；既有 experiment 与 audit capsule 继续绑定原文件哈希。语料和本框架都属于开发资产，不进入 Codex 或 srcq 发布 payload。
