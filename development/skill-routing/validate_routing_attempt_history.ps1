[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$AttemptHistoryPath,
    [string]$CurrentEvidencePath,
    [switch]$AllowStarted
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'routing_attempt_history.ps1')

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot 'evidence\attempts.json'
}
$AttemptHistoryPath = (Resolve-Path -LiteralPath $AttemptHistoryPath).Path
$history = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
if ($null -eq $history -or [int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
    throw 'Routing attempt history is missing or uses an unsupported schema'
}
if ([string]$history.active_cycle_id -notmatch '^[0-9A-Fa-f]{64}$') {
    throw 'Routing attempt history has an invalid active cycle id'
}
if ([int]$history.max_attempts_per_unchanged_input -ne (Get-AgentBaseRoutingAttemptLimit) -or
    [int]$history.max_receipts_per_cycle -ne (Get-AgentBaseRoutingAttemptLedgerLimit)) {
    throw 'Routing attempt history uses different bounded receipt limits'
}
if (@($history.attempts).Count -gt (Get-AgentBaseRoutingAttemptLedgerLimit)) {
    throw 'Routing attempt history exceeds its active-cycle receipt limit'
}
if (-not [string]::IsNullOrWhiteSpace([string]$history.previous_ledger_sha256) -and [string]$history.previous_ledger_sha256 -notmatch '^[0-9A-Fa-f]{64}$') {
    throw 'Routing attempt history has an invalid previous-ledger hash link'
}
if (-not [string]::IsNullOrWhiteSpace([string]$history.previous_cycle_id) -and [string]$history.previous_cycle_id -notmatch '^[0-9A-Fa-f]{64}$') {
    throw 'Routing attempt history has an invalid previous cycle id'
}
if ([int]$history.previous_attempt_count -lt 0 -or [string]::IsNullOrWhiteSpace([string]$history.ledger_start_reason)) {
    throw 'Routing attempt history lacks bounded ledger rollover metadata'
}

$ledgerStarted = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse([string]$history.ledger_started_at_utc, [ref]$ledgerStarted) -or $ledgerStarted.Offset -ne [TimeSpan]::Zero) {
    throw 'Routing attempt history has a non-UTC ledger start timestamp'
}

$attemptIds = @{}
$evaluatorIds = @{}
$attemptsByKey = @{}
foreach ($attempt in @($history.attempts)) {
    $attemptId = [string]$attempt.attempt_id
    if ($attemptId -notmatch '^[0-9a-f]{32}$' -or $attemptIds.ContainsKey($attemptId)) {
        throw "Routing attempt history contains an invalid or duplicate attempt id: $attemptId"
    }
    $attemptIds[$attemptId] = $true
    if ([string]$attempt.cycle_id -ne [string]$history.active_cycle_id) {
        throw "Routing attempt $attemptId is outside the active bounded cycle"
    }
    if ([string]$attempt.phase -notin @('Routing', 'Policy', 'References')) {
        throw "Routing attempt has an invalid phase: $($attempt.phase)"
    }
    if ([string]$attempt.origin -notin @('formal', 'baseline_import')) {
        throw "Routing attempt has an invalid origin: $($attempt.origin)"
    }
    if ([string]$attempt.outcome -notin @('started', 'passed', 'failed')) {
        throw "Routing attempt has an invalid outcome: $($attempt.outcome)"
    }
    foreach ($hashField in @('candidate_bundle_sha256', 'evaluation_input_sha256', 'evaluation_capsule_sha256')) {
        if ([string]$attempt.$hashField -notmatch '^[0-9A-Fa-f]{64}$') {
            throw "Routing attempt $attemptId has an invalid $hashField"
        }
    }
    if ([string]$attempt.attempt_key -ne (Get-AgentBaseRoutingAttemptKey -Phase $attempt.phase -CandidateBundleSha256 $attempt.candidate_bundle_sha256 -EvaluationInputSha256 $attempt.evaluation_input_sha256 -EvaluationCapsuleSha256 $attempt.evaluation_capsule_sha256)) {
        throw "Routing attempt $attemptId has a mismatched attempt key"
    }
    $started = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$attempt.started_at_utc, [ref]$started) -or $started.Offset -ne [TimeSpan]::Zero) {
        throw "Routing attempt $attemptId has a non-UTC start timestamp"
    }
    if (([string]$attempt.failure_summary).Length -gt 500 -or ([string]$attempt.retry_justification).Length -gt 300) {
        throw "Routing attempt $attemptId exceeds its bounded text contract"
    }
    foreach ($identityField in @('evaluator_id', 'evaluator_model', 'evaluator_runtime')) {
        if ([string]::IsNullOrWhiteSpace([string]$attempt.$identityField) -or ([string]$attempt.$identityField).Length -gt 300) {
            throw "Routing attempt $attemptId has an invalid $identityField"
        }
    }
    $evaluatorId = [string]$attempt.evaluator_id
    if ($evaluatorIds.ContainsKey($evaluatorId)) {
        throw "Routing attempt history reuses evaluator id: $evaluatorId"
    }
    $evaluatorIds[$evaluatorId] = $true

    if ([string]$attempt.outcome -eq 'started') {
        if (-not $AllowStarted) {
            throw "Routing attempt $attemptId was started but not explicitly finished"
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$attempt.completed_at_utc) -or
            -not [string]::IsNullOrWhiteSpace([string]$attempt.result_sha256) -or
            -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_class) -or
            -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary)) {
            throw "Started routing attempt $attemptId carries completion fields"
        }
    }
    else {
        $completed = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$attempt.completed_at_utc, [ref]$completed) -or $completed.Offset -ne [TimeSpan]::Zero -or $completed -lt $started) {
            throw "Routing attempt $attemptId has an invalid completion timestamp"
        }
        if ([string]$attempt.outcome -eq 'passed') {
            if ([string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                [string]::IsNullOrWhiteSpace([string]$attempt.evaluated_at_utc) -or
                -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_class) -or
                -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary)) {
                throw "Passed routing attempt $attemptId has invalid result or failure fields"
            }
        }
        else {
            if ([string]$attempt.failure_class -notin @('oracle_violation', 'identity_or_schema', 'execution_failed') -or [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary)) {
                throw "Failed routing attempt $attemptId lacks a bounded failure classification"
            }
            if ([string]$attempt.failure_class -eq 'execution_failed' -and -not [string]::IsNullOrWhiteSpace([string]$attempt.result_sha256)) {
                throw "Execution-failed routing attempt $attemptId unexpectedly carries a result hash"
            }
            if ([string]$attempt.failure_class -ne 'execution_failed' -and [string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$') {
                throw "Result-validation failure $attemptId lacks a result hash"
            }
        }
    }

    $key = [string]$attempt.attempt_key
    if (-not $attemptsByKey.ContainsKey($key)) {
        $attemptsByKey[$key] = New-Object 'System.Collections.Generic.List[object]'
    }
    $attemptsByKey[$key].Add($attempt)
}

