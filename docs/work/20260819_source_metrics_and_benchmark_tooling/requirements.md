# 源码指标与命令基准工具需求

## REQ-001 让模型跨项目使用源码指标与命令基准工具

- 状态: confirmed
- 来源: 用户 2026-08-19 要求让模型感知 `scc` 与 `hyperfine`，并按最高质量推进
- 关联: AC-001, AC-002, AC-003, AC-004, UDES-001, UDES-002

AgentBase 应让模型在跨项目任务中低成本发现并正确选择 `scc` 与 `hyperfine`：源码规模、语言和文件指标通过统一源码网关取得，命令性能比较通过独立基准工具完成。

## REQ-002 逐文件指标使用最低充分的路径表示

- 状态: confirmed
- 来源: 用户 2026-08-20 要求“在适合使用目录树的地方，改用目录树”
- 关联: AC-005, AC-006, UDES-004

`scc files` 的 model 投影应在不改变逐文件直接指标、稳定顺序、分页与恢复身份的前提下，按实际模型成本选择可逆目录树或扁平表示；不适合层级化的结果保持原有语义。

## AC-001 模型具有低固定成本的工具路由

- 状态: confirmed
- 关联: REQ-001

普通源码指标和命令基准任务无需先加载专项 skill、查询帮助或探测安装状态；全局规则提供足以选择正式入口的最短稳定语义，高级 scc 输出控制才按需加载 `source-query`。

## AC-002 Windows 主机入口安装并读回两个工具

- 状态: confirmed
- 关联: REQ-001, UDES-002

正式 Windows bootstrap 通过精确 winget 包身份安装或升级 `scc` 与 `hyperfine`，在 Check/Install 的 model 与 machine 视图中读回缺失、版本、支持状态和恢复动作，并由部署合同与回归测试消费。

## AC-003 scc 通过 srcq 统一运行

- 状态: confirmed
- 关联: REQ-001, UDES-001

普通入口为 `srcq scc <scc argv...>`，高级控制为 `srcq query scc <exec|defaults|doctor> ... -- <scc argv...>`。srcq 保留原生参数、退出和特殊模式，并从同一完整事实生成有界 model、稳定 machine 与 native/artifact 输出；正式规则不让模型直接绕过 srcq 调用 scc。

## AC-004 受影响合同无已知适用缺陷

- 状态: confirmed
- 关联: REQ-001

实现覆盖 scc 汇总、逐文件、大结果分页、续页快照、空结果、原生错误、版本漂移和特殊输出，保持 rg、fd 与 AST 合同非回退；安装、路由、release 与部署消费者完成验证。任何有效失败先修正原因再重验，最终只声明直接证据覆盖且不存在已知适用失败的范围。

## AC-005 files 自适应选择目录树

- 状态: confirmed
- 关联: REQ-002, UDES-004

路径规范、无重复或前缀冲突、保持当前稳定文件顺序且目录树的估算模型成本更低时，`files` model 使用合并单子链的目录树和单份列定义；否则回退到成本更低的扁平表示。每个叶子仍可恢复完整路径和全部直接指标。

## AC-006 非层级合同保持稳定

- 状态: confirmed
- 关联: REQ-002, UDES-004

`hotspots` 继续按复杂度、代码量、字节和路径排名，不为目录聚合改变顺序；summary、languages、machine、lossless、raw、artifact、分页证据单元、cursor 与 snapshot 合同不因 model 表示优化而改变。

## CON-001 本轮不运行独立 Codex 验证

- 状态: confirmed
- 来源: 用户明确说明本轮额度不足，独立 Codex 验证无法启动

本轮不得启动独立 Codex、control/candidate 或 detached evaluator 运行。静态路由合同、确定性测试、真实本地工具、真实 tokenizer、release 和沙箱部署验证继续执行；独立模型行为和端到端 Codex Token 收益保持未验证，不为追求完整状态绕过本约束。

## CON-002 本轮保持当前思考深度

- 状态: confirmed
- 来源: 用户明确要求单 turn 内不改变思考深度

本轮不查询、设置或解除当前线程的 next-turn 推理深度。

## CON-003 Publish 仍需后继单次授权

- 状态: confirmed
- 来源: 项目发布合同；当前请求授权开发但没有明确要求本次 Publish

本轮可构建和沙箱验证 release/installer，完成 Git 提交与私有远端同步；不得向真实 Codex 根目录执行 Publish，也不得把开发授权解释为正式发布授权。
