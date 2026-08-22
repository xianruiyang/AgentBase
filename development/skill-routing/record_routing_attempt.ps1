[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Begin', 'Finish', 'Reuse', 'CarryForward', 'Revalidate')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [ValidateSet('Routing', 'Policy', 'References')]
    [string]$Phase,
    [string]$AttemptId,
    [string]$ResultsPath,
    [string]$RoutingResultsPath,
    [string]$SourceEvidencePath,
    [string]$SourceStagePath,
    [string]$SourceAttemptHistoryPath,
    [string]$AttemptHistoryPath,
    [string]$ProjectRoot,
    [string]$EvaluatorId,
    [string]$EvaluatorModel,
    [string]$EvaluatorRuntime,
    [string]$RetryJustification,
    [string]$ExecutionFailureSummary,
    [string]$OrchestrationFailureSummary,
    [Nullable[long]]$DurationMilliseconds,
    [Nullable[long]]$InputTokens,
    [Nullable[long]]$CachedInputTokens,
    [Nullable[long]]$OutputTokens,
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
if (-not [string]::IsNullOrWhiteSpace($SourceEvidencePath)) {
    $SourceEvidencePath = (Resolve-Path -LiteralPath $SourceEvidencePath).Path
}
if (-not [string]::IsNullOrWhiteSpace($SourceStagePath)) {
    $SourceStagePath = (Resolve-Path -LiteralPath $SourceStagePath).Path
}
if (-not [string]::IsNullOrWhiteSpace($SourceAttemptHistoryPath)) {
    $SourceAttemptHistoryPath = (Resolve-Path -LiteralPath $SourceAttemptHistoryPath).Path
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
if (-not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary) -and $OrchestrationFailureSummary.Trim().Length -gt 500) {
    throw 'OrchestrationFailureSummary must not exceed 500 characters'
}
foreach ($metric in @($DurationMilliseconds, $InputTokens, $CachedInputTokens, $OutputTokens)) {
    if ($null -ne $metric -and [long]$metric -lt 0) {
        throw 'Duration and token metrics must be non-negative when supplied'
    }
}

if ($Phase -eq 'References') {
    if ([string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw 'RoutingResultsPath is required for the References phase'
    }
    $RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
}
elseif (-not [string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
    throw "RoutingResultsPath is not accepted for the $Phase phase"
}

$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'trigger-cases.json') -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$routingResults = if ($Phase -eq 'References') {
    Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
else {
    $null
}
if ($null -ne $routingResults) {
    Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults | Out-Null
}
$expectedCapsule = switch ($Phase) {
    'Policy' { Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract }
    'References' { Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults }
    default { Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract }
}
$cycleId = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $ProjectRoot -Contract $contract
$attemptKey = Get-AgentBaseRoutingAttemptKey -Phase $Phase -CandidateBundleSha256 $expectedCapsule.candidate_bundle_sha256 -EvaluationInputSha256 $expectedCapsule.evaluation_input_sha256 -EvaluationCapsuleSha256 $expectedCapsule.sha256

function Invoke-AgentBasePhaseValidation {
    param(
        [object]$Results
    )

    switch ($Phase) {
        'Policy' { Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -PolicyResults $Results | Out-Null }
        'References' { Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults -ReferenceResults $Results | Out-Null }
        default { Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $Results | Out-Null }
    }
}

function Get-AgentBaseSourceStage {
    param(
        [object]$Evidence
    )

    switch ($Phase) {
        'Policy' { return $Evidence.policy_evaluation }
        'References' { return $Evidence.reference_evaluation }
        default { return $Evidence }
    }
}

function New-AgentBaseCurrentHistory {
    param(
        [object]$ExistingHistory
    )

    if ($null -eq $ExistingHistory) {
        return New-AgentBaseRoutingAttemptHistory -CycleId $cycleId -Reason $(if ($BaselineImport) {
            'Imported validated staged evidence; attempts before this baseline are not reconstructed.'
        }
        else {
            'Started a formal phase-visible routing evidence cycle.'
        })
    }
    if ([int]$ExistingHistory.schema_version -eq (Get-AgentBaseRoutingAttemptHistorySchema) -and
        [string]$ExistingHistory.active_cycle_id -eq $cycleId) {
        return $ExistingHistory
    }
    $unfinished = @($ExistingHistory.attempts | Where-Object { [string]$_.outcome -eq 'started' })
    if ($unfinished.Count -gt 0) {
        throw "Cannot start evaluation generation $cycleId while generation $($ExistingHistory.active_cycle_id) has unfinished attempts"
    }
    $previousHash = (Get-FileHash -LiteralPath $AttemptHistoryPath -Algorithm SHA256).Hash
    $reason = if ([int]$ExistingHistory.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
        'Migrated the bounded attempt ledger to the phase-visible evidence schema; the previous ledger remains recoverable from Git history and this hash link.'
    }
    else {
        'Started a changed phase-visible evaluation generation; the previous bounded ledger remains recoverable from Git history and this hash link.'
    }
    return New-AgentBaseRoutingAttemptHistory -CycleId $cycleId -Reason $reason -PreviousCycleId ([string]$ExistingHistory.active_cycle_id) -PreviousLedgerSha256 $previousHash -PreviousAttemptCount @($ExistingHistory.attempts).Count
}

$lockPath = $AttemptHistoryPath + '.lock'
$lockStream = $null
$lockAcquired = $false
try {
    $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(10)
    while (-not $lockAcquired) {
        try {
            $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $lockAcquired = $true
        }
        catch [IO.IOException] {
            if ([DateTimeOffset]::UtcNow -ge $lockDeadline) {
                throw "Timed out after 10 seconds waiting for the routing-attempt history lock: $lockPath"
            }
            [Threading.Thread]::Sleep(50)
        }
    }

    $historyBeforeRollover = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
    if ($null -ne $historyBeforeRollover -and [int]$historyBeforeRollover.schema_version -eq (Get-AgentBaseRoutingAttemptHistorySchema) -and
        -not ($historyBeforeRollover.PSObject.Properties.Name -contains 'max_orchestration_failures_per_unchanged_input')) {
        $historyBeforeRollover | Add-Member -NotePropertyName max_orchestration_failures_per_unchanged_input -NotePropertyValue (Get-AgentBaseRoutingOrchestrationFailureLimit)
    }

    if ($Action -eq 'Revalidate') {
        if ([string]::IsNullOrWhiteSpace($ResultsPath)) {
            throw 'Revalidate requires ResultsPath'
        }
        if (-not [string]::IsNullOrWhiteSpace($AttemptId) -or
            -not [string]::IsNullOrWhiteSpace($SourceEvidencePath) -or -not [string]::IsNullOrWhiteSpace($SourceStagePath) -or
            -not [string]::IsNullOrWhiteSpace($SourceAttemptHistoryPath) -or -not [string]::IsNullOrWhiteSpace($RetryJustification) -or
            -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary) -or -not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorId) -or -not [string]::IsNullOrWhiteSpace($EvaluatorModel) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorRuntime) -or $BaselineImport -or $null -ne $DurationMilliseconds -or
            $null -ne $InputTokens -or $null -ne $CachedInputTokens -or $null -ne $OutputTokens) {
            throw 'Revalidate accepts only its phase, result, routing dependency, project root, and history path'
        }
        $history = $historyBeforeRollover
        if ($null -eq $history -or [int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema) -or
            [string]$history.active_cycle_id -ne $cycleId) {
            throw 'Revalidate requires a current-generation attempt ledger'
        }
        $stage = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        Invoke-AgentBasePhaseValidation -Results $stage
        $resultFileHash = (Get-FileHash -LiteralPath $ResultsPath -Algorithm SHA256).Hash
        $stageSemanticHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $Phase -Results $stage
        $attempts = @($history.attempts)
        if (@($attempts | Where-Object {
            [string]$_.attempt_key -eq $attemptKey -and [string]$_.outcome -eq 'passed'
        }).Count -gt 0) {
            throw "$Phase already has a passed receipt for the same visible input"
        }
        $sourceReceipts = @($attempts | Where-Object {
            [string]$_.phase -eq $Phase -and [string]$_.attempt_key -eq $attemptKey -and
            [string]$_.outcome -eq 'failed' -and [string]$_.failure_class -eq 'oracle_violation' -and
            [string]$_.result_sha256 -eq $resultFileHash -and
            [string]$_.evaluator_id -eq [string]$stage.evaluator.id -and
            [string]$_.candidate_bundle_sha256 -eq [string]$stage.candidate_bundle_sha256 -and
            [string]$_.evaluation_input_sha256 -eq [string]$stage.evaluation_input_sha256 -and
            [string]$_.evaluation_capsule_sha256 -eq [string]$stage.evaluation_capsule_sha256
        })
        if ($sourceReceipts.Count -ne 1) {
            throw "$Phase revalidation requires exactly one matching oracle-violation receipt and the identical result file"
        }
        if ($attempts.Count -ge (Get-AgentBaseRoutingAttemptLedgerLimit)) {
            throw "The active routing generation has reached its bounded receipt limit of $(Get-AgentBaseRoutingAttemptLedgerLimit)"
        }
        $sourceReceipt = $sourceReceipts[0]
        $now = [DateTimeOffset]::UtcNow.ToString('o')
        $receipt = [pscustomobject][ordered]@{
            attempt_id = [guid]::NewGuid().ToString('N')
            cycle_id = $cycleId.ToUpperInvariant()
            started_at_utc = $now
            completed_at_utc = $now
            phase = $Phase
            origin = 'oracle_revalidation'
            attempt_key = $attemptKey
            result_sha256 = $resultFileHash
            stage_result_sha256 = $stageSemanticHash
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            evaluator_id = [string]$stage.evaluator.id
            evaluator_model = [string]$stage.evaluator.model
            evaluator_runtime = [string]$stage.evaluator.runtime
            evaluated_at_utc = [string]$stage.evaluator.evaluated_at_utc
            outcome = 'passed'
            failure_class = $null
            failure_summary = $null
            retry_justification = $null
            previous_attempt_id = [string]$sourceReceipt.attempt_id
            changed_since_previous = @('oracle_contract')
            source_evidence_sha256 = $null
            source_receipt_id = [string]$sourceReceipt.attempt_id
            source_cycle_id = [string]$history.active_cycle_id
            duration_ms = 0
            input_tokens = 0
            cached_input_tokens = 0
            output_tokens = 0
        }
        $history.attempts = @($attempts) + $receipt
        Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history
        [pscustomobject]@{
            attempt_id = [string]$receipt.attempt_id
            cycle_id = [string]$receipt.cycle_id
            phase = $Phase
            origin = 'oracle_revalidation'
            outcome = 'passed'
        }
        return
    }

    if ($Action -eq 'CarryForward') {
        if ([string]::IsNullOrWhiteSpace($SourceStagePath) -or [string]::IsNullOrWhiteSpace($SourceAttemptHistoryPath)) {
            throw 'CarryForward requires SourceStagePath and SourceAttemptHistoryPath'
        }
        if (-not [string]::IsNullOrWhiteSpace($AttemptId) -or -not [string]::IsNullOrWhiteSpace($ResultsPath) -or
            -not [string]::IsNullOrWhiteSpace($SourceEvidencePath) -or -not [string]::IsNullOrWhiteSpace($RetryJustification) -or
            -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary) -or -not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorId) -or -not [string]::IsNullOrWhiteSpace($EvaluatorModel) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorRuntime) -or $BaselineImport -or $null -ne $DurationMilliseconds -or
            $null -ne $InputTokens -or $null -ne $CachedInputTokens -or $null -ne $OutputTokens) {
            throw 'CarryForward accepts only its phase, source stage, source history, routing dependency, project root, and current history path'
        }
        if ([IO.Path]::GetFullPath($SourceAttemptHistoryPath).Equals([IO.Path]::GetFullPath($AttemptHistoryPath), [StringComparison]::OrdinalIgnoreCase)) {
            throw 'CarryForward source history must be an immutable copy distinct from the current ledger path'
        }
        $sourceHistory = Read-AgentBaseRoutingAttemptHistory -Path $SourceAttemptHistoryPath
        if ($null -eq $sourceHistory -or [int]$sourceHistory.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema) -or
            [string]$sourceHistory.active_cycle_id -eq $cycleId -or
            @($sourceHistory.attempts | Where-Object { [string]$_.outcome -eq 'started' }).Count -gt 0) {
            throw 'CarryForward requires one closed prior-generation source ledger'
        }
        $sourceStage = Get-Content -LiteralPath $SourceStagePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        Invoke-AgentBasePhaseValidation -Results $sourceStage
        $sourceSemanticHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $Phase -Results $sourceStage
        $sourceFileHash = (Get-FileHash -LiteralPath $SourceStagePath -Algorithm SHA256).Hash
        $sourceReceipts = @($sourceHistory.attempts | Where-Object {
            [string]$_.phase -eq $Phase -and
            [string]$_.outcome -eq 'passed' -and
            [string]$_.stage_result_sha256 -eq $sourceSemanticHash -and
            [string]$_.evaluator_id -eq [string]$sourceStage.evaluator.id -and
            [string]$_.candidate_bundle_sha256 -eq [string]$sourceStage.candidate_bundle_sha256 -and
            [string]$_.evaluation_input_sha256 -eq [string]$sourceStage.evaluation_input_sha256 -and
            [string]$_.evaluation_capsule_sha256 -eq [string]$sourceStage.evaluation_capsule_sha256 -and
            (([string]$_.origin -eq 'evidence_reuse') -or [string]$_.result_sha256 -eq $sourceFileHash)
        })
        if ($sourceReceipts.Count -ne 1) {
            throw "$Phase carry-forward source does not match exactly one passed prior receipt"
        }
        $history = New-AgentBaseCurrentHistory -ExistingHistory $historyBeforeRollover
        $sourceLedgerHash = (Get-FileHash -LiteralPath $SourceAttemptHistoryPath -Algorithm SHA256).Hash
        if ([string]$history.active_cycle_id -ne $cycleId -or [string]$history.previous_ledger_sha256 -ne $sourceLedgerHash) {
            throw 'CarryForward current ledger is not linked to the supplied prior ledger'
        }
        $attempts = @($history.attempts)
        if (@($attempts | Where-Object { [string]$_.attempt_key -eq $attemptKey }).Count -gt 0) {
            throw "$Phase already has a current-generation receipt for the same visible input"
        }
        if ($attempts.Count -ge (Get-AgentBaseRoutingAttemptLedgerLimit)) {
            throw "The active routing generation has reached its bounded receipt limit of $(Get-AgentBaseRoutingAttemptLedgerLimit)"
        }
        if (@($attempts | Where-Object { [string]$_.evaluator_id -eq [string]$sourceStage.evaluator.id }).Count -gt 0) {
            throw "The active generation already cites evaluator id $($sourceStage.evaluator.id)"
        }
        $now = [DateTimeOffset]::UtcNow.ToString('o')
        $previous = @($attempts | Where-Object { [string]$_.phase -eq $Phase }) | Select-Object -Last 1
        $draft = [pscustomobject]@{
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            origin = 'staged_carry_forward'
            evaluator_model = [string]$sourceStage.evaluator.model
            evaluator_runtime = [string]$sourceStage.evaluator.runtime
        }
        $receipt = [pscustomobject][ordered]@{
            attempt_id = [guid]::NewGuid().ToString('N')
            cycle_id = $cycleId.ToUpperInvariant()
            started_at_utc = $now
            completed_at_utc = $now
            phase = $Phase
            origin = 'staged_carry_forward'
            attempt_key = $attemptKey
            result_sha256 = $sourceFileHash
            stage_result_sha256 = $sourceSemanticHash
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            evaluator_id = [string]$sourceStage.evaluator.id
            evaluator_model = [string]$sourceStage.evaluator.model
            evaluator_runtime = [string]$sourceStage.evaluator.runtime
            evaluated_at_utc = [string]$sourceStage.evaluator.evaluated_at_utc
            outcome = 'passed'
            failure_class = $null
            failure_summary = $null
            retry_justification = $null
            previous_attempt_id = if ($null -eq $previous) { $null } else { [string]$previous.attempt_id }
            changed_since_previous = @(Get-AgentBaseRoutingAttemptChanges -Previous $previous -Current $draft)
            source_evidence_sha256 = $null
            source_receipt_id = [string]$sourceReceipts[0].attempt_id
            source_cycle_id = [string]$sourceHistory.active_cycle_id
            duration_ms = 0
            input_tokens = 0
            cached_input_tokens = 0
            output_tokens = 0
        }
        $history.attempts = @($attempts) + $receipt
        Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history
        [pscustomobject]@{
            attempt_id = [string]$receipt.attempt_id
            cycle_id = [string]$receipt.cycle_id
            phase = $Phase
            origin = 'staged_carry_forward'
            outcome = 'passed'
        }
        return
    }

    if ($Action -eq 'Reuse') {
        if ([string]::IsNullOrWhiteSpace($SourceEvidencePath)) {
            throw 'Reuse requires SourceEvidencePath'
        }
        if (-not [string]::IsNullOrWhiteSpace($AttemptId) -or -not [string]::IsNullOrWhiteSpace($ResultsPath) -or
            -not [string]::IsNullOrWhiteSpace($SourceStagePath) -or -not [string]::IsNullOrWhiteSpace($SourceAttemptHistoryPath) -or
            -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary) -or -not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary) -or
            -not [string]::IsNullOrWhiteSpace($RetryJustification) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorId) -or -not [string]::IsNullOrWhiteSpace($EvaluatorModel) -or
            -not [string]::IsNullOrWhiteSpace($EvaluatorRuntime) -or $BaselineImport) {
            throw 'Reuse accepts only its phase, source evidence, routing dependency, project root, and history path'
        }
        $sourceEvidence = Get-Content -LiteralPath $SourceEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        $sourceStage = Get-AgentBaseSourceStage -Evidence $sourceEvidence
        if ($null -eq $sourceStage -or [string]$sourceStage.receipt_id -notmatch '^[0-9a-f]{32}$') {
            throw "$Phase source evidence does not carry a valid prior receipt id"
        }
        Invoke-AgentBasePhaseValidation -Results $sourceStage
        $history = New-AgentBaseCurrentHistory -ExistingHistory $historyBeforeRollover
        $attempts = @($history.attempts)
        if (@($attempts | Where-Object { [string]$_.attempt_key -eq $attemptKey }).Count -gt 0) {
            throw "$Phase already has a receipt for the same visible input in the active generation"
        }
        if ($attempts.Count -ge (Get-AgentBaseRoutingAttemptLedgerLimit)) {
            throw "The active routing generation has reached its bounded receipt limit of $(Get-AgentBaseRoutingAttemptLedgerLimit)"
        }
        if (@($attempts | Where-Object { [string]$_.evaluator_id -eq [string]$sourceStage.evaluator.id }).Count -gt 0) {
            throw "The active generation already cites evaluator id $($sourceStage.evaluator.id)"
        }
        $now = [DateTimeOffset]::UtcNow.ToString('o')
        $previous = @($attempts | Where-Object { [string]$_.phase -eq $Phase }) | Select-Object -Last 1
        $draft = [pscustomobject]@{
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            origin = 'evidence_reuse'
            evaluator_model = [string]$sourceStage.evaluator.model
            evaluator_runtime = [string]$sourceStage.evaluator.runtime
        }
        $receipt = [pscustomobject][ordered]@{
            attempt_id = [guid]::NewGuid().ToString('N')
            cycle_id = $cycleId.ToUpperInvariant()
            started_at_utc = $now
            completed_at_utc = $now
            phase = $Phase
            origin = 'evidence_reuse'
            attempt_key = $attemptKey
            result_sha256 = $null
            stage_result_sha256 = Get-AgentBaseStageSemanticResultFingerprint -Phase $Phase -Results $sourceStage
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            evaluator_id = [string]$sourceStage.evaluator.id
            evaluator_model = [string]$sourceStage.evaluator.model
            evaluator_runtime = [string]$sourceStage.evaluator.runtime
            evaluated_at_utc = [string]$sourceStage.evaluator.evaluated_at_utc
            outcome = 'passed'
            failure_class = $null
            failure_summary = $null
            retry_justification = $null
            previous_attempt_id = if ($null -eq $previous) { $null } else { [string]$previous.attempt_id }
            changed_since_previous = @(Get-AgentBaseRoutingAttemptChanges -Previous $previous -Current $draft)
            source_evidence_sha256 = (Get-FileHash -LiteralPath $SourceEvidencePath -Algorithm SHA256).Hash
            source_receipt_id = [string]$sourceStage.receipt_id
            source_cycle_id = $null
            duration_ms = 0
            input_tokens = 0
            cached_input_tokens = 0
            output_tokens = 0
        }
        $history.attempts = @($attempts) + $receipt
        Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history
        [pscustomobject]@{
            attempt_id = [string]$receipt.attempt_id
            cycle_id = [string]$receipt.cycle_id
            phase = $Phase
            origin = 'evidence_reuse'
            outcome = 'passed'
        }
        return
    }

    if (-not [string]::IsNullOrWhiteSpace($SourceEvidencePath)) {
        throw "$Action does not accept SourceEvidencePath"
    }
    if (-not [string]::IsNullOrWhiteSpace($SourceStagePath) -or -not [string]::IsNullOrWhiteSpace($SourceAttemptHistoryPath)) {
        throw "$Action does not accept carry-forward source paths"
    }

    if ($Action -eq 'Begin') {
        foreach ($identity in @($EvaluatorId, $EvaluatorModel, $EvaluatorRuntime)) {
            if ([string]::IsNullOrWhiteSpace($identity) -or $identity.Length -gt 300) {
                throw 'Begin requires bounded EvaluatorId, EvaluatorModel, and EvaluatorRuntime values'
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($AttemptId) -or -not [string]::IsNullOrWhiteSpace($ResultsPath) -or
            -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary) -or -not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary) -or
            $null -ne $DurationMilliseconds -or
            $null -ne $InputTokens -or $null -ne $CachedInputTokens -or $null -ne $OutputTokens) {
            throw 'Begin does not accept completion fields'
        }
        $history = New-AgentBaseCurrentHistory -ExistingHistory $historyBeforeRollover
        $attempts = @($history.attempts)
        if ($BaselineImport -and @($attempts | Where-Object { [string]$_.phase -eq $Phase }).Count -gt 0) {
            throw "BaselineImport is valid only for the first receipt of a phase"
        }
        if (@($attempts | Where-Object { [string]$_.evaluator_id -eq $EvaluatorId }).Count -gt 0) {
            throw "Evaluator id has already been used in the active generation: $EvaluatorId"
        }
        $sameInputAttempts = @($attempts | Where-Object { [string]$_.attempt_key -eq $attemptKey })
        if (-not $BaselineImport -and $sameInputAttempts.Count -gt 0 -and [string]::IsNullOrWhiteSpace($RetryJustification)) {
            throw "The $Phase phase already has a receipt for unchanged visible input; provide RetryJustification for one bounded re-evaluation"
        }
        $samplingAttempts = @($sameInputAttempts | Where-Object { [string]$_.failure_class -ne 'orchestration_failed' })
        $orchestrationFailures = @($sameInputAttempts | Where-Object { [string]$_.failure_class -eq 'orchestration_failed' })
        if ($samplingAttempts.Count -ge (Get-AgentBaseRoutingAttemptLimit)) {
            throw "The $Phase phase reached the limit of $(Get-AgentBaseRoutingAttemptLimit) evaluator attempts for unchanged visible input"
        }
        if ($orchestrationFailures.Count -ge (Get-AgentBaseRoutingOrchestrationFailureLimit)) {
            throw "The $Phase phase reached the limit of $(Get-AgentBaseRoutingOrchestrationFailureLimit) pre-evaluator orchestration failures for unchanged visible input"
        }
        if ($attempts.Count -ge (Get-AgentBaseRoutingAttemptLedgerLimit)) {
            throw "The active routing generation has reached its bounded receipt limit of $(Get-AgentBaseRoutingAttemptLedgerLimit)"
        }
        $previous = @($attempts | Where-Object { [string]$_.phase -eq $Phase }) | Select-Object -Last 1
        $origin = if ($BaselineImport) { 'baseline_import' } else { 'formal' }
        $draft = [pscustomobject]@{
            candidate_bundle_sha256 = [string]$expectedCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$expectedCapsule.evaluation_input_sha256
            evaluation_capsule_sha256 = [string]$expectedCapsule.sha256
            origin = $origin
            evaluator_model = $EvaluatorModel
            evaluator_runtime = $EvaluatorRuntime
        }
        $receipt = [pscustomobject][ordered]@{
            attempt_id = [guid]::NewGuid().ToString('N')
            cycle_id = $cycleId.ToUpperInvariant()
            started_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            completed_at_utc = $null
            phase = $Phase
            origin = $origin
            attempt_key = $attemptKey
            result_sha256 = $null
            stage_result_sha256 = $null
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
            changed_since_previous = @(Get-AgentBaseRoutingAttemptChanges -Previous $previous -Current $draft)
            source_evidence_sha256 = $null
            source_receipt_id = $null
            source_cycle_id = $null
            duration_ms = $null
            input_tokens = $null
            cached_input_tokens = $null
            output_tokens = $null
        }
        $history.attempts = @($attempts) + $receipt
        Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history
        [pscustomobject]@{
            attempt_id = [string]$receipt.attempt_id
            cycle_id = [string]$receipt.cycle_id
            phase = $Phase
            origin = $origin
            outcome = 'started'
        }
        return
    }

    if ($BaselineImport -or -not [string]::IsNullOrWhiteSpace($RetryJustification) -or
        -not [string]::IsNullOrWhiteSpace($EvaluatorId) -or -not [string]::IsNullOrWhiteSpace($EvaluatorModel) -or
        -not [string]::IsNullOrWhiteSpace($EvaluatorRuntime)) {
        throw 'Finish does not accept Begin-only fields'
    }
    $history = $historyBeforeRollover
    if ($null -eq $history -or [int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
        throw 'Finish requires an existing current-schema attempt ledger'
    }
    if ([string]$history.active_cycle_id -ne $cycleId) {
        throw "Finish input belongs to generation $cycleId, not active generation $($history.active_cycle_id)"
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
        throw "Attempt $AttemptId is already complete with outcome $($receipt.outcome)"
    }
    if ([string]$receipt.attempt_key -ne $attemptKey) {
        throw "Attempt $AttemptId no longer matches the current visible candidate, input, or capsule"
    }
    $hasResult = -not [string]::IsNullOrWhiteSpace($ResultsPath)
    $hasExecutionFailure = -not [string]::IsNullOrWhiteSpace($ExecutionFailureSummary)
    $hasOrchestrationFailure = -not [string]::IsNullOrWhiteSpace($OrchestrationFailureSummary)
    $completionModeCount = @(@($hasResult, $hasExecutionFailure, $hasOrchestrationFailure) | Where-Object { $_ }).Count
    if ($completionModeCount -ne 1) {
        throw 'Finish requires exactly one of ResultsPath, ExecutionFailureSummary, or OrchestrationFailureSummary'
    }

    $validationFailure = $null
    $failureClass = $null
    $resultFileHash = $null
    $stageResultHash = $null
    $evaluatedAtUtc = $null
    if ($hasOrchestrationFailure) {
        $validationFailure = $OrchestrationFailureSummary.Trim()
        $failureClass = 'orchestration_failed'
    }
    elseif ($hasExecutionFailure) {
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
                Invoke-AgentBasePhaseValidation -Results $results
                $stageResultHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $Phase -Results $results
            }
            catch {
                $validationFailure = $_.Exception.Message
                $failureClass = if ($validationFailure -match 'evaluation failed with \d+ violation') { 'oracle_violation' } else { 'identity_or_schema' }
            }
        }
    }

    $receipt.completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $receipt.result_sha256 = $resultFileHash
    $receipt.stage_result_sha256 = $stageResultHash
    $receipt.evaluated_at_utc = $evaluatedAtUtc
    $receipt.duration_ms = if ($null -eq $DurationMilliseconds) { $null } else { [long]$DurationMilliseconds }
    $receipt.input_tokens = if ($null -eq $InputTokens) { $null } else { [long]$InputTokens }
    $receipt.cached_input_tokens = if ($null -eq $CachedInputTokens) { $null } else { [long]$CachedInputTokens }
    $receipt.output_tokens = if ($null -eq $OutputTokens) { $null } else { [long]$OutputTokens }
    $receipt.outcome = if ($null -eq $validationFailure) { 'passed' } else { 'failed' }
    $receipt.failure_class = $failureClass
    $receipt.failure_summary = Get-AgentBaseRoutingAttemptSummary -Message $validationFailure
    Write-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath -History $history

    if ($null -ne $validationFailure) {
        throw "Recorded failed $Phase attempt $AttemptId ($failureClass): $validationFailure"
    }
    [pscustomobject]@{
        attempt_id = $AttemptId
        cycle_id = [string]$receipt.cycle_id
        phase = $Phase
        origin = [string]$receipt.origin
        outcome = 'passed'
    }
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}
