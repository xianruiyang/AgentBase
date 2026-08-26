# Codex deployment

`manage_agentbase.ps1` is the only AgentBase entry point that installs project-managed files into a Codex home. It validates project truth and the canonical detached routing-policy evidence, compares the selected managed contract with the installation, stages and backs up only changed managed paths, applies selected present and retired asset states atomically, verifies fingerprints, and records a rollback manifest. Directory payloads and plugin packaging share `development/common/payload_contract.ps1`, so project-only tests, test fixtures, benchmarks, runtime caches, logs, coverage output, dependency trees, build directories, temporary files, and reparse points cannot enter either bundle or its source fingerprint.

Portable global payload semantics are owned by [`global/README.md`](../../global/README.md), routing evidence by [`development/skill-routing/README.md`](../skill-routing/README.md), and plugin assembly by [`development/plugin-packaging/README.md`](../plugin-packaging/README.md). This document owns only host preparation and the Validate, Publish, Status, migration, and Rollback lifecycle; it does not redefine those upstream payloads.

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

`managed_asset_lifecycle.json` is the deployment owner's complete cross-version inventory for managed paths and portable config keys. Every unit has a stable identity and an explicit `present`, `retired`, or `transferred` state. Present units must match the current source-derived payload and config-key owners exactly; removing a current source without declaring its lifecycle transition fails validation. A retired path has an absent desired state: `Status` exposes a residual path, while `Publish` verifies the declared kind and reparse boundary, moves the complete path into the normal rollback backup, and removes it. A retired config key is removable only when its installed assignment still matches the last published AgentBase value; a modified or provenance-free key blocks publication instead of being guessed away, and an intentional ownership handoff is recorded as `transferred`. Transferred and unlisted host assets remain untouched. Schema 7 manifests record the full inventory and carry config provenance across delivery modes and settings scopes, so a later transition cannot silently lose a previously published identity. Historical retirements remain in the contract while direct upgrade from those releases is supported.

The settings option merges only changed, explicitly reviewed portable keys from `global/config.toml` into an existing `config.toml`, plus any lifecycle-approved retired key removal. MCP tables, project trust, plugin and marketplace state, runtime-generated fields, transferred keys, and unowned keys that share a managed table remain unchanged. Standalone managed files are replaced only when their content differs; skill directories are diffed at managed-file granularity, including removal of stale project-only test or benchmark files, while excluded host-generated runtime artifacts remain untouched. The publish transaction backs up only changed complete files, rollback restores them, and unrelated personal agents remain untouched. Omitting the option never touches settings or agent files.

The portable config reproduces disabled reasoning summaries, low output verbosity, personality, never-ask approval policy, full-access command sandbox mode, live web search, Standard speed, multi-agent, hook, and desktop preferences including disabled prompt suggestions. Main-thread model, default reasoning effort, and the Windows sandbox backend remain host-owned and are preserved during migration. The `[agents]` table owns the unclassified subagent fallback; each semantic custom-agent file independently owns its actual model and reasoning effort. Deployment validates the fixed `evidence`/`experiment`/`operator` file set, schema, filename/name identity, explicit safe model identifier, supported effort, Chinese prose, role distinctness, and sensitive-data boundary without copying the selected model, effort, or role text into the validator. Retired `luna`, `sol`, and `terra` paths remain in the lifecycle inventory so a later authorized portable-settings publication removes old managed copies without touching unrelated personal agents. The transferred `windows.sandbox` identity preserves its cross-version history while leaving the installed value untouched; evaluation-only elevated initialization remains owned by the explicit evaluator setup entry. The portable key set deliberately excludes authentication, project trust paths, marketplace/plugin caches, MCP absolute paths, the Windows sandbox backend, hook trust hashes, runtime-generated `notify` and `node_repl` entries, histories, logs, and secrets. Exclusion means AgentBase does not own or replace those host values; it does not mean deployment deletes them.

The files under `global/agents/` follow the [official Codex custom-agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents). Codex-provided `default`, `worker`, and `explorer` agents are not duplicated in the repository. They remain owned by the installed Codex release, avoiding custom files that would override built-in agents with the same names.

`approval_policy = "never"` and `sandbox_mode = "danger-full-access"` reproduce the portable command policy. The host or Codex UI separately owns `windows.sandbox`; AgentBase publication must not select or initialize an elevated backend during application startup. Review the portable values before installing on another machine; workspace or organization policy can still restrict them.

## Prepare a Windows host

PowerShell 7, `fd`, `scc`, `hyperfine`, Python 3, Node.js LTS, ast-grep, a user-level Codex CLI and the independently installed `srcq.exe` are host prerequisites, not part of the AgentBase payload. Codex on Windows prefers `pwsh.exe` when it is available, but the desktop package does not install it. Its WindowsApps `codex.exe` is also protected by package-identity execute ACLs and is not a valid ordinary child-process entry. AgentBase therefore standardizes on PowerShell 7, requires an `fd` build that supports `--max-results`, an `scc` build that supports `--by-file`, JSON and json2 output, a `hyperfine` build that supports warmup and JSON export, Python 3.11+, Node.js `>=22.9 <27`, ast-grep 0.44.1 and user npm `@openai/codex@0.148.0` with the isolated `exec` flags used by routing evaluation。`srcq` 必须从 `tools/srcq` 的受验证 Windows release 通过 `scripts/install-srcq.ps1` 安装到用户 PATH；skill、插件和 Codex 发布不会复制或回退到私有二进制。

