function Get-AgentBaseRoutingAttemptHistorySchema {
    return 3
}

function Get-AgentBaseRoutingAttemptLimit {
    return 2
}

function Get-AgentBaseRoutingOrchestrationFailureLimit {
    return 2
}

function Get-AgentBaseRoutingAttemptLedgerLimit {
    return 6
}

function Get-AgentBaseRoutingAttemptKey {
    param(
        [string]$Phase,
        [string]$CandidateBundleSha256,
        [string]$EvaluationInputSha256,
        [string]$EvaluationCapsuleSha256
    )

    return @(
        $Phase.ToLowerInvariant()
        $CandidateBundleSha256.ToUpperInvariant()
        $EvaluationInputSha256.ToUpperInvariant()
        $EvaluationCapsuleSha256.ToUpperInvariant()
    ) -join '|'
}

function Read-AgentBaseRoutingAttemptHistory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Routing attempt history must be a real file: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
}

function Write-AgentBaseRoutingAttemptHistory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$History
    )

    $directory = Split-Path -Parent $Path
    if ([string]::IsNullOrWhiteSpace($directory) -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Routing attempt history directory must already exist: $directory"
    }
    $json = $History | ConvertTo-Json -Depth 50
    $temporaryPath = Join-Path $directory ('.{0}.{1}.tmp' -f ([IO.Path]::GetFileName($Path)), [guid]::NewGuid().ToString('N'))
    $utf8NoBom = [Text.UTF8Encoding]::new($false)
    try {
        [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, $utf8NoBom)
        [IO.File]::Move($temporaryPath, [IO.Path]::GetFullPath($Path), $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            [IO.File]::Delete($temporaryPath)
        }
    }
}

function New-AgentBaseRoutingAttemptHistory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CycleId,
        [Parameter(Mandatory = $true)]
        [string]$Reason,
        [string]$PreviousCycleId,
        [string]$PreviousLedgerSha256,
        [int]$PreviousAttemptCount = 0
    )

    return [pscustomobject][ordered]@{
        schema_version = Get-AgentBaseRoutingAttemptHistorySchema
        active_cycle_id = $CycleId.ToUpperInvariant()
        ledger_started_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        ledger_start_reason = $Reason
        previous_cycle_id = if ([string]::IsNullOrWhiteSpace($PreviousCycleId)) { $null } else { $PreviousCycleId.ToUpperInvariant() }
        previous_ledger_sha256 = if ([string]::IsNullOrWhiteSpace($PreviousLedgerSha256)) { $null } else { $PreviousLedgerSha256.ToUpperInvariant() }
        previous_attempt_count = $PreviousAttemptCount
        max_attempts_per_unchanged_input = Get-AgentBaseRoutingAttemptLimit
        max_orchestration_failures_per_unchanged_input = Get-AgentBaseRoutingOrchestrationFailureLimit
        max_receipts_per_cycle = Get-AgentBaseRoutingAttemptLedgerLimit
        attempts = @()
    }
}

function Get-AgentBaseRoutingAttemptSummary {
    param(
        [string]$Message,
        [int]$MaximumLength = 500
    )

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return $null
    }
    $summary = [regex]::Replace($Message.Trim(), '\s+', ' ')
    if ($summary.Length -gt $MaximumLength) {
        return $summary.Substring(0, $MaximumLength)
    }
    return $summary
}

function Get-AgentBaseRoutingAttemptChanges {
    param(
        [object]$Previous,
        [object]$Current
    )

    if ($null -eq $Previous) {
        return @('initial_receipt')
    }
    $changes = New-Object 'System.Collections.Generic.List[string]'
    foreach ($field in @(
        'candidate_bundle_sha256',
        'evaluation_input_sha256',
        'evaluation_capsule_sha256',
        'origin',
        'evaluator_model',
        'evaluator_runtime'
    )) {
        if ([string]$Previous.$field -ne [string]$Current.$field) {
            $changes.Add($field)
        }
    }
    if ($changes.Count -eq 0) {
        $changes.Add('receipt_only')
    }
    return [object[]]$changes
}
