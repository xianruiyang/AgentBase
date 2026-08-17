function Get-TomlBlocks {
    param(
        [string]$Text
    )

    $normalized = $Text.Replace("`r`n", "`n").Replace("`r", "`n").TrimEnd([char]10)
    $lines = if ([string]::IsNullOrEmpty($normalized)) { @() } else { @($normalized -split "`n") }
    $blocks = New-Object 'System.Collections.Generic.List[object]'
    $currentLines = New-Object 'System.Collections.Generic.List[string]'
    $current = [pscustomobject]@{
        name = ""
        header = $null
        lines = $currentLines
    }
    foreach ($line in $lines) {
        $tableName = $null
        if ($line -match '^\s*\[\[([^\]]+)\]\]\s*(?:#.*)?$') {
            $tableName = "[[$($Matches[1].Trim())]]"
        }
        elseif ($line -match '^\s*\[([^\]]+)\]\s*(?:#.*)?$') {
            $tableName = $Matches[1].Trim()
        }
        if ($null -ne $tableName) {
            $blocks.Add($current)
            $currentLines = New-Object 'System.Collections.Generic.List[string]'
            $current = [pscustomobject]@{
                name = $tableName
                header = $line
                lines = $currentLines
            }
            continue
        }
        $current.lines.Add($line)
    }
    $blocks.Add($current)
    return $blocks.ToArray()
}

function Get-PortableConfigSpec {
    param(
        [string]$PortableText
    )

    $spec = New-Object 'System.Collections.Generic.List[object]'
    foreach ($block in @(Get-TomlBlocks -Text $PortableText)) {
        $assignments = New-Object 'System.Collections.Generic.List[object]'
        foreach ($line in @($block.lines)) {
            if ($line -match '^\s*([A-Za-z0-9_-]+)\s*=') {
                $key = $Matches[1]
                if (@($assignments | Where-Object { [string]$_.key -ceq $key }).Count -gt 0) {
                    throw "Portable Codex config contains a duplicate managed key: $($block.name).$key"
                }
                $assignments.Add([pscustomobject]@{
                    key = $key
                    line = $line.Trim()
                })
            }
        }
        if ($assignments.Count -gt 0) {
            $spec.Add([pscustomobject]@{
                name = [string]$block.name
                header = if ([string]::IsNullOrEmpty([string]$block.name)) { $null } else { [string]$block.header }
                assignments = $assignments.ToArray()
            })
        }
    }
    return $spec.ToArray()
}

function Get-PortableConfigAssignmentFingerprint {
    param(
        [string]$Line
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Line.Trim())
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-', '')
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-PortableConfigManagedUnits {
    param(
        [string]$PortableText
    )

    $units = New-Object 'System.Collections.Generic.List[object]'
    foreach ($block in @(Get-PortableConfigSpec -PortableText $PortableText)) {
        $tableToken = if ([string]::IsNullOrEmpty([string]$block.name)) { 'root' } else { ([string]$block.name).ToLowerInvariant() }
        foreach ($assignment in @($block.assignments)) {
            $keyToken = ([string]$assignment.key).ToLowerInvariant()
            $units.Add([pscustomobject]@{
                id = "config:$tableToken/$keyToken"
                kind = 'config_key'
                table = [string]$block.name
                key = [string]$assignment.key
                delivery_modes = @('DirectCompatibility', 'Plugin')
                requires_portable_settings = $true
                source_fingerprint = Get-PortableConfigAssignmentFingerprint -Line ([string]$assignment.line)
            })
        }
    }
    return $units.ToArray()
}

function Get-PortableConfigAssignmentState {
    param(
        [string]$Text,
        [string]$Table,
        [string]$Key
    )

    $matchingBlocks = @(Get-TomlBlocks -Text $Text | Where-Object { [string]$_.name -ceq $Table })
    if ($matchingBlocks.Count -gt 1) {
        throw "Codex config contains duplicate managed table: $Table"
    }
    $matchingLines = @(if ($matchingBlocks.Count -ne 0) {
        $matchingBlocks[0].lines | Where-Object {
            $_ -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq $Key
        }
    })
    if ($matchingLines.Count -gt 1) {
        throw "Codex config contains duplicate managed key: $Table.$Key"
    }
    if ($matchingLines.Count -eq 0) {
        return [pscustomobject]@{ present = $false; fingerprint = $null }
    }
    return [pscustomobject]@{
        present = $true
        fingerprint = Get-PortableConfigAssignmentFingerprint -Line ([string]($matchingLines[0]))
    }
}

function Get-PortableConfigContractText {
    param(
        [string]$Text,
        [string]$PortableText,
        [object[]]$RetiredConfigKeys = @()
    )

    $targetBlocks = @(Get-TomlBlocks -Text $Text)
    $output = New-Object 'System.Collections.Generic.List[string]'
    foreach ($managedBlock in @(Get-PortableConfigSpec -PortableText $PortableText)) {
        $matchingBlocks = @($targetBlocks | Where-Object { [string]$_.name -ceq [string]$managedBlock.name })
        if ($matchingBlocks.Count -gt 1) {
            throw "Codex config contains duplicate managed table: $($managedBlock.name)"
        }
        if (-not [string]::IsNullOrEmpty([string]$managedBlock.name)) {
            $output.Add([string]$managedBlock.header)
        }
        foreach ($assignment in @($managedBlock.assignments)) {
            $matchingLines = @(if ($matchingBlocks.Count -ne 0) {
                $matchingBlocks[0].lines | Where-Object {
                    $_ -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq [string]$assignment.key
                }
            })
            if ($matchingLines.Count -gt 1) {
                throw "Codex config contains duplicate managed key: $($managedBlock.name).$($assignment.key)"
            }
            if ($matchingLines.Count -eq 1) {
                $output.Add(([string]($matchingLines[0])).Trim())
            }
            else {
                $output.Add("$($assignment.key) = <MISSING>")
            }
        }
    }
    foreach ($retired in @($RetiredConfigKeys | Sort-Object id)) {
        $state = Get-PortableConfigAssignmentState -Text $Text -Table ([string]$retired.table) -Key ([string]$retired.key)
        $fingerprint = if ([bool]$state.present) { [string]$state.fingerprint } else { '<MISSING>' }
        $output.Add("@retired|$($retired.table)|$($retired.key)|$fingerprint")
    }
    return (($output.ToArray() -join [Environment]::NewLine) + [Environment]::NewLine)
}

function Get-PortableConfigContractFingerprint {
    param(
        [string]$Path,
        [string]$PortableSourcePath,
        [object[]]$RetiredConfigKeys = @()
    )

    if (-not (Test-Path -LiteralPath $PortableSourcePath -PathType Leaf)) {
        throw "Portable Codex config is missing: $PortableSourcePath"
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return "MISSING"
    }
    $portableText = Get-Content -LiteralPath $PortableSourcePath -Raw -Encoding UTF8
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $contractText = Get-PortableConfigContractText -Text $text -PortableText $portableText -RetiredConfigKeys $RetiredConfigKeys
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($contractText)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "")
        return "FILE|$($bytes.Length)|$hash"
    }
    finally {
        $algorithm.Dispose()
    }
}

