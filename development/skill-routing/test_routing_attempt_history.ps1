$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'routing_evaluation_common.ps1')
. (Join-Path $PSScriptRoot 'routing_attempt_history.ps1')

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'trigger-cases.json') -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ('AgentBase-routing-attempt-test-' + [guid]::NewGuid().ToString('N'))
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$recorder = Join-Path $PSScriptRoot 'record_routing_attempt.ps1'

function Write-TestJson {
    param(
        [string]$Path,
        [object]$Value
    )

    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
}

function New-TestEvaluator {
    param(
        [string]$Id
    )

    return [pscustomobject][ordered]@{
        id = $Id
        model = 'test-model'
        runtime = 'test/windows/read-only/ephemeral'
        evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        isolation_mode = 'detached-capsule'
        repository_accessed = $false
        hidden_expectations_accessed = $false
        auth_mode = 'read-only-hardlink'
        model_catalog_sha256 = ('A' * 64)
        disabled_features = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    }
}

try {
    [IO.Directory]::CreateDirectory($testRoot) | Out-Null
    $routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
    $routingCases = @($contract.cases | ForEach-Object {
        [pscustomobject]@{
            id = [string]$_.id
            selected_skills = @(ConvertTo-AgentBaseStringArray $_.expected_skills)
            selected_peer_skills = @(ConvertTo-AgentBaseStringArray $_.expected_peer_skills)
        }
    })
    $routing = New-AgentBaseRoutingResultEnvelope -Phase Routing -Capsule $routingCapsule -Evaluator (New-TestEvaluator 'ledger-routing') -Cases $routingCases
    $policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
    $policy = New-AgentBaseRoutingResultEnvelope -Phase Policy -Capsule $policyCapsule -Evaluator (New-TestEvaluator 'ledger-policy') -Cases @($contract.cases | ForEach-Object {
        [pscustomobject]@{ id = [string]$_.id; behavior_tags = @(ConvertTo-AgentBaseStringArray $_.expected_behavior_tags) }
    })
    $referenceCapsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routing
    $contractById = @{}
    foreach ($case in @($contract.cases)) { $contractById[[string]$case.id] = $case }
    $references = New-AgentBaseRoutingResultEnvelope -Phase References -Capsule $referenceCapsule -Evaluator (New-TestEvaluator 'ledger-references') -Cases @($referenceCapsule.payload.cases | ForEach-Object {
        $capsuleCase = $_
        $contractCase = $contractById[[string]$capsuleCase.id]
        [pscustomobject]@{
            id = [string]$capsuleCase.id
            selected_references = @($capsuleCase.selected_reference_skills | ForEach-Object {
                $skillName = [string]$_
                $property = "expected_$($skillName.Replace('-', '_'))_references"
                [pscustomobject]@{ skill = $skillName; references = @(ConvertTo-AgentBaseStringArray $contractCase.$property) }
            })
        }
    })

    $routingPath = Join-Path $testRoot 'routing.json'
    $policyPath = Join-Path $testRoot 'policy.json'
    $referencePath = Join-Path $testRoot 'references.json'
    Write-TestJson -Path $routingPath -Value $routing
    Write-TestJson -Path $policyPath -Value $policy
    Write-TestJson -Path $referencePath -Value $references

    $historyPath = Join-Path $testRoot 'attempts.json'
    $routingBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $historyPath -EvaluatorId $routing.evaluator.id -EvaluatorModel $routing.evaluator.model -EvaluatorRuntime $routing.evaluator.runtime -BaselineImport
    & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $routingBegin.attempt_id -ResultsPath $routingPath -AttemptHistoryPath $historyPath | Out-Null
    $policyBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Policy -AttemptHistoryPath $historyPath -EvaluatorId $policy.evaluator.id -EvaluatorModel $policy.evaluator.model -EvaluatorRuntime $policy.evaluator.runtime -BaselineImport
    & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Policy -AttemptId $policyBegin.attempt_id -ResultsPath $policyPath -AttemptHistoryPath $historyPath | Out-Null
    $referenceBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase References -RoutingResultsPath $routingPath -AttemptHistoryPath $historyPath -EvaluatorId $references.evaluator.id -EvaluatorModel $references.evaluator.model -EvaluatorRuntime $references.evaluator.runtime -BaselineImport
    & $recorder -Action Finish -ProjectRoot $projectRoot -Phase References -AttemptId $referenceBegin.attempt_id -ResultsPath $referencePath -RoutingResultsPath $routingPath -AttemptHistoryPath $historyPath | Out-Null

    $currentPath = Join-Path $testRoot 'current.json'
    & (Join-Path $PSScriptRoot 'merge_routing_evidence.ps1') -ProjectRoot $projectRoot -RoutingResultsPath $routingPath -PolicyResultsPath $policyPath -ReferenceResultsPath $referencePath -RoutingAttemptId $routingBegin.attempt_id -PolicyAttemptId $policyBegin.attempt_id -ReferenceAttemptId $referenceBegin.attempt_id -OutputPath $currentPath -AttemptHistoryPath $historyPath | Out-Null
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath -CurrentEvidencePath $currentPath | Out-Null
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    if ([int]$history.schema_version -ne 3 -or @($history.attempts).Count -ne 3) {
        throw 'Baseline phase receipts did not create the phase-visible ledger schema'
    }

    $initializeCurrentPath = Join-Path $testRoot 'initialize-current.json'
    $initializeHistoryPath = Join-Path $testRoot 'initialize-attempts.json'
    [IO.File]::Copy($currentPath, $initializeCurrentPath)
    $initialized = & (Join-Path $PSScriptRoot 'initialize_routing_attempt_history.ps1') -ProjectRoot $projectRoot -CurrentEvidencePath $initializeCurrentPath -AttemptHistoryPath $initializeHistoryPath
    if ([int]$initialized.imported_receipt_count -ne 3) {
        throw 'History initialization did not import all three stage results'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $initializeHistoryPath -CurrentEvidencePath $initializeCurrentPath | Out-Null

    $reuseHistoryPath = Join-Path $testRoot 'reuse-attempts.json'
    [IO.File]::Copy($historyPath, $reuseHistoryPath)
    $oldHistory = Get-Content -LiteralPath $reuseHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $oldHistory.active_cycle_id = 'A' * 64
    foreach ($attempt in @($oldHistory.attempts)) { $attempt.cycle_id = 'A' * 64 }
    Write-TestJson -Path $reuseHistoryPath -Value $oldHistory
    $reuse = & $recorder -Action Reuse -ProjectRoot $projectRoot -Phase Routing -SourceEvidencePath $currentPath -AttemptHistoryPath $reuseHistoryPath
    $reuseHistory = Get-Content -LiteralPath $reuseHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    if (@($reuseHistory.attempts).Count -ne 1 -or [string]$reuseHistory.attempts[0].origin -ne 'evidence_reuse' -or
        [string]$reuseHistory.attempts[0].source_evidence_sha256 -notmatch '^[0-9A-F]{64}$' -or
        [string]$reuseHistory.attempts[0].source_receipt_id -ne [string]$routingBegin.attempt_id) {
        throw 'Evidence reuse did not roll the generation and preserve source provenance'
    }

    $unjustifiedRejected = $false
    try {
        & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $reuseHistoryPath -EvaluatorId 'ledger-unjustified' -EvaluatorModel 'test-model' -EvaluatorRuntime 'test/runtime' | Out-Null
    }
    catch {
        $unjustifiedRejected = $_.Exception.Message.Contains('provide RetryJustification')
    }
    if (-not $unjustifiedRejected) {
        throw 'A reuse receipt did not require justification before unchanged-input re-evaluation'
    }

    $retry = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $reuseHistoryPath -EvaluatorId 'ledger-retry' -EvaluatorModel 'test-model' -EvaluatorRuntime 'test/runtime' -RetryJustification 'One bounded diagnostic re-evaluation after reuse.'
    $unfinishedRejected = $false
    try {
        & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $reuseHistoryPath | Out-Null
    }
    catch {
        $unfinishedRejected = $_.Exception.Message.Contains('not explicitly finished')
    }
    if (-not $unfinishedRejected) {
        throw 'An unfinished formal evaluator run did not block the history gate'
    }
    $executionFailureRecorded = $false
    try {
        & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $retry.attempt_id -AttemptHistoryPath $reuseHistoryPath -ExecutionFailureSummary 'Synthetic evaluator execution failure.' -DurationMilliseconds 5 | Out-Null
    }
    catch {
        $executionFailureMessage = $_.Exception.Message
        $executionFailureRecorded = $_.Exception.Message.Contains('(execution_failed)')
    }
    if (-not $executionFailureRecorded) {
        throw "Evaluator execution failure was not recorded by Finish: $executionFailureMessage"
    }
    $limitRejected = $false
    try {
        & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $reuseHistoryPath -EvaluatorId 'ledger-third' -EvaluatorModel 'test-model' -EvaluatorRuntime 'test/runtime' -RetryJustification 'A third receipt must be rejected.' | Out-Null
    }
    catch {
        $limitRejected = $_.Exception.Message.Contains('reached the limit')
    }
    if (-not $limitRejected) {
        throw 'Unchanged visible input exceeded its bounded two-receipt limit'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $reuseHistoryPath | Out-Null

    $parallelHistoryPath = Join-Path $testRoot 'parallel-attempts.json'
    $pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $parallelProcesses = New-Object 'System.Collections.Generic.List[object]'
    foreach ($phaseName in @('Routing', 'Policy')) {
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $pwshPath
        foreach ($argument in @(
            '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', $recorder,
            '-Action', 'Begin',
            '-ProjectRoot', $projectRoot,
            '-Phase', $phaseName,
            '-AttemptHistoryPath', $parallelHistoryPath,
            '-EvaluatorId', ('parallel-' + $phaseName.ToLowerInvariant()),
            '-EvaluatorModel', 'test-model',
            '-EvaluatorRuntime', 'test/runtime'
        )) {
            $startInfo.ArgumentList.Add([string]$argument)
        }
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) { throw "Parallel $phaseName recorder did not start" }
        $parallelProcesses.Add([pscustomobject]@{
            phase = $phaseName
            process = $process
            stdout = $process.StandardOutput.ReadToEndAsync()
            stderr = $process.StandardError.ReadToEndAsync()
        })
    }
    foreach ($entry in $parallelProcesses) {
        if (-not $entry.process.WaitForExit(30000)) {
            try { $entry.process.Kill($true) } catch { }
            throw "Parallel $($entry.phase) recorder exceeded its bounded wait"
        }
        $parallelStdout = $entry.stdout.GetAwaiter().GetResult()
        $parallelStderr = $entry.stderr.GetAwaiter().GetResult()
        $parallelExitCode = $entry.process.ExitCode
        $entry.process.Dispose()
        if ($parallelExitCode -ne 0) {
            throw "Parallel $($entry.phase) recorder failed: $parallelStderr $parallelStdout"
        }
    }
    $parallelHistory = Get-Content -LiteralPath $parallelHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    if (@($parallelHistory.attempts).Count -ne 2 -or @($parallelHistory.attempts | Where-Object { $_.outcome -ne 'started' }).Count -ne 0) {
        throw 'Bounded history locking did not serialize two parallel Begin operations'
    }
    foreach ($parallelAttempt in @($parallelHistory.attempts)) {
        try {
            & $recorder -Action Finish -ProjectRoot $projectRoot -Phase $parallelAttempt.phase -AttemptId $parallelAttempt.attempt_id -AttemptHistoryPath $parallelHistoryPath -ExecutionFailureSummary 'Synthetic parallel-lock completion.' | Out-Null
        }
        catch {
            if (-not $_.Exception.Message.Contains('(execution_failed)')) { throw }
        }
    }

    if (-not (Test-Path -LiteralPath ($parallelHistoryPath + '.lock') -PathType Leaf)) {
        throw 'Parallel history locking did not retain its stable lock inode'
    }

    $orchestrationHistoryPath = Join-Path $testRoot 'orchestration-attempts.json'
    $orchestrationBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $orchestrationHistoryPath -EvaluatorId 'orchestration-first' -EvaluatorModel 'test-model' -EvaluatorRuntime 'test/runtime'
    $orchestrationRecorded = $false
    try {
        & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $orchestrationBegin.attempt_id -AttemptHistoryPath $orchestrationHistoryPath -OrchestrationFailureSummary 'Synthetic failure before the evaluator process started.' | Out-Null
    }
    catch {
        $orchestrationRecorded = $_.Exception.Message.Contains('(orchestration_failed)')
    }
    if (-not $orchestrationRecorded) {
        throw 'Pre-evaluator orchestration failure was not recorded distinctly'
    }
    $postOrchestrationBegin = & $recorder -Action Begin -ProjectRoot $projectRoot -Phase Routing -AttemptHistoryPath $orchestrationHistoryPath -EvaluatorId 'orchestration-retry' -EvaluatorModel 'test-model' -EvaluatorRuntime 'test/runtime' -RetryJustification 'Retry after repairing the pre-evaluator orchestration fault.'
    try {
        & $recorder -Action Finish -ProjectRoot $projectRoot -Phase Routing -AttemptId $postOrchestrationBegin.attempt_id -AttemptHistoryPath $orchestrationHistoryPath -ExecutionFailureSummary 'Synthetic evaluator failure after process startup.' | Out-Null
    }
    catch {
        if (-not $_.Exception.Message.Contains('(execution_failed)')) { throw }
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $orchestrationHistoryPath | Out-Null

    $carrySourceHistoryPath = Join-Path $testRoot 'carry-source-attempts.json'
    $carryCurrentHistoryPath = Join-Path $testRoot 'carry-current-attempts.json'
    $carrySourceHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $carrySourceHistory.active_cycle_id = ('B' * 64)
    $carrySourceHistory.previous_cycle_id = $null
    $carrySourceHistory.previous_ledger_sha256 = $null
    $carrySourceHistory.previous_attempt_count = 0
    foreach ($carrySourceAttempt in @($carrySourceHistory.attempts)) {
        $carrySourceAttempt.cycle_id = ('B' * 64)
    }
    Write-TestJson -Path $carrySourceHistoryPath -Value $carrySourceHistory
    [IO.File]::Copy($carrySourceHistoryPath, $carryCurrentHistoryPath)
    $carry = & $recorder -Action CarryForward -ProjectRoot $projectRoot -Phase Routing -SourceStagePath $routingPath -SourceAttemptHistoryPath $carrySourceHistoryPath -AttemptHistoryPath $carryCurrentHistoryPath
    $carryHistory = Get-Content -LiteralPath $carryCurrentHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    if ([string]$carry.origin -ne 'staged_carry_forward' -or @($carryHistory.attempts).Count -ne 1 -or
        [string]$carryHistory.attempts[0].source_cycle_id -ne ('B' * 64) -or
        [string]$carryHistory.attempts[0].source_receipt_id -ne [string]$routingBegin.attempt_id -or
        [string]$carryHistory.attempts[0].result_sha256 -ne (Get-FileHash -LiteralPath $routingPath -Algorithm SHA256).Hash) {
        throw 'Staged carry-forward did not bind the prior generation, source receipt, and exact result file'
    }
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $carryCurrentHistoryPath | Out-Null

    Write-Output 'Routing attempt history tests passed: formal, reuse, and staged carry-forward receipts, source provenance, initialization, atomic merge, stable bounded parallel locking, distinct pre-evaluator failures, unfinished-run blocking, execution failures, justified retry, and bounded rollover are enforced.'
}
finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $approvedBase = $tempBase.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($approvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $resolved).StartsWith('AgentBase-routing-attempt-test-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
