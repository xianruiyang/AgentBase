# Codex deployment

`manage_agentbase.ps1` is the only AgentBase entry point that installs files into a Codex home. It validates project truth, stages the complete selected payload, backs up every target, installs atomically, verifies fingerprints, and records a rollback manifest. Directory payloads exclude runtime-only caches, logs, coverage output, dependency trees, build directories, and temporary files from both copying and fingerprinting, so local execution cannot change the deployable bundle.

## Payloads

The default payload remains:

- `global/AGENTS.md` -> `<CodexRoot>/AGENTS.md`;
- the required `skills/<name>/` directories -> `<CodexRoot>/skills/<name>/`.

`-InstallPortableSettings` explicitly adds:

- `global/config.toml` -> `<CodexRoot>/config.toml`;
- `global/hooks.template.json`, resolved against the selected Codex root -> `<CodexRoot>/hooks.json`.
- `global/agents/luna.toml`, `sol.toml`, and `terra.toml` -> the matching files under `<CodexRoot>/agents/`.

The settings option replaces an existing `config.toml`, `hooks.json`, and the three matching custom-agent files, but the same publish transaction backs them up and the normal rollback action restores them. It does not replace the whole `agents/` directory, so unrelated personal agents remain untouched. Omitting the option preserves the existing default behavior and never touches any settings or agent file.

The portable config reproduces the reviewed model, balanced main-thread reasoning default, personality, service tier, sandbox, multi-agent, hook, and desktop preferences. The portable agents reproduce the current `luna`, `sol`, and `terra` role descriptions, models, and developer instructions; subagent reasoning effort is intentionally unpinned so model defaults or explicit dispatch settings can choose it. The payload deliberately excludes authentication, project trust paths, marketplace/plugin caches, MCP absolute paths, hook trust hashes, runtime-generated `notify` and `node_repl` entries, histories, logs, and secrets.

The files under `global/agents/` follow the [official Codex custom-agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents). Codex-provided `default`, `worker`, and `explorer` agents are not duplicated in the repository. They remain owned by the installed Codex release, avoiding custom files that would override built-in agents with the same names.

`sandbox_mode = "danger-full-access"` and the elevated Windows sandbox reproduce the current local workflow. Review these values before installing on another machine; workspace or organization policy can still restrict them.

## Prepare a Windows host

PowerShell 7, `fd`, Python 3, Node.js LTS, and ast-grep are host prerequisites, not part of the AgentBase payload. Codex on Windows prefers `pwsh.exe` when it is available, but the Codex package does not install it; a clean Windows host can otherwise run commands through the older system shell. AgentBase therefore standardizes on PowerShell 7, requires an `fd` build that supports `--max-results`, Python 3.11+, Node.js `>=22.9 <27`, and the precisely verified ast-grep 0.44.1 runtime used by the bundled `sgy` workflow.

When the user asks Codex to prepare, reproduce, or deploy AgentBase on a new Windows machine, that request authorizes installation of these prerequisites through the project entry point. Run it before Validate or Publish:

```powershell
& '.\development\codex-deployment\bootstrap_windows.ps1' -Action Install
```

The script is idempotent. It uses the exact winget package IDs `Microsoft.PowerShell`, `sharkdp.fd`, `Python.Python.3.13`, and `OpenJS.NodeJS.LTS`, then uses that Node installation to install the exact npm package `@ast-grep/cli@0.44.1`. It changes only missing or unsupported prerequisites and reads back every resolved executable and version plus `fd --max-results` support. Use `-Action Check` for a read-only audit. If PowerShell or another PATH-providing prerequisite was installed, restart the ChatGPT desktop app or begin a new Codex task before continuing so the agent host sees the new commands.

## Validate

Validation checks the global rule and Skill contract, the portable config allowlist, the exact custom-agent file/schema contract, the hooks schema and placeholder boundary, and the independent `vscode-lsp-mcp` release owner:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

The repeatable sandbox test covers default preservation, explicit settings and custom-agent installation, resolved hook paths, unrelated Skill and agent preservation, and rollback:

```powershell
& '.\development\codex-deployment\test_manage_agentbase.ps1' -ProjectRoot (Get-Location).Path
```

## Publish on another Windows machine

Install and sign in to Codex first. Then clone or copy the repository, run the Windows host preparation above, review `global/config.toml`, and run from the project root:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -InstallPortableSettings
```

The configured model, service tier, and plugin availability still depend on the signed-in account and any workspace or organization policy. Review or adjust those entries when the target account does not provide the same capabilities.

Restart the ChatGPT desktop app or begin a new Codex task after publishing. Open `/hooks`, review the exact commands, and trust them on the new machine; hook trust hashes are machine state and are intentionally not copied. QQ completion remains off until it is enabled for a specific workspace or task through `codex-qq-hook`.

The current workflow also uses these separately installed plugins when their capabilities are needed:

- `github@openai-curated`;
- `documents@openai-primary-runtime`;
- `pdf@openai-primary-runtime`;
- `spreadsheets@openai-primary-runtime`;
- `presentations@openai-primary-runtime`;
- `template-creator@openai-primary-runtime`.

Plugin installation, accounts, and connector authentication are host-managed state and are not reproduced by copying `config.toml`.

`vscode-lsp-mcp` also keeps its own release lifecycle. Build and install it through `mcp/vscode-lsp-mcp/docs/installation.md`, register its managed launcher as described in `mcp/vscode-lsp-mcp/docs/configuration.md`, and restart Codex. Unrelated or optional current MCP entries such as Blender, disabled Notion/Figma endpoints, and app-managed `node_repl` are not part of the AgentBase portable payload.

## Roll back

Use the exact backup path returned by Publish:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -BackupPath '<exact-backup-path>'
```

Rollback derives its targets from the publish manifest. If portable settings were installed, the prior `config.toml`, `hooks.json`, and matching custom-agent files are restored in the same transaction as the prior AGENTS and Skill files; newly introduced managed agents are removed, and unrelated agents remain untouched.
