param(
    [ValidateSet("Validate", "Status", "Publish", "Rollback")]
    [string]$Action = "Validate",
    [string]$ProjectRoot,
    [string]$CodexRoot,
    [string]$BackupPath,
    [switch]$AllowInstalledDrift,
    [switch]$InstallPortableSettings,
    [ValidateSet("DirectCompatibility", "Plugin")]
    [string]$SkillDeliveryMode = "DirectCompatibility"
)

$ErrorActionPreference = "Stop"

$formatDataPath = Join-Path $PSScriptRoot "manage_agentbase.format.ps1xml"
Update-FormatData -PrependPath $formatDataPath -ErrorAction Stop

$payloadContractPath = Join-Path (Split-Path -Parent $PSScriptRoot) "common\payload_contract.ps1"
. $payloadContractPath
$portableConfigContractPath = Join-Path $PSScriptRoot "portable_config.ps1"
. $portableConfigContractPath
$managedAssetLifecycleScriptPath = Join-Path $PSScriptRoot "managed_asset_lifecycle.ps1"
. $managedAssetLifecycleScriptPath
$portableAgentContractPath = Join-Path $PSScriptRoot "portable_agents.ps1"
. $portableAgentContractPath

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ($InstallPortableSettings -and @("Publish", "Status") -notcontains $Action) {
    throw "InstallPortableSettings is valid only with Action Publish or Status"
}

function Set-AgentBaseResultType {
    param(
        [psobject]$Result,
        [ValidateSet("Validate", "Status", "Publish", "Rollback")]
        [string]$Kind
    )

    $Result.PSObject.TypeNames.Insert(0, "AgentBase.Deployment.${Kind}Result")
    return $Result
}

function Assert-ChildPath {
    param(
        [string]$Root,
        [string]$Path,
        [string]$Label
    )

    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside the approved root: $pathFull"
    }
}

