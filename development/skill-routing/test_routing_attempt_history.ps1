$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$currentEvidencePath = Join-Path $PSScriptRoot 'evidence\current.json'
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$testRoot = Join-Path $tempBase ('AgentBase-routing-attempt-test-' + [guid]::NewGuid().ToString('N'))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$recorder = Join-Path $PSScriptRoot 'record_routing_attempt.ps1'

function Write-TestJson {
    param(
        [string]$Path,
        [object]$Value
    )

    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
}

function New-StageFiles {
    param(
        [string]$Prefix
    )

    $current = Get-Content -LiteralPath $currentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $routing = Get-Content -LiteralPath $currentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $routing.PSObject.Properties.Remove('policy_evaluation')
    $routing.PSObject.Properties.Remove('reference_evaluation')
    $paths = [pscustomobject]@{
        routing = Join-Path $testRoot "$Prefix-routing.json"
        policy = Join-Path $testRoot "$Prefix-policy.json"
        references = Join-Path $testRoot "$Prefix-references.json"
    }
    Write-TestJson -Path $paths.routing -Value $routing
    Write-TestJson -Path $paths.policy -Value $current.policy_evaluation
    Write-TestJson -Path $paths.references -Value $current.reference_evaluation
    return [pscustomobject]@{ current = $current; routing_value = $routing; paths = $paths }
}

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $stages = New-StageFiles -Prefix 'current'

    $baselineHistoryPath = Join-Path $testRoot 'baseline-attempts.json'
    $baseline = & (Join-Path $PSScriptRoot 'initialize_routing_attempt_history.ps1') -ProjectRoot $projectRoot -CurrentEvidencePath $currentEvidencePath -AttemptHistoryPath $baselineHistoryPath
    if ([int]$baseline.imported_receipt_count -ne 3) {
        throw 'Baseline import did not register all three current evidence stages'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $baselineHistoryPath -CurrentEvidencePath $currentEvidencePath | Out-Null
    $baselineHistory = Get-Content -LiteralPath $baselineHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if ([int]$baselineHistory.schema_version -ne 2 -or @($baselineHistory.attempts).Count -ne 3) {
        throw 'Baseline import did not create the bounded two-phase ledger schema'
    }

    $routingAttemptId = [string](@($baselineHistory.attempts | Where-Object { [string]$_.phase -eq 'Routing' })[0].attempt_id)
    $policyAttemptId = [string](@($baselineHistory.attempts | Where-Object { [string]$_.phase -eq 'Policy' })[0].attempt_id)
    $referenceAttemptId = [string](@($baselineHistory.attempts | Where-Object { [string]$_.phase -eq 'References' })[0].attempt_id)
    $mergedEvidencePath = Join-Path $testRoot 'merged-current.json'
    & (Join-Path $PSScriptRoot 'merge_routing_evidence.ps1') -ProjectRoot $projectRoot -RoutingResultsPath $stages.paths.routing -PolicyResultsPath $stages.paths.policy -ReferenceResultsPath $stages.paths.references -RoutingAttemptId $routingAttemptId -PolicyAttemptId $policyAttemptId -ReferenceAttemptId $referenceAttemptId -OutputPath $mergedEvidencePath -AttemptHistoryPath $baselineHistoryPath | Out-Null
    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $projectRoot -ResultsPath $mergedEvidencePath | Out-Null

    $historyPath = Join-Path $testRoot 'attempts.json'
    $executionBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $historyPath -EvaluatorId 'routing-attempt-test-execution-failure' -EvaluatorModel 'gpt-5.6-sol' -EvaluatorRuntime 'test/windows/read-only'
    $unfinishedRejected = $false
    try {
        & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath | Out-Null
    }
    catch {
        $unfinishedRejected = $_.Exception.Message.Contains('not explicitly finished')
    }
    if (-not $unfinishedRejected) {
        throw 'An unfinished evaluator run did not block the formal history gate'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath -AllowStarted | Out-Null

    $executionFailureRecorded = $false
    try {
        & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $executionBegin.attempt_id -AttemptHistoryPath $historyPath -ExecutionFailureSummary 'Detached evaluator exited before producing a result file.' | Out-Null
    }
    catch {
        $executionFailureRecorded = $_.Exception.Message.Contains('(execution_failed)')
    }
    if (-not $executionFailureRecorded) {
        throw 'Evaluator execution failure was not recorded by Finish'
    }
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($history.attempts).Count -ne 1 -or [string]$history.attempts[0].failure_class -ne 'execution_failed' -or -not [string]::IsNullOrWhiteSpace([string]$history.attempts[0].result_sha256)) {
        throw 'Execution-failure receipt is incomplete'
    }

    $unjustifiedRejected = $false
    try {
        & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $historyPath -EvaluatorId 'routing-attempt-test-unjustified' -EvaluatorModel 'gpt-5.6-sol' -EvaluatorRuntime 'test/windows/read-only' | Out-Null
    }
    catch {
        $unjustifiedRejected = $_.Exception.Message.Contains('provide RetryJustification')
    }
    if (-not $unjustifiedRejected) {
        throw 'Unchanged routing input accepted an unexplained evaluator rerun'
    }

    $successResult = $stages.routing_value
    $successResult.evaluator.id = 'routing-attempt-test-success'
    $successResult.evaluator.model = 'gpt-5.6-sol'
    $successResult.evaluator.runtime = 'test/windows/read-only'
    $successResult.evaluator.evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $successResultPath = Join-Path $testRoot 'successful-routing.json'
    Write-TestJson -Path $successResultPath -Value $successResult
    $successBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $historyPath -EvaluatorId $successResult.evaluator.id -EvaluatorModel $successResult.evaluator.model -EvaluatorRuntime $successResult.evaluator.runtime -RetryJustification 'One bounded retry after an evaluator execution failure.'
    $successFinish = & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $successBegin.attempt_id -ResultsPath $successResultPath -AttemptHistoryPath $historyPath
    if ([string]$successFinish.outcome -ne 'passed') {
        throw 'Justified evaluator retry did not finish as passed'
    }

    $limitRejected = $false
    try {
        & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $historyPath -EvaluatorId 'routing-attempt-test-third' -EvaluatorModel 'gpt-5.6-sol' -EvaluatorRuntime 'test/windows/read-only' -RetryJustification 'A second retry must still be rejected.' | Out-Null
    }
    catch {
        $limitRejected = $_.Exception.Message.Contains('has reached the limit')
    }
    if (-not $limitRejected) {
        throw 'Unchanged routing input exceeded its bounded formal-attempt limit'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath | Out-Null

    $rolloverHistoryPath = Join-Path $testRoot 'rollover-attempts.json'
    Copy-Item -LiteralPath $historyPath -Destination $rolloverHistoryPath
    $oldLedger = Get-Content -LiteralPath $rolloverHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    $oldLedger.active_cycle_id = 'A' * 64
    foreach ($attempt in @($oldLedger.attempts)) {
        $attempt.cycle_id = 'A' * 64
    }
    Write-TestJson -Path $rolloverHistoryPath -Value $oldLedger
    $rollover = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $rolloverHistoryPath -EvaluatorId 'routing-attempt-test-rollover' -EvaluatorModel 'gpt-5.6-sol' -EvaluatorRuntime 'test/windows/read-only'
    $rolledLedger = Get-Content -LiteralPath $rolloverHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($rolledLedger.attempts).Count -ne 1 -or [int]$rolledLedger.previous_attempt_count -ne 2 -or [string]$rolledLedger.previous_ledger_sha256 -notmatch '^[0-9A-F]{64}$' -or [string]$rolledLedger.attempts[0].attempt_id -ne [string]$rollover.attempt_id) {
        throw 'Changed evaluation cycle did not roll the active ledger with a bounded hash link'
    }

    Write-Output 'Routing attempt history tests passed: baseline import, explicit begin/finish, execution failures, unfinished-run blocking, bounded retries, merge binding, and cycle rollover are enforced.'
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $resolvedTestRoot).StartsWith('AgentBase-routing-attempt-test-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolvedTestRoot"
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
