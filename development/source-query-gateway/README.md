# 源码查询研究框架

本目录只向 Git 提供可复用的研究框架、协议检查器、格式说明和合成测试。当前工具的源码、行为合同及开发验证入口由 [srcq](../../tools/srcq/README.md) 持有；真实查询题目和研究记录遵循 [CON-008](../../docs/requirements.md#con-008-真实评测数据仅保留在本机)，不随源码分发。

## 入口与职责

- [代码搜索基准](../code-search-benchmark/README.md)：显式加载本地语料，冻结实验身份、运行及归档；基础检查使用合成数据。
- `prepare_benchmark_homes.py`：准备或复用有界隔离环境，不以目录存在替代运行证据。
- `build_routing_capsule.py`、`verify_routing_result.py`：从本地路由题库形成研究输入并核对结果结构。
- [历史校验器](history/README.md)：显式消费本机索引，验证可用的原始结果与审计资产；缺失私有索引不表示验证通过。
- [原生后端协议](backend-contract/README.md)与 [AST 基线](ast-baseline/README.md)：公开工具协议、合成 fixture 与确定性检查，不包含真实解题答案。
- `tests/`：只验证上述框架的稳定行为，不运行真实模型评测。

## 本机私有资产

既有 `benchmark-corpus-seed.json`、`routing-cases.json`、`evidence/`、`history/index.json` 及研究任务、状态、结果和顶层历史 Markdown 文档保留在原本机路径，已排除于 Git。它们包含实际题目、答案、逐题审计或与这些内容紧密关联的实验记录；不能改名放入 fixture、提交到别处或当作新克隆的必需文件。

顶层历史 `plan.md`、`requirements.md`、`design.md` 等只供原宿主追溯研究，不再作为 Git 分发的当前工具入口。新克隆使用上面的框架入口；需要真实研究时由操作者提供本地数据，框架不得自动下载私有题库或启动模型补齐缺失证据。仓内引用与完整哈希仍由本地记录维护，不为脱敏重写真实运行事实。