When the user asks Codex to prepare, reproduce, or deploy AgentBase on a new Windows machine, that request authorizes installation of these prerequisites through the project entry point. Run it before Validate or Publish:

```powershell
& '.\development\codex-deployment\bootstrap_windows.ps1' -Action Install
```

The script is idempotent. It uses the exact winget package IDs `Microsoft.PowerShell`, `sharkdp.fd`, `BenBoyter.scc`, `sharkdp.hyperfine`, `Python.Python.3.13`, and `OpenJS.NodeJS.LTS`, then uses that Node installation to install the exact npm packages `@ast-grep/cli@0.44.1` and `@openai/codex@0.148.0`. For Codex it reads the native npm binary directly, verifies the required `exec` isolation and schema flags, and places the user npm prefix before WindowsApps in the persisted User PATH. [`development/common/codex_cli_runtime.ps1`](../common/codex_cli_runtime.ps1) is the shared owner for the native npm executable layouts consumed by both bootstrap readback and the routing runner; it covers nested optional-package, hoisted optional-package and package-vendor fallback layouts while excluding WindowsApps and reparse points. The routing runner resolves the resulting absolute native path and never trusts ambiguous command-name resolution. The bootstrap changes only missing or unsupported prerequisites and reads back every resolved executable, version and required capability. Use `-Action Check` for a read-only audit. Direct output defaults to the model view: success is `{ready:true}`, while failure lists only unsupported tools and the recovery action. Add `-View Machine` when automation needs the complete tool, package, path, version and capability JSON. If any PATH-providing prerequisite was installed or reordered, fully exit and restart the Codex desktop host before continuing so the new process inherits the persisted PATH. Starting another task inside the same host does not prove that PATH was refreshed.

Before publishing a payload that contains `source-query`, run the independent runtime owner's status entry and require `ready=true`, then run both the AST and scc doctors. The status command verifies the installed manifest, managed file hashes, binary version and unique PATH entry; `manage_agentbase.ps1` does not copy or repair that external runtime or the scc engine:

```powershell
& '.\tools\srcq\scripts\install-srcq.ps1' Status
srcq doctor
srcq query scc doctor
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
published : false
gaps      : published_manifest_missing,installed_payload_differs_from_source
```

Publish and Rollback additionally show the exact backup or retired-payload path needed for recovery. Plugin installation and an unavailable `srcq` runtime appear only when they require a separate action.

Assign the result when a program or a later model step needs the machine contract, then select the exact field or serialize the complete object explicitly:

```powershell
$result = & '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex')
$result.formal_publication_gaps
$result | ConvertTo-Json -Depth 10
```

## Validate

Before formal Validate, run the incremental owner once. It performs zero model runs when current phase-visible evidence remains valid, otherwise reuses proven stages, runs only `evaluate` stages, parallelizes Routing and Policy, and delays References until the relevant Routing selection is known:

```powershell
& '.\development\skill-routing\refresh_routing_evidence.ps1' -ProjectRoot (Get-Location).Path
```

Validation first runs the zero-model-token routing infrastructure suite for syntax, fingerprints, capsules, planner decisions, isolated runtime configuration, attempt lifecycle and crash recovery. It also runs the evaluator-disabled AgentBase Windows SWE infrastructure suite; that gate validates corpus, isolation, identity, patch, receipt and recovery contracts without cloning task sources, installing task dependencies, qualifying cases, running an external Verifier or starting a model. Validation then checks the global rule and Skill contract, the separately isolated description-only Routing, independent behavior-policy and post-selection reference capsules, their generation and phase-visible identities, clean-input attestations, current receipt IDs and capsule/candidate/input hashes in `development/skill-routing/evidence/current.json`. It also verifies the matching formal or evidence-reuse receipts, source links, semantic result hashes, zero-cost reuse claims, unfinished attempts and bounded unchanged-input retries in `development/skill-routing/evidence/attempts.json`, plus the complete managed-asset lifecycle and current source identities, portable config allowlist, custom-agent structure/identity/safety contract, hooks schema and independent `vscode-lsp-mcp` release owner. Staged evidence proves routing, coarse policy labels, reference selection, isolation and formal provenance only; it does not replace skill regressions or component release gates:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

Validate and Publish deliberately do not run the real candidate permission probe or the cross-owner final assessment. Those explicit entries use the same elevated profile as a future candidate; first use can request administrator approval and configure the native Windows sandbox, so they must not be hidden inside a routine gate:

```powershell
python.exe -X utf8 .\development\agent-evaluation\agent_eval.py check --suite all
python.exe -X utf8 .\development\agent-evaluation\agent_eval.py sandbox-check --view machine
python.exe -X utf8 .\development\agent-evaluation\agent_eval.py assess --suite all --view machine
```

