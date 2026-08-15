---
name: symbol-structure-workflow
description: 安全组织由 VS Code Provider 执行的语义代码修改与编辑器操作。用于用户已授权并需要语义重命名、Code Action、格式化应用、工作区 task/command、调试控制或窗口/Extension Host 重载时；不用于只读文本、文件、AST、定义、类型、引用、层级或诊断查询，这些由 source-query 承担。
---

# Symbol Structure Workflow

只有用户已授权相应外部影响时才进入本 skill。修改前先用 `$source-query` 或已有证据确认目标身份、源码范围和当前版本，但不例行重复已充分的查询。

完整读取 [editor-operations.md](references/editor-operations.md)，按当前操作只发现所需的预览或执行能力。rename、Code Action 和格式化遵循 `preview → 审查完整身份与范围 → 单次 apply → 读回实际状态 → 定向验证`；预览截断、文档变化、执行状态未知或授权不足时停止。task、command、debug 与重载只在用户目标确实需要时使用，不把编辑器能力当作源码查询或构建成功证据。
