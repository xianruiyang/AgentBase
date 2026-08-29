# Verifier bootstrap assets

本目录只保存 AgentBase Windows SWE 在创建隔离 Python venv 后、访问 SOCKS 代理前必须离线安装的固定 bootstrap 资产，不进入 Codex 发布 payload，也不是题目依赖真源。

`PySocks-1.7.1-py3-none-any.whl` 来自 PyPI 的 PySocks 1.7.1 发布，采用 BSD 许可证；wheel 内包含原始 `LICENSE`。文件 SHA-256 为 `2725bd0a9925919b9b51739eea5f9e2bae91e83288108a9ad338b2e3a4435ee5`。`windows_verifier.py` 在每次 Python dependency setup 前验证该哈希并通过 `pip --no-index` 安装，随后题目自己的固定 setup 才能使用 Codex `.env` 投影的 SOCKS transport。
