[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$OutputPath,
    [ValidateSet("Routing", "Policy", "References")]
    [string]$Phase = "Routing",
    [string]$RoutingResultsPath
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $leaf = switch ($Phase) {
        "Policy" { "AgentBase-behavior-policy-evaluation-capsule.json" }
        "References" { "AgentBase-routing-reference-evaluation-capsule.json" }
        default { "AgentBase-routing-evaluation-capsule.json" }
    }
    $OutputPath = Join-Path ([IO.Path]::GetTempPath()) $leaf
}
$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory) -or -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Output directory must already exist: $outputDirectory"
}

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null

$contractPath = Join-Path $PSScriptRoot "trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($Phase -eq "References") {
    if ([string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw "RoutingResultsPath is required for the References phase"
    }
    $RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
    & (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $ProjectRoot -ResultsPath $RoutingResultsPath -RoutingOnly | Out-Null
    $routingResults = Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $capsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults
}
elseif ($Phase -eq "Policy") {
    if (-not [string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw "RoutingResultsPath is not accepted for the independent Policy phase"
    }
    $capsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract
}
else {
    if (-not [string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw "RoutingResultsPath is not accepted for the Routing phase"
    }
    $capsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract
}
$json = $capsule.payload | ConvertTo-Json -Depth 12
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($OutputPath, $json + [Environment]::NewLine, $utf8NoBom)

[pscustomobject]@{
    path = (Resolve-Path -LiteralPath $OutputPath).Path
    phase = $Phase
    evaluation_capsule_sha256 = $capsule.sha256
    candidate_bundle_sha256 = $capsule.candidate_bundle_sha256
    evaluation_input_sha256 = $capsule.evaluation_input_sha256
    case_count = @($capsule.payload.cases).Count
}