function Remove-RetiredPortableConfigKeysFromText {
    param(
        [string]$Text,
        [object[]]$RetiredConfigKeys
    )

    if (@($RetiredConfigKeys).Count -eq 0) {
        return $Text
    }
    $lineEnding = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $blocks = New-Object 'System.Collections.Generic.List[object]'
    foreach ($block in @(Get-TomlBlocks -Text $Text)) { $blocks.Add($block) }
    foreach ($retired in @($RetiredConfigKeys)) {
        $matchingBlocks = @($blocks | Where-Object { [string]$_.name -ceq [string]$retired.table })
        if ($matchingBlocks.Count -gt 1) {
            throw "Codex config contains duplicate managed table: $($retired.table)"
        }
        if ($matchingBlocks.Count -eq 0) {
            continue
        }
        $matchingIndices = New-Object 'System.Collections.Generic.List[int]'
        $targetBlock = $matchingBlocks[0]
        for ($index = 0; $index -lt $targetBlock.lines.Count; $index++) {
            $line = [string]$targetBlock.lines[$index]
            if ($line -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq [string]$retired.key) {
                $matchingIndices.Add($index)
            }
        }
        if ($matchingIndices.Count -gt 1) {
            throw "Codex config contains duplicate managed key: $($retired.table).$($retired.key)"
        }
        if ($matchingIndices.Count -eq 1) {
            $targetBlock.lines.RemoveAt($matchingIndices[0])
        }
    }

    $output = New-Object 'System.Collections.Generic.List[string]'
    foreach ($block in $blocks) {
        if ($null -ne $block.header) { $output.Add([string]$block.header) }
        foreach ($line in @($block.lines)) { $output.Add([string]$line) }
    }
    while ($output.Count -gt 0 -and [string]::IsNullOrEmpty($output[$output.Count - 1])) {
        $output.RemoveAt($output.Count - 1)
    }
    return (($output.ToArray() -join $lineEnding) + $lineEnding)
}

