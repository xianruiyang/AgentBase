# Codex deployment

`manage_agentbase.ps1` is the only AgentBase entry point that installs files into a Codex home. It validates project truth, stages the complete selected payload, backs up every target, installs atomically, verifies fingerprints, and records a rollback manifest.

## Payloads

The default payload remains:

- `global/AGENTS.md` -> `<CodexRoot>/AGENTS.md`;
- the required `skills/<name>/` directories -> `<CodexRoot>/skills/<name>/`.

`-InstallPortableSettings` explicitly adds:

- `global/config.toml` -> `<CodexRoot>/config.toml`;
- `global/hooks.template.json`, resolved against the selected Codex root -> `<CodexRoot>/hooks.json`.

The settings option replaces an existing `config.toml` and `hooks.json`, but the same publish transaction backs them up and the normal rollback action restores them. Omitting the option preserves the existing default behavior and never touches those files.

The portable config reproduces the reviewed model, reasoning, personality, service tier, sandbox, multi-agent, hook, and desktop preferences. It deliberately excludes authentication, project trust paths, marketplace/plugin caches, MCP absolute paths, hook trust hashes, runtime-generated `notify` and `node_repl` entries, histories, logs, and secrets.

`sandbox_mode = "danger-full-access"` and the elevated Windows sandbox reproduce the current local workflow. Review these values before installing on another machine; workspace or organization policy can still restrict them.

## Validate

Validation checks the global rule and Skill contract, the portable config allowlist, the hooks schema and placeholder boundary, and the independent `vscode-lsp-mcp` release owner:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

The repeatable sandbox test covers default preservation, explicit settings installation, resolved hook paths, unrelated Skill preservation, and rollback:

```powershell
& '.\development\codex-deployment\test_manage_agentbase.ps1' -ProjectRoot (Get-Location).Path
```

## Publish on another Windows machine

Install and sign in to Codex first. Then clone or copy the repository, review `global/config.toml`, and run from the project root:

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

Rollback derives its targets from the publish manifest. If portable settings were installed, the prior `config.toml` and `hooks.json` are restored in the same transaction as the prior AGENTS and Skill files.
