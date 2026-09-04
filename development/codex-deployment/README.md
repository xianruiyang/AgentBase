# Codex deployment

`manage_agentbase.ps1` is the only AgentBase entry point that installs project-managed files into a Codex home. It validates project truth and the deterministic payload contract, compares the selected managed contract with the installation, stages and backs up only changed managed paths, applies selected present and retired asset states atomically, verifies fingerprints, and records a rollback manifest. Directory payloads and plugin packaging share `development/common/payload_contract.ps1`, so project-only tests, test fixtures, benchmarks, routing research evidence, runtime caches, logs, coverage output, dependency trees, build directories, temporary files, and reparse points cannot enter either bundle or its source fingerprint.

`Deploy` changes one specified Codex installation and records rollback state. It never creates a component version, tag, release package, or external distribution asset; those operations belong to each component's independent `Release` contract.

Portable global payload semantics are owned by [`global/README.md`](../../global/README.md), routing research by [`development/skill-routing/README.md`](../skill-routing/README.md), and plugin assembly by [`development/plugin-packaging/README.md`](../plugin-packaging/README.md). This document owns only host preparation and the Validate, Deploy, Status, migration, and Rollback lifecycle; it does not redefine those upstream payloads.

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
- `global/agents/evidence.toml`, `experiment.toml`, and `operator.toml` -> the matching files under `<CodexRoot>/agents/`.

In `Plugin` mode the same switch adds `config.toml` and the three agents but omits `hooks.json`, because the plugin supplies those hooks.

`managed_asset_lifecycle.json` is the deployment owner's complete cross-version inventory for managed paths and portable config keys. Every unit has a stable identity and an explicit `present`, `retired`, or `transferred` state. Present units must match the current source-derived payload and config-key owners exactly; removing a current source without declaring its lifecycle transition fails validation. A retired path has an absent desired state: `Status` exposes a residual path, while `Deploy` verifies the declared kind and reparse boundary, moves the complete path into the normal rollback backup, and removes it. A retired config key is removable only when its installed assignment still matches the last deployed AgentBase value; a modified or provenance-free key blocks deployment instead of being guessed away, and an intentional ownership handoff is recorded as `transferred`. Transferred and unlisted host assets remain untouched. Schema 9 deployment manifests record the full inventory and config provenance without routing research evidence; schema 8 deployments and schemas 1—7 with legacy `published` state remain read-only compatible for Status and Rollback. Historical retirements remain in the contract while direct upgrade from those releases is supported.

The settings option merges only changed, explicitly reviewed portable keys from `global/config.toml` into an existing `config.toml`, plus any lifecycle-approved retired key removal. MCP tables, project trust, plugin and marketplace state, runtime-generated fields, transferred keys, and unowned keys that share a managed table remain unchanged. Standalone managed files are replaced only when their content differs; skill directories are diffed at managed-file granularity, including removal of stale project-only test or benchmark files, while excluded host-generated runtime artifacts remain untouched. The deployment transaction backs up only changed complete files, rollback restores them, and unrelated personal agents remain untouched. Omitting the option never touches settings or agent files.

The portable config reproduces disabled reasoning summaries, low output verbosity, personality, never-ask approval policy, full-access command sandbox mode, live web search, Standard speed, the multi-agent feature switch, hook, and desktop preferences including disabled prompt suggestions. Main-thread model, default reasoning effort, and the Windows sandbox backend remain host-owned and are preserved during migration. Portable settings do not own a proactive mode, tool hint, nested-delegation policy, or client-side forced spawn. `global/AGENTS.md` owns the user-first default division of work, root review responsibility, and permission to wait without parallel work; `subagent-orchestration` owns fixed-role selection, real-child evidence, waiting, handoff, and the rule that child delegation requires an explicit current-task request. The `[agents]` table owns a six-spawned-thread concurrency cap plus the unclassified subagent model/effort fallback; the cap controls capacity only, not whether delegation occurs. Each semantic custom-agent file independently owns its actual model and reasoning effort. Deployment validates the fixed `evidence`/`experiment`/`operator` file set, schema, filename/name identity, explicit safe model identifier, supported effort, Chinese prose, role distinctness, and sensitive-data boundary without copying the selected model, effort, or role text into the validator. Retired `luna`, `sol`, and `terra` paths remain in the lifecycle inventory so a later authorized portable-settings deployment removes old managed copies without touching unrelated personal agents. The transferred `windows.sandbox` identity preserves its cross-version history while leaving the installed value untouched; evaluation-only elevated initialization remains owned by the explicit evaluator setup entry. The portable key set deliberately excludes authentication, project trust paths, marketplace/plugin caches, MCP absolute paths, the Windows sandbox backend, hook trust hashes, runtime-generated `notify` and `node_repl` entries, histories, logs, and secrets. Exclusion means AgentBase does not own or replace those host values; it does not mean deployment deletes them.

