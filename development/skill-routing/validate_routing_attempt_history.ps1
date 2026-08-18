[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$AttemptHistoryPath,
    [string]$CurrentEvidencePath
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
if ([int]$history.max_attempts_per_unchanged_input -ne (Get-AgentBaseRoutingAttemptLimit)) {
    throw 'Routing attempt history uses a different unchanged-input attempt limit'
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
    if ([string]$attempt.phase -notin @('Routing', 'Policy', 'References')) {
        throw "Routing attempt has an invalid phase: $($attempt.phase)"
    }
    if ([string]$attempt.origin -notin @('formal', 'baseline_import')) {
        throw "Routing attempt has an invalid origin: $($attempt.origin)"
    }
    if ([string]$attempt.outcome -notin @('passed', 'failed')) {
        throw "Routing attempt has an invalid outcome: $($attempt.outcome)"
    }
    foreach ($hashField in @('result_sha256', 'candidate_bundle_sha256', 'evaluation_input_sha256', 'evaluation_capsule_sha256')) {
        if ([string]$attempt.$hashField -notmatch '^[0-9A-Fa-f]{64}$') {
            throw "Routing attempt $attemptId has an invalid $hashField"
        }
    }
    if ([string]$attempt.attempt_key -ne (Get-AgentBaseRoutingAttemptKey -Phase $attempt.phase -CandidateBundleSha256 $attempt.candidate_bundle_sha256 -EvaluationInputSha256 $attempt.evaluation_input_sha256 -EvaluationCapsuleSha256 $attempt.evaluation_capsule_sha256)) {
        throw "Routing attempt $attemptId has a mismatched attempt key"
    }
    $recorded = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$attempt.recorded_at_utc, [ref]$recorded) -or $recorded.Offset -ne [TimeSpan]::Zero) {
        throw "Routing attempt $attemptId has a non-UTC recorded timestamp"
    }
    if (([string]$attempt.failure_summary).Length -gt 500 -or ([string]$attempt.retry_justification).Length -gt 300) {
        throw "Routing attempt $attemptId exceeds its bounded text contract"
    }
    if ([string]$attempt.outcome -eq 'passed' -and (-not [string]::IsNullOrWhiteSpace([string]$attempt.failure_class) -or -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary))) {
        throw "Passed routing attempt $attemptId carries failure fields"
    }
    if ([string]$attempt.outcome -eq 'failed' -and ([string]$attempt.failure_class -notin @('oracle_violation', 'identity_or_schema') -or [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary))) {
        throw "Failed routing attempt $attemptId lacks a bounded failure classification"
    }
    $evaluatorId = [string]$attempt.evaluator_id
    if (-not [string]::IsNullOrWhiteSpace($evaluatorId) -and [string]$attempt.outcome -eq 'passed') {
        if ($evaluatorIds.ContainsKey($evaluatorId)) {
            throw "Passed routing attempt history reuses evaluator id: $evaluatorId"
        }
        $evaluatorIds[$evaluatorId] = $true
    }
    elseif ([string]$attempt.outcome -eq 'passed') {
        throw "Passed routing attempt $attemptId lacks an evaluator id"
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

Write-Output "Routing attempt history valid: $(@($history.attempts).Count) bounded receipts; unchanged inputs allow at most $(Get-AgentBaseRoutingAttemptLimit) justified attempts."
