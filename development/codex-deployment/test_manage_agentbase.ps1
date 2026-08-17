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
$externalPreflightRoot = Join-Path ([IO.Path]::GetTempPath()) ("AgentBase-srcq-preflight-test-" + [guid]::NewGuid().ToString("N"))
$externalPreflightRejected = $false
$managedAssetLifecycle = Get-Content -LiteralPath (Join-Path $ProjectRoot 'development\codex-deployment\managed_asset_lifecycle.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$retiredManagedSkills = @($managedAssetLifecycle.paths.retired | ForEach-Object { [IO.Path]::GetFileName(([string]$_.path).Replace('/', '\')) })

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
    $oldLocalAppData = $env:LOCALAPPDATA
    try {
        $env:LOCALAPPDATA = Join-Path $externalPreflightRoot "localappdata"
        New-Item -ItemType Directory -Path $env:LOCALAPPDATA -Force | Out-Null
        $externalCodexRoot = Join-Path $externalPreflightRoot "codex"
        try {
            & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $externalCodexRoot | Out-Null
        }
        catch {
            $externalPreflightRejected = $_.Exception.Message -match 'srcq runtime is not ready'
        }
        if (-not $externalPreflightRejected -or (Test-Path -LiteralPath (Join-Path $externalCodexRoot 'AGENTS.md'))) {
            throw "Publish did not reject a missing srcq runtime before writing the payload"
        }
    }
    finally {
        $env:LOCALAPPDATA = $oldLocalAppData
    }

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
        'model_reasoning_effort = "high"'
        'notify = ["keep-host-notify"]'
        '[agents]'
        'default_subagent_model = "gpt-5.6-terra"'
        'default_subagent_reasoning_effort = "low"'
        'keep-host-agent-setting = true'
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

    $wrongKindRetiredPath = Join-Path $codexRoot "skills\rg-token-safe"
    Write-FixtureText -Path $wrongKindRetiredPath -Text ("unexpected file" + [Environment]::NewLine)
    $wrongKindRetiredHash = (Get-FileHash -LiteralPath $wrongKindRetiredPath -Algorithm SHA256).Hash
    $wrongKindRetirementRejected = $false
    try {
        & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot | Out-Null
    }
    catch {
        $wrongKindRetirementRejected = $_.Exception.Message -like "Retired managed path has unexpected kind*"
    }
    if (-not $wrongKindRetirementRejected -or
        -not (Test-Path -LiteralPath $wrongKindRetiredPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $wrongKindRetiredPath -Algorithm SHA256).Hash -ne $wrongKindRetiredHash -or
        (Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash -ne $originalAgentsHash) {
        throw "Publish did not safely reject a retired managed path with the wrong kind"
    }
    Remove-Item -LiteralPath $wrongKindRetiredPath -Force

    $retiredFixtureHashes = @{}
    foreach ($retiredSkill in $retiredManagedSkills) {
        $retiredSkillRoot = Join-Path $codexRoot "skills\$retiredSkill"
        New-Item -ItemType Directory -Path $retiredSkillRoot -Force | Out-Null
        $retiredSkillPath = Join-Path $retiredSkillRoot "SKILL.md"
        Write-FixtureText -Path $retiredSkillPath -Text ("retired fixture: $retiredSkill" + [Environment]::NewLine)
        Write-FixtureText -Path (Join-Path $retiredSkillRoot "host-note.txt") -Text ("must be recoverable" + [Environment]::NewLine)
        $retiredFixtureHashes[$retiredSkill] = (Get-FileHash -LiteralPath $retiredSkillPath -Algorithm SHA256).Hash
    }

    $prePublishStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([int]$prePublishStatus.retired_managed_path_present_count -ne $retiredManagedSkills.Count -or
        @($prePublishStatus.formal_publication_gaps) -notcontains "retired_managed_paths_present") {
        throw "Status did not expose the installed retired managed paths before publication"
    }

    $defaultPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if (-not [bool]$defaultPublish.skills_installed -or [bool]$defaultPublish.hooks_installed -or [bool]$defaultPublish.portable_settings_installed) {
        throw "Default publish reported an inconsistent direct-compatibility payload"
    }
    if ([bool]$defaultPublish.portable_settings_installed) {
        throw "Default publish unexpectedly installed portable settings"
    }
    if ([bool]$defaultPublish.runtime_prerequisite_in_scope) {
        throw "Deployment sandbox unexpectedly consumed the host srcq installation"
    }
    if ([int]$defaultPublish.retired_managed_path_removed_count -ne $retiredManagedSkills.Count) {
        throw "Default publish did not report all retired managed paths"
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
    if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\source-query\SKILL.md") -PathType Leaf)) {
        throw "Default publish omitted the formal source-query skill"
    }
    $defaultManifest = Get-Content -LiteralPath (Join-Path $defaultPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$defaultManifest.schema_version -ne 7 -or
        [string]$defaultManifest.managed_asset_lifecycle_sha256 -ne [string]$defaultPublish.managed_asset_lifecycle_sha256 -or
        @($defaultManifest.managed_asset_units).Count -ne [int]$defaultPublish.managed_asset_unit_count) {
        throw "Default publish manifest did not record the complete managed-asset lifecycle"
    }
    foreach ($retiredSkill in $retiredManagedSkills) {
        if (Test-Path -LiteralPath (Join-Path (Join-Path $codexRoot "skills") $retiredSkill)) {
            throw "Default publish retained a retired query skill: $retiredSkill"
        }
        $relativeRetiredPath = "skills\$retiredSkill"
        $retiredTargetState = @($defaultManifest.targets | Where-Object { [string]$_.relative_path -eq $relativeRetiredPath })
        $backupSkillPath = Join-Path $defaultPublish.backup_path "payload\$relativeRetiredPath\SKILL.md"
        if ($retiredTargetState.Count -ne 1 -or [string]$retiredTargetState[0].desired_state -ne "absent" -or
            -not [bool]$retiredTargetState[0].existed_before -or
            -not (Test-Path -LiteralPath $backupSkillPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $backupSkillPath -Algorithm SHA256).Hash -ne $retiredFixtureHashes[$retiredSkill]) {
            throw "Default publish did not preserve a recoverable retirement receipt: $retiredSkill"
        }
    }
    $queryRuntimeArtifacts = @(Get-ChildItem -LiteralPath (Join-Path $codexRoot "skills\source-query") -Recurse -Force -File | Where-Object {
        $_.Extension -eq '.exe' -or $_.Name -in @('sgy.exe', 'srcq.exe')
    })
    if ($queryRuntimeArtifacts.Count -ne 0) {
        throw "Default publish copied a private source-query runtime"
    }
    $defaultStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if (-not [bool]$defaultStatus.managed_payload_formally_published -or
        -not [bool]$defaultStatus.manifest_matches_managed_asset_lifecycle -or
        [int]$defaultStatus.retired_managed_path_present_count -ne 0) {
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
    foreach ($retiredSkill in $retiredManagedSkills) {
        $restoredRetiredSkill = Join-Path $codexRoot "skills\$retiredSkill\SKILL.md"
        if (-not (Test-Path -LiteralPath $restoredRetiredSkill -PathType Leaf) -or
            (Get-FileHash -LiteralPath $restoredRetiredSkill -Algorithm SHA256).Hash -ne $retiredFixtureHashes[$retiredSkill]) {
            throw "Rollback did not restore a retired managed path: $retiredSkill"
        }
    }
    $rolledBackStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([int]$rolledBackStatus.retired_managed_path_present_count -ne $retiredManagedSkills.Count -or
        @($rolledBackStatus.formal_publication_gaps) -notcontains "retired_managed_paths_present") {
        throw "Status did not expose restored retired paths after rollback"
    }

    $settingsPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings
    if (-not [bool]$settingsPublish.portable_settings_installed) {
        throw "Portable-settings publish did not report settings installation"
    }
    if ([int]$settingsPublish.portable_agent_count -ne 3) {
        throw "Portable-settings publish reported an unexpected custom-agent count"
    }
    if ([int]$settingsPublish.retired_managed_path_removed_count -ne $retiredManagedSkills.Count) {
        throw "Portable-settings publish did not retire the restored legacy paths"
    }
    $installedConfigText = Get-Content -LiteralPath (Join-Path $codexRoot "config.toml") -Raw -Encoding UTF8
    foreach ($preservedHostFragment in @(
        'model = "old-model"'
        'model_reasoning_effort = "high"'
        'notify = ["keep-host-notify"]'
        'keep-host-agent-setting = true'
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
        'model_reasoning_summary = "none"'
        'model_verbosity = "low"'
        'approval_policy = "never"'
        'sandbox_mode = "danger-full-access"'
        'web_search = "live"'
        'service_tier = "default"'
        'project_doc_max_bytes = 65536'
        'default_subagent_model = "gpt-5.6-luna"'
        'default_subagent_reasoning_effort = "max"'
        'conversationDetailMode = "STEPS_COMMANDS"'
        'ambient-suggestions-enabled = false'
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
    if ([int]$manifest.schema_version -ne 7 -or [string]::IsNullOrWhiteSpace([string]$manifest.installed_contract_bundle_sha256) -or [string]::IsNullOrWhiteSpace([string]$manifest.routing_evidence_sha256) -or [string]::IsNullOrWhiteSpace([string]$manifest.routing_evaluation_capsule_sha256) -or [string]::IsNullOrWhiteSpace([string]$manifest.managed_asset_lifecycle_sha256) -or @($manifest.managed_asset_units).Count -eq 0) {
        throw "Publish manifest is missing the current routing and managed-asset lifecycle receipts"
    }
    $scopeBridgePublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    $scopeBridgeManifest = Get-Content -LiteralPath (Join-Path $scopeBridgePublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $scopeBridgeConfigReceipts = @($scopeBridgeManifest.managed_asset_units | Where-Object {
        [string]$_.kind -eq 'config_key' -and [string]$_.state -eq 'present'
    })
    if ($scopeBridgeConfigReceipts.Count -eq 0 -or
        @($scopeBridgeConfigReceipts | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.last_managed_source_fingerprint) }).Count -ne 0) {
        throw "A publication outside portable-settings scope did not carry config provenance from the latest lifecycle receipt"
    }

    $installedCacheRoot = Join-Path $codexRoot "skills\codex-event-logger\tests\__pycache__"
    New-Item -ItemType Directory -Path $installedCacheRoot -Force | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $installedCacheRoot "runtime-probe.pyc"), [byte[]]@(5, 6, 7, 8))

    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $scopeBridgePublish.backup_path | Out-Null
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
    foreach ($retiredSkill in $retiredManagedSkills) {
        if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\$retiredSkill\SKILL.md") -PathType Leaf)) {
            throw "Portable-settings rollback did not restore a retired managed path: $retiredSkill"
        }
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
    $pluginSkillTargets = @($pluginManifest.targets | Where-Object { [string]$_.relative_path -like "skills\*" })
    if ($pluginTargets -contains "hooks.json" -or $pluginSkillTargets.Count -ne $retiredManagedSkills.Count -or
        @($pluginSkillTargets | Where-Object {
            [string]$_.desired_state -ne "absent" -or
            $retiredManagedSkills -notcontains ([IO.Path]::GetFileName([string]$_.relative_path))
        }).Count -ne 0) {
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
    foreach ($retiredSkill in $retiredManagedSkills) {
        if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\$retiredSkill\SKILL.md") -PathType Leaf)) {
            throw "Plugin delivery rollback did not restore a retired managed path: $retiredSkill"
        }
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
        retired_managed_paths_removed = $true
        retired_managed_paths_rollback_restored = $true
        retired_wrong_kind_rejected = $true
        status_derived_from_manifest_and_fingerprints = $true
        lifecycle_provenance_crossed_publication_scope = $true
        plugin_delivery_rejected_parallel_direct_entry = $true
        plugin_delivery_omitted_direct_skills_and_hooks = $true
        publish_rejected_missing_srcq_runtime = $externalPreflightRejected
        deployment_sandbox_ignored_host_srcq = $true
        unrelated_skill_preserved = $true
        unrelated_agent_preserved = $true
        explicit_target_count = $manifestTargets.Count
    }
}
finally {
    if (Test-Path -LiteralPath $externalPreflightRoot) {
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        $resolvedExternal = [IO.Path]::GetFullPath($externalPreflightRoot)
        if (-not $resolvedExternal.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $resolvedExternal).StartsWith('AgentBase-srcq-preflight-test-', [StringComparison]::Ordinal)) {
            throw "Refusing external preflight cleanup outside the approved temp root: $resolvedExternal"
        }
        Remove-Item -LiteralPath $resolvedExternal -Recurse -Force
    }
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
