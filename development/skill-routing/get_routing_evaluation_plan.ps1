[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$CurrentEvidencePath,
    [string]$RoutingResultsPath,
    [ValidateSet("model", "machine")]
    [string]$View = "model"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($CurrentEvidencePath)) {
    $CurrentEvidencePath = Join-Path $PSScriptRoot "evidence\current.json"
}
$CurrentEvidencePath = [IO.Path]::GetFullPath($CurrentEvidencePath)

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$sourceEvidence = if (Test-Path -LiteralPath $CurrentEvidencePath -PathType Leaf) {
    Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
else {
    $null
}
$routingResults = if ([string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
    $null
}
else {
    $resolvedRoutingPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
    Get-Content -LiteralPath $resolvedRoutingPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
$plan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $ProjectRoot -Contract $contract -SourceEvidence $sourceEvidence -RoutingResultsForReferences $routingResults

if ($View -eq "machine") {
    $plan | ConvertTo-Json -Depth 20
    return
}

Write-Output "generation=$($plan.evaluation_generation_sha256)"
Write-Output "runs=$($plan.evaluation_count) reuse=$($plan.reuse_count) blocked=$($plan.blocked_count) pending=$($plan.pending_count)"
foreach ($phase in @("Routing", "Policy", "References")) {
    $decision = $plan.phases.$phase
    Write-Output "$phase=$($decision.action) reason=$($decision.reason)"
}
if (@($plan.parallel_first_wave).Count -gt 0) {
    Write-Output "parallel_first_wave=$(@($plan.parallel_first_wave) -join ',')"
}
