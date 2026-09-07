if (-not (Get-Command -Name Get-TomlBlocks -CommandType Function -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'portable_config.ps1')
}

function Test-OriginalConfigSingleLineAssignment {
    param(
        [string]$Line,
        [string]$Table,
        [string]$Key
    )

    if ($Line -notmatch '^\s*[A-Za-z0-9_-]+\s*=\s*(.*)$') {
        throw "Codex config assignment cannot be restored safely: $Table.$Key"
    }
    $value = $Matches[1].TrimStart()
    if ($value.StartsWith('"""') -or $value.StartsWith("'''")) {
        $delimiter = $value.Substring(0, 3)
        if ($value.IndexOf($delimiter, 3, [StringComparison]::Ordinal) -lt 0) {
            throw "Codex config contains a multiline managed value that cannot be restored safely: $Table.$Key"
        }
    }
    elseif ($value.StartsWith('[')) {
        if ($value.Contains('#') -or -not $value.TrimEnd().EndsWith(']')) {
            throw "Codex config contains a multiline managed value that cannot be restored safely: $Table.$Key"
        }
    }
    elseif ($value.StartsWith('{')) {
        if ($value.Contains('#') -or -not $value.TrimEnd().EndsWith('}')) {
            throw "Codex config contains a multiline managed value that cannot be restored safely: $Table.$Key"
        }
    }
    return $true
}

function Get-OriginalConfigAssignment {
    param(
        [string]$Text,
        [string]$Table,
        [string]$Key
    )

    $state = Get-PortableConfigAssignmentState -Text $Text -Table $Table -Key $Key
    if (-not [bool]$state.present) {
        return [pscustomobject]@{ present = $false; line = $null }
    }

    $block = @(Get-TomlBlocks -Text $Text | Where-Object { [string]$_.name -ceq $Table })[0]
    $line = @($block.lines | Where-Object {
        $_ -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq $Key
    })[0]
    $null = Test-OriginalConfigSingleLineAssignment -Line ([string]$line) -Table $Table -Key $Key
    return [pscustomobject]@{ present = $true; line = [string]$line }
}

function Test-OriginalConfigAssignmentEqual {
    param([object]$Left, [object]$Right)

    if ([bool]$Left.present -ne [bool]$Right.present) { return $false }
    if (-not [bool]$Left.present) { return $true }
    return (Get-PortableConfigAssignmentFingerprint -Line ([string]$Left.line)) -eq
        (Get-PortableConfigAssignmentFingerprint -Line ([string]$Right.line))
}

function Get-OriginalConfigRestorePlan {
    param(
        [string]$OriginalText,
        [string]$ExpectedText,
        [string]$CurrentText,
        [object[]]$Keys
    )

    $lineEnding = if ($CurrentText.Contains("`r`n")) { "`r`n" } else { "`n" }
    $blocks = New-Object 'System.Collections.Generic.List[object]'
    foreach ($block in @(Get-TomlBlocks -Text $CurrentText)) { $blocks.Add($block) }
    $conflicts = New-Object 'System.Collections.Generic.List[string]'
    $seen = @{}
    $changed = $false

    foreach ($managedKey in @($Keys)) {
        $table = [string]$managedKey.table
        $key = [string]$managedKey.key
        $identity = if ([string]::IsNullOrEmpty($table)) { $key } else { "$table.$key" }
        if ($seen.ContainsKey($identity)) {
            throw "Original config restore keys contain a duplicate managed key: $identity"
        }
        $seen[$identity] = $true

        $original = Get-OriginalConfigAssignment -Text $OriginalText -Table $table -Key $key
        $expected = Get-OriginalConfigAssignment -Text $ExpectedText -Table $table -Key $key
        $current = Get-OriginalConfigAssignment -Text $CurrentText -Table $table -Key $key
        if (Test-OriginalConfigAssignmentEqual -Left $current -Right $original) { continue }
        if (-not (Test-OriginalConfigAssignmentEqual -Left $current -Right $expected)) {
            $conflicts.Add($identity)
            continue
        }

        $matchingBlocks = @($blocks | Where-Object { [string]$_.name -ceq $table })
        if ($matchingBlocks.Count -eq 0 -and [bool]$original.present) {
            $originalBlock = @(Get-TomlBlocks -Text $OriginalText | Where-Object { [string]$_.name -ceq $table })[0]
            $newLines = New-Object 'System.Collections.Generic.List[string]'
            $newBlock = [pscustomobject]@{
                name = $table
                header = if ([string]::IsNullOrEmpty($table)) { $null } else { [string]$originalBlock.header }
                lines = $newLines
            }
            $blocks.Add($newBlock)
            $matchingBlocks = @($newBlock)
        }
        if ($matchingBlocks.Count -ne 1) {
            throw "Codex config restore target table is unavailable or ambiguous: $table"
        }
        $targetBlock = $matchingBlocks[0]
        $matchingIndices = New-Object 'System.Collections.Generic.List[int]'
        for ($index = 0; $index -lt $targetBlock.lines.Count; $index++) {
            $candidate = [string]$targetBlock.lines[$index]
            if ($candidate -match '^\s*([A-Za-z0-9_-]+)\s*=' -and $Matches[1] -ceq $key) {
                $matchingIndices.Add($index)
            }
        }
        if ($matchingIndices.Count -eq 0 -and [bool]$original.present) {
            $targetBlock.lines.Add([string]$original.line)
            $changed = $true
            continue
        }
        if ($matchingIndices.Count -ne 1) {
            throw "Codex config restore target assignment is unavailable: $identity"
        }
        if ([bool]$original.present) {
            $targetBlock.lines[$matchingIndices[0]] = [string]$original.line
        }
        else {
            $targetBlock.lines.RemoveAt($matchingIndices[0])
        }
        $changed = $true
    }

    if (-not $changed) {
        return [pscustomobject]@{ text = $CurrentText; conflicts = $conflicts.ToArray() }
    }

    $output = New-Object 'System.Collections.Generic.List[string]'
    foreach ($block in $blocks) {
        if ($null -ne $block.header) { $output.Add([string]$block.header) }
        foreach ($line in @($block.lines)) { $output.Add([string]$line) }
    }
    while ($output.Count -gt 0 -and [string]::IsNullOrEmpty($output[$output.Count - 1])) {
        $output.RemoveAt($output.Count - 1)
    }
    $text = if ($output.Count -eq 0) { '' } else { ($output.ToArray() -join $lineEnding) + $lineEnding }
    return [pscustomobject]@{ text = $text; conflicts = $conflicts.ToArray() }
}
