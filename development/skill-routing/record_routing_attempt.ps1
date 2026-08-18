[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Begin', 'Finish')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [ValidateSet('Routing', 'Policy', 'References')]
    [string]$Phase,
    [string]$AttemptId,
    [string]$ResultsPath,
    [string]$RoutingResultsPath,
    [string]$AttemptHistoryPath,
    [string]$ProjectRoot,
    [string]$EvaluatorId,
    [string]$EvaluatorModel,
    [string]$EvaluatorRuntime,
    [string]$RetryJustification,
    [string]$ExecutionFailureSummary,
    [switch]$BaselineImport
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'routing_evaluation_common.ps1')
. (Join-Path $PSScriptRoot 'routing_attempt_history.ps1')

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not [string]::IsNullOrWhiteSpace($ResultsPath)) {
    $ResultsPath = (Resolve-Path -LiteralPath $ResultsPath).Path
}
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot 'evidence\attempts.json'
}
$AttemptHistoryPath = [IO.Path]::GetFullPath($AttemptHistoryPath)

if (-not [string]::IsNullOrWhiteSpace($RetryJustification) -and $RetryJustification.Trim().Length -gt 300) {
    throw 'RetryJustification must not exceed 300 characters'
}
if (-not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary) -and $ExecutionFailureSummary.Trim().Length -gt 500) {
    throw 'ExecutionFailureSummary must not exceed 500 characters'
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
$cycleId = if ($Phase -eq 'Routing') { [string]$expectedCapsule.sha256 } else { [string]$routingResults.evaluation_capsule_sha256 }
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
    if ($Action -eq 'Begin') {
        foreach ($identity in @($EvaluatorId, $EvaluatorModel, $EvaluatorRuntime)) {
            if ([string]::IsNullOrWhiteSpace($identity) -or $identity.Length -gt 300) {
                throw 'Begin requires bounded EvaluatorId, EvaluatorModel, and EvaluatorRuntime values'
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($AttemptId) -or -not [string]::IsNullOrWhiteSpace($ResultsPath) -or -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary)) {
            throw 'Begin does not accept AttemptId, ResultsPath, or ExecutionFailureSummary'
        }

        if ($null -eq $history) {
            $history = New-AgentBaseRoutingAttemptHistory -CycleId $cycleId -Reason $(if ($BaselineImport) {
                'Imported the current validated staged evidence; attempts before this baseline are not reconstructed.'
            }
            else {
                'Formal routing evaluation cycle began before evaluator execution.'
            })
        }
        elseif ([int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
            throw "Unsupported routing attempt history schema: $($history.schema_version)"
        }
        elseif ([string]$history.active_cycle_id -ne $cycleId) {
            $unfinished = @($history.attempts | Where-Object { [string]$_.outcome -eq 'started' })
            if ($unfinished.Count -gt 0) {
                throw "Cannot start routing cycle $cycleId while cycle $($history.active_cycle_id) has unfinished attempts"
            }
            $previousHash = (Get-FileHash -LiteralPath $AttemptHistoryPath -Algorithm SHA256).Hash
            $history = New-AgentBaseRoutingAttemptHistory -CycleId $cycleId -Reason 'Started a changed routing evaluation cycle; the previous bounded ledger remains recoverable from Git history and this hash link.' -PreviousCycleId ([string]$history.active_cycle_id) -PreviousLedgerSha256 $previousHash -PreviousAttemptCount @($history.attempts).Count
        }

        $attempts = @($history.attempts)
        if ($BaselineImport -and @($attempts | Where-Object { [string]$_.phase -eq $Phase }).Count -gt 0) {
            throw "BaselineImport is valid only for the first recorded attempt of a phase"
        }
        if (@($attempts | Where-Object { [string]$_.evaluator_id -eq $EvaluatorId }).Count -gt 0) {
            throw "Routing evaluator id has already been used in the active cycle: $EvaluatorId"
        }
        $sameInputAttempts = @($attempts | Where-Object { [string]$_.attempt_key -eq $attemptKey })
        if (-not $BaselineImport -and $sameInputAttempts.Count -gt 0 -and [string]::IsNullOrWhiteSpace($RetryJustification)) {
            throw "The $Phase phase already has a formal attempt for the same candidate, input, and capsule; provide RetryJustification before one bounded retry, or change the candidate/input"
        }
        if ($sameInputAttempts.Count -ge (Get-AgentBaseRoutingAttemptLimit)) {
            throw "The $Phase phase has reached the limit of $(Get-AgentBaseRoutingAttemptLimit) attempts for unchanged input; change the candidate or evaluation input before another formal attempt"
        }
        if ($attempts.Count -ge (Get-AgentBaseRoutingAttemptLedgerLimit)) {
            throw "The active routing cycle has reached its bounded receipt limit of $(Get-AgentBaseRoutingAttemptLedgerLimit)"
        }

        $previous = @($attempts | Where-Object { [string]$_.phase -eq $Phase }) | Select-Object -Last 1
        $receiptDraft = [pscustomobject]@{
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            evaluator_model = $EvaluatorModel
            evaluator_runtime = $EvaluatorRuntime
        }
        $receipt = [pscustomobject]@{
            attempt_id = [guid]::NewGuid().ToString('N')
            cycle_id = $cycleId.ToUpperInvariant()
            started_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            completed_at_utc = $null
            phase = $Phase
            origin = if ($BaselineImport) { 'baseline_import' } else { 'formal' }
            attempt_key = $attemptKey
            result_sha256 = $null
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            evaluator_id = $EvaluatorId.Trim()
            evaluator_model = $EvaluatorModel.Trim()
            evaluator_runtime = $EvaluatorRuntime.Trim()
            evaluated_at_utc = $null
            outcome = 'started'
            failure_class = $null
            failure_summary = $null
            retry_justification = if ([string]::IsNullOrWhiteSpace($RetryJustification)) { $null } else { $RetryJustification.Trim() }
            previous_attempt_id = if ($null -eq $previous) { $null } else { [string]$previous.attempt_id }
            changed_since_previous = @(Get-AgentBaseRoutingAttemptChanges -Previous $previous -Current $receiptDraft)
        }
        $history.attempts = @($attempts) + $receipt
        Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history
        [pscustomobject]@{
            attempt_id = [string]$receipt.attempt_id
            cycle_id = [string]$receipt.cycle_id
            phase = $Phase
            outcome = 'started'
        }
        return
    }

    if ($BaselineImport -or -not [string]::IsNullOrWhiteSpace($RetryJustification) -or -not [string]::IsNullOrWhiteSpace($EvaluatorId) -or -not [string]::IsNullOrWhiteSpace($EvaluatorModel) -or -not [string]::IsNullOrWhiteSpace($EvaluatorRuntime)) {
        throw 'Finish does not accept Begin-only evaluator, retry, or baseline fields'
    }
    if ($null -eq $history -or [int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
        throw 'Finish requires an existing current-schema routing attempt ledger'
    }
    if ([string]$history.active_cycle_id -ne $cycleId) {
        throw "Finish input belongs to routing cycle $cycleId, not active cycle $($history.active_cycle_id)"
    }
    if ($AttemptId -notmatch '^[0-9a-f]{32}$') {
        throw 'Finish requires a valid AttemptId returned by Begin'
    }
    $matching = @($history.attempts | Where-Object { [string]$_.attempt_id -eq $AttemptId -and [string]$_.phase -eq $Phase })
    if ($matching.Count -ne 1) {
        throw "Finish could not find exactly one $Phase attempt: $AttemptId"
    }
    $receipt = $matching[0]
    if ([string]$receipt.outcome -ne 'started') {
        throw "Routing attempt $AttemptId is already complete with outcome $($receipt.outcome)"
    }
    if ([string]$receipt.attempt_key -ne $attemptKey) {
        throw "Routing attempt $AttemptId no longer matches the current candidate, input, or capsule"
    }

    $hasResult = -not [string]::IsNullOrWhiteSpace($ResultsPath)
    $hasExecutionFailure = -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary)
    if ($hasResult -eq $hasExecutionFailure) {
        throw 'Finish requires exactly one of ResultsPath or ExecutionFailureSummary'
    }

    $validationFailure = $null
    $failureClass = $null
    $resultFileHash = $null
    $evaluatedAtUtc = $null
    if ($hasExecutionFailure) {
        $validationFailure = $ExecutionFailureSummary.Trim()
        $failureClass = 'execution_failed'
    }
    else {
        $resultFileHash = (Get-FileHash -LiteralPath $ResultsPath -Algorithm SHA256).Hash
        $results = $null
        try {
            $results = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        }
        catch {
            $validationFailure = $_.Exception.Message
            $failureClass = 'identity_or_schema'
        }
        if ($null -ne $results) {
            if ([string]$results.evaluator.id -ne [string]$receipt.evaluator_id -or
                [string]$results.evaluator.model -ne [string]$receipt.evaluator_model -or
                [string]$results.evaluator.runtime -ne [string]$receipt.evaluator_runtime) {
                $validationFailure = 'Evaluator identity in the result does not match the identity registered by Begin'
                $failureClass = 'identity_or_schema'
            }
            $evaluatedAtUtc = [string]$results.evaluator.evaluated_at_utc
        }
        if ($null -eq $validationFailure) {
            try {
                switch ($Phase) {
                    'Policy' { $null = Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults -PolicyResults $results }
                    'References' { $null = Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults -ReferenceResults $results }
                    default { & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $ResultsPath -RoutingOnly | Out-Null }
                }
            }
            catch {
                $validationFailure = $_.Exception.Message
                $failureClass = if ($validationFailure -match 'failed with \d+ violation') { 'oracle_violation' } else { 'identity_or_schema' }
            }
        }
    }

    $receipt.completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $receipt.result_sha256 = $resultFileHash
    $receipt.evaluated_at_utc = $evaluatedAtUtc
    $receipt.outcome = if ($null -eq $validationFailure) { 'passed' } else { 'failed' }
    $receipt.failure_class = $failureClass
    $receipt.failure_summary = Get-AgentBaseRoutingAttemptSummary -Message $validationFailure
    Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history

    if ($null -ne $validationFailure) {
        throw "Recorded failed $Phase routing attempt $AttemptId ($failureClass): $validationFailure"
    }
    [pscustomobject]@{
        attempt_id = $AttemptId
        cycle_id = [string]$receipt.cycle_id
        phase = $Phase
        outcome = 'passed'
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
