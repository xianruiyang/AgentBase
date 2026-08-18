$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$currentEvidencePath = Join-Path $PSScriptRoot 'evidence\current.json'
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$testRoot = Join-Path $tempBase ('AgentBase-routing-attempt-test-' + [guid]::NewGuid().ToString('N'))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-TestJson {
    param(
        [string]$Path,
        [object]$Value
    )

    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
}

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $baselineHistoryPath = Join-Path $testRoot 'baseline-attempts.json'
    $baseline = & (Join-Path $PSScriptRoot 'initialize_routing_attempt_history.ps1') -ProjectRoot $projectRoot -CurrentEvidencePath $currentEvidencePath -AttemptHistoryPath $baselineHistoryPath
    if ([int]$baseline.imported_receipt_count -ne 3) {
        throw 'Baseline import did not register all three current evidence stages'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $baselineHistoryPath -CurrentEvidencePath $currentEvidencePath | Out-Null

    $current = Get-Content -LiteralPath $currentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $routing = Get-Content -LiteralPath $currentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $routing.PSObject.Properties.Remove('policy_evaluation')
    $routing.PSObject.Properties.Remove('reference_evaluation')
    $currentRoutingPath = Join-Path $testRoot 'current-routing.json'
    $currentPolicyPath = Join-Path $testRoot 'current-policy.json'
    $currentReferencesPath = Join-Path $testRoot 'current-references.json'
    $mergedEvidencePath = Join-Path $testRoot 'merged-current.json'
    Write-TestJson -Path $currentRoutingPath -Value $routing
    Write-TestJson -Path $currentPolicyPath -Value $current.policy_evaluation
    Write-TestJson -Path $currentReferencesPath -Value $current.reference_evaluation
    & (Join-Path $PSScriptRoot 'merge_routing_evidence.ps1') -ProjectRoot $projectRoot -RoutingResultsPath $currentRoutingPath -PolicyResultsPath $currentPolicyPath -ReferenceResultsPath $currentReferencesPath -OutputPath $mergedEvidencePath -AttemptHistoryPath $baselineHistoryPath | Out-Null
    & (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $projectRoot -ResultsPath $mergedEvidencePath | Out-Null
    $baselineHistory = Get-Content -LiteralPath $baselineHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($baselineHistory.attempts).Count -ne 3) {
        throw 'Formal merge did not reuse exact baseline receipts idempotently'
    }

    $failedResult = Get-Content -LiteralPath $currentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $failedResult.PSObject.Properties.Remove('policy_evaluation')
    $failedResult.PSObject.Properties.Remove('reference_evaluation')
    $failedResult.evaluator.id = 'routing-attempt-test-failure'
    $failedResult.evaluator.evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $failedResult.cases[0].selected_skills = @('unknown-test-skill')
    $failedResultPath = Join-Path $testRoot 'failed-routing.json'
    Write-TestJson -Path $failedResultPath -Value $failedResult

    $historyPath = Join-Path $testRoot 'attempts.json'
    $failed = $false
    try {
        & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $failedResultPath -AttemptHistoryPath $historyPath | Out-Null
    }
    catch {
        $failed = $_.Exception.Message.Contains('Recorded failed Routing routing attempt')
    }
    if (-not $failed) {
        throw 'Invalid routing output was not recorded as a failed formal attempt'
    }
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($history.attempts).Count -ne 1 -or [string]$history.attempts[0].outcome -ne 'failed' -or [string]$history.attempts[0].failure_class -ne 'oracle_violation') {
        throw 'Failed routing attempt receipt is incomplete'
    }

    $routing.evaluator.id = 'routing-attempt-test-success'
    $routing.evaluator.evaluated_at_utc = [DateTimeOffset]::UtcNow.AddSeconds(1).ToString('o')
    $successResultPath = Join-Path $testRoot 'successful-routing.json'
    Write-TestJson -Path $successResultPath -Value $routing
    $unjustifiedRejected = $false
    try {
        & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $successResultPath -AttemptHistoryPath $historyPath | Out-Null
    }
    catch {
        $unjustifiedRejected = $_.Exception.Message.Contains('provide RetryJustification')
    }
    if (-not $unjustifiedRejected) {
        throw 'Unchanged routing input accepted an unexplained evaluator rerun'
    }
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($history.attempts).Count -ne 1) {
        throw 'Rejected retry mutated the formal attempt history'
    }

    $accepted = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $successResultPath -AttemptHistoryPath $historyPath -RetryJustification 'Test-only bounded nondeterministic retry after a recorded oracle failure.'
    if ([string]$accepted.outcome -ne 'passed' -or [bool]$accepted.reused) {
        throw 'Justified bounded retry was not recorded as a new passed attempt'
    }
    $reused = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $successResultPath -AttemptHistoryPath $historyPath
    if (-not [bool]$reused.reused -or [string]$reused.attempt_id -ne [string]$accepted.attempt_id) {
        throw 'Exact passed result reuse created another formal attempt'
    }

    $thirdResult = Get-Content -LiteralPath $successResultPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $thirdResult.evaluator.id = 'routing-attempt-test-third'
    $thirdResult.evaluator.evaluated_at_utc = [DateTimeOffset]::UtcNow.AddSeconds(2).ToString('o')
    $thirdResultPath = Join-Path $testRoot 'third-routing.json'
    Write-TestJson -Path $thirdResultPath -Value $thirdResult
    $limitRejected = $false
    try {
        & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $thirdResultPath -AttemptHistoryPath $historyPath -RetryJustification 'A second retry must still be rejected.' | Out-Null
    }
    catch {
        $limitRejected = $_.Exception.Message.Contains('has reached the limit')
    }
    if (-not $limitRejected) {
        throw 'Unchanged routing input exceeded its bounded formal-attempt limit'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath | Out-Null
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($history.attempts).Count -ne 2 -or [string]::IsNullOrWhiteSpace([string]$history.attempts[1].retry_justification)) {
        throw 'Bounded retry history does not preserve its explicit justification'
    }

    $identityHistoryPath = Join-Path $testRoot 'identity-attempts.json'
    $routingBaselinePath = Join-Path $testRoot 'routing-baseline.json'
    Write-TestJson -Path $routingBaselinePath -Value $routing
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Routing -ResultsPath $routingBaselinePath -AttemptHistoryPath $identityHistoryPath -BaselineImport | Out-Null
    $duplicatePolicy = $current.policy_evaluation
    $duplicatePolicy.evaluator.id = [string]$routing.evaluator.id
    $duplicatePolicy.evaluator.evaluated_at_utc = [DateTimeOffset]::UtcNow.AddSeconds(3).ToString('o')
    $duplicatePolicyPath = Join-Path $testRoot 'duplicate-policy-evaluator.json'
    Write-TestJson -Path $duplicatePolicyPath -Value $duplicatePolicy
    $identityFailureRecorded = $false
    try {
        & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -ProjectRoot $projectRoot -Phase Policy -ResultsPath $duplicatePolicyPath -RoutingResultsPath $routingBaselinePath -AttemptHistoryPath $identityHistoryPath | Out-Null
    }
    catch {
        $identityFailureRecorded = $_.Exception.Message.Contains('has already been used by a passed formal attempt')
    }
    if (-not $identityFailureRecorded) {
        throw 'Cross-stage evaluator identity reuse did not create a failed formal receipt'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $identityHistoryPath | Out-Null
    $identityHistory = Get-Content -LiteralPath $identityHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30
    if (@($identityHistory.attempts).Count -ne 2 -or [string]$identityHistory.attempts[1].failure_class -ne 'identity_or_schema') {
        throw 'Cross-stage evaluator identity failure receipt is incomplete'
    }

    Write-Output 'Routing attempt history tests passed: baseline provenance, failed receipts, unchanged-input justification, exact-result reuse, retry limits, and cross-stage evaluator identity are enforced.'
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
