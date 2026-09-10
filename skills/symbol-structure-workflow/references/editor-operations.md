# 编辑器操作与 Apply 生命周期

## Code Action、格式化与 Rename

- 仅在诊断驱动或用户要求 Provider 修复时请求并预览选中的 Code Action；仅在用户要求或验收需要时预览格式化。
- Code Action、格式化和 rename 均先确认文件、范围、edit 数量和完整性，再单次 apply。
- `DOCUMENT_CHANGED` 或 preview 失效时重读源码并重新预览，不复用旧 edit。

## Task 与命令

- 构建、测试和 lint 使用 `target.kind: task` 与 `taskName`；重名时加 `taskRoot`，不调用会弹 QuickPick 的 `workbench.action.tasks.*`。
- task 拒绝 input/command 变量、background、CustomExecution 和不可验证完成；失败后按状态与退出码处理，不用终端注入绕过。
- task 默认只在失败时保留 `outputLog`；确需检查成功输出时才设置 `retainOutputLog: true`。
- 日志正文不进入 MCP 响应；先用路径、行数和字节数定界，再受限搜索必要片段。缺少日志不等于没有终端输出。
- 自定义 command 需要精确策略条目；无参数保存、调试控制、窗口/Extension Host 重载和已声明前台 task 仍以当前可信工作区策略为准。

## 调试控制

- 仅在任务需要时调用 debug start/run、continue、step、pause、restart 或 stop；不调用 `debug.selectandstart`，不替用户选择交互式配置。
- 调试或 task 状态未知时先读回，不重复启动相同操作。

## 重载生命周期

- `reloadWindow` / `restartExtensionHost` 成功只表示已接受并延迟调度，Bridge 预期会断开。
- 等待明确恢复后重新 `list_workspaces`，不复用旧 `workspaceId`，也不重复重载。
- 退出 VS Code、扩展安装/卸载、认证、输入/确认 UI、禁用 companion 或主动断开 Bridge 不得自动执行。

## 验收

1. apply 后检查目标文件、edit 落点和无关差异。
2. 读取必要诊断，但不把诊断清零当作编译或运行时成功。
3. 按受影响契约运行 formatter、lint/typecheck、构建或定向测试。
4. 报告 Provider 接受状态、实际文件状态、验证结果和未覆盖边界。
