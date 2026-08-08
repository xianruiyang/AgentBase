param(
    [ValidateSet("Validate", "Publish", "Rollback")]
    [string]$Action = "Validate",
    [string]$ProjectRoot,
    [string]$CodexRoot,
    [string]$BackupPath,
    [switch]$AllowInstalledDrift
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

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

function Get-BundleFingerprint {
    param(
        [object[]]$Targets,
        [ValidateSet("source", "installed")]
        [string]$Side
    )

    $records = @($Targets | Sort-Object relative_path | ForEach-Object {
        $path = if ($Side -eq "source") { $_.source_path } else { $_.installed_path }
        "$($_.relative_path)|$(Get-PathFingerprint $path)"
    })
    return Get-TextSha256 ($records -join [Environment]::NewLine)
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Value
    )

    $json = $Value | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8NoBom)
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

function Get-ValidatedSource {
    param(
        [string]$Root,
        [string]$InstallRoot
    )

    & (Join-Path $Root "development\skill-routing\validate_contract.ps1") -ProjectRoot $Root | Out-Null
    $contract = Get-Content -LiteralPath (Join-Path $Root "development\skill-routing\trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $targets = New-Object 'System.Collections.Generic.List[object]'
    $targets.Add([pscustomobject]@{
        relative_path = "AGENTS.md"
        source_path = Join-Path $Root "global\AGENTS.md"
        installed_path = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot "AGENTS.md" }
        kind = "file"
    })
    foreach ($skill in @($contract.required_skills)) {
        $relativePath = "skills\$skill"
        $targets.Add([pscustomobject]@{
            relative_path = $relativePath
            source_path = Join-Path (Join-Path $Root "skills") ([string]$skill)
            installed_path = if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $null } else { Join-Path $InstallRoot $relativePath }
            kind = "directory"
        })
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
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $null
    $sourceFingerprint = Get-BundleFingerprint -Targets $source.targets -Side source
    [pscustomobject]@{
        action = "Validate"
        source_bundle_sha256 = $sourceFingerprint
        global_bytes = (Get-Item -LiteralPath (Join-Path $ProjectRoot "global\AGENTS.md")).Length
        skill_count = @($source.contract.required_skills).Count
        mcp = "$($source.mcp_name)@$($source.mcp_version)"
        mcp_release_owner = Join-Path $ProjectRoot "mcp\vscode-lsp-mcp"
    }
    return
}

$CodexRoot = Resolve-CodexRoot -RequestedRoot $CodexRoot -Create ($Action -eq "Publish")

if ($Action -eq "Publish") {
    $source = Get-ValidatedSource -Root $ProjectRoot -InstallRoot $CodexRoot
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
            Copy-Item -LiteralPath $target.source_path -Destination $stagePath -Recurse -Force
            if ((Get-PathFingerprint $stagePath) -ne (Get-PathFingerprint $target.source_path)) {
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
