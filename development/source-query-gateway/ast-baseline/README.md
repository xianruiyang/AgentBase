# sgy AST 非回退基线

本目录冻结 `sgy 0.1.2` 在统一源码查询网关实施前的公开 AST 合同。基线源码身份为 `sha256:ca18b3ba31582ed789eb3efb9f915d68aaf5e8b2838582cd487c8ff56d614e4f`，与当前签署的 skill runtime release record 一致。

`help/schema/capabilities` 文件按文本语义比较并忽略 CRLF/LF 差异；其他 AST 行为由 `tools/sgy` 现有 workspace 测试和真实 0.41.1/0.42.0/0.44.1 矩阵承担。后续实现不得为了 rg/fd 对称而更新这些基线；只有独立确认的 AST 契约变更才建立新基线并说明迁移。

定向比较当前构建：

```powershell
python.exe -X utf8 .\compare_ast_baseline.py --sgy D:\path\to\sgy.exe
```

这份基线是项目测试资产，不进入 Codex payload。
