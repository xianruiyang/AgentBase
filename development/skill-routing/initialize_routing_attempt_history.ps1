[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$CurrentEvidencePath,
    [string]$AttemptHistoryPath
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($CurrentEvidencePath)) {
    $CurrentEvidencePath = Join-Path $PSScriptRoot 'evidence\current.json'
}
$CurrentEvidencePath = (Resolve-Path -LiteralPath $CurrentEvidencePath).Path
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot 'evidence\attempts.json'
}
$AttemptHistoryPath = [IO.Path]::GetFullPath($AttemptHistoryPath)
if (Test-Path -LiteralPath $AttemptHistoryPath) {
    throw "Routing attempt history already exists: $AttemptHistoryPath"
}

& (Join-Path $PSScriptRoot 'validate_routing_results.ps1') -ProjectRoot $ProjectRoot -ResultsPath $CurrentEvidencePath | Out-Null
$current = Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempRoot = Join-Path $tempBase ("AgentBase-routing-attempt-init-{0}" -f [guid]::NewGuid().ToString('N'))
$utf8NoBom = [Text.UTF8Encoding]::new($false)
try {
    [IO.Directory]::CreateDirectory($tempRoot) | Out-Null
    $stageFiles = [ordered]@{
        Routing = Join-Path $tempRoot 'routing.json'
        Policy = Join-Path $tempRoot 'policy.json'
        References = Join-Path $tempRoot 'references.json'
    }
    $routing = [pscustomobject][ordered]@{
        schema_version = $current.schema_version
        evaluation_kind = $current.evaluation_kind
        fingerprint_schema = $current.fingerprint_schema
        evaluator = $current.evaluator
        evaluation_capsule_sha256 = $current.evaluation_capsule_sha256
        candidate_bundle_sha256 = $current.candidate_bundle_sha256
        evaluation_input_sha256 = $current.evaluation_input_sha256
        cases = @($current.cases)
    }
    [IO.File]::WriteAllText($stageFiles.Routing, ($routing | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
    [IO.File]::WriteAllText($stageFiles.Policy, ($current.policy_evaluation | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
    [IO.File]::WriteAllText($stageFiles.References, ($current.reference_evaluation | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)

    $routingBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase Routing -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $routing.evaluator.id -EvaluatorModel $routing.evaluator.model -EvaluatorRuntime $routing.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase Routing -AttemptId $routingBegin.attempt_id -ResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    $policyBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase Policy -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $current.policy_evaluation.evaluator.id -EvaluatorModel $current.policy_evaluation.evaluator.model -EvaluatorRuntime $current.policy_evaluation.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase Policy -AttemptId $policyBegin.attempt_id -ResultsPath $stageFiles.Policy -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    $referenceBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase References -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $current.reference_evaluation.evaluator.id -EvaluatorModel $current.reference_evaluation.evaluator.model -EvaluatorRuntime $current.reference_evaluation.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase References -AttemptId $referenceBegin.attempt_id -ResultsPath $stageFiles.References -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    & (Join-Path $PSScriptRoot 'merge_routing_evidence.ps1') -ProjectRoot $ProjectRoot -RoutingResultsPath $stageFiles.Routing -PolicyResultsPath $stageFiles.Policy -ReferenceResultsPath $stageFiles.References -RoutingAttemptId $routingBegin.attempt_id -PolicyAttemptId $policyBegin.attempt_id -ReferenceAttemptId $referenceBegin.attempt_id -AttemptHistoryPath $AttemptHistoryPath -OutputPath $CurrentEvidencePath | Out-Null
    [pscustomobject]@{
        path = (Resolve-Path -LiteralPath $AttemptHistoryPath).Path
        imported_receipt_count = 3
        history_start_reason = 'Imported current evidence; earlier attempts were not reconstructed.'
    }
}
finally {
    $resolved = [IO.Path]::GetFullPath($tempRoot)
    $approvedBase = $tempBase.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($approvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $resolved).StartsWith('AgentBase-routing-attempt-init-', [StringComparison]::Ordinal)) {
        throw "Refusing cleanup outside the approved temp root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
