# PLAN 11.1 单元验证门禁

本目录保存跨 package 的单元覆盖门禁，不复制各 workspace 已有测试实现。

- `plan-11-1-coverage.test.mjs` 将 PLAN 11.1 的 17 类边界绑定到直接行为测试的稳定名称；删除、改名或遗漏证据会使 `npm test` 失败。
- 同一门禁从构建后的 protocol public entry 编译 19 个 inputSchema 与 19 个 outputSchema，并核对冻结的 19-tool registry。
- 行为测试仍位于 `packages/*/src/*.test.ts`，由 workspace runner 先构建并执行；本目录只负责跨包覆盖完整性和公共契约总数。

运行入口：

```powershell
npm test
npm run verify
```