The files under `global/agents/` follow the [official Codex custom-agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents). Codex-provided `default`, `worker`, and `explorer` agents are not duplicated in the repository. They remain owned by the installed Codex release, avoiding custom files that would override built-in agents with the same names.

`approval_policy = "never"` and `sandbox_mode = "danger-full-access"` reproduce the portable command policy. The host or Codex UI separately owns `windows.sandbox`; AgentBase deployment must not select or initialize an elevated backend during application startup. Review the portable values before installing on another machine; workspace or organization policy can still restrict them.

## Prepare a Windows host

PowerShell 7, `fd`, `scc`, `hyperfine`, Python 3, Node.js LTS, ast-grep, a user-level Codex CLI, the independently installed `srcq.exe`, and the independently installed `workctl`/`taskctl` workflow CLI are host prerequisites, not part of the AgentBase payload. Codex on Windows prefers `pwsh.exe` when it is available, but the desktop package does not install it. Its WindowsApps `codex.exe` is also protected by package-identity execute ACLs and is not a valid ordinary child-process entry. AgentBase therefore standardizes on PowerShell 7, requires an `fd` build that supports `--max-results`, an `scc` build that supports `--by-file`, JSON and json2 output, a `hyperfine` build that supports warmup and JSON export, Python 3.11+, Node.js `>=22.9 <27`, ast-grep 0.44.1 and user npm `@openai/codex@0.151.0` with the isolated `exec` flags used by routing evaluation。`srcq` 必须从 `tools/srcq` 的受验证 Windows release 通过 `scripts/install-srcq.ps1` 安装到用户 PATH；workflow-cli 必须从 `tools/workflow-cli` 的受验证 Windows package 通过 `scripts/install-workflow-cli.ps1` 安装到用户 PATH；skill、插件和 Codex 部署不会复制或回退到私有二进制。

When the user asks Codex to prepare, reproduce, or deploy AgentBase on a new Windows machine, that request authorizes installation of these prerequisites through the project entry point. Run it before Validate or Deploy:

```powershell
& '.\development\codex-deployment\bootstrap_windows.ps1' -Action Install
```

The script is idempotent. It uses the exact winget package IDs `Microsoft.PowerShell`, `sharkdp.fd`, `BenBoyter.scc`, `sharkdp.hyperfine`, `Python.Python.3.13`, and `OpenJS.NodeJS.LTS`, then uses that Node installation to install the exact npm packages `@ast-grep/cli@0.44.1` and `@openai/codex@0.151.0`. For Codex it reads the native npm binary directly, verifies the required `exec` isolation and schema flags, and places the user npm prefix before WindowsApps in the persisted User PATH. [`development/common/codex_cli_runtime.ps1`](../common/codex_cli_runtime.ps1) is the shared owner for the native npm executable layouts consumed by both bootstrap readback and the routing runner; it covers nested optional-package, hoisted optional-package and package-vendor fallback layouts while excluding WindowsApps and reparse points. The routing runner resolves the resulting absolute native path and never trusts ambiguous command-name resolution. The bootstrap changes only missing or unsupported prerequisites and reads back every resolved executable, version and required capability. Use `-Action Check` for a read-only audit. Direct output defaults to the model view: success is `{ready:true}`, while failure lists only unsupported tools and the recovery action. Add `-View Machine` when automation needs the complete tool, package, path, version and capability JSON. If any PATH-providing prerequisite was installed or reordered, fully exit and restart the Codex desktop host before continuing so the new process inherits the persisted PATH. Starting another task inside the same host does not prove that PATH was refreshed.

Before deploying a payload that contains `source-query`, run the independent runtime owner's status entry and require `ready=true`, then run both the AST and scc doctors. The status command verifies the installed manifest, managed file hashes, binary version and unique PATH entry; `manage_agentbase.ps1` does not copy or repair that external runtime or the scc engine:

```powershell
& '.\tools\srcq\scripts\install-srcq.ps1' Status
srcq doctor
srcq query scc doctor
```

