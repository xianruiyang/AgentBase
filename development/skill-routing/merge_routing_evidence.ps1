[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RoutingResultsPath,
    [Parameter(Mandatory = $true)]
    [string]$PolicyResultsPath,
    [Parameter(Mandatory = $true)]
    [string]$ReferenceResultsPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
$PolicyResultsPath = (Resolve-Path -LiteralPath $PolicyResultsPath).Path
$ReferenceResultsPath = (Resolve-Path -LiteralPath $ReferenceResultsPath).Path
$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory) -or -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Output directory must already exist: $outputDirectory"
}

& (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $ProjectRoot -ResultsPath $RoutingResultsPath -RoutingOnly | Out-Null
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$routing = Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$policy = Get-Content -LiteralPath $PolicyResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$references = Get-Content -LiteralPath $ReferenceResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$null = Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing -PolicyResults $policy
$null = Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing -ReferenceResults $references
$stageEvaluatorIds = @(
    [string]$routing.evaluator.id
    [string]$policy.evaluator.id
    [string]$references.evaluator.id
)
if (@($stageEvaluatorIds | Sort-Object -Unique).Count -ne 3) {
    throw "Routing, behavior-policy, and routing-reference evidence must come from distinct evaluator runs"
}

$routing | Add-Member -NotePropertyName "policy_evaluation" -NotePropertyValue $policy -Force
$routing | Add-Member -NotePropertyName "reference_evaluation" -NotePropertyValue $references -Force
$json = $routing | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$temporaryPath = Join-Path $outputDirectory (".{0}.{1}.tmp" -f ([IO.Path]::GetFileName($OutputPath)), [guid]::NewGuid().ToString("N"))
try {
    [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, $utf8NoBom)
    & (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $ProjectRoot -ResultsPath $temporaryPath | Out-Null
    [IO.File]::Move($temporaryPath, $outputFullPath, $true)
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

[pscustomobject]@{
    path = (Resolve-Path -LiteralPath $outputFullPath).Path
    routing_case_count = @($routing.cases).Count
    policy_case_count = @($policy.cases).Count
    reference_case_count = @($references.cases).Count
    candidate_bundle_sha256 = [string]$routing.candidate_bundle_sha256
    routing_evaluation_capsule_sha256 = [string]$routing.evaluation_capsule_sha256
    policy_evaluation_capsule_sha256 = [string]$policy.evaluation_capsule_sha256
    reference_evaluation_capsule_sha256 = [string]$references.evaluation_capsule_sha256
}
