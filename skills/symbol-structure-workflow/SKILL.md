---
name: symbol-structure-workflow
description: 安全组织由 VS Code Provider 执行的语义修改和编辑器操作。用于已授权的语义重命名、Code Action、格式化、workspace task/command、调试控制或窗口/Extension Host 重载；不用于只读文本、文件、AST、定义、类型、引用、层级或诊断查询，后者由 source-query 承担。
---

# Symbol Structure Workflow

仅在用户已授权相应外部影响时进入。修改前用 `$source-query` 或已有证据确认目标身份、源码范围和当前版本，不重复充分查询。

完整读取 [editor-operations.md](references/editor-operations.md)，只发现当前操作所需的预览或执行能力。rename、Code Action 和格式化遵循 `preview → 审查完整身份与范围 → 单次 apply → 读回实际状态 → 定向验证`；预览截断、文档变化、执行状态未知或授权不足时停止。仅在目标需要时使用 task、command、debug 或重载；不把编辑器能力当作源码查询或构建成功证据。