function Get-RetiredPortableConfigKeyDiagnostics {
    param(
        [string]$InstalledPath,
        [object[]]$RetiredConfigKeys,
        [object]$PreviousManifest
    )

    if (@($RetiredConfigKeys).Count -eq 0 -or -not (Test-Path -LiteralPath $InstalledPath -PathType Leaf)) {
        return @()
    }
    $previousById = @{}
    if ($null -ne $PreviousManifest -and $PreviousManifest.PSObject.Properties.Name -contains 'managed_asset_units') {
        foreach ($unit in @($PreviousManifest.managed_asset_units)) { $previousById[[string]$unit.id] = $unit }
    }
    $installedText = Get-Content -LiteralPath $InstalledPath -Raw -Encoding UTF8
    $diagnostics = New-Object 'System.Collections.Generic.List[object]'
    foreach ($retired in @($RetiredConfigKeys)) {
        $actual = Get-PortableConfigAssignmentState -Text $installedText -Table ([string]$retired.table) -Key ([string]$retired.key)
        if (-not [bool]$actual.present) {
            continue
        }
        $expected = $null
        if ($previousById.ContainsKey([string]$retired.id)) {
            $previous = $previousById[[string]$retired.id]
            if ($previous.PSObject.Properties.Name -contains 'source_fingerprint') {
                $expected = [string]$previous.source_fingerprint
            }
            elseif ($previous.PSObject.Properties.Name -contains 'last_managed_source_fingerprint') {
                $expected = [string]$previous.last_managed_source_fingerprint
            }
        }
        $status = if ([string]::IsNullOrWhiteSpace($expected)) {
            'unverifiable'
        }
        elseif ([string]$actual.fingerprint -eq $expected) {
            'removable'
        }
        else {
            'modified'
        }
        $diagnostics.Add([pscustomobject]@{
            id = [string]$retired.id
            table = [string]$retired.table
            key = [string]$retired.key
            status = $status
        })
    }
    return $diagnostics.ToArray()
}

function Get-MergedPortableConfigText {
    param(
        [string]$PortableSourcePath,
        [string]$InstalledPath,
        [object[]]$RetiredConfigKeys = @()
    )

    $portableText = Get-Content -LiteralPath $PortableSourcePath -Raw -Encoding UTF8
    if (-not (Test-Path -LiteralPath $InstalledPath -PathType Leaf)) {
        $normalizedPortableText = $portableText.Replace("`r`n", "`n").Replace("`r", "`n").Replace("`n", [Environment]::NewLine)
        return $normalizedPortableText.TrimEnd([char]13, [char]10) + [Environment]::NewLine
    }
    $installedText = Get-Content -LiteralPath $InstalledPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($installedText)) {
        $normalizedPortableText = $portableText.Replace("`r`n", "`n").Replace("`r", "`n").Replace("`n", [Environment]::NewLine)
        return $normalizedPortableText.TrimEnd([char]13, [char]10) + [Environment]::NewLine
    }
    $lineEnding = if ($installedText.Contains("`r`n")) { "`r`n" } else { "`n" }

    $blocks = New-Object 'System.Collections.Generic.List[object]'
    foreach ($block in @(Get-TomlBlocks -Text $installedText)) {
        $blocks.Add($block)
    }
    foreach ($managedBlock in @(Get-PortableConfigSpec -PortableText $portableText)) {
        $matchingBlocks = @($blocks | Where-Object { [string]$_.name -ceq [string]$managedBlock.name })
        if ($matchingBlocks.Count -gt 1) {
            throw "Codex config contains duplicate managed table: $($managedBlock.name)"
        }
        if ($matchingBlocks.Count -eq 0) {
            if ($blocks.Count -gt 0) {
                $previousBlock = $blocks[$blocks.Count - 1]
                $previousHasContent = $null -ne $previousBlock.header -or $previousBlock.lines.Count -gt 0
                if ($previousHasContent -and ($previousBlock.lines.Count -eq 0 -or -not [string]::IsNullOrEmpty([string]$previousBlock.lines[$previousBlock.lines.Count - 1]))) {
                    $previousBlock.lines.Add("")
                }
            }
            $newLines = New-Object 'System.Collections.Generic.List[string]'
            foreach ($assignment in @($managedBlock.assignments)) {
                $newLines.Add([string]$assignment.line)
            }
            $targetBlock = [pscustomobject]@{
                name = [string]$managedBlock.name
                header = [string]$managedBlock.header
                lines = $newLines
            }
            $blocks.Add($targetBlock)
        }
        else {
            $targetBlock = $matchingBlocks[0]
            foreach ($assignment in @($managedBlock.assignments)) {
                $matchingIndices = New-Object 'System.Collections.Generic.List[int]'
                for ($index = 0; $index -lt $targetBlock.lines.Count; $index++) {
                    $line = [string]$targetBlock.lines[$index]
                    if ($line -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq [string]$assignment.key) {
                        $matchingIndices.Add($index)
                    }
                }
                if ($matchingIndices.Count -gt 1) {
                    throw "Codex config contains duplicate managed key: $($managedBlock.name).$($assignment.key)"
                }
                if ($matchingIndices.Count -eq 1) {
                    $targetBlock.lines[$matchingIndices[0]] = [string]$assignment.line
                }
                else {
                    $targetBlock.lines.Add([string]$assignment.line)
                }
            }
        }
    }

    $output = New-Object 'System.Collections.Generic.List[string]'
    foreach ($block in $blocks) {
        if ($null -ne $block.header) {
            $output.Add([string]$block.header)
        }
        foreach ($line in @($block.lines)) {
            $output.Add([string]$line)
        }
    }
    while ($output.Count -gt 0 -and [string]::IsNullOrEmpty($output[$output.Count - 1])) {
        $output.RemoveAt($output.Count - 1)
    }
    $merged = (($output.ToArray() -join $lineEnding) + $lineEnding)
    return Remove-RetiredPortableConfigKeysFromText -Text $merged -RetiredConfigKeys $RetiredConfigKeys
}
