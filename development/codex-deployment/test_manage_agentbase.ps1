param(
    [string]$ProjectRoot,
    [string]$RetainedTestRootToClean
)

$ErrorActionPreference = "Stop"

Update-FormatData -PrependPath (Join-Path $PSScriptRoot 'manage_agentbase.format.ps1xml') -ErrorAction Stop

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
$retiredManagedPaths = @($managedAssetLifecycle.paths.retired)
$retiredDefaultPaths = @($retiredManagedPaths | Where-Object {
    @($_.modes) -contains 'DirectCompatibility' -and -not [bool]$_.requires_portable_settings
})
$retiredPortablePaths = @($retiredManagedPaths | Where-Object { @($_.modes) -contains 'DirectCompatibility' })
$retiredPluginPaths = @($retiredManagedPaths | Where-Object { @($_.modes) -contains 'Plugin' })

function Write-FixtureText {
    param(
        [string]$Path,
        [string]$Text
    )

    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Get-RetiredFixtureProbePath {
    param(
        [string]$Root,
        [object]$LifecycleEntry
    )

    $managedPath = Join-Path $Root ([string]$LifecycleEntry.path).Replace('/', '\')
    if ([string]$LifecycleEntry.kind -eq 'directory') {
        return Join-Path $managedPath 'SKILL.md'
    }
    return $managedPath
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
    $validationDisplay = ($baselineValidation | Out-String -Width 4096).Trim()
    if ($validationDisplay -notmatch '(?m)^valid\s*:\s*true\r?$' -or
        $validationDisplay -match 'source_bundle_sha256|routing_evidence_sha256') {
        throw "Validate default display did not preserve the compact model-facing contract"
    }
    $validationMachine = ($baselineValidation | ConvertTo-Json -Depth 10 | ConvertFrom-Json)
    if ([string]$validationMachine.action -ne 'Validate' -or
        [string]$validationMachine.source_bundle_sha256 -ne [string]$baselineValidation.source_bundle_sha256 -or
        [string]::IsNullOrWhiteSpace([string]$validationMachine.routing_evidence_sha256)) {
        throw "Validate compact display changed the complete machine-readable object"
    }
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
        '[windows]'
        'sandbox = "unelevated"'
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
    foreach ($retiredPath in $retiredManagedPaths) {
        $managedFixturePath = Join-Path $codexRoot ([string]$retiredPath.path).Replace('/', '\')
        $fixtureProbePath = Get-RetiredFixtureProbePath -Root $codexRoot -LifecycleEntry $retiredPath
        New-Item -ItemType Directory -Path (Split-Path -Parent $fixtureProbePath) -Force | Out-Null
        if (-not (Test-Path -LiteralPath $fixtureProbePath -PathType Leaf)) {
            Write-FixtureText -Path $fixtureProbePath -Text ("retired fixture: $([string]$retiredPath.id)" + [Environment]::NewLine)
        }
        if ([string]$retiredPath.kind -eq 'directory') {
            Write-FixtureText -Path (Join-Path $managedFixturePath 'host-note.txt') -Text ("must be recoverable" + [Environment]::NewLine)
        }
        $retiredFixtureHashes[[string]$retiredPath.id] = (Get-FileHash -LiteralPath $fixtureProbePath -Algorithm SHA256).Hash
    }

    $prePublishStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([int]$prePublishStatus.retired_managed_path_present_count -ne $retiredDefaultPaths.Count -or
        @($prePublishStatus.formal_publication_gaps) -notcontains "retired_managed_paths_present") {
        throw "Status did not expose the installed retired managed paths before publication"
    }
    $prePublishDisplay = ($prePublishStatus | Out-String -Width 4096).Trim()
    if ($prePublishDisplay -notmatch '(?m)^published\s*:\s*false\r?$' -or
        $prePublishDisplay -notmatch '(?m)^gaps\s*:.*retired_managed_paths_present' -or
        $prePublishDisplay -match 'source_bundle_sha256|installed_bundle_sha256|codex_root') {
        throw "Status default display did not retain only the actionable publication diagnosis"
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
    if ([int]$defaultPublish.retired_managed_path_removed_count -ne $retiredDefaultPaths.Count) {
        throw "Default publish did not report all retired managed paths"
    }
    $defaultPublishDisplay = ($defaultPublish | Out-String -Width 4096).Trim()
    if ($defaultPublishDisplay -notmatch '(?m)^published\s*:\s*true\r?$' -or
        $defaultPublishDisplay -notmatch '(?m)^changed\s*:\s*\d+\r?$' -or
        $defaultPublishDisplay -notmatch '(?m)^backup\s*:' -or
        $defaultPublishDisplay -match 'source_bundle_sha256|routing_evidence_sha256|managed_asset_lifecycle_sha256') {
        throw "Publish default display did not retain the result and rollback handle without machine-only identities"
    }
    $defaultPublishMachine = ($defaultPublish | ConvertTo-Json -Depth 10 | ConvertFrom-Json)
    if ([string]$defaultPublishMachine.action -ne 'Publish' -or
        [string]$defaultPublishMachine.source_bundle_sha256 -ne [string]$defaultPublish.source_bundle_sha256 -or
        [string]$defaultPublishMachine.backup_path -ne [string]$defaultPublish.backup_path) {
        throw "Publish compact display changed the complete machine-readable object"
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
    foreach ($retiredPath in $retiredDefaultPaths) {
        $relativeRetiredPath = ([string]$retiredPath.path).Replace('/', '\')
        if (Test-Path -LiteralPath (Join-Path $codexRoot $relativeRetiredPath)) {
            throw "Default publish retained a retired managed path: $relativeRetiredPath"
        }
        $retiredTargetState = @($defaultManifest.targets | Where-Object { [string]$_.relative_path -eq $relativeRetiredPath })
        $backupProbePath = if ([string]$retiredPath.kind -eq 'directory') {
            Join-Path $defaultPublish.backup_path "payload\$relativeRetiredPath\SKILL.md"
        }
        else {
            Join-Path $defaultPublish.backup_path "payload\$relativeRetiredPath"
        }
        if ($retiredTargetState.Count -ne 1 -or [string]$retiredTargetState[0].desired_state -ne "absent" -or
            -not [bool]$retiredTargetState[0].existed_before -or
            -not (Test-Path -LiteralPath $backupProbePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $backupProbePath -Algorithm SHA256).Hash -ne $retiredFixtureHashes[[string]$retiredPath.id]) {
            throw "Default publish did not preserve a recoverable retirement receipt: $relativeRetiredPath"
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
    $defaultStatusDisplay = ($defaultStatus | Out-String -Width 4096).Trim()
    if ($defaultStatusDisplay -notmatch '(?m)^published\s*:\s*true\r?$' -or
        $defaultStatusDisplay -match '(?m)^gaps\s*:|source_bundle_sha256|installed_bundle_sha256') {
        throw "Healthy Status default display included non-actionable machine detail"
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
    $defaultRollback = & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $defaultPublish.backup_path
    $defaultRollbackDisplay = ($defaultRollback | Out-String -Width 4096).Trim()
    if ($defaultRollbackDisplay -notmatch '(?m)^rolled_back\s*:\s*true\r?$' -or
        $defaultRollbackDisplay -notmatch '(?m)^restored\s*:\s*\d+\r?$' -or
        $defaultRollbackDisplay -notmatch '(?m)^retired_payload\s*:' -or
        $defaultRollbackDisplay -match 'codex_root|backup_path|mcp_changed') {
        throw "Rollback default display did not retain only the result and recovery location"
    }
    foreach ($retiredPath in $retiredDefaultPaths) {
        $restoredProbePath = Get-RetiredFixtureProbePath -Root $codexRoot -LifecycleEntry $retiredPath
        if (-not (Test-Path -LiteralPath $restoredProbePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $restoredProbePath -Algorithm SHA256).Hash -ne $retiredFixtureHashes[[string]$retiredPath.id]) {
            throw "Rollback did not restore a retired managed path: $([string]$retiredPath.path)"
        }
    }
    $rolledBackStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([int]$rolledBackStatus.retired_managed_path_present_count -ne $retiredDefaultPaths.Count -or
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
    if ([int]$settingsPublish.retired_managed_path_removed_count -ne $retiredPortablePaths.Count) {
        throw "Portable-settings publish did not retire the restored legacy paths"
    }
    $installedConfigText = Get-Content -LiteralPath (Join-Path $codexRoot "config.toml") -Raw -Encoding UTF8
    foreach ($preservedHostFragment in @(
        'model = "old-model"'
        'model_reasoning_effort = "high"'
        'notify = ["keep-host-notify"]'
        'keep-host-agent-setting = true'
        '[windows]'
        'sandbox = "unelevated"'
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
        'max_concurrent_threads_per_session = 6'
        'default_subagent_model = "gpt-5.6-luna"'
        'default_subagent_reasoning_effort = "medium"'
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
    $reasoningHookGroup = $installedHooks.hooks.SessionStart[0]
    $reasoningHookCommand = [string]$reasoningHookGroup.hooks[0].commandWindows
    if ([string]$reasoningHookGroup.matcher -ne "startup|resume|clear|compact" -or
        -not $reasoningHookCommand.Contains($codexRoot) -or
        -not $reasoningHookCommand.EndsWith(" -Hook") -or
        [int]$reasoningHookGroup.hooks[0].additionalContextLimit -ne 32) {
        throw "Installed SessionStart hook does not preserve the reasoning-state context contract"
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
    $windowsSandboxLifecycle = @($manifest.managed_asset_units | Where-Object { [string]$_.id -eq 'config:windows/sandbox' })
    if ($windowsSandboxLifecycle.Count -ne 1 -or [string]$windowsSandboxLifecycle[0].state -ne 'transferred') {
        throw "Portable-settings publish did not preserve the Windows sandbox ownership transfer"
    }
    $manifestTargets = @($manifest.targets.relative_path | Sort-Object)
    if ($manifestTargets -notcontains "config.toml" -or $manifestTargets -notcontains "hooks.json") {
        throw "Portable settings are missing from the rollback manifest"
    }
    foreach ($agentName in @("evidence", "experiment", "operator")) {
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
    foreach ($agentName in @("evidence", "experiment", "operator")) {
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
    foreach ($retiredPath in $retiredPortablePaths) {
        $restoredProbePath = Get-RetiredFixtureProbePath -Root $codexRoot -LifecycleEntry $retiredPath
        if (-not (Test-Path -LiteralPath $restoredProbePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $restoredProbePath -Algorithm SHA256).Hash -ne $retiredFixtureHashes[[string]$retiredPath.id]) {
            throw "Portable-settings rollback did not restore a retired managed path: $([string]$retiredPath.path)"
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
    $pluginRetiredRelativePaths = @($retiredPluginPaths | ForEach-Object { ([string]$_.path).Replace('/', '\') })
    $pluginRetiredTargets = @($pluginManifest.targets | Where-Object { $pluginRetiredRelativePaths -contains [string]$_.relative_path })
    if ($pluginTargets -contains "hooks.json" -or $pluginRetiredTargets.Count -ne $retiredPluginPaths.Count -or
        @($pluginRetiredTargets | Where-Object {
            [string]$_.desired_state -ne "absent"
        }).Count -ne 0) {
        throw "Plugin delivery manifest does not contain the expected retired paths or contains global hooks"
    }
    $pluginStatus = & $manage -Action Status -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings -SkillDeliveryMode Plugin
    if (-not [bool]$pluginStatus.managed_payload_formally_published -or [bool]$pluginStatus.plugin_installation_inspected -or -not [bool]$pluginStatus.plugin_mode_ready -or [int]$pluginStatus.direct_compatibility_conflict_count -ne 0) {
        throw "Plugin delivery status did not distinguish the managed payload from external plugin installation"
    }
    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $pluginPublish.backup_path | Out-Null
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash -ne $originalAgentsHash) {
        throw "Plugin delivery rollback did not restore AGENTS.md"
    }
    foreach ($retiredPath in $retiredPluginPaths) {
        $restoredProbePath = Get-RetiredFixtureProbePath -Root $codexRoot -LifecycleEntry $retiredPath
        if (-not (Test-Path -LiteralPath $restoredProbePath -PathType Leaf)) {
            throw "Plugin delivery rollback did not restore a retired managed path: $([string]$retiredPath.path)"
        }
    }

    $succeeded = $true
    $result = [pscustomobject]@{
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
        compact_default_display_preserved_machine_contract = $true
        compact_status_display_retained_actionable_gaps = $true
        publish_rejected_missing_srcq_runtime = $externalPreflightRejected
        deployment_sandbox_ignored_host_srcq = $true
        unrelated_skill_preserved = $true
        unrelated_agent_preserved = $true
        explicit_target_count = $manifestTargets.Count
    }
    $result.PSObject.TypeNames.Insert(0, 'AgentBase.Deployment.TestResult')
    $result
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
