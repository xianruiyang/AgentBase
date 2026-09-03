$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-routing-recovery-test-{0}" -f [guid]::NewGuid().ToString('N'))
$evidenceDirectory = Join-Path $testRoot "evidence"
$currentPath = Join-Path $evidenceDirectory "current.json"
$historyPath = Join-Path $evidenceDirectory "attempts.json"
$generation = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $projectRoot -Contract $contract
$pendingRoot = Join-Path (Join-Path $evidenceDirectory "pending") $generation
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$recorder = Join-Path $PSScriptRoot "record_routing_attempt.ps1"
$previousEvaluatorGuard = $env:AGENTBASE_ROUTING_EVALUATOR_DISABLED
$env:AGENTBASE_ROUTING_EVALUATOR_DISABLED = '1'

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
        model = "test-model"
        runtime = "test/windows/read-only/ephemeral/cases-only-v4"
        evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        isolation_mode = "detached-capsule"
        repository_accessed = $false
        hidden_expectations_accessed = $false
        auth_mode = "read-only-hardlink"
        model_catalog_sha256 = ('A' * 64)
        disabled_features = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    }
}

try {
    [IO.Directory]::CreateDirectory($pendingRoot) | Out-Null
    $routingPath = Join-Path $pendingRoot "routing.json"
    $policyPath = Join-Path $pendingRoot "policy.json"
    $referencesPath = Join-Path $pendingRoot "references.json"

    $routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
    $routing = New-AgentBaseRoutingResultEnvelope -Phase Routing -Capsule $routingCapsule -Evaluator (New-TestEvaluator "recovery-routing") -Cases @($contract.cases | ForEach-Object {
        [pscustomobject]@{
            id = [string]$_.id
            selected_skills = @(ConvertTo-AgentBaseStringArray $_.expected_skills)
            selected_peer_skills = @(ConvertTo-AgentBaseStringArray $_.expected_peer_skills)
        }
    })
    Write-TestJson -Path $routingPath -Value $routing

    $policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
    $policy = New-AgentBaseRoutingResultEnvelope -Phase Policy -Capsule $policyCapsule -Evaluator (New-TestEvaluator "recovery-policy") -Cases @($contract.cases | ForEach-Object {
        [pscustomobject]@{ id = [string]$_.id; behavior_tags = @(ConvertTo-AgentBaseStringArray $_.expected_behavior_tags) }
    })
    Write-TestJson -Path $policyPath -Value $policy

    $contractById = @{}
    foreach ($case in @($contract.cases)) { $contractById[[string]$case.id] = $case }
    $referenceCapsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routing
    $references = New-AgentBaseRoutingResultEnvelope -Phase References -Capsule $referenceCapsule -Evaluator (New-TestEvaluator "recovery-references") -Cases @($referenceCapsule.payload.cases | ForEach-Object {
        $capsuleCase = $_
        $contractCase = $contractById[[string]$capsuleCase.id]
        [pscustomobject]@{
            id = [string]$capsuleCase.id
            selected_references = @($capsuleCase.selected_reference_skills | ForEach-Object {
                $skillName = [string]$_
                $expectedProperty = "expected_$($skillName.Replace('-', '_'))_references"
                [pscustomobject]@{
                    skill = $skillName
                    references = @(ConvertTo-AgentBaseStringArray $contractCase.$expectedProperty)
                }
            })
        }
    })
    Write-TestJson -Path $referencesPath -Value $references

    $stageDefinitions = @(
        [pscustomobject]@{ phase = "Routing"; path = $routingPath; evaluator = $routing.evaluator; routing = $null },
        [pscustomobject]@{ phase = "Policy"; path = $policyPath; evaluator = $policy.evaluator; routing = $null },
        [pscustomobject]@{ phase = "References"; path = $referencesPath; evaluator = $references.evaluator; routing = $routingPath }
    )
    foreach ($stage in $stageDefinitions) {
        $beginParameters = @{
            Action = "Begin"
            ProjectRoot = $projectRoot
            Phase = $stage.phase
            AttemptHistoryPath = $historyPath
            EvaluatorId = [string]$stage.evaluator.id
            EvaluatorModel = [string]$stage.evaluator.model
            EvaluatorRuntime = [string]$stage.evaluator.runtime
        }
        if ($stage.phase -eq "References") { $beginParameters.RoutingResultsPath = $stage.routing }
        $begin = & $recorder @beginParameters
        $finishParameters = @{
            Action = "Finish"
            ProjectRoot = $projectRoot
            Phase = $stage.phase
            AttemptHistoryPath = $historyPath
            AttemptId = $begin.attempt_id
            ResultsPath = $stage.path
            DurationMilliseconds = 1
            InputTokens = 1
            CachedInputTokens = 0
            OutputTokens = 1
        }
        if ($stage.phase -eq "References") { $finishParameters.RoutingResultsPath = $stage.routing }
        & $recorder @finishParameters | Out-Null
    }

    $preRefreshHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $referenceFailure = @($preRefreshHistory.attempts | Where-Object { [string]$_.phase -eq 'References' })
    if ($referenceFailure.Count -ne 1) { throw 'Reference revalidation fixture did not find one source receipt' }
    $referenceFailure[0].outcome = 'failed'
    $referenceFailure[0].stage_result_sha256 = $null
    $referenceFailure[0].failure_class = 'oracle_violation'
    $referenceFailure[0].failure_summary = 'Synthetic prior-oracle rejection of an otherwise unchanged result.'
    Write-TestJson -Path $historyPath -Value $preRefreshHistory

    $refresh = & (Join-Path $PSScriptRoot "refresh_routing_evidence.ps1") -ProjectRoot $projectRoot -CurrentEvidencePath $currentPath -AttemptHistoryPath $historyPath -View machine
    if ([string]$refresh.action -ne "refreshed" -or [int]$refresh.evaluator_run_count -ne 0 -or
        [int]$refresh.recovered_phase_count -ne 2 -or [int]$refresh.oracle_revalidated_phase_count -ne 1 -or
        [int]$refresh.reused_phase_count -ne 0) {
        throw "Refresh did not recover two passed stages and revalidate one exact oracle-rejected result without evaluator runs"
    }
    if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf) -or (Test-Path -LiteralPath $pendingRoot)) {
        throw "Recovered refresh did not atomically publish current evidence and retire its pending generation"
    }
    & (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $projectRoot -ResultsPath $currentPath | Out-Null
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $projectRoot -AttemptHistoryPath $historyPath -CurrentEvidencePath $currentPath | Out-Null
    $tamperedHistoryPath = Join-Path $testRoot 'tampered-revalidation-attempts.json'
    $tamperedHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $tamperedRevalidation = @($tamperedHistory.attempts | Where-Object { [string]$_.origin -eq 'oracle_revalidation' })
    if ($tamperedRevalidation.Count -ne 1) { throw 'Oracle revalidation fixture did not create one provenance receipt' }
    $tamperedRevalidation[0].source_receipt_id = '0' * 32
    Write-TestJson -Path $tamperedHistoryPath -Value $tamperedHistory
    $tamperedRejected = $false
    try {
        & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $projectRoot -AttemptHistoryPath $tamperedHistoryPath | Out-Null
    }
    catch {
        $tamperedRejected = $_.Exception.Message.Contains('zero-cost failed-result link') -or
            $_.Exception.Message.Contains('reuses evaluator id')
    }
    if (-not $tamperedRejected) { throw 'Oracle revalidation accepted a tampered source receipt link' }

    $carryEvidenceDirectory = Join-Path $testRoot "carry-evidence"
    $carryCurrentPath = Join-Path $carryEvidenceDirectory "current.json"
    $carryHistoryPath = Join-Path $carryEvidenceDirectory "attempts.json"
    $priorGeneration = ('C' * 64)
    $carryPriorRoot = Join-Path (Join-Path $carryEvidenceDirectory "pending") $priorGeneration
    [IO.Directory]::CreateDirectory($carryPriorRoot) | Out-Null
    Write-TestJson -Path (Join-Path $carryPriorRoot "routing.json") -Value $routing
    Write-TestJson -Path (Join-Path $carryPriorRoot "policy.json") -Value $policy
    Write-TestJson -Path (Join-Path $carryPriorRoot "references.json") -Value $references
    $carryHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $carryHistory.active_cycle_id = $priorGeneration
    $carryHistory.previous_cycle_id = $null
    $carryHistory.previous_ledger_sha256 = $null
    $carryHistory.previous_attempt_count = 0
    foreach ($carryAttempt in @($carryHistory.attempts)) { $carryAttempt.cycle_id = $priorGeneration }
    Write-TestJson -Path $carryHistoryPath -Value $carryHistory

    $carryRefresh = & (Join-Path $PSScriptRoot "refresh_routing_evidence.ps1") -ProjectRoot $projectRoot -CurrentEvidencePath $carryCurrentPath -AttemptHistoryPath $carryHistoryPath -View machine
    if ([string]$carryRefresh.action -ne "refreshed" -or [int]$carryRefresh.evaluator_run_count -ne 0 -or
        [int]$carryRefresh.recovered_phase_count -ne 0 -or [int]$carryRefresh.carried_forward_phase_count -ne 3 -or
        [int]$carryRefresh.reused_phase_count -ne 0) {
        throw "Refresh did not carry all three unchanged passed stages across generations without evaluator runs"
    }
    if (-not (Test-Path -LiteralPath $carryCurrentPath -PathType Leaf) -or
        @(Get-ChildItem -LiteralPath (Join-Path $carryEvidenceDirectory "pending") -Directory -Force).Count -ne 0) {
        throw "Carry-forward refresh did not publish current evidence and retire old/new staging generations"
    }
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $projectRoot -AttemptHistoryPath $carryHistoryPath -CurrentEvidencePath $carryCurrentPath | Out-Null

    $crossEvidenceDirectory = Join-Path $testRoot "cross-generation-revalidation-evidence"
    $crossCurrentPath = Join-Path $crossEvidenceDirectory "current.json"
    $crossHistoryPath = Join-Path $crossEvidenceDirectory "attempts.json"
    $crossPriorGeneration = ('E' * 64)
    $crossPriorRoot = Join-Path (Join-Path $crossEvidenceDirectory "pending") $crossPriorGeneration
    [IO.Directory]::CreateDirectory($crossPriorRoot) | Out-Null
    Write-TestJson -Path (Join-Path $crossPriorRoot "routing.json") -Value $routing
    Write-TestJson -Path (Join-Path $crossPriorRoot "policy.json") -Value $policy
    Write-TestJson -Path (Join-Path $crossPriorRoot "references.json") -Value $references
    $crossHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $crossHistory.active_cycle_id = $crossPriorGeneration
    $crossHistory.previous_cycle_id = $null
    $crossHistory.previous_ledger_sha256 = $null
    $crossHistory.previous_attempt_count = 0
    $crossHistory.attempts = @($crossHistory.attempts | Where-Object { [string]$_.outcome -eq 'passed' })
    foreach ($crossAttempt in @($crossHistory.attempts)) {
        $crossAttempt.cycle_id = $crossPriorGeneration
        if ([string]$crossAttempt.origin -eq 'oracle_revalidation') {
            $crossAttempt.origin = 'formal'
            $crossAttempt.previous_attempt_id = $null
            $crossAttempt.changed_since_previous = @('initial_receipt')
            $crossAttempt.source_receipt_id = $null
            $crossAttempt.source_cycle_id = $null
        }
    }
    $crossPolicyFailure = @($crossHistory.attempts | Where-Object { [string]$_.phase -eq 'Policy' })
    if ($crossPolicyFailure.Count -ne 1) { throw 'Cross-generation revalidation fixture did not find one policy receipt' }
    $crossPolicySourceReceiptId = [string]$crossPolicyFailure[0].attempt_id
    $crossPolicyFailure[0].outcome = 'failed'
    $crossPolicyFailure[0].stage_result_sha256 = $null
    $crossPolicyFailure[0].failure_class = 'oracle_violation'
    $crossPolicyFailure[0].failure_summary = 'Synthetic prior-generation oracle rejection of an otherwise unchanged result.'
    Write-TestJson -Path $crossHistoryPath -Value $crossHistory
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $projectRoot -AttemptHistoryPath $crossHistoryPath | Out-Null

    $crossRefresh = & (Join-Path $PSScriptRoot "refresh_routing_evidence.ps1") -ProjectRoot $projectRoot -CurrentEvidencePath $crossCurrentPath -AttemptHistoryPath $crossHistoryPath -View machine
    if ([string]$crossRefresh.action -ne "refreshed" -or [int]$crossRefresh.evaluator_run_count -ne 0 -or
        [int]$crossRefresh.oracle_revalidated_phase_count -ne 1 -or [int]$crossRefresh.carried_forward_phase_count -ne 2 -or
        [int]$crossRefresh.reused_phase_count -ne 0) {
        throw "Refresh did not revalidate one exact prior-generation oracle rejection and carry two passed stages without evaluator runs"
    }
    $crossFinalHistory = Get-Content -LiteralPath $crossHistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $crossRevalidation = @($crossFinalHistory.attempts | Where-Object {
        [string]$_.phase -eq 'Policy' -and [string]$_.origin -eq 'oracle_revalidation'
    })
    if ($crossRevalidation.Count -ne 1 -or
        [string]$crossRevalidation[0].source_receipt_id -ne $crossPolicySourceReceiptId -or
        [string]$crossRevalidation[0].source_cycle_id -ne $crossPriorGeneration -or
        -not [string]::IsNullOrWhiteSpace([string]$crossRevalidation[0].previous_attempt_id)) {
        throw 'Cross-generation oracle revalidation did not retain its exact prior failure provenance'
    }
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $projectRoot -AttemptHistoryPath $crossHistoryPath -CurrentEvidencePath $crossCurrentPath | Out-Null

    $resumeEvidenceDirectory = Join-Path $testRoot "resume-carry-evidence"
    $resumeCurrentPath = Join-Path $resumeEvidenceDirectory "current.json"
    $resumeHistoryPath = Join-Path $resumeEvidenceDirectory "attempts.json"
    $resumePriorGeneration = ('D' * 64)
    $resumePendingBase = Join-Path $resumeEvidenceDirectory "pending"
    $resumePriorRoot = Join-Path $resumePendingBase $resumePriorGeneration
    $resumeCurrentRoot = Join-Path $resumePendingBase $generation
    [IO.Directory]::CreateDirectory($resumePriorRoot) | Out-Null
    [IO.Directory]::CreateDirectory($resumeCurrentRoot) | Out-Null
    Write-TestJson -Path (Join-Path $resumePriorRoot "routing.json") -Value $routing
    Write-TestJson -Path (Join-Path $resumePriorRoot "policy.json") -Value $policy
    Write-TestJson -Path (Join-Path $resumePriorRoot "references.json") -Value $references
    $resumeHistory = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 -DateKind String
    $resumeHistory.active_cycle_id = $resumePriorGeneration
    $resumeHistory.previous_cycle_id = $null
    $resumeHistory.previous_ledger_sha256 = $null
    $resumeHistory.previous_attempt_count = 0
    foreach ($resumeAttempt in @($resumeHistory.attempts)) { $resumeAttempt.cycle_id = $resumePriorGeneration }
    Write-TestJson -Path $resumeHistoryPath -Value $resumeHistory
    $resumeSourceHistoryPath = Join-Path $resumeCurrentRoot 'source-attempts.json'
    [IO.File]::Copy($resumeHistoryPath, $resumeSourceHistoryPath)
    $resumeRoutingPath = Join-Path $resumeCurrentRoot 'routing.json'
    [IO.File]::Copy((Join-Path $resumePriorRoot 'routing.json'), $resumeRoutingPath)
    & $recorder -Action CarryForward -ProjectRoot $projectRoot -Phase Routing -SourceStagePath $resumeRoutingPath -SourceAttemptHistoryPath $resumeSourceHistoryPath -AttemptHistoryPath $resumeHistoryPath | Out-Null

    $resumeRefresh = & (Join-Path $PSScriptRoot "refresh_routing_evidence.ps1") -ProjectRoot $projectRoot -CurrentEvidencePath $resumeCurrentPath -AttemptHistoryPath $resumeHistoryPath -View machine
    if ([string]$resumeRefresh.action -ne "refreshed" -or [int]$resumeRefresh.evaluator_run_count -ne 0 -or
        [int]$resumeRefresh.recovered_phase_count -ne 1 -or [int]$resumeRefresh.carried_forward_phase_count -ne 2 -or
        [int]$resumeRefresh.reused_phase_count -ne 0) {
        throw "Refresh did not resume a partially carried generation without repeating model work"
    }
    if (-not (Test-Path -LiteralPath $resumeCurrentPath -PathType Leaf) -or
        @(Get-ChildItem -LiteralPath $resumePendingBase -Directory -Force).Count -ne 0) {
        throw "Resumed carry-forward refresh did not publish current evidence and retire its staging"
    }
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $projectRoot -AttemptHistoryPath $resumeHistoryPath -CurrentEvidencePath $resumeCurrentPath | Out-Null

    Write-Output "Routing refresh recovery tests passed: same-generation results resume, exact oracle-rejected output revalidates at zero Token within or across generations, cross-generation carry survives interruption, merges are atomic, and staging retires after commit."
}
finally {
    $env:AGENTBASE_ROUTING_EVALUATOR_DISABLED = $previousEvaluatorGuard
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $approvedBase = $tempBase.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($approvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $resolved).StartsWith('AgentBase-routing-recovery-test-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temporary root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
