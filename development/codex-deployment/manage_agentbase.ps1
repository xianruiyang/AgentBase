param(
    [ValidateSet("Validate", "Publish", "Rollback")]
    [string]$Action = "Validate",
    [string]$ProjectRoot,
    [string]$CodexRoot,
    [string]$BackupPath,
    [switch]$AllowInstalledDrift,
    [switch]$InstallPortableSettings
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ($InstallPortableSettings -and $Action -ne "Publish") {
    throw "InstallPortableSettings is valid only with Action Publish"
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
        [string]$Path
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
    $records = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
        if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to fingerprint a reparse point: $($_.FullName)"
        }
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

    if ($Target.PSObject.Properties.Name -contains "source_text" -and $null -ne $Target.source_text) {
        return Get-TextFileFingerprint ([string]$Target.source_text)
    }
    return Get-PathFingerprint ([string]$Target.source_path)
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
            Get-PathFingerprint $_.installed_path
        }
        "$($_.relative_path)|$fingerprint"
    })
    return Get-TextSha256 ($records -join [Environment]::NewLine)
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
        'model = "gpt-5.6-sol"'
        'model_reasoning_effort = "max"'
        'personality = "pragmatic"'
        'sandbox_mode = "danger-full-access"'
        'service_tier = "priority"'
        '[agents]'
        'enabled = true'
        'default_subagent_model = "gpt-5.6-luna"'
        'default_subagent_reasoning_effort = "max"'
        '[windows]'
        'sandbox = "elevated"'
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

