[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Routing', 'Policy', 'References')]
    [string]$Phase,
    [Parameter(Mandatory = $true)]
    [string]$ResultsPath,
    [string]$RoutingResultsPath,
    [string]$AttemptHistoryPath,
    [string]$ProjectRoot,
    [string]$RetryJustification,
    [switch]$BaselineImport
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'routing_evaluation_common.ps1')
. (Join-Path $PSScriptRoot 'routing_attempt_history.ps1')

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$ResultsPath = (Resolve-Path -LiteralPath $ResultsPath).Path
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot 'evidence\attempts.json'
}
$AttemptHistoryPath = [IO.Path]::GetFullPath($AttemptHistoryPath)
if (-not [string]::IsNullOrWhiteSpace($RetryJustification) -and $RetryJustification.Trim().Length -gt 300) {
    throw 'RetryJustification must not exceed 300 characters'
}

if ($Phase -in @('Policy', 'References')) {
    if ([string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw "RoutingResultsPath is required for the $Phase phase"
    }
    $RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $RoutingResultsPath -RoutingOnly | Out-Null
}

$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'trigger-cases.json') -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$routingResults = if ($Phase -in @('Policy', 'References')) {
    Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
else {
    $null
}
$expectedCapsule = switch ($Phase) {
    'Policy' { Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults }
    'References' { Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults }
    default { Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract }
}

$resultFileHash = (Get-FileHash -LiteralPath $ResultsPath -Algorithm SHA256).Hash
$results = $null
$parseFailure = $null
try {
    $results = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
catch {
    $parseFailure = $_.Exception.Message
}

$evaluatorId = if ($null -ne $results) { [string]$results.evaluator.id } else { '' }
$evaluatorModel = if ($null -ne $results) { [string]$results.evaluator.model } else { '' }
$evaluatorRuntime = if ($null -ne $results) { [string]$results.evaluator.runtime } else { '' }
$evaluatedAtUtc = if ($null -ne $results) { [string]$results.evaluator.evaluated_at_utc } else { '' }
$attemptKey = Get-AgentBaseRoutingAttemptKey -Phase $Phase -CandidateBundleSha256 $expectedCapsule.candidate_bundle_sha256 -EvaluationInputSha256 $expectedCapsule.evaluation_input_sha256 -EvaluationCapsuleSha256 $expectedCapsule.sha256

$lockPath = $AttemptHistoryPath + '.lock'
$lockStream = $null
$lockAcquired = $false
try {
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $lockAcquired = $true
    }
    catch {
        throw "Another routing-attempt recorder owns the history lock: $lockPath"
    }

    $history = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
    if ($null -eq $history) {
        $history = [pscustomobject]@{
            schema_version = Get-AgentBaseRoutingAttemptHistorySchema
            history_started_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            history_start_reason = if ($BaselineImport) {
                'Imported the current validated staged evidence; attempts before this baseline are not reconstructed.'
            }
            else {
                'Formal routing-attempt recording started before the first recorded evaluation.'
            }
            max_attempts_per_unchanged_input = Get-AgentBaseRoutingAttemptLimit
            attempts = @()
        }
    }
    elseif ([int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
        throw "Unsupported routing attempt history schema: $($history.schema_version)"
    }

    $attempts = @($history.attempts)
    $sameResult = @($attempts | Where-Object { [string]$_.phase -eq $Phase -and [string]$_.result_sha256 -eq $resultFileHash })
    if ($sameResult.Count -gt 0) {
        $existing = $sameResult[-1]
        if ([string]$existing.outcome -eq 'passed') {
            [pscustomobject]@{
                attempt_id = [string]$existing.attempt_id
                phase = $Phase
                outcome = 'passed'
                reused = $true
            }
            return
        }
        throw "The identical failed routing result is already recorded as attempt $($existing.attempt_id); change the candidate or evaluator result before retrying"
    }
    $preValidationFailure = $null
    if (-not [string]::IsNullOrWhiteSpace($evaluatorId)) {
        $samePassedEvaluator = @($attempts | Where-Object { [string]$_.outcome -eq 'passed' -and [string]$_.evaluator_id -eq $evaluatorId })
        if ($samePassedEvaluator.Count -gt 0) {
            $preValidationFailure = "Routing evaluator id has already been used by a passed formal attempt: $evaluatorId"
        }
    }

    $sameInputAttempts = @($attempts | Where-Object { [string]$_.attempt_key -eq $attemptKey })
    if ($BaselineImport -and $sameInputAttempts.Count -gt 0) {
        throw "BaselineImport is valid only for the first recorded attempt of a phase and input"
    }
    if (-not $BaselineImport -and $sameInputAttempts.Count -gt 0 -and [string]::IsNullOrWhiteSpace($RetryJustification)) {
        throw "The $Phase phase already has a formal attempt for the same candidate, input, and capsule; provide RetryJustification before generating one bounded nondeterministic retry, or change the candidate/input"
    }
    if ($sameInputAttempts.Count -ge (Get-AgentBaseRoutingAttemptLimit)) {
        throw "The $Phase phase has reached the limit of $(Get-AgentBaseRoutingAttemptLimit) attempts for unchanged input; change the candidate or evaluation input before another formal attempt"
    }

    $validationFailure = if ($null -ne $parseFailure) { $parseFailure } else { $preValidationFailure }
    if ($null -eq $validationFailure) {
        try {
            switch ($Phase) {
                'Policy' {
                    $null = Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults -PolicyResults $results
                }
                'References' {
                    $null = Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults -ReferenceResults $results
                }
                default {
                    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $ResultsPath -RoutingOnly | Out-Null
                }
            }
        }
        catch {
            $validationFailure = $_.Exception.Message
        }
    }

    $previous = @($attempts | Where-Object { [string]$_.phase -eq $Phase }) | Select-Object -Last 1
    $receiptDraft = [pscustomobject]@{
        candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
        evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
        evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
        evaluator_model = $evaluatorModel
        evaluator_runtime = $evaluatorRuntime
    }
    $receipt = [pscustomobject]@{
        attempt_id = [guid]::NewGuid().ToString('N')
        recorded_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        phase = $Phase
        origin = if ($BaselineImport) { 'baseline_import' } else { 'formal' }
        attempt_key = $attemptKey
        result_sha256 = $resultFileHash
        candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
        evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
        evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
        evaluator_id = $evaluatorId
        evaluator_model = $evaluatorModel
        evaluator_runtime = $evaluatorRuntime
        evaluated_at_utc = $evaluatedAtUtc
        outcome = if ($null -eq $validationFailure) { 'passed' } else { 'failed' }
        failure_class = if ($null -eq $validationFailure) {
            $null
        }
        elseif ($validationFailure -match 'failed with \d+ violation') {
            'oracle_violation'
        }
        else {
            'identity_or_schema'
        }
        failure_summary = Get-AgentBaseRoutingAttemptSummary -Message $validationFailure
        retry_justification = if ([string]::IsNullOrWhiteSpace($RetryJustification)) { $null } else { $RetryJustification.Trim() }
        previous_attempt_id = if ($null -eq $previous) { $null } else { [string]$previous.attempt_id }
        changed_since_previous = @(Get-AgentBaseRoutingAttemptChanges -Previous $previous -Current $receiptDraft)
    }
    $history.attempts = @($attempts) + $receipt
    Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history

    if ($null -ne $validationFailure) {
        throw "Recorded failed $Phase routing attempt $($receipt.attempt_id): $validationFailure"
    }
    [pscustomobject]@{
        attempt_id = [string]$receipt.attempt_id
        phase = $Phase
        outcome = 'passed'
        reused = $false
    }
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
    if ($lockAcquired -and (Test-Path -LiteralPath $lockPath)) {
        Remove-Item -LiteralPath $lockPath -Force
    }
}