foreach ($entry in $attemptsByKey.GetEnumerator()) {
    $sameInputAttempts = [object[]]$entry.Value
    if ($sameInputAttempts.Count -gt (Get-AgentBaseRoutingAttemptLimit)) {
        throw "Routing attempt history exceeds the unchanged-input attempt limit for $($entry.Key)"
    }
    for ($index = 1; $index -lt $sameInputAttempts.Count; $index++) {
        if ([string]::IsNullOrWhiteSpace([string]$sameInputAttempts[$index].retry_justification)) {
            throw "Routing attempt $($sameInputAttempts[$index].attempt_id) repeats unchanged input without a justification"
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($CurrentEvidencePath)) {
    $CurrentEvidencePath = (Resolve-Path -LiteralPath $CurrentEvidencePath).Path
    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $CurrentEvidencePath | Out-Null
    $current = Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    if ([string]$history.active_cycle_id -ne [string]$current.evaluation_capsule_sha256) {
        throw 'Current evidence does not belong to the active routing-attempt cycle'
    }
    $stages = @(
        [pscustomobject]@{ phase = 'Routing'; result = $current },
        [pscustomobject]@{ phase = 'Policy'; result = $current.policy_evaluation },
        [pscustomobject]@{ phase = 'References'; result = $current.reference_evaluation }
    )
    foreach ($stage in $stages) {
        $matchingReceipt = @($history.attempts | Where-Object {
            [string]$_.phase -eq [string]$stage.phase -and
            [string]$_.outcome -eq 'passed' -and
            [string]$_.evaluator_id -eq [string]$stage.result.evaluator.id -and
            [string]$_.candidate_bundle_sha256 -eq [string]$stage.result.candidate_bundle_sha256 -and
            [string]$_.evaluation_input_sha256 -eq [string]$stage.result.evaluation_input_sha256 -and
            [string]$_.evaluation_capsule_sha256 -eq [string]$stage.result.evaluation_capsule_sha256
        })
        if ($matchingReceipt.Count -ne 1) {
            throw "Current $($stage.phase) evidence does not have exactly one matching passed attempt receipt"
        }
    }
}

Write-Output "Routing attempt history valid: $(@($history.attempts).Count)/$(Get-AgentBaseRoutingAttemptLedgerLimit) receipts in active cycle $($history.active_cycle_id); unchanged inputs allow at most $(Get-AgentBaseRoutingAttemptLimit) justified attempts."
