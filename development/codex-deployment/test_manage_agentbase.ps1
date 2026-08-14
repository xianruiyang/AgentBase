param(
    [string]$ProjectRoot,
    [string]$RetainedTestRootToClean
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$sandboxRoot = Join-Path $ProjectRoot "development\codex-deployment\sandbox"
$testRoot = Join-Path $sandboxRoot ("portable-settings-test-" + [guid]::NewGuid().ToString("N"))
$codexRoot = Join-Path $testRoot "codex"
$manage = Join-Path $ProjectRoot "development\codex-deployment\manage_agentbase.ps1"
$payloadContractPath = Join-Path $ProjectRoot "development\common\payload_contract.ps1"
. $payloadContractPath
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$succeeded = $false
$sourceCacheRoot = Join-Path $ProjectRoot "skills\codex-event-logger\tests\__pycache__"
$sourceCacheProbe = Join-Path $sourceCacheRoot ("agentbase-deployment-probe-" + [guid]::NewGuid().ToString("N") + ".pyc")
$sourceCacheRootCreated = $false

function Write-FixtureText {
    param(
        [string]$Path,
        [string]$Text
    )

    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Remove-TestRootSafely {
    param(
        [string]$Path
    )

    $approvedRoot = [IO.Path]::GetFullPath($sandboxRoot).TrimEnd('\') + '\'
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not $resolvedPath.StartsWith($approvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing sandbox cleanup outside approved root: $resolvedPath"
    }
    if (-not (Split-Path -Leaf $resolvedPath).StartsWith("portable-settings-test-", [StringComparison]::Ordinal)) {
        throw "Refusing sandbox cleanup for an unrelated directory: $resolvedPath"
    }
    if (Test-Path -LiteralPath $resolvedPath) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
}

if (-not [string]::IsNullOrWhiteSpace($RetainedTestRootToClean)) {
    Remove-TestRootSafely -Path $RetainedTestRootToClean
}

try {
    $baselineValidation = & $manage -Action Validate -ProjectRoot $ProjectRoot
    if (-not (Test-Path -LiteralPath $sourceCacheRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $sourceCacheRoot | Out-Null
        $sourceCacheRootCreated = $true
    }
    [IO.File]::WriteAllBytes($sourceCacheProbe, [byte[]]@(1, 2, 3, 4))
    $cacheValidation = & $manage -Action Validate -ProjectRoot $ProjectRoot
    if ([string]$baselineValidation.source_bundle_sha256 -ne [string]$cacheValidation.source_bundle_sha256) {
        throw "A runtime cache file changed the deployable source fingerprint"
    }

    New-Item -ItemType Directory -Path (Join-Path $codexRoot "skills\user-skill") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $codexRoot "agents") -Force | Out-Null
    Write-FixtureText -Path (Join-Path $codexRoot "AGENTS.md") -Text ("old agents" + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "config.toml") -Text ((@(
        'model = "old-model"'
        'notify = ["keep-host-notify"]'
        '[mcp_servers.keep]'
        'command = "keep"'
        '[features]'
        'path = "keep-host-feature"'
        '[projects.''D:\workspace'']'
        'trust_level = "trusted"'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "hooks.json") -Text ((@(
        '{'
        '  "hooks": {}'
        '}'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "skills\user-skill\SKILL.md") -Text ((@(
        '---'
        'name: user-skill'
        'description: keep'
        '---'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "agents\luna.toml") -Text ((@(
        'name = "luna"'
        'description = "old luna"'
        'developer_instructions = "old"'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "agents\user-agent.toml") -Text ((@(
        'name = "user_agent"'
        'description = "keep"'
        'developer_instructions = "keep"'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)

    $originalAgentsHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash
    $originalConfigHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash
    $originalHooksHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash
    $originalLunaHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\luna.toml") -Algorithm SHA256).Hash
    $originalUserAgentHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\user-agent.toml") -Algorithm SHA256).Hash

    $defaultPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if (-not [bool]$defaultPublish.skills_installed -or [bool]$defaultPublish.hooks_installed -or [bool]$defaultPublish.portable_settings_installed) {
        throw "Default publish reported an inconsistent direct-compatibility payload"
    }
    if ([bool]$defaultPublish.portable_settings_installed) {
        throw "Default publish unexpectedly installed portable settings"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash -ne $originalConfigHash) {
        throw "Default publish changed config.toml"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash -ne $originalHooksHash) {
        throw "Default publish changed hooks.json"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\luna.toml") -Algorithm SHA256).Hash -ne $originalLunaHash) {
        throw "Default publish changed a custom agent"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\user-agent.toml") -Algorithm SHA256).Hash -ne $originalUserAgentHash) {
        throw "Default publish changed an unrelated custom agent"
    }
    $installedRuntimeArtifacts = @(Get-ChildItem -LiteralPath (Join-Path $codexRoot "skills") -Recurse -Force -File | Where-Object {
        $_.FullName -match '(?i)[\\/]__pycache__[\\/]' -or $_.Extension -in @('.pyc', '.pyo')
    })
    if ($installedRuntimeArtifacts.Count -ne 0) {
        throw "Default publish copied runtime artifacts into the Codex skill payload"
    }
    $installedProjectOnlyArtifacts = @(Get-ChildItem -LiteralPath (Join-Path $codexRoot "skills") -Recurse -Force -File | Where-Object {
        $relativePath = $_.FullName.Substring((Join-Path $codexRoot "skills").Length + 1).Replace('\', '/')
        Test-AgentBaseProjectOnlyArtifact -RelativePath $relativePath
    })
    if ($installedProjectOnlyArtifacts.Count -ne 0) {
        throw "Default publish copied project-only tests or benchmarks into the Codex skill payload"
    }
    $defaultStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if (-not [bool]$defaultStatus.managed_payload_formally_published) {
        throw "Status did not recognize the current direct-compatibility publish"
    }

    $staleProjectTestPath = Join-Path $codexRoot "skills\codex-event-logger\tests\stale_project_test.py"
    New-Item -ItemType Directory -Path (Split-Path -Parent $staleProjectTestPath) -Force | Out-Null
    Write-FixtureText -Path $staleProjectTestPath -Text ("project-only" + [Environment]::NewLine)
    $staleTestStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([bool]$staleTestStatus.managed_payload_formally_published -or @($staleTestStatus.formal_publication_gaps) -notcontains "installed_payload_differs_from_source") {
        throw "Status did not report a stale project-only test in the managed Codex payload"
    }
    $testCleanupPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    $testCleanupManifest = Get-Content -LiteralPath (Join-Path $testCleanupPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$testCleanupPublish.changed_path_count -ne 1 -or @($testCleanupManifest.targets).Count -ne 1 -or
        [string]$testCleanupManifest.targets[0].relative_path -ne "skills\codex-event-logger\tests\stale_project_test.py" -or
        [string]$testCleanupManifest.targets[0].desired_state -ne "absent" -or
        (Test-Path -LiteralPath $staleProjectTestPath) -or
        (Test-Path -LiteralPath (Split-Path -Parent $staleProjectTestPath))) {
        throw "Incremental publish did not remove a stale project-only test from the Codex payload"
    }

    $changedSkillPath = Join-Path $codexRoot "skills\codex-event-logger\SKILL.md"
    $untouchedSkillPath = Join-Path $codexRoot "skills\codex-qq-hook\SKILL.md"
    Write-FixtureText -Path $changedSkillPath -Text ("corrupted installed skill" + [Environment]::NewLine)
    $sentinelWriteTime = [DateTime]::SpecifyKind([DateTime]::Parse("2020-01-02T03:04:05"), [DateTimeKind]::Utc)
    [IO.File]::SetLastWriteTimeUtc($untouchedSkillPath, $sentinelWriteTime)
    $repairPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    $repairManifest = Get-Content -LiteralPath (Join-Path $repairPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$repairPublish.changed_path_count -ne 1 -or @($repairManifest.targets).Count -ne 1 -or [string]$repairManifest.targets[0].relative_path -ne "skills\codex-event-logger\SKILL.md") {
        throw "Incremental publish did not limit the transaction to the changed managed file"
    }
    if ([IO.File]::GetLastWriteTimeUtc($untouchedSkillPath) -ne $sentinelWriteTime) {
        throw "Incremental publish rewrote an unchanged managed file"
    }
    $noOpPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    $noOpManifest = Get-Content -LiteralPath (Join-Path $noOpPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$noOpPublish.changed_path_count -ne 0 -or @($noOpManifest.targets).Count -ne 0) {
        throw "No-op publish created changed payload targets"
    }
    if ([IO.File]::GetLastWriteTimeUtc($untouchedSkillPath) -ne $sentinelWriteTime) {
        throw "No-op publish touched an unchanged managed file"
    }
    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $defaultPublish.backup_path | Out-Null

    $settingsPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings
    if (-not [bool]$settingsPublish.portable_settings_installed) {
        throw "Portable-settings publish did not report settings installation"
    }
    if ([int]$settingsPublish.portable_agent_count -ne 3) {
        throw "Portable-settings publish reported an unexpected custom-agent count"
    }
    $installedConfigText = Get-Content -LiteralPath (Join-Path $codexRoot "config.toml") -Raw -Encoding UTF8
    foreach ($preservedHostFragment in @(
        'notify = ["keep-host-notify"]'
        '[mcp_servers.keep]'
        'command = "keep"'
        'path = "keep-host-feature"'
        '[projects.''D:\workspace'']'
        'trust_level = "trusted"'
    )) {
        if (-not $installedConfigText.Contains($preservedHostFragment)) {
            throw "Portable-settings publish removed host-owned config: $preservedHostFragment"
        }
    }
    foreach ($portableFragment in @(
        'model = "gpt-5.6-sol"'
        'project_doc_max_bytes = 65536'
        'default_subagent_model = "gpt-5.6-luna"'
        'conversationDetailMode = "STEPS_COMMANDS"'
    )) {
        if (-not $installedConfigText.Contains($portableFragment)) {
            throw "Portable-settings publish did not install a managed setting: $portableFragment"
        }
    }
    $settingsStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings
    if (-not [bool]$settingsStatus.managed_payload_formally_published -or -not [bool]$settingsStatus.installed_matches_source) {
        throw "Status did not compare portable config by its managed contract"
    }
    $installedHooksText = Get-Content -LiteralPath (Join-Path $codexRoot "hooks.json") -Raw -Encoding UTF8
    if ($installedHooksText.Contains("{{CODEX_ROOT}}")) {
        throw "Installed hooks contain an unresolved placeholder"
    }
    $installedHooks = $installedHooksText | ConvertFrom-Json
    $firstCommand = [string]$installedHooks.hooks.UserPromptSubmit[0].hooks[0].commandWindows
    if (-not $firstCommand.Contains($codexRoot)) {
        throw "Installed hooks do not reference the selected Codex root"
    }
    $sourceAgentFiles = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "global\agents") -File -Filter "*.toml")
    foreach ($sourceAgentFile in $sourceAgentFiles) {
        $installedAgentPath = Join-Path (Join-Path $codexRoot "agents") $sourceAgentFile.Name
        if (-not (Test-Path -LiteralPath $installedAgentPath -PathType Leaf)) {
            throw "Portable custom agent was not installed: $($sourceAgentFile.Name)"
        }
        if ((Get-FileHash -LiteralPath $installedAgentPath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $sourceAgentFile.FullName -Algorithm SHA256).Hash) {
            throw "Installed custom agent does not match the portable source: $($sourceAgentFile.Name)"
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\user-skill\SKILL.md") -PathType Leaf)) {
        throw "Unrelated user skill was removed"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\user-agent.toml") -Algorithm SHA256).Hash -ne $originalUserAgentHash) {
        throw "Unrelated custom agent was changed"
    }
    $manifest = Get-Content -LiteralPath (Join-Path $settingsPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifestTargets = @($manifest.targets.relative_path | Sort-Object)
    if ($manifestTargets -notcontains "config.toml" -or $manifestTargets -notcontains "hooks.json") {
        throw "Portable settings are missing from the rollback manifest"
    }
    foreach ($agentName in @("luna", "sol", "terra")) {
        if ($manifestTargets -notcontains "agents\$agentName.toml") {
            throw "Portable custom agent is missing from the rollback manifest: $agentName"
        }
    }
    if ([int]$manifest.schema_version -ne 5 -or [string]::IsNullOrWhiteSpace([string]$manifest.installed_contract_bundle_sha256) -or [string]::IsNullOrWhiteSpace([string]$manifest.routing_evidence_sha256) -or [string]::IsNullOrWhiteSpace([string]$manifest.routing_evaluation_capsule_sha256)) {
        throw "Publish manifest is missing the current detached routing-policy evidence receipt"
    }

    $installedCacheRoot = Join-Path $codexRoot "skills\codex-event-logger\tests\__pycache__"
    New-Item -ItemType Directory -Path $installedCacheRoot -Force | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $installedCacheRoot "runtime-probe.pyc"), [byte[]]@(5, 6, 7, 8))

    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $settingsPublish.backup_path | Out-Null
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash -ne $originalAgentsHash) {
        throw "Rollback did not restore AGENTS.md"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash -ne $originalConfigHash) {
        throw "Rollback did not restore config.toml"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash -ne $originalHooksHash) {
        throw "Rollback did not restore hooks.json"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\luna.toml") -Algorithm SHA256).Hash -ne $originalLunaHash) {
        throw "Rollback did not restore the original luna agent"
    }
    foreach ($agentName in @("sol", "terra")) {
        if (Test-Path -LiteralPath (Join-Path $codexRoot "agents\$agentName.toml")) {
            throw "Rollback did not remove the newly installed custom agent: $agentName"
        }
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "agents\user-agent.toml") -Algorithm SHA256).Hash -ne $originalUserAgentHash) {
        throw "Rollback changed the unrelated custom agent"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\user-skill\SKILL.md") -PathType Leaf)) {
        throw "Rollback removed the unrelated user skill"
    }

    $pluginConflictSkill = Join-Path $codexRoot "skills\codex-event-logger"
    New-Item -ItemType Directory -Path $pluginConflictSkill -Force | Out-Null
    Write-FixtureText -Path (Join-Path $pluginConflictSkill "SKILL.md") -Text ("direct compatibility conflict" + [Environment]::NewLine)
    $pluginConflictStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings -SkillDeliveryMode Plugin
    if ([bool]$pluginConflictStatus.plugin_mode_ready -or [int]$pluginConflictStatus.direct_compatibility_conflict_count -ne 1 -or [bool]$pluginConflictStatus.managed_payload_formally_published) {
        throw "Plugin status did not expose the direct-compatibility conflict"
    }
    $pluginConflictRejected = $false
    try {
        & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings -SkillDeliveryMode Plugin | Out-Null
    }
    catch {
        $pluginConflictRejected = $_.Exception.Message -like "Plugin delivery mode requires the direct-compatibility skills*"
    }
    if (-not $pluginConflictRejected) {
        throw "Plugin delivery mode did not reject a duplicate direct skill"
    }
    Remove-Item -LiteralPath $pluginConflictSkill -Recurse -Force

    $pluginPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings -SkillDeliveryMode Plugin
    if ([bool]$pluginPublish.skills_installed -or [bool]$pluginPublish.hooks_installed -or -not [bool]$pluginPublish.plugin_installation_must_be_verified_separately) {
        throw "Plugin delivery mode reported an inconsistent managed payload"
    }
    $pluginManagedSkill = Join-Path $codexRoot "skills\codex-event-logger"
    if (Test-Path -LiteralPath $pluginManagedSkill) {
        throw "Plugin delivery mode installed direct skill payloads"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash -ne $originalHooksHash) {
        throw "Plugin delivery mode changed global hooks instead of using bundled plugin hooks"
    }
    $pluginManifest = Get-Content -LiteralPath (Join-Path $pluginPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $pluginTargets = @($pluginManifest.targets.relative_path)
    if ($pluginTargets -contains "hooks.json" -or @($pluginTargets | Where-Object { $_ -like "skills\*" }).Count -ne 0) {
        throw "Plugin delivery manifest contains direct skills or hooks"
    }
    $pluginStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings -SkillDeliveryMode Plugin
    if (-not [bool]$pluginStatus.managed_payload_formally_published -or [bool]$pluginStatus.plugin_installation_inspected -or -not [bool]$pluginStatus.plugin_mode_ready -or [int]$pluginStatus.direct_compatibility_conflict_count -ne 0) {
        throw "Plugin delivery status did not distinguish the managed payload from external plugin installation"
    }
    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $pluginPublish.backup_path | Out-Null
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash -ne $originalAgentsHash) {
        throw "Plugin delivery rollback did not restore AGENTS.md"
    }

    $succeeded = $true
    [pscustomobject]@{
        default_publish_preserved_settings = $true
        explicit_publish_merged_portable_settings = $true
        host_owned_config_preserved = $true
        custom_agents_installed = $true
        hooks_root_resolved = $true
        rollback_restored_settings = $true
        runtime_artifacts_excluded = $true
        project_only_tests_and_benchmarks_excluded = $true
        runtime_cache_ignored_for_rollback_drift = $true
        single_file_incremental_publish = $true
        no_op_publish_touched_nothing = $true
        status_derived_from_manifest_and_fingerprints = $true
        plugin_delivery_rejected_parallel_direct_entry = $true
        plugin_delivery_omitted_direct_skills_and_hooks = $true
        unrelated_skill_preserved = $true
        unrelated_agent_preserved = $true
        explicit_target_count = $manifestTargets.Count
    }
}
finally {
    if (Test-Path -LiteralPath $sourceCacheProbe -PathType Leaf) {
        Remove-Item -LiteralPath $sourceCacheProbe -Force
    }
    if ($sourceCacheRootCreated -and (Test-Path -LiteralPath $sourceCacheRoot -PathType Container)) {
        $remainingCacheItems = @(Get-ChildItem -LiteralPath $sourceCacheRoot -Force)
        if ($remainingCacheItems.Count -eq 0) {
            Remove-Item -LiteralPath $sourceCacheRoot -Force
        }
    }
    if ($succeeded -and (Test-Path -LiteralPath $testRoot)) {
        Remove-TestRootSafely -Path $testRoot
    }
    elseif (-not $succeeded) {
        Write-Warning "Deployment test sandbox retained for diagnosis: $testRoot"
    }
}
