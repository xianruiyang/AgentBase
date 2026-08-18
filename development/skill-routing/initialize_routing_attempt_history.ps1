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
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$tempRoot = Join-Path $tempBase ('AgentBase-routing-attempt-init-' + [guid]::NewGuid().ToString('N'))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $routing = Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $routing.PSObject.Properties.Remove('policy_evaluation')
    $routing.PSObject.Properties.Remove('reference_evaluation')
    $stageFiles = @{
        Routing = Join-Path $tempRoot 'routing.json'
        Policy = Join-Path $tempRoot 'policy.json'
        References = Join-Path $tempRoot 'references.json'
    }
    [IO.File]::WriteAllText($stageFiles.Routing, ($routing | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
    [IO.File]::WriteAllText($stageFiles.Policy, ($current.policy_evaluation | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
    [IO.File]::WriteAllText($stageFiles.References, ($current.reference_evaluation | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)

    $routingBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase Routing -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $routing.evaluator.id -EvaluatorModel $routing.evaluator.model -EvaluatorRuntime $routing.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase Routing -AttemptId $routingBegin.attempt_id -ResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    $policyBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase Policy -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $current.policy_evaluation.evaluator.id -EvaluatorModel $current.policy_evaluation.evaluator.model -EvaluatorRuntime $current.policy_evaluation.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase Policy -AttemptId $policyBegin.attempt_id -ResultsPath $stageFiles.Policy -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    $referenceBegin = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Begin -ProjectRoot $ProjectRoot -Phase References -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath -EvaluatorId $current.reference_evaluation.evaluator.id -EvaluatorModel $current.reference_evaluation.evaluator.model -EvaluatorRuntime $current.reference_evaluation.evaluator.runtime -BaselineImport
    & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') -Action Finish -ProjectRoot $ProjectRoot -Phase References -AttemptId $referenceBegin.attempt_id -ResultsPath $stageFiles.References -RoutingResultsPath $stageFiles.Routing -AttemptHistoryPath $AttemptHistoryPath | Out-Null
    & (Join-Path $PSScriptRoot 'validate_routing_attempt_history.ps1') -ProjectRoot $ProjectRoot -AttemptHistoryPath $AttemptHistoryPath -CurrentEvidencePath $CurrentEvidencePath | Out-Null
    [pscustomobject]@{
        path = (Resolve-Path -LiteralPath $AttemptHistoryPath).Path
        imported_receipt_count = 3
        history_start_reason = 'Imported current evidence; earlier attempts were not reconstructed.'
    }
}
finally {
    $resolvedTempRoot = [IO.Path]::GetFullPath($tempRoot)
    if (-not $resolvedTempRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $resolvedTempRoot).StartsWith('AgentBase-routing-attempt-init-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolvedTempRoot"
    }
    if (Test-Path -LiteralPath $resolvedTempRoot) {
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}