`workctl` and `taskctl` are installed separately from the workflow-cli package. Use its entry point for `Install`, `Upgrade`, and read-only `Status`; it verifies the package manifest, both command versions, and the single installer-managed user PATH entry. This host installation is distinct from Codex `Deploy` and component `Release`:

```powershell
& '.\tools\workflow-cli\scripts\build-workflow-cli.ps1'
& '.\tools\workflow-cli\scripts\install-workflow-cli.ps1' -Action Install -Archive '.\tools\workflow-cli\dist\workflow-cli-0.1.0.zip'
& '.\tools\workflow-cli\scripts\install-workflow-cli.ps1' -Action Status -View Machine
```

The installer also defaults to a compact model receipt. Ready `Status` retains only `ready`, `version` and the exact `binary`; failures retain the reason, direct diagnosis and recovery. Install and upgrade add the binary only when a PATH change requires an immediate explicit doctor call. Use `-View Machine` for the stable complete JSON consumed by deployment validation and other programs.

When `Install` added PATH in the current task, use the exact `binary` returned by `Status` for the immediate doctor readback, then fully exit and restart the Codex desktop host before relying on command-name resolution. A new task in the existing host is not a substitute for that process restart.

## Result surfaces

The host bootstrap and srcq installer compute one canonical result and default to a compact model projection; `-View Machine` serializes that same result as complete JSON. `manage_agentbase.ps1` returns one complete PowerShell object for programmatic consumers. Its direct console rendering is likewise a model-facing view of that same object: it omits hashes, repeated scope, empty collections and successful default checks, while retaining the outcome, actionable exceptions and rollback locations. None of these views creates a second status calculation.

Typical direct output is intentionally small:

```text
valid : true
```

```text
deployed : false
gaps      : deployment_manifest_missing,installed_payload_differs_from_source
```

Deploy and Rollback additionally show the exact backup or retired-payload path needed for recovery. Plugin installation and an unavailable `srcq` runtime appear only when they require a separate action.

Assign the result when a program or a later model step needs the machine contract, then select the exact field or serialize the complete object explicitly:

```powershell
$result = & '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex')
$result.formal_deployment_gaps
$result | ConvertTo-Json -Depth 10
```

## Validate

Formal Validate checks the selected delivery mode's complete source candidate: the actual deployment payload, structural global-rule/Skill contract, managed-asset lifecycle, and the portable settings, hooks or custom-agent sources that mode can consume. Status and Deploy validate only assets selected by their delivery mode and `-InstallPortableSettings`; an invalid unselected source cannot block or alter that operation. Plugin mode does not consume the global hooks template because plugin hooks are owned by the built package. Validate does not read or require routing research evidence, and does not run routing-infrastructure, Windows SWE evaluator or other development-component test suites. Run each component's deterministic tests once, after the candidate is stable, only when that component is affected; unrelated component failures cannot block a payload-only deployment. When actual model routing behavior needs investigation, use the explicit research entry documented under `development/skill-routing` rather than attaching it to deployment:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

Validate and Deploy deliberately do not run the Windows SWE corpus, qualification, Verifier or candidate model. Inspecting host/task prerequisites remains a separate read-only action:

```powershell
python.exe -X utf8 .\development\agent-evaluation\agent_eval.py check --suite all
```

`check` reports missing base/task tools, including pnpm only when the selected suite needs it. It does not install software, prepare external sources, run a Verifier or call a model. The final evaluator no longer owns a Windows sandbox setup/status/permission-probe lifecycle; candidate and Verifier runs are explicit component operations documented in `development/agent-evaluation/README.md`.

`run` accepts `--installed-codex-root`; it defaults to `CODEX_HOME` or `%USERPROFILE%\.codex` and uses that root only for existing authentication and session usage accounting. Candidate configuration and agents are projected from repository truth; credentials are not copied or linked. `recover` consumes the recorded candidate result and runs only the independent Verifier, so it neither needs the installation root nor calls a model.

The repeatable tests cover lifecycle identity continuity, explicit retirement, safe config-key provenance and removal, default preservation, explicit settings and custom-agent installation, resolved hook paths, unrelated Skill and agent preservation, seeded retired-path detection/removal/restoration, wrong-kind refusal, cross-scope provenance, and rollback:

```powershell
& '.\development\codex-deployment\test_portable_config.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_portable_agents.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_managed_asset_lifecycle.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_manage_agentbase.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_bootstrap_windows.ps1'
```