function Get-TextSha256 {
    param(
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-PathFingerprint {
    param(
        [string]$Path,
        [switch]$IncludeProjectOnlyArtifacts
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return "MISSING"
    }

    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to fingerprint a reparse point: $Path"
    }
    if (-not $item.PSIsContainer) {
        return "FILE|$($item.Length)|$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash)"
    }

    $root = $item.FullName.TrimEnd('\')
    $records = @(Get-AgentBasePayloadFiles -Root $root -IncludeProjectOnlyArtifacts:$IncludeProjectOnlyArtifacts | ForEach-Object {
        $relativePath = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
        "$relativePath|$($_.Length)|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
    })
    return Get-TextSha256 ("DIRECTORY" + [Environment]::NewLine + ($records -join [Environment]::NewLine))
}

function Get-TextFileFingerprint {
    param(
        [string]$Text
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($Text)
    return "FILE|$($bytes.Length)|$(Get-TextSha256 $Text)"
}

function Get-TargetSourceFingerprint {
    param(
        [object]$Target
    )

    if ($Target.PSObject.Properties.Name -contains "fingerprint_mode" -and [string]$Target.fingerprint_mode -eq "portable_config") {
        $retiredConfigKeys = if ($Target.PSObject.Properties.Name -contains 'retired_config_keys') { @($Target.retired_config_keys) } else { @() }
        return Get-PortableConfigContractFingerprint -Path ([string]$Target.source_path) -PortableSourcePath ([string]$Target.source_path) -RetiredConfigKeys $retiredConfigKeys
    }
    if ($Target.PSObject.Properties.Name -contains "source_text" -and $null -ne $Target.source_text) {
        return Get-TextFileFingerprint ([string]$Target.source_text)
    }
    return Get-PathFingerprint ([string]$Target.source_path)
}

function Get-TargetInstalledContractFingerprint {
    param(
        [object]$Target
    )

    if ($Target.PSObject.Properties.Name -contains "fingerprint_mode" -and [string]$Target.fingerprint_mode -eq "portable_config") {
        $retiredConfigKeys = if ($Target.PSObject.Properties.Name -contains 'retired_config_keys') { @($Target.retired_config_keys) } else { @() }
        return Get-PortableConfigContractFingerprint -Path ([string]$Target.installed_path) -PortableSourcePath ([string]$Target.source_path) -RetiredConfigKeys $retiredConfigKeys
    }
    return Get-PathFingerprint ([string]$Target.installed_path) -IncludeProjectOnlyArtifacts
}

function Get-ExpectedStagedFingerprint {
    param(
        [object]$Target
    )

    if ($Target.PSObject.Properties.Name -contains "source_text" -and $null -ne $Target.source_text) {
        return Get-TextFileFingerprint ([string]$Target.source_text)
    }
    return Get-TargetSourceFingerprint $Target
}

function Get-BundleFingerprint {
    param(
        [object[]]$Targets,
        [ValidateSet("source", "installed")]
        [string]$Side
    )

    $records = @($Targets | Sort-Object relative_path | ForEach-Object {
        $fingerprint = if ($Side -eq "source") {
            Get-TargetSourceFingerprint $_
        }
        else {
            Get-TargetInstalledContractFingerprint $_
        }
        "$($_.relative_path)|$fingerprint"
    })
    return Get-TextSha256 ($records -join [Environment]::NewLine)
}

function Get-FullInstalledBundleFingerprint {
    param(
        [object[]]$Targets
    )

    $records = @($Targets | Sort-Object relative_path | ForEach-Object {
        "$($_.relative_path)|$(Get-PathFingerprint $_.installed_path -IncludeProjectOnlyArtifacts)"
    })
    return Get-TextSha256 ($records -join [Environment]::NewLine)
}

function Get-RetiredManagedChangeTargets {
    param(
        [object[]]$Targets
    )

    $changes = New-Object 'System.Collections.Generic.List[object]'
    foreach ($target in @($Targets)) {
        if (-not (Test-Path -LiteralPath $target.installed_path)) {
            continue
        }
        $item = Get-Item -LiteralPath $target.installed_path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to retire a managed reparse point: $($target.relative_path)"
        }
        $actualKind = if ($item.PSIsContainer) { 'directory' } else { 'file' }
        if ($actualKind -ne [string]$target.kind) {
            throw "Retired managed path has unexpected kind: $($target.relative_path) (expected $($target.kind), found $actualKind)"
        }
        $null = Get-PathFingerprint -Path $item.FullName -IncludeProjectOnlyArtifacts
        $changes.Add([pscustomobject]@{
            relative_path = [string]$target.relative_path
            source_path = $null
            source_text = $null
            installed_path = [string]$target.installed_path
            kind = [string]$target.kind
            desired_state = "absent"
        })
    }
    return $changes.ToArray()
}

function Get-IncrementalChangeTargets {
    param(
        [object[]]$Targets
    )

    $changes = New-Object 'System.Collections.Generic.List[object]'
    foreach ($target in @($Targets)) {
        if ([string]$target.kind -eq "file") {
            if (Test-Path -LiteralPath $target.installed_path -PathType Container) {
                throw "Managed file target is occupied by a directory: $($target.relative_path)"
            }
            if ((Get-TargetInstalledContractFingerprint $target) -eq (Get-TargetSourceFingerprint $target)) {
                continue
            }
            $change = [ordered]@{
                relative_path = [string]$target.relative_path
                source_path = [string]$target.source_path
                source_text = if ($target.PSObject.Properties.Name -contains "source_text") { $target.source_text } else { $null }
                installed_path = [string]$target.installed_path
                kind = "file"
                desired_state = "present"
            }
            if ($target.PSObject.Properties.Name -contains "fingerprint_mode") {
                $change.fingerprint_mode = [string]$target.fingerprint_mode
            }
            $changes.Add([pscustomobject]$change)
            continue
        }

        if ([string]$target.kind -ne "directory") {
            throw "Unsupported incremental target kind: $($target.kind)"
        }
        if (Test-Path -LiteralPath $target.installed_path -PathType Leaf) {
            throw "Managed directory target is occupied by a file: $($target.relative_path)"
        }

        $sourceRoot = (Get-Item -LiteralPath $target.source_path -Force).FullName.TrimEnd('\')
        $sourceFiles = @{}
        foreach ($file in @(Get-AgentBasePayloadFiles -Root $sourceRoot)) {
            $relativeFile = $file.FullName.Substring($sourceRoot.Length + 1).Replace('\', '/')
            $sourceFiles[$relativeFile] = $file
        }

        $installedRoot = [IO.Path]::GetFullPath([string]$target.installed_path).TrimEnd('\')
        $installedFiles = @{}
        if (Test-Path -LiteralPath $installedRoot -PathType Container) {
            foreach ($file in @(Get-AgentBasePayloadFiles -Root $installedRoot -IncludeProjectOnlyArtifacts)) {
                $relativeFile = $file.FullName.Substring($installedRoot.Length + 1).Replace('\', '/')
                $installedFiles[$relativeFile] = $file
            }
        }

        $relativeFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($relativeFile in @($sourceFiles.Keys)) { $null = $relativeFiles.Add([string]$relativeFile) }
        foreach ($relativeFile in @($installedFiles.Keys)) { $null = $relativeFiles.Add([string]$relativeFile) }
        foreach ($relativeFile in @($relativeFiles | Sort-Object)) {
            $hasSource = $sourceFiles.ContainsKey($relativeFile)
            $hasInstalled = $installedFiles.ContainsKey($relativeFile)
            if ($hasSource -and $hasInstalled -and
                (Get-PathFingerprint $sourceFiles[$relativeFile].FullName) -eq (Get-PathFingerprint $installedFiles[$relativeFile].FullName)) {
                continue
            }

            $relativePath = (([string]$target.relative_path).TrimEnd([char[]]@('\', '/')) + '\' + $relativeFile.Replace('/', '\'))
            $installedPath = Join-Path $installedRoot $relativeFile.Replace('/', '\')
            Assert-ChildPath -Root $installedRoot -Path $installedPath -Label "Incremental managed file"
            $changes.Add([pscustomobject]@{
                relative_path = $relativePath
                source_path = if ($hasSource) { [string]$sourceFiles[$relativeFile].FullName } else { $null }
                source_text = $null
                installed_path = $installedPath
                kind = "file"
                desired_state = if ($hasSource) { "present" } else { "absent" }
            })
        }
    }
    return $changes.ToArray()
}

function Remove-EmptyManagedProjectOnlyDirectories {
    param(
        [object[]]$Targets
    )

    foreach ($target in @($Targets | Where-Object { [string]$_.kind -eq "directory" })) {
        $installedRoot = [IO.Path]::GetFullPath([string]$target.installed_path).TrimEnd('\')
        if (-not (Test-Path -LiteralPath $installedRoot -PathType Container)) {
            continue
        }
        $directories = @(Get-ChildItem -LiteralPath $installedRoot -Recurse -Force -Directory | Sort-Object { $_.FullName.Length } -Descending)
        foreach ($directory in $directories) {
            $relativeDirectory = $directory.FullName.Substring($installedRoot.Length + 1).Replace('\', '/')
            if (-not (Test-AgentBaseProjectOnlyArtifact -RelativePath ($relativeDirectory + "/.agentbase-directory-probe"))) {
                continue
            }
            if ($null -ne (Get-ChildItem -LiteralPath $directory.FullName -Force | Select-Object -First 1)) {
                continue
            }
            Assert-ChildPath -Root $installedRoot -Path $directory.FullName -Label "Empty project-only payload directory"
            Remove-Item -LiteralPath $directory.FullName -Force
        }
    }
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Text
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Value
    )

    $json = $Value | ConvertTo-Json -Depth 10
    Write-Utf8NoBomFile -Path $Path -Text ($json + [Environment]::NewLine)
}

function Get-ValidatedRoutingEvidence {
    param(
        [string]$Root
    )

    $evidencePath = Join-Path $Root "development\skill-routing\evidence\current.json"
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        throw "Current staged routing evidence is missing: $evidencePath"
    }
    $evidenceItem = Get-Item -LiteralPath $evidencePath -Force
    if (($evidenceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Current staged routing evidence must be a real file: $evidencePath"
    }

    & (Join-Path $Root "development\skill-routing\validate_routing_results.ps1") -ProjectRoot $Root -ResultsPath $evidencePath | Out-Null
    & (Join-Path $Root "development\skill-routing\validate_routing_attempt_history.ps1") -ProjectRoot $Root -AttemptHistoryPath (Join-Path $Root "development\skill-routing\evidence\attempts.json") -CurrentEvidencePath $evidencePath | Out-Null
    $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -DateKind String
    if ([string]::IsNullOrWhiteSpace([string]$evidence.evaluator.id)) {
        throw "Current staged routing evidence does not identify its routing evaluator run"
    }
    return [pscustomobject]@{
        path = $evidenceItem.FullName
        sha256 = (Get-FileHash -LiteralPath $evidenceItem.FullName -Algorithm SHA256).Hash
        evaluator_id = [string]$evidence.evaluator.id
        evaluator_model = [string]$evidence.evaluator.model
        evaluator_runtime = [string]$evidence.evaluator.runtime
        evaluated_at_utc = [string]$evidence.evaluator.evaluated_at_utc
        repository_accessed = [bool]$evidence.evaluator.repository_accessed
        hidden_expectations_accessed = [bool]$evidence.evaluator.hidden_expectations_accessed
        evaluation_capsule_sha256 = [string]$evidence.evaluation_capsule_sha256
        candidate_bundle_sha256 = [string]$evidence.candidate_bundle_sha256
        evaluation_input_sha256 = [string]$evidence.evaluation_input_sha256
        evaluation_generation_sha256 = [string]$evidence.evaluation_generation_sha256
        routing_receipt_id = [string]$evidence.receipt_id
        policy_receipt_id = [string]$evidence.policy_evaluation.receipt_id
        reference_receipt_id = [string]$evidence.reference_evaluation.receipt_id
        case_count = @($evidence.cases).Count
    }
}

function Get-LatestPublishedManifest {
    param(
        [string]$InstallRoot,
        [ValidateSet("DirectCompatibility", "Plugin")]
        [string]$DeliveryMode = "DirectCompatibility",
        [bool]$PortableSettingsInstalled = $false,
        [switch]$IgnorePublicationScope,
        [int]$MinimumSchemaVersion = 1
    )

    $backupsRoot = Join-Path $InstallRoot "backups"
    if (-not (Test-Path -LiteralPath $backupsRoot -PathType Container)) {
        return $null
    }

    foreach ($backupDirectory in @(Get-ChildItem -LiteralPath $backupsRoot -Directory -Filter "AgentBase-*" -Force | Sort-Object Name -Descending | Select-Object -First 200)) {
        if (($backupDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        $manifestPath = Join-Path $backupDirectory.FullName "manifest.json"
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            continue
        }
        $manifestItem = Get-Item -LiteralPath $manifestPath -Force
        if (($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            continue
        }
        if ([string]$manifest.state -ne "published" -or @(1, 2, 3, 4, 5, 6, 7) -notcontains [int]$manifest.schema_version) {
            continue
        }
        if ([int]$manifest.schema_version -lt $MinimumSchemaVersion) {
            continue
        }
        if (-not [string]::Equals([IO.Path]::GetFullPath([string]$manifest.codex_root), [IO.Path]::GetFullPath($InstallRoot), [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $manifestMode = if ($manifest.PSObject.Properties.Name -contains "skill_delivery_mode") {
            [string]$manifest.skill_delivery_mode
        }
        else {
            "DirectCompatibility"
        }
        if (-not $IgnorePublicationScope -and
            ($manifestMode -ne $DeliveryMode -or [bool]$manifest.portable_settings_installed -ne $PortableSettingsInstalled)) {
            continue
        }
        return [pscustomobject]@{
            path = $manifestItem.FullName
            document = $manifest
        }
    }
    return $null
}

function Get-PluginModeDirectCompatibilityConflicts {
    param(
        [string]$InstallRoot,
        [object[]]$RequiredSkills
    )

    $conflicts = New-Object 'System.Collections.Generic.List[string]'
    foreach ($skill in @($RequiredSkills)) {
        $relativePath = "skills\$([string]$skill)"
        if (Test-Path -LiteralPath (Join-Path (Join-Path $InstallRoot $relativePath) "SKILL.md") -PathType Leaf) {
            $conflicts.Add($relativePath)
        }
    }

    $hooksPath = Join-Path $InstallRoot "hooks.json"
    if (Test-Path -LiteralPath $hooksPath -PathType Leaf) {
        $hooksItem = Get-Item -LiteralPath $hooksPath -Force
        if (($hooksItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $conflicts.Add("hooks.json (unverified reparse point)")
        }
        else {
            try {
                $hooksDocument = Get-Content -LiteralPath $hooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $hasAgentBaseHook = $false
                if ($hooksDocument.PSObject.Properties.Name -contains "hooks") {
                    foreach ($eventProperty in @($hooksDocument.hooks.PSObject.Properties)) {
                        foreach ($group in @($eventProperty.Value)) {
                            foreach ($handler in @($group.hooks)) {
                                foreach ($commandProperty in @("command", "commandWindows")) {
                                    if ($handler.PSObject.Properties.Name -contains $commandProperty) {
                                        $commandText = [string]$handler.$commandProperty
                                        if ($commandText -match '(?i)(codex-event-logger|codex-qq-hook)') {
                                            $hasAgentBaseHook = $true
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                if ($hasAgentBaseHook) {
                    $conflicts.Add("hooks.json (AgentBase direct hook)")
                }
            }
            catch {
                # Plugin delivery does not own unrelated global hooks. An unreadable file is
                # handled by the host; it is not evidence of an AgentBase direct-hook conflict.
            }
        }
    }
    return @($conflicts)
}

function Get-ReversedArray {
    param(
        [object]$Values
    )

    [object[]]$items = @($Values | ForEach-Object { $_ })
    [Array]::Reverse($items)
    return $items
}

function Set-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )

    if ($Object -is [Collections.IDictionary]) {
        $Object[$Name] = $Value
        return
    }
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
        return
    }
    $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
}

function Test-PortableConfigSource {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Portable Codex config is missing: $Path"
    }

    $expectedLines = @(
        'model_reasoning_summary = "none"'
        'model_verbosity = "low"'
        'personality = "pragmatic"'
        'approval_policy = "never"'
        'sandbox_mode = "danger-full-access"'
        'web_search = "live"'
        'service_tier = "default"'
        'project_doc_max_bytes = 65536'
        '[agents]'
        'enabled = true'
        'default_subagent_model = "gpt-5.6-luna"'
        'default_subagent_reasoning_effort = "max"'
        '[features]'
        'hooks = true'
        'multi_agent = true'
        'js_repl = false'
        '[desktop]'
        'conversationDetailMode = "STEPS_COMMANDS"'
        'followUpQueueMode = "queue"'
        'notifications-turn-mode = "always"'
        'ambient-suggestions-enabled = false'
        'show-context-window-usage = true'
        'enabled-reasoning-efforts = ["low", "medium", "high", "xhigh", "ultra", "max"]'
    )
    $actualLines = @(Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and -not $_.StartsWith('#')
    })
    $unexpected = @($actualLines | Where-Object { $expectedLines -notcontains $_ })
    if ($unexpected.Count -gt 0) {
        throw "Portable Codex config contains an unreviewed line: $($unexpected[0])"
    }
    $missing = @($expectedLines | Where-Object { $actualLines -notcontains $_ })
    if ($missing.Count -gt 0) {
        throw "Portable Codex config is missing a required line: $($missing[0])"
    }
    $duplicates = @($actualLines | Group-Object | Where-Object { $_.Count -gt 1 })
    if ($duplicates.Count -gt 0) {
        throw "Portable Codex config contains a duplicate line: $($duplicates[0].Name)"
    }
    if (($actualLines -join [Environment]::NewLine) -ne ($expectedLines -join [Environment]::NewLine)) {
        throw "Portable Codex config structure or setting order differs from the reviewed contract"
    }

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $payload = $actualLines -join [Environment]::NewLine
    if ($payload -match '(?i)([a-z]:[\\/]|\\\\|https?://|api[_-]?key|password|secret|credential|trusted_hash|notify\s*=|mcp_servers|projects|marketplaces|plugins|shell_environment_policy|\[skills\]|\[hooks\])') {
        throw "Portable Codex config contains machine state, a machine path, or a sensitive setting"
    }
    if ($raw -match '(?i)([a-z]:[\\/]|\\\\|https?://|api[_-]?key\s*=|password\s*=|secret\s*=|credential\s*=|trusted_hash\s*=)') {
        throw "Portable Codex config comments contain a machine path or sensitive assignment"
    }
}

function Test-HooksTemplateSource {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Portable hooks template is missing: $Path"
    }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    try {
        $document = $raw | ConvertFrom-Json
    }
    catch {
        throw "Portable hooks template is not valid JSON: $($_.Exception.Message)"
    }
    if ($raw -match '(?i)([a-z]:\\\\|https?://|api[_-]?key|password|secret|credential|trusted_hash)') {
        throw "Portable hooks template contains a machine path or a sensitive setting"
    }
    $placeholderCount = [regex]::Matches($raw, '\{\{CODEX_ROOT\}\}').Count
    if ($placeholderCount -ne 12) {
        throw "Portable hooks template must contain exactly 12 Codex-root placeholders; found $placeholderCount"
    }

    $expectedEvents = @("PostToolUse", "PreToolUse", "Stop", "UserPromptSubmit")
    $actualEvents = @($document.hooks.PSObject.Properties.Name | Sort-Object)
    if (($actualEvents -join '|') -ne ($expectedEvents -join '|')) {
        throw "Portable hooks template contains an unexpected event set: $($actualEvents -join ', ')"
    }
    $expectedHandlerCounts = @{
        UserPromptSubmit = 1
        Stop = 2
        PreToolUse = 1
        PostToolUse = 1
    }
    $eventLoggerCommand = 'pwsh.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{{CODEX_ROOT}}\skills\codex-event-logger\scripts\codex_event_logger.ps1"'
    $qqCommand = 'pwsh.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{{CODEX_ROOT}}\skills\codex-qq-hook\scripts\codex_stop_qq_notify.ps1" -CodexRoot "{{CODEX_ROOT}}"'
    $allowedCommands = @($eventLoggerCommand, $qqCommand)
    foreach ($eventName in $expectedEvents) {
        $groups = @($document.hooks.$eventName)
        if ($groups.Count -ne 1) {
            throw "Portable hooks template must contain one matcher group for $eventName"
        }
        $handlers = @($groups[0].hooks)
        if ($handlers.Count -ne $expectedHandlerCounts[$eventName]) {
            throw "Portable hooks template contains an unexpected handler count for $eventName"
        }
        foreach ($handler in $handlers) {
            if ([string]$handler.type -ne "command") {
                throw "Portable hooks template supports command handlers only"
            }
            if ($allowedCommands -notcontains [string]$handler.command -or [string]$handler.commandWindows -ne [string]$handler.command) {
                throw "Portable hooks template contains an unreviewed command for $eventName"
            }
        }
    }
}

function Get-ResolvedHooksText {
    param(
        [string]$TemplatePath,
        [string]$InstallRoot
    )

    $raw = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8
    $jsonEscapedRoot = $InstallRoot.Replace('\', '\\')
    $resolved = $raw.Replace('{{CODEX_ROOT}}', $jsonEscapedRoot)
    if ($resolved.Contains('{{CODEX_ROOT}}')) {
        throw "Portable hooks template contains an unresolved Codex-root placeholder"
    }
    try {
        $null = $resolved | ConvertFrom-Json
    }
    catch {
        throw "Resolved portable hooks are not valid JSON: $($_.Exception.Message)"
    }
    if (-not $resolved.EndsWith([Environment]::NewLine)) {
        $resolved += [Environment]::NewLine
    }
    return $resolved
}

function Get-ValidatedSource {
    param(
        [string]$Root,
        [string]$InstallRoot,
        [bool]$IncludePortableSettings,
        [ValidateSet("DirectCompatibility", "Plugin")]
        [string]$DeliveryMode,
        [object]$PreviousManifest
    )

    & (Join-Path $Root "development\skill-routing\validate_contract.ps1") -ProjectRoot $Root | Out-Null
    $routingEvidence = Get-ValidatedRoutingEvidence -Root $Root
    $hostBootstrapPath = Join-Path $Root "development\codex-deployment\bootstrap_windows.ps1"
    if (-not (Test-Path -LiteralPath $hostBootstrapPath -PathType Leaf)) {
        throw "Windows host bootstrap is missing: $hostBootstrapPath"
    }
    $hostBootstrapContent = Get-Content -LiteralPath $hostBootstrapPath -Raw -Encoding UTF8
    $requiredBootstrapFragments = @(
        'ValidateSet("Check", "Install")'
        'ValidateSet("Model", "Machine")'
        'Format-HostPrerequisiteModelResult'
        'Microsoft.PowerShell'
        'sharkdp.fd'
        'BenBoyter.scc'
        'sharkdp.hyperfine'
        'Python.Python.3.13'
        'OpenJS.NodeJS.LTS'
        '@ast-grep/cli@0.44.1'
        '@openai/codex@0.148.0'
        'Test-UserNpmPathPrecedence'
        'isolation_options_supported'
        '--ignore-user-config'
        '$version.Major -ge 7'
        '--max-results'
        '[version]"22.9.0"'
        '[version]"3.11.0"'
        'winget.exe'
        'npm.cmd'
    )
    foreach ($requiredBootstrapFragment in $requiredBootstrapFragments) {
        if (-not $hostBootstrapContent.Contains($requiredBootstrapFragment)) {
            throw "Windows host bootstrap is missing required contract fragment: $requiredBootstrapFragment"
        }
    }
    $projectAgentsContent = Get-Content -LiteralPath (Join-Path $Root "AGENTS.md") -Raw -Encoding UTF8
    $deploymentReadmeContent = Get-Content -LiteralPath (Join-Path $Root "development\codex-deployment\README.md") -Raw -Encoding UTF8
    if (-not $projectAgentsContent.Contains('bootstrap_windows.ps1') -or -not $projectAgentsContent.Contains('-Action Install') -or
        -not $projectAgentsContent.Contains('用户级 Codex CLI')) {
        throw "Project AGENTS.md does not route Windows reproduction through the host bootstrap"
    }
    if (-not $deploymentReadmeContent.Contains('bootstrap_windows.ps1') -or -not $deploymentReadmeContent.Contains('-Action Check') -or
        -not $deploymentReadmeContent.Contains('-View Machine')) {
        throw "Deployment README does not document the Windows host bootstrap lifecycle"
    }
    if (-not $deploymentReadmeContent.Contains('install-srcq.ps1') -or -not $deploymentReadmeContent.Contains('ready=true') -or
        -not $deploymentReadmeContent.Contains('srcq doctor') -or -not $deploymentReadmeContent.Contains('srcq query scc doctor')) {
        throw "Deployment README does not retain the independent srcq runtime preflight"
    }
    $portableConfigPath = Join-Path $Root "global\config.toml"
    $hooksTemplatePath = Join-Path $Root "global\hooks.template.json"
    $portableAgentsPath = Join-Path $Root "global\agents"
    Test-PortableConfigSource -Path $portableConfigPath
    Test-HooksTemplateSource -Path $hooksTemplatePath
    $portableAgentFiles = @(Get-ValidatedPortableAgentSources -Path $portableAgentsPath)
    $portableSettingsRecords = @(
        "global/config.toml|$(Get-PathFingerprint $portableConfigPath)"
        "global/hooks.template.json|$(Get-PathFingerprint $hooksTemplatePath)"
    )
    foreach ($portableAgentFile in $portableAgentFiles) {
        $portableSettingsRecords += "global/agents/$($portableAgentFile.Name)|$(Get-PathFingerprint $portableAgentFile.FullName)"
    }
    $portableSettingsFingerprint = Get-TextSha256 ($portableSettingsRecords -join [Environment]::NewLine)

    $contract = Get-Content -LiteralPath (Join-Path $Root "development\skill-routing\trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $portableConfigText = Get-Content -LiteralPath $portableConfigPath -Raw -Encoding UTF8
    $currentConfigUnits = @(Get-PortableConfigManagedUnits -PortableText $portableConfigText)
    $potentialTargets = New-Object 'System.Collections.Generic.List[object]'
    $potentialTargets.Add([pscustomobject]@{
        lifecycle_id = 'global:agents-md'
        relative_path = 'AGENTS.md'
        source_path = Join-Path $Root 'global\AGENTS.md'
        target_kind = 'file'
        delivery_modes = @('DirectCompatibility', 'Plugin')
        requires_portable_settings = $false
        role = 'plain'
    })
    foreach ($skill in @($contract.required_skills)) {
        $potentialTargets.Add([pscustomobject]@{
            lifecycle_id = "skill:$([string]$skill)"
            relative_path = "skills\$([string]$skill)"
            source_path = Join-Path (Join-Path $Root 'skills') ([string]$skill)
            target_kind = 'directory'
            delivery_modes = @('DirectCompatibility')
            requires_portable_settings = $false
            role = 'plain'
        })
    }
    $potentialTargets.Add([pscustomobject]@{
        lifecycle_id = 'settings:config'
        relative_path = 'config.toml'
        source_path = $portableConfigPath
        target_kind = 'file'
        delivery_modes = @('DirectCompatibility', 'Plugin')
        requires_portable_settings = $true
        role = 'portable_config'
    })
    $potentialTargets.Add([pscustomobject]@{
        lifecycle_id = 'settings:hooks'
        relative_path = 'hooks.json'
        source_path = $hooksTemplatePath
        target_kind = 'file'
        delivery_modes = @('DirectCompatibility')
        requires_portable_settings = $true
        role = 'hooks'
    })
    foreach ($portableAgentFile in $portableAgentFiles) {
        $potentialTargets.Add([pscustomobject]@{
            lifecycle_id = "agent:$($portableAgentFile.BaseName)"
            relative_path = "agents\$($portableAgentFile.Name)"
            source_path = $portableAgentFile.FullName
            target_kind = 'file'
            delivery_modes = @('DirectCompatibility', 'Plugin')
            requires_portable_settings = $true
            role = 'plain'
        })
    }

    $currentPathUnits = @($potentialTargets | ForEach-Object {
        [pscustomobject]@{
            id = [string]$_.lifecycle_id
            kind = 'path'
            relative_path = [string]$_.relative_path
            path_kind = [string]$_.target_kind
            delivery_modes = @($_.delivery_modes)
            requires_portable_settings = [bool]$_.requires_portable_settings
        }
    })
    $lifecyclePath = Join-Path $Root 'development\codex-deployment\managed_asset_lifecycle.json'
    $lifecycle = Get-ManagedAssetLifecycleContract -Path $lifecyclePath -CurrentPathUnits $currentPathUnits -CurrentConfigUnits $currentConfigUnits -PreviousManifest $PreviousManifest
    $retiredPathUnits = @(Get-SelectedRetiredManagedPathUnits -Contract $lifecycle -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)
    $retiredConfigUnits = @(Get-SelectedRetiredManagedConfigUnits -Contract $lifecycle -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)
    $retiredConfigDiagnostics = if (-not [string]::IsNullOrWhiteSpace($InstallRoot) -and $IncludePortableSettings) {
        @(Get-RetiredPortableConfigKeyDiagnostics -InstalledPath (Join-Path $InstallRoot 'config.toml') -RetiredConfigKeys $retiredConfigUnits -PreviousManifest $PreviousManifest)
    }
    else {
        @()
    }

    $targets = New-Object 'System.Collections.Generic.List[object]'
    foreach ($potential in @($potentialTargets | Where-Object {
        @($_.delivery_modes) -contains $DeliveryMode -and
        (-not [bool]$_.requires_portable_settings -or $IncludePortableSettings)
    })) {
        if ([string]::IsNullOrWhiteSpace($InstallRoot) -and [bool]$potential.requires_portable_settings) {
            throw 'InstallRoot is required when portable settings are selected'
        }
        $installedPath = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot ([string]$potential.relative_path) }
        $target = [ordered]@{
            lifecycle_id = [string]$potential.lifecycle_id
            relative_path = [string]$potential.relative_path
            source_path = [string]$potential.source_path
            source_text = $null
            installed_path = $installedPath
            kind = [string]$potential.target_kind
        }
        if ([string]$potential.role -eq 'portable_config') {
            $target.source_text = Get-MergedPortableConfigText -PortableSourcePath $portableConfigPath -InstalledPath $installedPath -RetiredConfigKeys $retiredConfigUnits
            $target.fingerprint_mode = 'portable_config'
            $target.retired_config_keys = @($retiredConfigUnits)
        }
        elseif ([string]$potential.role -eq 'hooks') {
            $target.source_text = Get-ResolvedHooksText -TemplatePath $hooksTemplatePath -InstallRoot $InstallRoot
        }
        $targets.Add([pscustomobject]$target)
    }
    $retiredPathTargets = @($retiredPathUnits | ForEach-Object {
        $installedPath = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot ([string]$_.relative_path) }
        if ($null -ne $installedPath) {
            Assert-ChildPath -Root $InstallRoot -Path $installedPath -Label 'Retired managed path'
        }
        [pscustomobject]@{
            lifecycle_id = [string]$_.id
            relative_path = [string]$_.relative_path
            source_path = $null
            source_text = $null
            installed_path = $installedPath
            kind = [string]$_.path_kind
            desired_state = 'absent'
        }
    })
    $lifecycleReceiptUnits = @(Get-ManagedAssetLifecycleReceiptUnits -Contract $lifecycle -CurrentConfigUnits $currentConfigUnits -PreviousManifest $PreviousManifest -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)

    $mcpPackagePath = Join-Path $Root "mcp\vscode-lsp-mcp\package.json"
    if (-not (Test-Path -LiteralPath $mcpPackagePath -PathType Leaf)) {
        throw "vscode-lsp-mcp package.json is missing: $mcpPackagePath"
    }
    $mcpPackage = Get-Content -LiteralPath $mcpPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$mcpPackage.scripts.'release:build') -or [string]::IsNullOrWhiteSpace([string]$mcpPackage.scripts.'release:verify')) {
        throw "vscode-lsp-mcp must retain release:build and release:verify as its authoritative release entry points"
    }

    return [pscustomobject]@{
        contract = $contract
        targets = $targets.ToArray()
        mcp_name = [string]$mcpPackage.name
        mcp_version = [string]$mcpPackage.version
        portable_settings_sha256 = $portableSettingsFingerprint
        portable_config_path = $portableConfigPath
        hooks_template_path = $hooksTemplatePath
        portable_agents_path = $portableAgentsPath
        portable_agent_names = @($portableAgentFiles.BaseName)
        managed_asset_lifecycle = $lifecycle
        managed_asset_lifecycle_receipt_units = @($lifecycleReceiptUnits)
        retired_path_targets = @($retiredPathTargets)
        retired_config_units = @($retiredConfigUnits)
        retired_config_diagnostics = @($retiredConfigDiagnostics)
        host_bootstrap_path = $hostBootstrapPath
        routing_evidence = $routingEvidence
        skill_delivery_mode = $DeliveryMode
        skills_managed = $DeliveryMode -eq "DirectCompatibility"
        hooks_managed = $IncludePortableSettings -and $DeliveryMode -eq "DirectCompatibility"
    }
}

function Resolve-CodexRoot {
    param(
        [string]$RequestedRoot,
        [bool]$Create
    )

    if ([string]::IsNullOrWhiteSpace($RequestedRoot)) {
        throw "CodexRoot must be supplied explicitly for $Action"
    }
    $fullPath = [IO.Path]::GetFullPath($RequestedRoot)
    if (-not (Test-Path -LiteralPath $fullPath)) {
        if (-not $Create) {
            throw "CodexRoot does not exist: $fullPath"
        }
        $parent = Split-Path -Parent $fullPath
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "CodexRoot parent must already exist: $parent"
        }
        New-Item -ItemType Directory -Path $fullPath | Out-Null
    }
    $item = Get-Item -LiteralPath $fullPath -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "CodexRoot must be a real directory, not a file or reparse point: $fullPath"
    }
    return $item.FullName
}

function Test-DeploymentSandboxRoot {
    param([string]$Root, [string]$InstallRoot)
    $sandboxRoot = [IO.Path]::GetFullPath((Join-Path $Root 'development\codex-deployment\sandbox')).TrimEnd('\') + '\'
    $candidate = [IO.Path]::GetFullPath($InstallRoot)
    $candidate.StartsWith($sandboxRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Get-SrcqRuntimePreflight {
    param(
        [string]$Root,
        [bool]$Required
    )
    try {
        $installer = Join-Path $Root 'tools\srcq\scripts\install-srcq.ps1'
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
            throw "srcq installer status entry is missing: $installer"
        }
        $cargoManifest = Join-Path $Root 'tools\srcq\Cargo.toml'
        $cargoText = Get-Content -LiteralPath $cargoManifest -Raw -Encoding UTF8
        $workspacePackage = [regex]::Match($cargoText, '(?ms)^\[workspace\.package\]\s*$(.*?)(?=^\[|\z)')
        $versionMatch = if ($workspacePackage.Success) { [regex]::Match($workspacePackage.Groups[1].Value, '(?m)^version\s*=\s*"([^"]+)"\s*$') } else { $null }
        if ($null -eq $versionMatch -or -not $versionMatch.Success) {
            throw "Cannot read the expected srcq workspace version"
        }
        $expectedVersion = $versionMatch.Groups[1].Value

        $statusText = @(& $installer Status -View Machine 2>&1)
        $statusExit = $LASTEXITCODE
        $status = $null
        try { $status = ($statusText -join [Environment]::NewLine) | ConvertFrom-Json } catch { }
        if ($statusExit -ne 0 -or $null -eq $status -or -not [bool]$status.ready) {
            $detail = if ($null -ne $status -and -not [string]::IsNullOrWhiteSpace([string]$status.error)) { [string]$status.error } else { $statusText -join ' ' }
            throw "srcq runtime is not ready: $detail. Run tools\srcq\scripts\install-srcq.ps1 Install with the current validated archive, then retry."
        }
        if ([string]$status.version -ne $expectedVersion -or [string]$status.binaryVersion -ne "srcq $expectedVersion") {
            throw "srcq runtime version does not match project version $expectedVersion"
        }
        if ([string]$status.path.backend -ne 'User' -or -not [bool]$status.pathReady -or [int]$status.pathEntryCount -ne 1) {
            throw "srcq runtime must have exactly one installer-managed user PATH entry"
        }
        $binary = [IO.Path]::GetFullPath([string]$status.binary)
        $doctorText = @(& $binary doctor 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "srcq doctor failed: $($doctorText -join ' ')"
        }
        $sccDoctorText = @(& $binary query scc doctor --output machine 2>&1)
        $sccDoctorExit = $LASTEXITCODE
        $sccDoctorDocument = $sccDoctorText -join [Environment]::NewLine
        $sccVersionMatch = [regex]::Match($sccDoctorDocument, '(?m)^"observed_version": (?<value>"(?:[^"\\]|\\.)*")\s*$')
        $sccObservedVersion = if ($sccVersionMatch.Success) {
            try { [string]($sccVersionMatch.Groups['value'].Value | ConvertFrom-Json) } catch { $null }
        } else { $null }
        if ($sccDoctorExit -ne 0 -or
            $sccDoctorDocument -notmatch '(?m)^\s+"schema": "sgy\.query\.doctor/v1"\s*$' -or
            $sccDoctorDocument -notmatch '(?m)^\s+"backend": "scc"\s*$' -or
            $sccDoctorDocument -notmatch '(?m)^\s+"ok": true\s*$' -or
            $sccObservedVersion -notmatch '^scc version \d+\.\d+\.\d+') {
            throw "srcq scc doctor failed: $($sccDoctorText -join ' '). Run development\codex-deployment\bootstrap_windows.ps1 -Action Install, restart the Codex desktop host if PATH changed, then retry."
        }
        return [pscustomobject]@{
            in_scope = $true
            ready = $true
            version = $expectedVersion
            binary = $binary
            integrity = [string]$status.integrity
            path_entry_count = [int]$status.pathEntryCount
            doctor_ok = $true
            scc_doctor_ok = $true
            scc_version = $sccObservedVersion
        }
    }
    catch {
        if ($Required) { throw }
        return [pscustomobject]@{
            in_scope = $true
            ready = $false
            version = $null
            binary = $null
            integrity = $null
            path_entry_count = 0
            doctor_ok = $false
            scc_doctor_ok = $false
            scc_version = $null
            error = $_.Exception.Message
        }
    }
}

if ($Action -eq "Validate") {
    & (Join-Path $ProjectRoot "development\skill-routing\test_routing_infrastructure.ps1") -ProjectRoot $ProjectRoot | Out-Null
    & (Join-Path $ProjectRoot "development\agent-evaluation\test_agent_evaluation_infrastructure.ps1") -ProjectRoot $ProjectRoot | Out-Null
}

if ($Action -eq "Validate") {
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $null -IncludePortableSettings $false -DeliveryMode $SkillDeliveryMode
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    $result = [pscustomobject]@{
        action = "Validate"
        skill_delivery_mode = $SkillDeliveryMode
        source_bundle_sha256 = $sourceFingerprint
        global_bytes = (Get-Item -LiteralPath (Join-Path $ProjectRoot "global\AGENTS.md")).Length
        skill_count = @($source.contract.required_skills).Count
        mcp = "$($source.mcp_name)@$($source.mcp_version)"
        mcp_release_owner = Join-Path $ProjectRoot "mcp\vscode-lsp-mcp"
        portable_settings_sha256 = $source.portable_settings_sha256
        portable_config = $source.portable_config_path
        hooks_template = $source.hooks_template_path
        portable_agents = $source.portable_agents_path
        portable_agent_count = @($source.portable_agent_names).Count
        managed_asset_lifecycle = $source.managed_asset_lifecycle.path
        managed_asset_lifecycle_sha256 = $source.managed_asset_lifecycle.sha256
        managed_asset_unit_count = @($source.managed_asset_lifecycle.units).Count
        managed_asset_present_count = @($source.managed_asset_lifecycle.units | Where-Object { [string]$_.state -eq 'present' }).Count
        managed_asset_retired_count = @($source.managed_asset_lifecycle.units | Where-Object { [string]$_.state -eq 'retired' }).Count
        managed_asset_transferred_count = @($source.managed_asset_lifecycle.units | Where-Object { [string]$_.state -eq 'transferred' }).Count
        host_bootstrap = $source.host_bootstrap_path
        routing_evidence = $source.routing_evidence.path
        routing_evidence_sha256 = $source.routing_evidence.sha256
        routing_case_count = $source.routing_evidence.case_count
    }
    Set-AgentBaseResultType -Result $result -Kind Validate
    return
}

$CodexRoot = Resolve-CodexRoot -RequestedRoot $CodexRoot -Create ($Action -eq "Publish")

if ($Action -eq "Publish" -and -not (Test-DeploymentSandboxRoot -Root $ProjectRoot -InstallRoot $CodexRoot)) {
    & (Join-Path $ProjectRoot "development\skill-routing\test_routing_infrastructure.ps1") -ProjectRoot $ProjectRoot | Out-Null
    & (Join-Path $ProjectRoot "development\agent-evaluation\test_agent_evaluation_infrastructure.ps1") -ProjectRoot $ProjectRoot | Out-Null
}

if ($Action -eq "Status") {
    $publishRecord = Get-LatestPublishedManifest -InstallRoot $CodexRoot -DeliveryMode $SkillDeliveryMode -PortableSettingsInstalled ([bool]$InstallPortableSettings)
    $manifest = if ($null -eq $publishRecord) { $null } else { $publishRecord.document }
    $lifecyclePublishRecord = Get-LatestPublishedManifest -InstallRoot $CodexRoot -IgnorePublicationScope -MinimumSchemaVersion 7
    $lifecycleManifest = if ($null -eq $lifecyclePublishRecord) { $null } else { $lifecyclePublishRecord.document }
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $CodexRoot -IncludePortableSettings ([bool]$InstallPortableSettings) -DeliveryMode $SkillDeliveryMode -PreviousManifest $lifecycleManifest
    $srcqRuntime = if (Test-DeploymentSandboxRoot -Root $ProjectRoot -InstallRoot $CodexRoot) {
        [pscustomobject]@{ in_scope = $false; ready = $null; version = $null; binary = $null; integrity = $null; path_entry_count = 0; doctor_ok = $null; scc_doctor_ok = $null; scc_version = $null }
    } else {
        Get-SrcqRuntimePreflight -Root $ProjectRoot -Required $false
    }
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    $installedFingerprint = Get-BundleFingerprint -Targets $source.targets -Side installed
    $installedFullFingerprint = Get-FullInstalledBundleFingerprint -Targets $source.targets
    $retiredManagedTargets = @(Get-RetiredManagedChangeTargets -Targets $source.retired_path_targets)
    $retiredConfigDiagnostics = @($source.retired_config_diagnostics)
    $retiredConfigModified = @($retiredConfigDiagnostics | Where-Object { [string]$_.status -eq 'modified' })
    $retiredConfigUnverifiable = @($retiredConfigDiagnostics | Where-Object { [string]$_.status -eq 'unverifiable' })
    $directCompatibilityConflicts = if ($SkillDeliveryMode -eq "Plugin") {
        @(Get-PluginModeDirectCompatibilityConflicts -InstallRoot $CodexRoot -RequiredSkills @($source.contract.required_skills))
    }
    else {
        @()
    }
    $pluginModeReady = $SkillDeliveryMode -ne "Plugin" -or $directCompatibilityConflicts.Count -eq 0
    $manifestMatchesSource = $null -ne $manifest -and [string]$manifest.source_bundle_sha256 -eq $sourceFingerprint
    $manifestInstalledContractFingerprint = if ($null -ne $manifest -and $manifest.PSObject.Properties.Name -contains "installed_contract_bundle_sha256") {
        [string]$manifest.installed_contract_bundle_sha256
    }
    elseif ($null -ne $manifest) {
        [string]$manifest.installed_bundle_sha256
    }
    else {
        $null
    }
    $manifestMatchesInstalled = $null -ne $manifest -and $manifestInstalledContractFingerprint -eq $installedFingerprint
    $manifestEvidenceMatches = $null -ne $manifest -and
        $manifest.PSObject.Properties.Name -contains "routing_evidence_sha256" -and
        [string]$manifest.routing_evidence_sha256 -eq [string]$source.routing_evidence.sha256
    $manifestLifecycleMatches = $null -ne $manifest -and
        $manifest.PSObject.Properties.Name -contains 'managed_asset_lifecycle_sha256' -and
        [string]$manifest.managed_asset_lifecycle_sha256 -eq [string]$source.managed_asset_lifecycle.sha256
    $installedMatchesSource = $installedFingerprint -eq $sourceFingerprint
    $publicationGaps = New-Object 'System.Collections.Generic.List[string]'
    if (-not $installedMatchesSource) { $publicationGaps.Add("installed_payload_differs_from_source") }
    if ($null -eq $manifest) { $publicationGaps.Add("published_manifest_missing") }
    elseif (-not $manifestMatchesSource) { $publicationGaps.Add("published_manifest_source_is_stale") }
    if ($null -ne $manifest -and -not $manifestMatchesInstalled) { $publicationGaps.Add("installed_payload_differs_from_manifest") }
    if ($null -ne $manifest -and -not $manifestEvidenceMatches) { $publicationGaps.Add("published_manifest_routing_evidence_is_stale") }
    if ($null -ne $manifest -and -not $manifestLifecycleMatches) { $publicationGaps.Add("published_manifest_managed_asset_lifecycle_is_stale") }
    if ($retiredManagedTargets.Count -gt 0) { $publicationGaps.Add("retired_managed_paths_present") }
    if ($retiredConfigDiagnostics.Count -gt 0) { $publicationGaps.Add('retired_managed_config_keys_present') }
    if ($retiredConfigModified.Count -gt 0) { $publicationGaps.Add('retired_managed_config_keys_modified') }
    if ($retiredConfigUnverifiable.Count -gt 0) { $publicationGaps.Add('retired_managed_config_keys_unverifiable') }
    if (-not $pluginModeReady) { $publicationGaps.Add("plugin_mode_has_direct_compatibility_conflicts") }
    $result = [pscustomobject]@{
        action = "Status"
        codex_root = $CodexRoot
        skill_delivery_mode = $SkillDeliveryMode
        portable_settings_in_scope = [bool]$InstallPortableSettings
        source_bundle_sha256 = $sourceFingerprint
        installed_bundle_sha256 = $installedFingerprint
        installed_contract_bundle_sha256 = $installedFingerprint
        installed_full_bundle_sha256 = $installedFullFingerprint
        installed_matches_source = $installedMatchesSource
        latest_publish_manifest = if ($null -eq $publishRecord) { $null } else { $publishRecord.path }
        manifest_matches_source = $manifestMatchesSource
        manifest_matches_installed = $manifestMatchesInstalled
        manifest_matches_routing_evidence = $manifestEvidenceMatches
        manifest_matches_managed_asset_lifecycle = $manifestLifecycleMatches
        managed_asset_lifecycle_sha256 = $source.managed_asset_lifecycle.sha256
        managed_asset_unit_count = @($source.managed_asset_lifecycle.units).Count
        retired_managed_path_present_count = $retiredManagedTargets.Count
        retired_managed_paths_present = @($retiredManagedTargets.relative_path)
        retired_managed_config_key_present_count = $retiredConfigDiagnostics.Count
        retired_managed_config_key_conflict_count = $retiredConfigModified.Count + $retiredConfigUnverifiable.Count
        retired_managed_config_key_conflicts = @($retiredConfigDiagnostics | Where-Object { [string]$_.status -ne 'removable' } | ForEach-Object { "$($_.id):$($_.status)" })
        managed_payload_formally_published = $installedMatchesSource -and $manifestMatchesSource -and $manifestMatchesInstalled -and $manifestEvidenceMatches -and $manifestLifecycleMatches -and $retiredManagedTargets.Count -eq 0 -and $retiredConfigDiagnostics.Count -eq 0 -and $pluginModeReady
        formal_publication_gap_count = $publicationGaps.Count
        formal_publication_gaps = @($publicationGaps)
        plugin_installation_in_scope = $SkillDeliveryMode -eq "Plugin"
        plugin_installation_inspected = $false
        plugin_mode_ready = if ($SkillDeliveryMode -eq "Plugin") { $pluginModeReady } else { $null }
        direct_compatibility_conflict_count = $directCompatibilityConflicts.Count
        direct_compatibility_conflicts = @($directCompatibilityConflicts)
        runtime_prerequisite_in_scope = [bool]$srcqRuntime.in_scope
        srcq_runtime_ready = $srcqRuntime.ready
        srcq_version = $srcqRuntime.version
        srcq_binary = $srcqRuntime.binary
        srcq_integrity = $srcqRuntime.integrity
        srcq_path_entry_count = $srcqRuntime.path_entry_count
        srcq_doctor_ok = $srcqRuntime.doctor_ok
        srcq_scc_doctor_ok = $srcqRuntime.scc_doctor_ok
        scc_version = $srcqRuntime.scc_version
        srcq_runtime_error = if ($srcqRuntime.PSObject.Properties.Name -contains 'error') { $srcqRuntime.error } else { $null }
    }
    Set-AgentBaseResultType -Result $result -Kind Status
    return
}

if ($Action -eq "Publish") {
    $srcqRuntime = if (Test-DeploymentSandboxRoot -Root $ProjectRoot -InstallRoot $CodexRoot) {
        [pscustomobject]@{ in_scope = $false; ready = $null; version = $null; binary = $null; integrity = $null; path_entry_count = 0; doctor_ok = $null; scc_doctor_ok = $null; scc_version = $null }
    } else {
        Get-SrcqRuntimePreflight -Root $ProjectRoot -Required $true
    }
    $previousLifecycleRecord = Get-LatestPublishedManifest -InstallRoot $CodexRoot -IgnorePublicationScope -MinimumSchemaVersion 7
    $previousLifecycleManifest = if ($null -eq $previousLifecycleRecord) { $null } else { $previousLifecycleRecord.document }
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $CodexRoot -IncludePortableSettings ([bool]$InstallPortableSettings) -DeliveryMode $SkillDeliveryMode -PreviousManifest $previousLifecycleManifest
    $retiredConfigBlockingDiagnostics = @($source.retired_config_diagnostics | Where-Object { [string]$_.status -ne 'removable' })
    if ($retiredConfigBlockingDiagnostics.Count -gt 0) {
        $details = @($retiredConfigBlockingDiagnostics | ForEach-Object { "$($_.id):$($_.status)" }) -join ', '
        throw "Retired managed config keys cannot be removed safely. Preserve them by changing the lifecycle state to transferred, or restore the last managed value before retrying. Conflicts: $details"
    }
    if ($SkillDeliveryMode -eq "Plugin") {
        $directCompatibilityConflicts = @(Get-PluginModeDirectCompatibilityConflicts -InstallRoot $CodexRoot -RequiredSkills @($source.contract.required_skills))
        if ($directCompatibilityConflicts.Count -gt 0) {
            throw "Plugin delivery mode requires the direct-compatibility skills and AgentBase global hooks to be removed or rolled back first. Conflicts: $($directCompatibilityConflicts -join ', ')"
        }
    }
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    $currentChangeTargets = @(Get-IncrementalChangeTargets -Targets $source.targets)
    $retiredManagedTargets = @(Get-RetiredManagedChangeTargets -Targets $source.retired_path_targets)
    $retiredConfigRemoved = @($source.retired_config_diagnostics | Where-Object { [string]$_.status -eq 'removable' })
    $changeTargets = @((@($currentChangeTargets) + @($retiredManagedTargets)) | Sort-Object relative_path)
    $stageRoot = Join-Path $CodexRoot (".agentbase-stage-" + [guid]::NewGuid().ToString("N"))
    Assert-ChildPath -Root $CodexRoot -Path $stageRoot -Label "Stage path"
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

    $backedUp = New-Object 'System.Collections.Generic.List[string]'
    $installed = New-Object 'System.Collections.Generic.List[string]'
    $manifest = $null
    $manifestPath = $null
    try {
        foreach ($target in @($changeTargets | Where-Object { [string]$_.desired_state -eq "present" })) {
            $stagePath = Join-Path $stageRoot $target.relative_path
            $stageParent = Split-Path -Parent $stagePath
            if (-not (Test-Path -LiteralPath $stageParent -PathType Container)) {
                New-Item -ItemType Directory -Path $stageParent -Force | Out-Null
            }
            if ($target.PSObject.Properties.Name -contains "source_text" -and $null -ne $target.source_text) {
                Write-Utf8NoBomFile -Path $stagePath -Text ([string]$target.source_text)
            }
            else {
                Copy-Item -LiteralPath $target.source_path -Destination $stagePath -Force
            }
            if ((Get-PathFingerprint $stagePath) -ne (Get-ExpectedStagedFingerprint $target)) {
                throw "Staged payload hash mismatch: $($target.relative_path)"
            }
        }

        $backupName = "AgentBase-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
        $backupRoot = Join-Path (Join-Path $CodexRoot "backups") $backupName
        Assert-ChildPath -Root $CodexRoot -Path $backupRoot -Label "Backup path"
        New-Item -ItemType Directory -Path (Join-Path $backupRoot "payload") -Force | Out-Null
        $manifestPath = Join-Path $backupRoot "manifest.json"

        $targetStates = @($changeTargets | ForEach-Object {
            [ordered]@{
                relative_path = $_.relative_path
                kind = $_.kind
                desired_state = $_.desired_state
                existed_before = Test-Path -LiteralPath $_.installed_path
                before_fingerprint = Get-PathFingerprint $_.installed_path
            }
        })
        $manifest = [ordered]@{
            schema_version = 7
            state = "prepared"
            created_at_utc = [DateTime]::UtcNow.ToString("o")
            project_root = $ProjectRoot
            codex_root = $CodexRoot
            source_bundle_sha256 = $sourceFingerprint
            skill_delivery_mode = $SkillDeliveryMode
            skills_installed = [bool]$source.skills_managed
            hooks_installed = [bool]$source.hooks_managed
            portable_settings_sha256 = $source.portable_settings_sha256
            portable_settings_installed = [bool]$InstallPortableSettings
            portable_agent_names = @($source.portable_agent_names)
            managed_asset_lifecycle_sha256 = $source.managed_asset_lifecycle.sha256
            managed_asset_units = @($source.managed_asset_lifecycle_receipt_units)
            retired_managed_paths_removed = @($retiredManagedTargets.relative_path)
            retired_managed_config_keys_removed = @($retiredConfigRemoved.id)
            routing_evidence_path = $source.routing_evidence.path.Substring($ProjectRoot.Length + 1).Replace('\', '/')
            routing_evidence_sha256 = $source.routing_evidence.sha256
            routing_evaluator_id = $source.routing_evidence.evaluator_id
            routing_evaluator_model = $source.routing_evidence.evaluator_model
            routing_evaluator_runtime = $source.routing_evidence.evaluator_runtime
            routing_evaluated_at_utc = $source.routing_evidence.evaluated_at_utc
            routing_repository_accessed = $source.routing_evidence.repository_accessed
            routing_hidden_expectations_accessed = $source.routing_evidence.hidden_expectations_accessed
            routing_evaluation_capsule_sha256 = $source.routing_evidence.evaluation_capsule_sha256
            routing_candidate_bundle_sha256 = $source.routing_evidence.candidate_bundle_sha256
            routing_evaluation_input_sha256 = $source.routing_evidence.evaluation_input_sha256
            routing_case_count = $source.routing_evidence.case_count
            srcq_runtime_preflight_in_scope = [bool]$srcqRuntime.in_scope
            srcq_runtime_ready = $srcqRuntime.ready
            srcq_version = $srcqRuntime.version
            srcq_binary = $srcqRuntime.binary
            srcq_integrity = $srcqRuntime.integrity
            srcq_path_entry_count = $srcqRuntime.path_entry_count
            srcq_doctor_ok = $srcqRuntime.doctor_ok
            srcq_scc_doctor_ok = $srcqRuntime.scc_doctor_ok
            scc_version = $srcqRuntime.scc_version
            installed_bundle_sha256 = $null
            installed_contract_bundle_sha256 = $null
            targets = $targetStates
            backed_up_targets = @()
            installed_targets = @()
        }
        Write-JsonFile -Path $manifestPath -Value $manifest

        foreach ($target in $changeTargets) {
            if (Test-Path -LiteralPath $target.installed_path) {
                $backupTarget = Join-Path (Join-Path $backupRoot "payload") $target.relative_path
                $backupParent = Split-Path -Parent $backupTarget
                if (-not (Test-Path -LiteralPath $backupParent -PathType Container)) {
                    New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
                }
                Move-Item -LiteralPath $target.installed_path -Destination $backupTarget
                $backedUp.Add($target.relative_path)
                $manifest.backed_up_targets = $backedUp.ToArray()
                $manifest.state = "backing_up"
                Write-JsonFile -Path $manifestPath -Value $manifest
            }
        }
        Remove-EmptyManagedProjectOnlyDirectories -Targets $source.targets

        $manifest.state = "backed_up"
        Write-JsonFile -Path $manifestPath -Value $manifest
        foreach ($target in @($changeTargets | Where-Object { [string]$_.desired_state -eq "present" })) {
            $stagePath = Join-Path $stageRoot $target.relative_path
            $targetParent = Split-Path -Parent $target.installed_path
            if (-not (Test-Path -LiteralPath $targetParent -PathType Container)) {
                New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
            }
            Move-Item -LiteralPath $stagePath -Destination $target.installed_path
            $installed.Add($target.relative_path)
            $manifest.installed_targets = $installed.ToArray()
            $manifest.state = "installing"
            Write-JsonFile -Path $manifestPath -Value $manifest
        }

        $installedContractFingerprint = Get-BundleFingerprint -Targets $source.targets -Side installed
        if ($installedContractFingerprint -ne $sourceFingerprint) {
            throw "Installed bundle hash does not match the validated source bundle"
        }
        $manifest.installed_bundle_sha256 = Get-FullInstalledBundleFingerprint -Targets $changeTargets
        $manifest.installed_contract_bundle_sha256 = $installedContractFingerprint
        $manifest.state = "published"
        Set-ObjectProperty -Object $manifest -Name "published_at_utc" -Value ([DateTime]::UtcNow.ToString("o"))
        Write-JsonFile -Path $manifestPath -Value $manifest
    }
    catch {
        foreach ($relativePath in @(Get-ReversedArray $installed)) {
            $installedTarget = Join-Path $CodexRoot $relativePath
            Assert-ChildPath -Root $CodexRoot -Path $installedTarget -Label "Installed rollback target"
            if (Test-Path -LiteralPath $installedTarget) {
                Remove-Item -LiteralPath $installedTarget -Recurse -Force
            }
        }
        if ($null -ne $manifestPath) {
            $backupRoot = Split-Path -Parent $manifestPath
            foreach ($relativePath in @(Get-ReversedArray $backedUp)) {
                $backupTarget = Join-Path (Join-Path $backupRoot "payload") $relativePath
                $installedTarget = Join-Path $CodexRoot $relativePath
                $installedParent = Split-Path -Parent $installedTarget
                if (-not (Test-Path -LiteralPath $installedParent -PathType Container)) {
                    New-Item -ItemType Directory -Path $installedParent -Force | Out-Null
                }
                if (Test-Path -LiteralPath $backupTarget) {
                    Move-Item -LiteralPath $backupTarget -Destination $installedTarget
                }
            }
            if ($null -ne $manifest) {
                $manifest.state = "restored_after_publish_failure"
                Set-ObjectProperty -Object $manifest -Name "failure" -Value $_.Exception.Message
                Write-JsonFile -Path $manifestPath -Value $manifest
            }
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $stageRoot) {
            Assert-ChildPath -Root $CodexRoot -Path $stageRoot -Label "Stage cleanup path"
            Remove-Item -LiteralPath $stageRoot -Recurse -Force
        }
    }

    $result = [pscustomobject]@{
        action = "Publish"
        codex_root = $CodexRoot
        skill_delivery_mode = $SkillDeliveryMode
        source_bundle_sha256 = $sourceFingerprint
        backup_path = Split-Path -Parent $manifestPath
        mcp_changed = $false
        skills_installed = [bool]$source.skills_managed
        hooks_installed = [bool]$source.hooks_managed
        plugin_installation_managed = $false
        plugin_installation_must_be_verified_separately = $SkillDeliveryMode -eq "Plugin"
        portable_settings_installed = [bool]$InstallPortableSettings
        portable_agent_count = if ($InstallPortableSettings) { @($source.portable_agent_names).Count } else { 0 }
        changed_path_count = $changeTargets.Count
        managed_contract_count = @($source.targets).Count
        managed_asset_lifecycle_sha256 = $source.managed_asset_lifecycle.sha256
        managed_asset_unit_count = @($source.managed_asset_lifecycle.units).Count
        retired_managed_path_removed_count = $retiredManagedTargets.Count
        retired_managed_paths_removed = @($retiredManagedTargets.relative_path)
        retired_managed_config_key_removed_count = $retiredConfigRemoved.Count
        retired_managed_config_keys_removed = @($retiredConfigRemoved.id)
        routing_evidence_sha256 = $source.routing_evidence.sha256
        runtime_prerequisite_in_scope = [bool]$srcqRuntime.in_scope
        srcq_runtime_ready = $srcqRuntime.ready
        srcq_version = $srcqRuntime.version
        srcq_binary = $srcqRuntime.binary
        srcq_integrity = $srcqRuntime.integrity
        srcq_path_entry_count = $srcqRuntime.path_entry_count
        srcq_doctor_ok = $srcqRuntime.doctor_ok
        srcq_scc_doctor_ok = $srcqRuntime.scc_doctor_ok
        scc_version = $srcqRuntime.scc_version
    }
    Set-AgentBaseResultType -Result $result -Kind Publish
    return
}

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    throw "BackupPath is required for Rollback"
}
$BackupPath = (Resolve-Path -LiteralPath $BackupPath).Path
$backupsRoot = Join-Path $CodexRoot "backups"
Assert-ChildPath -Root $backupsRoot -Path $BackupPath -Label "Rollback backup"
$manifestPath = Join-Path $BackupPath "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Backup manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (@(1, 2, 3, 4, 5, 6, 7) -notcontains [int]$manifest.schema_version -or [string]$manifest.state -ne "published") {
    throw "Backup is not in a publish state that can be rolled back: $($manifest.state)"
}
if (-not [string]::Equals([IO.Path]::GetFullPath([string]$manifest.codex_root), [IO.Path]::GetFullPath($CodexRoot), [StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup manifest belongs to a different Codex root: $($manifest.codex_root)"
}

$rollbackTargets = @($manifest.targets | ForEach-Object {
    $relativePath = [string]$_.relative_path
    if ([string]::IsNullOrWhiteSpace($relativePath) -or [IO.Path]::IsPathRooted($relativePath) -or @($relativePath -split '[\\/]' | Where-Object { $_ -eq '..' }).Count -gt 0) {
        throw "Backup manifest contains an unsafe target path: $relativePath"
    }
    if (@("file", "directory") -notcontains [string]$_.kind) {
        throw "Backup manifest contains an invalid target kind: $($_.kind)"
    }
    $installedPath = Join-Path $CodexRoot $relativePath
    Assert-ChildPath -Root $CodexRoot -Path $installedPath -Label "Rollback target"
    [pscustomobject]@{
        relative_path = $relativePath
        source_path = $null
        installed_path = $installedPath
        kind = [string]$_.kind
    }
})

$installedFingerprint = Get-BundleFingerprint -Targets $rollbackTargets -Side installed
if (-not $AllowInstalledDrift -and $installedFingerprint -ne [string]$manifest.installed_bundle_sha256) {
    throw "Installed AgentBase files changed after publish; refusing rollback without -AllowInstalledDrift"
}

$retiredRoot = Join-Path $BackupPath ("retired-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
Assert-ChildPath -Root $BackupPath -Path $retiredRoot -Label "Rollback retired payload"
New-Item -ItemType Directory -Path $retiredRoot | Out-Null
$retired = New-Object 'System.Collections.Generic.List[string]'
$restored = New-Object 'System.Collections.Generic.List[string]'
try {
    $manifest.state = "rolling_back"
    Set-ObjectProperty -Object $manifest -Name "rollback_started_at_utc" -Value ([DateTime]::UtcNow.ToString("o"))
    Write-JsonFile -Path $manifestPath -Value $manifest

    foreach ($target in $rollbackTargets) {
        if (Test-Path -LiteralPath $target.installed_path) {
            $retiredTarget = Join-Path $retiredRoot $target.relative_path
            $retiredParent = Split-Path -Parent $retiredTarget
            if (-not (Test-Path -LiteralPath $retiredParent -PathType Container)) {
                New-Item -ItemType Directory -Path $retiredParent -Force | Out-Null
            }
            Move-Item -LiteralPath $target.installed_path -Destination $retiredTarget
            $retired.Add($target.relative_path)
        }
    }

    foreach ($targetState in @($manifest.targets)) {
        if ([bool]$targetState.existed_before) {
            $backupTarget = Join-Path (Join-Path $BackupPath "payload") ([string]$targetState.relative_path)
            $installedTarget = Join-Path $CodexRoot ([string]$targetState.relative_path)
            $installedParent = Split-Path -Parent $installedTarget
            if (-not (Test-Path -LiteralPath $backupTarget)) {
                throw "Backup payload is missing: $backupTarget"
            }
            if (-not (Test-Path -LiteralPath $installedParent -PathType Container)) {
                New-Item -ItemType Directory -Path $installedParent -Force | Out-Null
            }
            Move-Item -LiteralPath $backupTarget -Destination $installedTarget
            $restored.Add([string]$targetState.relative_path)
        }
    }

    foreach ($targetState in @($manifest.targets)) {
        $installedTarget = Join-Path $CodexRoot ([string]$targetState.relative_path)
        $actualFingerprint = Get-PathFingerprint $installedTarget
        if ($actualFingerprint -ne [string]$targetState.before_fingerprint) {
            throw "Rollback verification failed: $($targetState.relative_path)"
        }
    }

    $manifest.state = "rolled_back"
    Set-ObjectProperty -Object $manifest -Name "rolled_back_at_utc" -Value ([DateTime]::UtcNow.ToString("o"))
    Set-ObjectProperty -Object $manifest -Name "retired_payload" -Value $retiredRoot
    Write-JsonFile -Path $manifestPath -Value $manifest
}
catch {
    foreach ($relativePath in @(Get-ReversedArray $restored)) {
        $installedTarget = Join-Path $CodexRoot $relativePath
        $backupTarget = Join-Path (Join-Path $BackupPath "payload") $relativePath
        $backupParent = Split-Path -Parent $backupTarget
        if (-not (Test-Path -LiteralPath $backupParent -PathType Container)) {
            New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
        }
        if (Test-Path -LiteralPath $installedTarget) {
            Move-Item -LiteralPath $installedTarget -Destination $backupTarget
        }
    }
    foreach ($relativePath in @(Get-ReversedArray $retired)) {
        $retiredTarget = Join-Path $retiredRoot $relativePath
        $installedTarget = Join-Path $CodexRoot $relativePath
        $installedParent = Split-Path -Parent $installedTarget
        if (-not (Test-Path -LiteralPath $installedParent -PathType Container)) {
            New-Item -ItemType Directory -Path $installedParent -Force | Out-Null
        }
        if (Test-Path -LiteralPath $retiredTarget) {
            Move-Item -LiteralPath $retiredTarget -Destination $installedTarget
        }
    }
    $manifest.state = "published"
    Set-ObjectProperty -Object $manifest -Name "rollback_failure" -Value $_.Exception.Message
    Write-JsonFile -Path $manifestPath -Value $manifest
    throw
}

$result = [pscustomobject]@{
    action = "Rollback"
    codex_root = $CodexRoot
    backup_path = $BackupPath
    restored_target_count = $restored.Count
    retired_payload = $retiredRoot
    mcp_changed = $false
}
Set-AgentBaseResultType -Result $result -Kind Rollback
