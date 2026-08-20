# srcq benchmark

该 harness 使用同一批真实 ast-grep 结果比较 compact JSON、lossless YAML 和默认 Token-Safe YAML，并测量：

- UTF-8 bytes；
- `cl100k_base`、`o200k_base` 和固定 revision 的 Qwen2.5-Coder tokenizer；
- 真实 ast-grep 时间、srcq 端到端时间和两者中位数差值；
- 子进程树峰值 RSS；
- 六项确定性信息充分性任务；
- process count/sort 的单 run、多 run、峰值 RSS 与临时磁盘。

信息充分性任务是可复现的 Agent 上下文代理，不是线上 LLM 主观评测。报告必须保留这个边界。

## 环境

```powershell
python -m pip install -r benches/requirements.txt
cargo build --release
python benches/benchmark.py `
  --engine C:\path\to\ast-grep.exe `
  --srcq target\release\srcq.exe `
  --output D:\benchmark-output
```

默认执行 2 次 warmup、7 次记录样本。`--samples` 和 `--warmups` 可调整，但正式结果必须记录实际参数。输出目录包含 `benchmark-results.json`、三种格式的 canonical sample 和 process 输入/输出校验摘要。

默认基线的单变量敏感性分析：

```powershell
python benches/budget_sweep.py `
  --engine C:\path\to\ast-grep.exe `
  --srcq target\release\srcq.exe `
  --output D:\benchmark-output
```

该命令在 8 与 800 findings 的 run/scan/rewrite 上分别比较 20/40/80 条、200/400/800 字符和 12/24/48 KiB；cache 固定为 off，只为消除随机 cache id 对 token 计数的干扰。

结果完整性检查：

```powershell
python benches/validate_results.py D:\benchmark-output\benchmark-results.json D:\benchmark-output\budget-sweep.json
```

## scc 模型投影

`scc_projection_benchmark.py` 在同一源码快照上比较完整 json2 与完整 srcq 任务投影，并用真实 `cl100k_base`、`o200k_base` tokenizer 计数。可选 `--baseline-srcq` 会用同一 scc、cwd、参数和快照测量旧 srcq 的完整 files 投影，并以二进制 SHA-256 绑定双方身份。它同时拒绝未闭合分页和成本估算泄漏；结果只证明静态输出面的直接指标压缩，不证明端到端模型行为：

```powershell
python benches/scc_projection_benchmark.py `
  --srcq target\release\srcq.exe `
  --baseline-srcq C:\path\to\previous\srcq.exe `
  --scc C:\path\to\scc.exe `
  --root D:\path\to\project `
  --output target\scc-projection-benchmark.json
```

启动耗时或多命令分布不由该脚本复制实现；固定工作目录、输入、预热和命令版本后直接使用 AgentBase 主机前置中的 `hyperfine`，需要程序消费时由 hyperfine 写 JSON artifact。

Qwen tokenizer 固定为 `Qwen/Qwen2.5-Coder-7B-Instruct@c03e6d358207e414f1eca0bb1891e29f1db0e242`。首次运行需要下载 tokenizer 文件；之后可从 Hugging Face cache 离线复用。