`check` is read-only and reports missing base/task tools, including pnpm only when the selected suite needs it. `sandbox-check` runs no model but requires the formal elevated host-default-deny policy: minimal runtime paths, the candidate workspace and one per-attempt tmpdir are reopened, the complete `.agents/skills` projection is narrowed to read-only, and state/project/installed-root probes remain unreadable. It also runs hash-pinned srcq AST/cache, pagination, fd tree, scc machine and artifact round trips before a model can start. Known missing administrator setup returns `blocked-precondition` instead of falling back to unelevated. `assess` consumes the native Validate result, that permission result, current routing evidence and the selected SWE report without refreshing model evidence, running qualification, installing dependencies or publishing.

`run`, `recover`, `sandbox-check`, and `assess` accept `--installed-codex-root`; it defaults to `CODEX_HOME` or `%USERPROFILE%\.codex`. The evaluator denies that complete root to candidate tools and proves both staged and original `auth.json` are unreadable before a model can start. Pass the same explicit root to recovery when the original run used a non-default installation.

The repeatable tests cover lifecycle identity continuity, explicit retirement, safe config-key provenance and removal, default preservation, explicit settings and custom-agent installation, resolved hook paths, unrelated Skill and agent preservation, seeded retired-path detection/removal/restoration, wrong-kind refusal, cross-scope provenance, and rollback:

```powershell
& '.\development\codex-deployment\test_portable_config.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_portable_agents.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_managed_asset_lifecycle.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_manage_agentbase.ps1' -ProjectRoot (Get-Location).Path
& '.\development\codex-deployment\test_bootstrap_windows.ps1'
```

A successful direct test invocation renders only `tests : pass`. Assign its returned object before serialization when automation needs the individual check fields.

## Publish on another Windows machine

Every invocation that publishes to a real Codex root requires the user's explicit approval for that publication. Git maintenance, an earlier publication approval, successful validation, or a read-only status result does not carry that approval forward.

Install and sign in to Codex first. Then clone or copy the repository, run the Windows host preparation above, review `global/config.toml`, run the incremental routing evidence refresh, and choose one delivery mode.

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

The configured service tier and plugin availability still depend on the signed-in account and any workspace or organization policy. The main-thread model and default reasoning effort come from the target host rather than this payload. Review or adjust those settings when the target account does not provide the same capabilities.

Publish and `Status` prove only that the selected files are installed; they do not prove that an already-open task has rebuilt its runtime instruction, tool, MCP, or custom-agent surface. After publishing any `global/agents/*.toml` addition, removal, rename, model, effort, description, or instruction change, do not use an existing task to decide whether it took effect. Begin a new Codex task and inspect the custom roles exposed by the subagent creation interface; for a newly added or materially changed role, one bounded real invocation is the runtime verification. If a new task in the already-running desktop host still exposes the old role set, fully exit and restart the desktop host, then create another new task. Absence only in a pre-publication task is expected stale runtime state; absence after that fresh-host check is a deployment or runtime-discovery failure and must not be dismissed as successful publication.

MCP launcher or configuration changes require a full desktop-host restart before opening the verification task; merely starting another task in the same host is not sufficient evidence that the MCP process or tool schema was refreshed. In plugin mode, also verify the plugin is installed and enabled; in either mode open `/hooks`, review the exact commands, and trust them on the new machine. Hook trust hashes are machine state and are intentionally not copied. QQ completion remains off until it is enabled for a specific workspace or task through `codex-qq-hook`.

## Read publication status

`Status` is read-only. It derives state from the selected source payload, installed managed contract, latest matching `published` manifest, latest schema 7 lifecycle receipt across publication scopes, and current routing-policy evidence instead of trusting a README claim. For `config.toml`, only AgentBase-owned portable keys and declared retirements participate in publication identity; host-owned MCP, trust, plugin, marketplace, and runtime changes do not create false managed drift. Rollback still fingerprints the complete installed file and refuses to overwrite post-publish host changes unless drift is explicitly accepted:

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

Use the same delivery mode and settings scope that were published. `managed_payload_formally_published=true` covers only files managed by this script and also requires the matching manifest to carry the current lifecycle hash, every retired path to be absent, and every retired config key to be absent. Otherwise `formal_publication_gaps` identifies source/install/manifest/evidence/lifecycle drift or residual retired assets; config conflicts distinguish modified from provenance-free keys. In `Plugin` mode, `plugin_mode_ready=false` and `direct_compatibility_conflicts` identify current direct skills or global AgentBase hooks that must be removed before migration. `plugin_installation_inspected=false` is intentional: inspect plugin state through the plugin browser or `codex plugin list`.

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

Rollback derives its targets from the publish manifest. If portable settings were installed, the prior complete `config.toml`, `hooks.json`, and matching custom-agent files are restored in the same transaction as the prior AGENTS and Skill files; this also recovers a lifecycle-approved config-key removal. Newly introduced managed agents are removed, and unrelated agents remain untouched. A retired path removed by that publication is restored from the same backup, after which `Status` again exposes the retirement gap until a later approved Publish removes it.
