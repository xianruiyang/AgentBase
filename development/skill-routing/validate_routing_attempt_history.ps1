[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$AttemptHistoryPath,
    [string]$CurrentEvidencePath,
    [switch]$AllowStarted
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'routing_evaluation_common.ps1')
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
    throw 'Routing attempt history has an invalid active generation id'
}
if ([int]$history.max_attempts_per_unchanged_input -ne (Get-AgentBaseRoutingAttemptLimit) -or
    [int]$history.max_orchestration_failures_per_unchanged_input -ne (Get-AgentBaseRoutingOrchestrationFailureLimit) -or
    [int]$history.max_receipts_per_cycle -ne (Get-AgentBaseRoutingAttemptLedgerLimit)) {
    throw 'Routing attempt history uses different bounded receipt limits'
}
if (@($history.attempts).Count -gt (Get-AgentBaseRoutingAttemptLedgerLimit)) {
    throw 'Routing attempt history exceeds its active-generation receipt limit'
}
foreach ($hashField in @('previous_ledger_sha256', 'previous_cycle_id')) {
    if (-not [string]::IsNullOrWhiteSpace([string]$history.$hashField) -and [string]$history.$hashField -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "Routing attempt history has an invalid $hashField"
    }
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
$attemptsById = @{}
$attemptsByKey = @{}
foreach ($attempt in @($history.attempts)) {
    $attemptId = [string]$attempt.attempt_id
    if ($attemptId -notmatch '^[0-9a-f]{32}$' -or $attemptIds.ContainsKey($attemptId)) {
        throw "Routing attempt history contains an invalid or duplicate receipt id: $attemptId"
    }
    $attemptIds[$attemptId] = $true
    $attemptsById[$attemptId] = $attempt
    if ([string]$attempt.cycle_id -ne [string]$history.active_cycle_id) {
        throw "Routing receipt $attemptId is outside the active generation"
    }
    if ([string]$attempt.phase -notin @('Routing', 'Policy', 'References')) {
        throw "Routing receipt has an invalid phase: $($attempt.phase)"
    }
    if ([string]$attempt.origin -notin @('formal', 'baseline_import', 'evidence_reuse', 'staged_carry_forward', 'oracle_revalidation')) {
        throw "Routing receipt has an invalid origin: $($attempt.origin)"
    }
    if ([string]$attempt.outcome -notin @('started', 'passed', 'failed')) {
        throw "Routing receipt has an invalid outcome: $($attempt.outcome)"
    }
    foreach ($hashField in @('candidate_bundle_sha256', 'evaluation_input_sha256', 'evaluation_capsule_sha256')) {
        if ([string]$attempt.$hashField -notmatch '^[0-9A-Fa-f]{64}$') {
            throw "Routing receipt $attemptId has an invalid $hashField"
        }
    }
    if ([string]$attempt.attempt_key -ne (Get-AgentBaseRoutingAttemptKey -Phase $attempt.phase -CandidateBundleSha256 $attempt.candidate_bundle_sha256 -EvaluationInputSha256 $attempt.evaluation_input_sha256 -EvaluationCapsuleSha256 $attempt.evaluation_capsule_sha256)) {
        throw "Routing receipt $attemptId has a mismatched attempt key"
    }
    $started = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$attempt.started_at_utc, [ref]$started) -or $started.Offset -ne [TimeSpan]::Zero) {
        throw "Routing receipt $attemptId has a non-UTC start timestamp"
    }
    if (([string]$attempt.failure_summary).Length -gt 500 -or ([string]$attempt.retry_justification).Length -gt 300) {
        throw "Routing receipt $attemptId exceeds its bounded text contract"
    }
    foreach ($identityField in @('evaluator_id', 'evaluator_model', 'evaluator_runtime')) {
        if ([string]::IsNullOrWhiteSpace([string]$attempt.$identityField) -or ([string]$attempt.$identityField).Length -gt 300) {
            throw "Routing receipt $attemptId has an invalid $identityField"
        }
    }
    $priorEvaluatorReceipt = if ($evaluatorIds.ContainsKey([string]$attempt.evaluator_id)) {
        $evaluatorIds[[string]$attempt.evaluator_id]
    }
    else {
        $null
    }
    $isLinkedOracleRevalidation = $null -ne $priorEvaluatorReceipt -and
        [string]$attempt.origin -eq 'oracle_revalidation' -and
        [string]$attempt.source_receipt_id -eq [string]$priorEvaluatorReceipt.attempt_id -and
        [string]$priorEvaluatorReceipt.outcome -eq 'failed' -and
        [string]$priorEvaluatorReceipt.failure_class -eq 'oracle_violation'
    if ($null -ne $priorEvaluatorReceipt -and -not $isLinkedOracleRevalidation) {
        throw "Routing attempt history reuses evaluator id: $($attempt.evaluator_id)"
    }
    if ($null -eq $priorEvaluatorReceipt) {
        $evaluatorIds[[string]$attempt.evaluator_id] = $attempt
    }
    foreach ($metricField in @('duration_ms', 'input_tokens', 'cached_input_tokens', 'output_tokens')) {
        if ($null -ne $attempt.$metricField -and [long]$attempt.$metricField -lt 0) {
            throw "Routing receipt $attemptId has a negative $metricField"
        }
    }

    if ([string]$attempt.outcome -eq 'started') {
        if (-not $AllowStarted) {
            throw "Routing attempt $attemptId was started but not explicitly finished"
        }
        foreach ($completionField in @('completed_at_utc', 'result_sha256', 'stage_result_sha256', 'evaluated_at_utc', 'failure_class', 'failure_summary', 'source_evidence_sha256', 'source_receipt_id', 'source_cycle_id', 'duration_ms', 'input_tokens', 'cached_input_tokens', 'output_tokens')) {
            if ($null -ne $attempt.$completionField -and -not [string]::IsNullOrWhiteSpace([string]$attempt.$completionField)) {
                throw "Started routing attempt $attemptId carries completion field $completionField"
            }
        }
    }
    else {
        $completed = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$attempt.completed_at_utc, [ref]$completed) -or $completed.Offset -ne [TimeSpan]::Zero -or $completed -lt $started) {
            throw "Routing receipt $attemptId has an invalid completion timestamp"
        }
        if ([string]$attempt.outcome -eq 'passed') {
            if ([string]$attempt.stage_result_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                [string]::IsNullOrWhiteSpace([string]$attempt.evaluated_at_utc) -or
                -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_class) -or
                -not [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary)) {
                throw "Passed routing receipt $attemptId has invalid result or failure fields"
            }
            if ([string]$attempt.origin -eq 'evidence_reuse') {
                if (-not [string]::IsNullOrWhiteSpace([string]$attempt.result_sha256) -or
                    [string]$attempt.source_evidence_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                    [string]$attempt.source_receipt_id -notmatch '^[0-9a-f]{32}$' -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_cycle_id) -or
                    [long]$attempt.duration_ms -ne 0 -or [long]$attempt.input_tokens -ne 0 -or
                    [long]$attempt.cached_input_tokens -ne 0 -or [long]$attempt.output_tokens -ne 0) {
                    throw "Reuse receipt $attemptId lacks an exact zero-cost source link"
                }
            }
            elseif ([string]$attempt.origin -eq 'staged_carry_forward') {
                if ([string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_evidence_sha256) -or
                    [string]$attempt.source_receipt_id -notmatch '^[0-9a-f]{32}$' -or
                    [string]$attempt.source_cycle_id -notmatch '^[0-9A-Fa-f]{64}$' -or
                    [string]$attempt.source_cycle_id -ne [string]$history.previous_cycle_id -or
                    [long]$attempt.duration_ms -ne 0 -or [long]$attempt.input_tokens -ne 0 -or
                    [long]$attempt.cached_input_tokens -ne 0 -or [long]$attempt.output_tokens -ne 0) {
                    throw "Carry-forward receipt $attemptId lacks an exact prior-generation stage link"
                }
            }
            elseif ([string]$attempt.origin -eq 'oracle_revalidation') {
                $sameGenerationSource = [string]$attempt.source_cycle_id -eq [string]$history.active_cycle_id
                $priorGenerationSource = -not [string]::IsNullOrWhiteSpace([string]$history.previous_cycle_id) -and
                    [string]$attempt.source_cycle_id -eq [string]$history.previous_cycle_id
                $sourceReceipt = if ($sameGenerationSource -and $attemptsById.ContainsKey([string]$attempt.source_receipt_id)) {
                    $attemptsById[[string]$attempt.source_receipt_id]
                }
                else {
                    $null
                }
                $commonLinkInvalid = [string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_evidence_sha256) -or
                    [string]$attempt.source_receipt_id -notmatch '^[0-9a-f]{32}$' -or
                    [long]$attempt.duration_ms -ne 0 -or [long]$attempt.input_tokens -ne 0 -or
                    [long]$attempt.cached_input_tokens -ne 0 -or [long]$attempt.output_tokens -ne 0 -or
                    @($attempt.changed_since_previous) -notcontains 'oracle_contract'
                $sameGenerationLinkInvalid = $sameGenerationSource -and (
                    [string]$attempt.previous_attempt_id -ne [string]$attempt.source_receipt_id -or
                    $null -eq $sourceReceipt -or [string]$sourceReceipt.outcome -ne 'failed' -or
                    [string]$sourceReceipt.failure_class -ne 'oracle_violation' -or
                    [string]$sourceReceipt.attempt_key -ne [string]$attempt.attempt_key -or
                    [string]$sourceReceipt.result_sha256 -ne [string]$attempt.result_sha256 -or
                    [string]$sourceReceipt.evaluator_id -ne [string]$attempt.evaluator_id)
                $priorGenerationLinkInvalid = $priorGenerationSource -and (
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.previous_attempt_id) -or
                    [string]$history.previous_ledger_sha256 -notmatch '^[0-9A-Fa-f]{64}$')
                if ($commonLinkInvalid -or (-not $sameGenerationSource -and -not $priorGenerationSource) -or
                    $sameGenerationLinkInvalid -or $priorGenerationLinkInvalid) {
                    throw "Oracle-revalidation receipt $attemptId lacks an exact zero-cost failed-result link"
                }
            }
            else {
                if ([string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_evidence_sha256) -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_receipt_id) -or
                    -not [string]::IsNullOrWhiteSpace([string]$attempt.source_cycle_id)) {
                    throw "Formal or baseline receipt $attemptId has invalid result provenance"
                }
            }
        }
        else {
            if ([string]$attempt.failure_class -notin @('oracle_violation', 'identity_or_schema', 'execution_failed', 'orchestration_failed') -or
                [string]::IsNullOrWhiteSpace([string]$attempt.failure_summary) -or
                -not [string]::IsNullOrWhiteSpace([string]$attempt.stage_result_sha256)) {
                throw "Failed routing receipt $attemptId lacks a bounded failure classification"
            }
            if ([string]$attempt.failure_class -in @('execution_failed', 'orchestration_failed') -and -not [string]::IsNullOrWhiteSpace([string]$attempt.result_sha256)) {
                throw "Pre-result routing receipt $attemptId unexpectedly carries a result hash"
            }
            if ([string]$attempt.failure_class -notin @('execution_failed', 'orchestration_failed') -and [string]$attempt.result_sha256 -notmatch '^[0-9A-Fa-f]{64}$') {
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
    $sameInputReceipts = [object[]]$entry.Value
    $oracleRevalidations = @($sameInputReceipts | Where-Object { [string]$_.origin -eq 'oracle_revalidation' })
    if ($oracleRevalidations.Count -gt 1) {
        throw "Routing attempt history contains more than one oracle revalidation for $($entry.Key)"
    }
    $samplingReceipts = @($sameInputReceipts | Where-Object {
        [string]$_.failure_class -ne 'orchestration_failed' -and [string]$_.origin -ne 'oracle_revalidation'
    })
    $orchestrationFailures = @($sameInputReceipts | Where-Object { [string]$_.failure_class -eq 'orchestration_failed' })
    if ($samplingReceipts.Count -gt (Get-AgentBaseRoutingAttemptLimit)) {
        throw "Routing attempt history exceeds the unchanged-input evaluator-attempt limit for $($entry.Key)"
    }
    if ($orchestrationFailures.Count -gt (Get-AgentBaseRoutingOrchestrationFailureLimit)) {
        throw "Routing attempt history exceeds the unchanged-input orchestration-failure limit for $($entry.Key)"
    }
    for ($index = 1; $index -lt $sameInputReceipts.Count; $index++) {
        if ([string]$sameInputReceipts[$index].origin -eq 'formal' -and
            [string]::IsNullOrWhiteSpace([string]$sameInputReceipts[$index].retry_justification)) {
            throw "Routing attempt $($sameInputReceipts[$index].attempt_id) re-evaluates unchanged input without a justification"
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($CurrentEvidencePath)) {
    $CurrentEvidencePath = (Resolve-Path -LiteralPath $CurrentEvidencePath).Path
    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $CurrentEvidencePath | Out-Null
    $current = Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    if ([string]$history.active_cycle_id -ne [string]$current.evaluation_generation_sha256) {
        throw 'Current evidence does not belong to the active evaluation generation'
    }
    $stages = @(
        [pscustomobject]@{ phase = 'Routing'; result = $current },
        [pscustomobject]@{ phase = 'Policy'; result = $current.policy_evaluation },
        [pscustomobject]@{ phase = 'References'; result = $current.reference_evaluation }
    )
    foreach ($stage in $stages) {
        $semanticHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $stage.phase -Results $stage.result
        $matching = @($history.attempts | Where-Object {
            [string]$_.attempt_id -eq [string]$stage.result.receipt_id -and
            [string]$_.phase -eq [string]$stage.phase -and
            [string]$_.outcome -eq 'passed' -and
            [string]$_.stage_result_sha256 -eq $semanticHash -and
            [string]$_.evaluator_id -eq [string]$stage.result.evaluator.id -and
            [string]$_.candidate_bundle_sha256 -eq [string]$stage.result.candidate_bundle_sha256 -and
            [string]$_.evaluation_input_sha256 -eq [string]$stage.result.evaluation_input_sha256 -and
            [string]$_.evaluation_capsule_sha256 -eq [string]$stage.result.evaluation_capsule_sha256
        })
        if ($matching.Count -ne 1) {
            throw "Current $($stage.phase) evidence does not have exactly one matching passed receipt"
        }
    }
}

Write-Output "Routing attempt history valid: $(@($history.attempts).Count)/$(Get-AgentBaseRoutingAttemptLedgerLimit) receipts in active generation $($history.active_cycle_id); unchanged inputs allow at most $(Get-AgentBaseRoutingAttemptLimit) evaluator attempts and $(Get-AgentBaseRoutingOrchestrationFailureLimit) pre-evaluator failures."
