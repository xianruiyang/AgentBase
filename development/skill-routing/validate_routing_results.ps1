[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ResultsPath,
    [string]$ProjectRoot,
    [switch]$FailOnUnexpectedSelections,
    [switch]$ShowWarnings,
    [switch]$RoutingOnly
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$ResultsPath = (Resolve-Path -LiteralPath $ResultsPath).Path

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$results = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String

$routingMessage = Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $results -FailOnUnexpectedSelections:$FailOnUnexpectedSelections -ShowWarnings:$ShowWarnings
Write-Verbose $routingMessage

if ($RoutingOnly) {
    Write-Output $routingMessage
    return
}

if ($null -eq $results.policy_evaluation) {
    throw "Skill-routing evidence is missing its independent behavior-policy evaluation"
}
if ($null -eq $results.reference_evaluation) {
    throw "Skill-routing evidence is missing its conditional reference evaluation"
}
$policyMessage = Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -PolicyResults $results.policy_evaluation -FailOnUnexpectedSelections:$FailOnUnexpectedSelections -ShowWarnings:$ShowWarnings
$referenceMessage = Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $results -ReferenceResults $results.reference_evaluation
Write-Verbose $policyMessage
Write-Verbose $referenceMessage

$expectedGeneration = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $ProjectRoot -Contract $contract
if ([string]$results.evaluation_generation_sha256 -ne $expectedGeneration) {
    throw "Current staged routing evidence belongs to a different evaluation generation"
}
foreach ($stage in @($results, $results.policy_evaluation, $results.reference_evaluation)) {
    if ([string]$stage.receipt_id -notmatch '^[0-9a-f]{32}$') {
        throw "Current staged routing evidence is missing a valid phase receipt id"
    }
}
$stageEvaluatorIds = @(
    [string]$results.evaluator.id
    [string]$results.policy_evaluation.evaluator.id
    [string]$results.reference_evaluation.evaluator.id
)
if (@($stageEvaluatorIds | Sort-Object -Unique).Count -ne 3) {
    throw "Routing, behavior-policy, and routing-reference evidence must originate from distinct evaluator runs"
}

Write-Output "Staged routing evidence valid: $(@($results.cases).Count) routing cases, $(@($results.policy_evaluation.cases).Count) policy cases, and $(@($results.reference_evaluation.cases).Count) reference cases; generation $expectedGeneration."
