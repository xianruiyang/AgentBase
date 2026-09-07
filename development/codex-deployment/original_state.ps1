# Local recovery data is owned by the deployment entry point, never the payload.
function Get-OriginalStateRoot {
    param([string]$Root)
    return Join-Path $Root 'backups\AgentBase-original'
}

function Assert-OriginalStatePath {
    param([string]$Root, [string]$Relative)
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative) -or
        $Relative.Contains(':') -or @($Relative -split '[\\/]' | Where-Object { $_ -in @('..', '.') }).Count) {
        throw 'Unsafe original-state relative path'
    }
    $path = Join-Path $Root $Relative
    Assert-ChildPath -Root $Root -Path $path -Label 'Original-state path'
    $cursor = $path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Original-state paths must not traverse reparse points'
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $path
}

function Save-OriginalState {
    param([string]$Root, [object]$State)
    $path = Assert-OriginalStatePath -Root (Get-OriginalStateRoot $Root) -Relative 'manifest.json'
    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    $temporary = "$path.tmp"
    Write-JsonFile -Path $temporary -Value $State
    [IO.File]::Move($temporary, $path, $true)
}

function Read-OriginalState {
    param([string]$Root)
    $base = Get-OriginalStateRoot $Root
    $path = Assert-OriginalStatePath -Root $base -Relative 'manifest.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.schema -ne 'agentbase.original-state/v1' -or
        [IO.Path]::GetFullPath([string]$state.codex_root) -ne [IO.Path]::GetFullPath($Root)) {
        throw 'Original-state manifest identity mismatch'
    }
    $seen = @{}
    foreach ($entry in @($state.files)) {
        $null = Assert-OriginalStatePath -Root $Root -Relative $entry.path
        if ($seen.ContainsKey([string]$entry.path)) { throw 'Duplicate original-state path' }
        $seen[[string]$entry.path] = $true
        if ($entry.before -ne 'MISSING') {
            $payload = Assert-OriginalStatePath -Root $base -Relative ("payload\" + $entry.path)
            if ((Get-PathFingerprint $payload) -ne $entry.before) { throw "Original backup damaged: $($entry.path)" }
        }
    }
    return $state
}

function Enter-AgentBaseMutationLock {
    param([string]$Root)
    $path = Assert-OriginalStatePath -Root $Root -Relative '.agentbase-deployment.lock'
    try { return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw 'Another deployment or recovery is writing this Codex root; retry after it finishes' }
}