function Get-ValidatedPortableAgentSources {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Portable Codex agents directory is missing: $Path"
    }

    $expectedAgents = [ordered]@{
        luna = [ordered]@{
            description = "Use Luna for clear, narrowly scoped, repeatable, or high-throughput tasks."
            model = "gpt-5.6-luna"
            developer_instructions = "Complete well-defined tasks quickly and stay within scope. Return concise, verifiable results."
        }
        sol = [ordered]@{
            description = "Use Sol for demanding, ambiguous, multi-step tasks that require deep reasoning and validation."
            model = "gpt-5.6-sol"
            developer_instructions = "Handle complex reasoning, implementation, and verification tasks. Keep conclusions evidence-based and validate material changes."
        }
        terra = [ordered]@{
            description = "Use Terra for general tasks that should balance quality, speed, and cost."
            model = "gpt-5.6-terra"
            developer_instructions = "Complete exploration, analysis, and routine implementation efficiently. Return concise, verifiable results."
        }
    }
    $entries = @(Get-ChildItem -LiteralPath $Path -Force | Sort-Object Name)
    $expectedNames = @($expectedAgents.Keys | ForEach-Object { "{0}.toml" -f $_ })
    $actualNames = @($entries.Name)
    if (($actualNames -join '|') -ne ($expectedNames -join '|')) {
        throw "Portable Codex agents contain an unexpected file set: $($actualNames -join ', ')"
    }

    foreach ($entry in $entries) {
        if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Portable Codex agent must be a real TOML file: $($entry.FullName)"
        }
        $agentName = [IO.Path]::GetFileNameWithoutExtension($entry.Name)
        $spec = $expectedAgents[$agentName]
        $expectedLines = @(
            "name = `"$agentName`""
            "description = `"$($spec.description)`""
            "model = `"$($spec.model)`""
            'developer_instructions = """'
            [string]$spec.developer_instructions
            '"""'
        )
        $actualLines = @(Get-Content -LiteralPath $entry.FullName -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        })
        if (($actualLines -join [Environment]::NewLine) -ne ($expectedLines -join [Environment]::NewLine)) {
            throw "Portable Codex agent differs from the reviewed contract: $($entry.Name)"
        }
        $raw = Get-Content -LiteralPath $entry.FullName -Raw -Encoding UTF8
        if ($raw -match '(?i)([a-z]:[\\/]|\\\\|https?://|api[_-]?key|password|secret|credential|trusted_hash|mcp_servers|skills\.config)') {
            throw "Portable Codex agent contains a machine path, external dependency, or sensitive setting: $($entry.Name)"
        }
    }

    return $entries
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
    if ($placeholderCount -ne 10) {
        throw "Portable hooks template must contain exactly 10 Codex-root placeholders; found $placeholderCount"
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
    $eventLoggerCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{{CODEX_ROOT}}\skills\codex-event-logger\scripts\codex_event_logger.ps1"'
    $qqCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{{CODEX_ROOT}}\skills\codex-qq-hook\scripts\codex_stop_qq_notify.ps1"'
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
        [bool]$IncludePortableSettings
    )

    & (Join-Path $Root "development\skill-routing\validate_contract.ps1") -ProjectRoot $Root | Out-Null
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
    $targets = New-Object 'System.Collections.Generic.List[object]'
    $targets.Add([pscustomobject]@{
        relative_path = "AGENTS.md"
        source_path = Join-Path $Root "global\AGENTS.md"
        source_text = $null
        installed_path = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot "AGENTS.md" }
        kind = "file"
    })
    foreach ($skill in @($contract.required_skills)) {
        $relativePath = "skills\$skill"
        $targets.Add([pscustomobject]@{
            relative_path = $relativePath
            source_path = Join-Path (Join-Path $Root "skills") ([string]$skill)
            source_text = $null
            installed_path = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot $relativePath }
            kind = "directory"
        })
    }
    if ($IncludePortableSettings) {
        if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
            throw "InstallRoot is required when portable settings are selected"
        }
        $targets.Add([pscustomobject]@{
            relative_path = "config.toml"
            source_path = $portableConfigPath
            source_text = $null
            installed_path = Join-Path $InstallRoot "config.toml"
            kind = "file"
        })
        $targets.Add([pscustomobject]@{
            relative_path = "hooks.json"
            source_path = $hooksTemplatePath
            source_text = Get-ResolvedHooksText -TemplatePath $hooksTemplatePath -InstallRoot $InstallRoot
            installed_path = Join-Path $InstallRoot "hooks.json"
            kind = "file"
        })
        foreach ($portableAgentFile in $portableAgentFiles) {
            $relativePath = "agents\$($portableAgentFile.Name)"
            $targets.Add([pscustomobject]@{
                relative_path = $relativePath
                source_path = $portableAgentFile.FullName
                source_text = $null
                installed_path = Join-Path $InstallRoot $relativePath
                kind = "file"
            })
        }
    }

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

if ($Action -eq "Validate") {
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $null -IncludePortableSettings $false
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    [pscustomobject]@{
        action = "Validate"
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
    }
    return
}

$CodexRoot = Resolve-CodexRoot -RequestedRoot $CodexRoot -Create ($Action -eq "Publish")

if ($Action -eq "Publish") {
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $CodexRoot -IncludePortableSettings ([bool]$InstallPortableSettings)
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    $stageRoot = Join-Path $CodexRoot (".agentbase-stage-" + [guid]::NewGuid().ToString("N"))
    Assert-ChildPath -Root $CodexRoot -Path $stageRoot -Label "Stage path"
    New-Item -ItemType Directory -Path (Join-Path $stageRoot "skills") -Force | Out-Null

    $backedUp = New-Object 'System.Collections.Generic.List[string]'
    $installed = New-Object 'System.Collections.Generic.List[string]'
    $manifest = $null
    $manifestPath = $null
    try {
        foreach ($target in $source.targets) {
            $stagePath = Join-Path $stageRoot $target.relative_path
            $stageParent = Split-Path -Parent $stagePath
            if (-not (Test-Path -LiteralPath $stageParent -PathType Container)) {
                New-Item -ItemType Directory -Path $stageParent -Force | Out-Null
            }
            if ($target.PSObject.Properties.Name -contains "source_text" -and $null -ne $target.source_text) {
                Write-Utf8NoBomFile -Path $stagePath -Text ([string]$target.source_text)
            }
            else {
                Copy-Item -LiteralPath $target.source_path -Destination $stagePath -Recurse -Force
            }
            if ((Get-PathFingerprint $stagePath) -ne (Get-TargetSourceFingerprint $target)) {
                throw "Staged payload hash mismatch: $($target.relative_path)"
            }
        }

        $backupName = "AgentBase-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
        $backupRoot = Join-Path (Join-Path $CodexRoot "backups") $backupName
        Assert-ChildPath -Root $CodexRoot -Path $backupRoot -Label "Backup path"
        New-Item -ItemType Directory -Path (Join-Path $backupRoot "payload") -Force | Out-Null
        $manifestPath = Join-Path $backupRoot "manifest.json"

        $targetStates = @($source.targets | ForEach-Object {
            [ordered]@{
                relative_path = $_.relative_path
                kind = $_.kind
                existed_before = Test-Path -LiteralPath $_.installed_path
                before_fingerprint = Get-PathFingerprint $_.installed_path
            }
        })
        $manifest = [ordered]@{
            schema_version = 1
            state = "prepared"
            created_at_utc = [DateTime]::UtcNow.ToString("o")
            project_root = $ProjectRoot
            codex_root = $CodexRoot
            source_bundle_sha256 = $sourceFingerprint
            portable_settings_sha256 = $source.portable_settings_sha256
            portable_settings_installed = [bool]$InstallPortableSettings
            portable_agent_names = @($source.portable_agent_names)
            installed_bundle_sha256 = $null
            targets = $targetStates
            backed_up_targets = @()
            installed_targets = @()
        }
        Write-JsonFile -Path $manifestPath -Value $manifest

        foreach ($target in $source.targets) {
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

        $manifest.state = "backed_up"
        Write-JsonFile -Path $manifestPath -Value $manifest
        foreach ($target in $source.targets) {
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

        $installedFingerprint = Get-BundleFingerprint -Targets $source.targets -Side installed
        if ($installedFingerprint -ne $sourceFingerprint) {
            throw "Installed bundle hash does not match the validated source bundle"
        }
        $manifest.installed_bundle_sha256 = $installedFingerprint
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

    [pscustomobject]@{
        action = "Publish"
        codex_root = $CodexRoot
        source_bundle_sha256 = $sourceFingerprint
        backup_path = Split-Path -Parent $manifestPath
        mcp_changed = $false
        portable_settings_installed = [bool]$InstallPortableSettings
        portable_agent_count = if ($InstallPortableSettings) { @($source.portable_agent_names).Count } else { 0 }
    }
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
if ($manifest.schema_version -ne 1 -or [string]$manifest.state -ne "published") {
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

[pscustomobject]@{
    action = "Rollback"
    codex_root = $CodexRoot
    backup_path = $BackupPath
    restored_target_count = $restored.Count
    retired_payload = $retiredRoot
    mcp_changed = $false
}
