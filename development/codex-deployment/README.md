# Codex deployment

`manage_agentbase.ps1` is the only AgentBase entry point that installs project-managed files into a Codex home. It validates project truth and the canonical detached routing-policy evidence, compares the selected managed contract with the installation, stages and backs up only changed managed paths, applies them atomically, verifies fingerprints, and records a rollback manifest. Directory payloads and plugin packaging share `development/common/payload_contract.ps1`, so runtime-only caches, logs, coverage output, dependency trees, build directories, temporary files, and reparse points cannot enter either bundle or its fingerprint.

## Payloads

`-SkillDeliveryMode DirectCompatibility` is the default only to preserve existing installations. Its payload is:

- `global/AGENTS.md` -> `<CodexRoot>/AGENTS.md`;
- the required `skills/<name>/` directories -> `<CodexRoot>/skills/<name>/`.

This is a declared migration path for hosts that already use `<CodexRoot>/skills`. Do not enable the `agentbase-core` plugin at the same time. Exit this mode after plugin installation, enable/disable behavior, bundled-hook trust, and uninstall/rollback have been verified on the target host.

`-SkillDeliveryMode Plugin` manages:

- `global/AGENTS.md` -> `<CodexRoot>/AGENTS.md`;
- when selected, portable `config.toml` and the three custom agents.

It deliberately omits direct skill directories and `hooks.json`; `agentbase-core` owns the skills and bundled hooks through `${PLUGIN_ROOT}`. Before writing, Plugin mode rejects any required skill still present under `<CodexRoot>/skills` and any AgentBase command still present in global `hooks.json`, so migration cannot silently retain parallel entries. The deployment script does not install, enable, or inspect the plugin, so plugin state remains a separate verified prerequisite rather than an implied part of the deployment receipt.

In `DirectCompatibility` mode, `-InstallPortableSettings` explicitly adds:

- `global/config.toml` -> `<CodexRoot>/config.toml`;
- `global/hooks.template.json`, resolved against the selected Codex root -> `<CodexRoot>/hooks.json`.
- `global/agents/luna.toml`, `sol.toml`, and `terra.toml` -> the matching files under `<CodexRoot>/agents/`.

In `Plugin` mode the same switch adds `config.toml` and the three agents but omits `hooks.json`, because the plugin supplies those hooks.

The settings option merges only changed, explicitly reviewed portable keys from `global/config.toml` into an existing `config.toml`. MCP tables, project trust, plugin and marketplace state, runtime-generated fields, and unowned keys that share a managed table remain unchanged. Standalone managed files are replaced only when their content differs; skill directories are diffed at managed-file granularity, including removal of stale managed files while excluded runtime artifacts remain untouched. The publish transaction backs up only changed complete files, rollback restores them, and unrelated personal agents remain untouched. Omitting the option never touches settings or agent files.

The portable config reproduces the reviewed model, balanced main-thread reasoning default, personality, service tier, sandbox, multi-agent, hook, and desktop preferences. The portable agents reproduce the current `luna`, `sol`, and `terra` role descriptions, models, and developer instructions; subagent reasoning effort is intentionally unpinned so model defaults or explicit dispatch settings can choose it. The portable key set deliberately excludes authentication, project trust paths, marketplace/plugin caches, MCP absolute paths, hook trust hashes, runtime-generated `notify` and `node_repl` entries, histories, logs, and secrets. Exclusion means AgentBase does not own or replace those host values; it does not mean deployment deletes them.

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

Validation checks the global rule and Skill contract, the separately isolated description-only routing, post-routing behavior-policy and post-selection reference capsules, their evaluator identities, clean-input attestations and capsule/candidate/input hashes in `development/skill-routing/evidence/current.json`, the portable config allowlist, the exact custom-agent file/schema contract, the hooks schema and placeholder boundary, and the independent `vscode-lsp-mcp` release owner. The attestation is an auditable input contract, not an OS sandbox claim. Staged evidence proves routing, coarse policy labels and reference selection only; it does not replace the skill regression or component release gates:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

The repeatable sandbox test covers default preservation, explicit settings and custom-agent installation, resolved hook paths, unrelated Skill and agent preservation, and rollback:

```powershell
& '.\development\codex-deployment\test_portable_config.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_manage_agentbase.ps1' -ProjectRoot (Get-Location).Path
```

## Publish on another Windows machine

Every invocation that publishes to a real Codex root requires the user's explicit approval for that publication. Git maintenance, an earlier publication approval, successful validation, or a read-only status result does not carry that approval forward.

Install and sign in to Codex first. Then clone or copy the repository, run the Windows host preparation above, review `global/config.toml`, generate a detached routing capsule and refresh current evidence with an evaluator that can read only that capsule, and choose one delivery mode.

For the recommended plugin route, build the package with the official validator, install `agentbase-core` from the repo-scoped `agentbase-local` marketplace, and publish only the project-managed global payload:

```powershell
& '.\development\plugin-packaging\build_plugin.ps1' -ProjectRoot (Get-Location).Path
codex plugin add agentbase-core@agentbase-local
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode Plugin -InstallPortableSettings
```

For an existing direct installation that has not completed plugin migration:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

The configured model, service tier, and plugin availability still depend on the signed-in account and any workspace or organization policy. Review or adjust those entries when the target account does not provide the same capabilities.

Restart the ChatGPT desktop app or begin a new Codex task after publishing. In plugin mode, verify the plugin is installed and enabled; in either mode open `/hooks`, review the exact commands, and trust them on the new machine. Hook trust hashes are machine state and are intentionally not copied. QQ completion remains off until it is enabled for a specific workspace or task through `codex-qq-hook`.

## Read publication status

`Status` is read-only. It derives state from the selected source payload, installed managed contract, latest matching `published` manifest, and current routing-policy evidence instead of trusting a README claim. For `config.toml`, only AgentBase-owned portable keys participate in publication identity; host-owned MCP, trust, plugin, marketplace, and runtime changes do not create false managed drift. Rollback still fingerprints the complete installed file and refuses to overwrite post-publish host changes unless drift is explicitly accepted:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

Use the same delivery mode and settings scope that were published. `managed_payload_formally_published=true` covers only files managed by this script; otherwise `formal_publication_gaps` identifies source/install/manifest/evidence drift. In `Plugin` mode, `plugin_mode_ready=false` and `direct_compatibility_conflicts` identify old direct skills or global AgentBase hooks that must be removed before migration. `plugin_installation_inspected=false` is intentional: inspect plugin state through the plugin browser or `codex plugin list`.

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