function Start-OriginalStateCapture {
    param([string]$Root, [object[]]$Changes, [object]$Source, [string]$Policy)
    $state = Read-OriginalState $Root
    if ($null -eq $state) {
        # Any prior receipt is history, including failed/rolled-back deployments.
        $backupRoot = Join-Path $Root 'backups'
        $hasHistory = (Test-Path -LiteralPath $backupRoot) -and
            @(Get-ChildItem -LiteralPath $backupRoot -Directory -Filter 'AgentBase-*' -Force |
                Where-Object { $_.Name -ne 'AgentBase-original' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'manifest.json')) }).Count -gt 0
        if ($Policy -eq 'Skip' -or $hasHistory) { return $null }
        $state = [pscustomobject]@{
            schema = 'agentbase.original-state/v1'; codex_root = $Root
            created_at_utc = [DateTime]::UtcNow.ToString('o'); state = 'active'
            plugin_used = $false; files = @(); config_keys = @()
        }
    } elseif ($Policy -eq 'Skip') {
        throw 'An original recovery point already exists; it cannot be skipped on later deployments'
    }
    if ($Source.skill_delivery_mode -eq 'Plugin') { $state.plugin_used = $true }
    $base = Get-OriginalStateRoot $Root
    # Retired directory payloads are expanded to files so later unrelated files survive.
    $files = @($Changes | ForEach-Object {
        if ($_.kind -eq 'directory') {
            $target = $_
            $null = Assert-OriginalStatePath -Root $Root -Relative $target.relative_path
            foreach ($file in @(Get-ChildItem -LiteralPath $target.installed_path -Recurse -File -Force)) {
                [pscustomobject]@{ relative_path = $file.FullName.Substring($Root.TrimEnd('\').Length + 1) }
            }
        } else { $_ }
    })
    foreach ($target in $files) {
        $relative = [string]$target.relative_path
        $path = Assert-OriginalStatePath -Root $Root -Relative $relative
        if (@($state.files | Where-Object { $_.path -eq $relative }).Count) { continue }
        $fingerprint = Get-PathFingerprint $path
        if ($fingerprint -ne 'MISSING') {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Recovery requires a regular file: $relative" }
            $copy = Assert-OriginalStatePath -Root $base -Relative ("payload\" + $relative)
            New-Item -ItemType Directory -Path (Split-Path -Parent $copy) -Force | Out-Null
            if (Test-Path -LiteralPath $copy) {
                if ((Get-PathFingerprint $copy) -ne $fingerprint) { throw "Uncommitted original backup conflicts: $relative" }
            } else { Copy-Item -LiteralPath $path -Destination $copy }
            if ((Get-PathFingerprint $copy) -ne $fingerprint -or (Get-PathFingerprint $path) -ne $fingerprint) {
                throw "File changed during original capture: $relative"
            }
        }
        $generatedLines = @()
        if ($relative -eq 'config.toml' -and $fingerprint -eq 'MISSING') {
            $generatedLines = @([string]$target.source_text -split '\r?\n' | Where-Object { $_ -match '^\s*#' } | ForEach-Object { $_.Trim() })
        }
        $state.files += [pscustomobject]@{ path = $relative; before = $fingerprint; expected = @($fingerprint); generated_lines = $generatedLines }
    }
    $config = @($Source.targets | Where-Object { $_.relative_path -eq 'config.toml' })
    if ($config.Count -and @($Changes | Where-Object { $_.relative_path -eq 'config.toml' }).Count) {
        $path = Assert-OriginalStatePath -Root $Root -Relative 'config.toml'
        $text = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { '' }
        foreach ($unit in @($Source.managed_asset_lifecycle_receipt_units | Where-Object { $_.kind -eq 'config_key' -and $_.state -ne 'transferred' })) {
            if (@($state.config_keys | Where-Object { $_.table -ceq $unit.table -and $_.key -ceq $unit.key }).Count) { continue }
            $original = Get-OriginalConfigAssignment -Text $text -Table $unit.table -Key $unit.key
            $state.config_keys += [pscustomobject]@{ table = $unit.table; key = $unit.key; original = $original; expected = @($original) }
        }
    }
    Save-OriginalState -Root $Root -State $state
    return $state
}

function Complete-OriginalStateCapture {
    param([string]$Root, [object]$State, [object]$Source, [object[]]$Changes)
    if ($null -eq $State) { return }
    foreach ($entry in @($State.files)) {
        if (-not @($Changes | Where-Object { $_.relative_path -eq $entry.path -or
            ($_.kind -eq 'directory' -and $entry.path.StartsWith($_.relative_path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) }).Count) { continue }
        $path = Assert-OriginalStatePath -Root $Root -Relative $entry.path
        $fingerprint = Get-PathFingerprint $path
        $entry.expected = @(@($entry.expected) + $fingerprint | Select-Object -Unique)
    }
    $path = Join-Path $Root 'config.toml'
    $text = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { '' }
    foreach ($key in @($State.config_keys)) {
        if (-not @($Source.managed_asset_lifecycle_receipt_units | Where-Object { $_.kind -eq 'config_key' -and $_.state -ne 'transferred' -and $_.table -ceq $key.table -and $_.key -ceq $key.key }).Count) { continue }
        if (-not @($Changes | Where-Object { $_.relative_path -eq 'config.toml' }).Count) { continue }
        $assignment = Get-OriginalConfigAssignment -Text $text -Table $key.table -Key $key.key
        if (-not @($key.expected | Where-Object { Test-OriginalConfigAssignmentEqual $_ $assignment }).Count) {
            $key.expected = @($key.expected) + $assignment
        }
    }
    $State.state = 'active'
    Save-OriginalState -Root $Root -State $State
}

function ConvertTo-OriginalAssignmentText {
    param([object]$Key, [object]$Assignment)
    if (-not $Assignment.present) { return '' }
    $header = if ($Key.table) { "[$($Key.table)]`n" } else { '' }
    return $header + $Assignment.line + "`n"
}

function Get-OriginalRestorePlan {
    param([string]$Root, [switch]$PluginDisabled)
    $state = Read-OriginalState $Root
    if ($null -eq $state) { throw 'No original recovery point exists; use an existing deployment Rollback receipt instead' }
    $actions = @(); $conflicts = @()
    foreach ($entry in @($state.files)) {
        $path = Assert-OriginalStatePath -Root $Root -Relative $entry.path
        $current = Get-PathFingerprint $path
        if ($current -eq $entry.before -and -not ($entry.path -eq 'config.toml' -and $state.config_keys.Count -gt 0)) { continue }
        $desiredText = $null
        if ($entry.path -eq 'config.toml' -and $state.config_keys.Count -gt 0 -and
            ($current -eq 'MISSING' -or (Test-Path -LiteralPath $path -PathType Leaf))) {
            $desiredText = if ($current -ne 'MISSING') { [IO.File]::ReadAllText($path) } else { '' }
            foreach ($key in @($state.config_keys)) {
                $observedAssignment = Get-OriginalConfigAssignment -Text $desiredText -Table $key.table -Key $key.key
                $expectedAssignment = @($key.expected | Where-Object { Test-OriginalConfigAssignmentEqual $_ $observedAssignment } | Select-Object -First 1)
                if (-not $expectedAssignment.Count) { $expectedAssignment = @($key.expected | Select-Object -Last 1) }
                $plan = Get-OriginalConfigRestorePlan -OriginalText (ConvertTo-OriginalAssignmentText $key $key.original) -ExpectedText (ConvertTo-OriginalAssignmentText $key $expectedAssignment[0]) -CurrentText $desiredText -Keys @($key)
                $conflicts += @($plan.conflicts | ForEach-Object { "config.toml:$_" })
                $desiredText = $plan.text
            }
            $managedHeaders = @($state.config_keys | Where-Object { $_.table } | ForEach-Object { "[$($_.table)]" })
            if ($entry.before -eq 'MISSING' -and -not @($desiredText -split '\r?\n' | Where-Object { $_.Trim() -and $_.Trim() -notin $managedHeaders -and $_.Trim() -notin @($entry.generated_lines) }).Count) { $desiredText = $null }
            elseif ($current -ne 'MISSING' -and $desiredText -ceq [IO.File]::ReadAllText($path)) { continue }
            if ($null -eq $desiredText -and $current -eq 'MISSING' -and $entry.before -eq 'MISSING') { continue }
        } elseif (@($entry.expected) -notcontains $current) {
            $conflicts += $entry.path
            continue
        }
        $actions += [pscustomobject]@{
            path = $entry.path; observed = $current; text = $desiredText
            action = if ($null -ne $desiredText -or $entry.before -ne 'MISSING') { 'restore' } else { 'remove' }
            original = $entry.before
        }
    }
    $external = @()
    if ($state.plugin_used -and -not $PluginDisabled) { $external = @('Disable or uninstall agentbase-core through the official plugin entry, then pass -PluginDisabled') }
    return [pscustomobject]@{ state = $state; actions = $actions; conflicts = $conflicts; external_actions = $external }
}

function Invoke-OriginalRestore {
    param([string]$Root, [switch]$Preview, [switch]$PluginDisabled)
    $plan = Get-OriginalRestorePlan -Root $Root -PluginDisabled:$PluginDisabled
    $public = [pscustomobject]@{
        action = if ($Preview) { 'PreviewRestore' } else { 'RestoreOriginal' }
        ready = $plan.conflicts.Count -eq 0 -and $plan.external_actions.Count -eq 0
        restored = $false
        change_count = $plan.actions.Count
        changes = @($plan.actions | Select-Object path, action)
        conflicts = @($plan.conflicts); external_actions = @($plan.external_actions)
    }
    if ($Preview) { return $public }
    if (-not $public.ready) { throw ('Original restore blocked; run PreviewRestore. Conflicts: ' + ($plan.conflicts -join ', ') + '; ' + ($plan.external_actions -join '; ')) }
    if ($plan.actions.Count -eq 0) {
        if ($plan.state.state -ne 'restored') {
            $plan.state.state = 'restored'
            Save-OriginalState -Root $Root -State $plan.state
        }
        $public.restored = $true
        return $public
    }
    $base = Get-OriginalStateRoot $Root
    $transaction = Assert-OriginalStatePath -Root $base -Relative ('restore-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $transaction -Force | Out-Null
    $applied = @()
    try {
        foreach ($entry in @($plan.actions)) {
            $path = Assert-OriginalStatePath -Root $Root -Relative $entry.path
            if ((Get-PathFingerprint $path) -ne $entry.observed) { throw "File changed after restore preview: $($entry.path)" }
            $backup = Assert-OriginalStatePath -Root $transaction -Relative $entry.path
            if ($entry.observed -ne 'MISSING') {
                New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
                Move-Item -LiteralPath $path -Destination $backup
            }
            $applied += $entry
            if ($entry.action -eq 'restore') {
                New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
                if ($null -ne $entry.text) { Write-Utf8NoBomFile -Path $path -Text $entry.text }
                else { Copy-Item -LiteralPath (Join-Path $base ("payload\" + $entry.path)) -Destination $path }
                $expected = if ($null -ne $entry.text) { Get-TextFileFingerprint $entry.text } else { $entry.original }
                if ((Get-PathFingerprint $path) -ne $expected) { throw "Restored file verification failed: $($entry.path)" }
            }
        }
        $plan.state.state = 'restored'
        Save-OriginalState -Root $Root -State $plan.state
    } catch {
        foreach ($entry in @(Get-ReversedArray $applied)) {
            $path = Assert-OriginalStatePath -Root $Root -Relative $entry.path
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
            $backup = Assert-OriginalStatePath -Root $transaction -Relative $entry.path
            if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $path }
        }
        throw
    }
    $public.restored = $true
    $public | Add-Member -NotePropertyName recovery_backup -NotePropertyValue $transaction
    return $public
}
