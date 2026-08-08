# Extension Host integration fixtures

- `extension-host-read-hierarchy`：Stage B 的真实 TypeScript 只读、隐藏文档和 dirty 文档矩阵；`large.ts` 与 `symbols.ts` 由 runner 确定性生成，避免维护 280 行重复夹具。
- `extension-host-hierarchy-lifecycle`：Stage C 的 type hierarchy supported、empty、timeout、cancel 与 Host 重启矩阵。
- `extension-host-mutation-command`：P6-003 的 rename/Code Action/format、dirty/save-mode、真实 process task、非零/超时和交互变量拒绝矩阵。
- `extension-host-all-tools`：P6-004 的冻结 18 工具、双 workspace 路由、写操作隔离、重启/死端点恢复和 stdio 帧矩阵；140 行 references 文件由 runner 生成。
- `extension-host-multilanguage`：P6-005 的 C++ 与 C# definition/reference/diagnostic/rename 实际 Provider 夹具；runner 只链接主机现有扩展并在临时副本中运行。

Runner 会先复制夹具到独立临时工作区，测试不会修改仓库内文件。