A successful direct test invocation renders only `tests : pass`. Assign its returned object before serialization when automation needs the individual check fields.

## Deploy on another Windows machine

Every invocation that deploys to a real Codex root requires the user's explicit approval for that deployment. Git maintenance, an earlier deployment approval, successful validation, or a read-only status result does not carry that approval forward.

Install and sign in to Codex first. Then clone or copy the repository, run the Windows host preparation above, review `global/config.toml`, and choose one delivery mode. Routing research evidence is not a deployment prerequisite.

For the recommended plugin route, build the package with the official validator, install `agentbase-core` from the repo-scoped `agentbase-local` marketplace, and deploy only the project-managed global payload:

```powershell
& '.\development\plugin-packaging\build_plugin.ps1' -ProjectRoot (Get-Location).Path
codex plugin add agentbase-core@agentbase-local
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Deploy -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode Plugin -InstallPortableSettings
```

For an existing direct installation that has not completed plugin migration:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Deploy -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

The configured service tier and plugin availability still depend on the signed-in account and any workspace or organization policy. The main-thread model and default reasoning effort come from the target host rather than this payload. Review or adjust those settings when the target account does not provide the same capabilities.

Deploy and `Status` prove only that the selected files are installed; they do not prove that an already-open task has rebuilt its runtime instruction, tool, MCP, or custom-agent surface. After deploying any `global/agents/*.toml` addition, removal, rename, model, effort, description, or instruction change, do not use an existing task to decide whether it took effect. Begin a new Codex task and inspect the custom roles exposed by the subagent creation interface; for a newly added or materially changed role, one bounded real invocation is the runtime verification. If a new task in the already-running desktop host still exposes the old role set, fully exit and restart the desktop host, then create another new task. Absence only in a pre-deployment task is expected stale runtime state; absence after that fresh-host check is a deployment or runtime-discovery failure and must not be dismissed as successful deployment.

MCP launcher or configuration changes require a full desktop-host restart before opening the verification task; merely starting another task in the same host is not sufficient evidence that the MCP process or tool schema was refreshed. In plugin mode, also verify the plugin is installed and enabled; in either mode open `/hooks`, review the exact commands, and trust them on the new machine. Hook trust hashes are machine state and are intentionally not copied. QQ completion remains off until it is enabled for a specific workspace or task through `codex-qq-hook`.

## Read deployment status

`Status` is read-only. It derives state from the selected source payload, installed managed contract, latest matching deployment manifest, and latest schema 7+ lifecycle receipt across deployment scopes instead of trusting a README claim. For `config.toml`, only AgentBase-owned portable keys and declared retirements participate in deployment identity; host-owned MCP, trust, plugin, marketplace, runtime, and routing research changes do not create false managed drift. Rollback still fingerprints the complete installed file and refuses to overwrite post-deployment host changes unless drift is explicitly accepted:

For a real (non-sandbox) Codex root, `Status` also reports the independently installed workflow-cli preflight (`workflow_cli_runtime_ready`, version, install root/current directory, User PATH entry count, and individual `workctl`/`taskctl` checks). `Deploy` requires this preflight and the existing `srcq` preflight before writing any Codex payload. Deployment test sandboxes intentionally set both runtime checks out of scope, so tests do not depend on host installations.

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

Use the same delivery mode and settings scope that were deployed. `managed_payload_formally_deployed=true` covers only files managed by this script and also requires the matching manifest to carry the current lifecycle hash, every retired path to be absent, and every retired config key to be absent. Otherwise `formal_deployment_gaps` identifies source/install/manifest/lifecycle drift or residual retired assets; config conflicts distinguish modified from provenance-free keys. In `Plugin` mode, `plugin_mode_ready=false` and `direct_compatibility_conflicts` identify current direct skills or global AgentBase hooks that must be removed before migration. `plugin_installation_inspected=false` is intentional: inspect plugin state through the plugin browser or `codex plugin list`.

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

Use the exact backup path returned by Deploy:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -BackupPath '<exact-backup-path>'
```

Rollback derives its targets from the deployment manifest. If portable settings were installed, the prior complete `config.toml`, `hooks.json`, and matching custom-agent files are restored in the same transaction as the prior AGENTS and Skill files; this also recovers a lifecycle-approved config-key removal. Newly introduced managed agents are removed, and unrelated agents remain untouched. A retired path removed by that deployment is restored from the same backup, after which `Status` again exposes the retirement gap until a later approved Deploy removes it.
