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
    [Parameter(Mandatory = $true)]
    [string]$RoutingAttemptId,
    [Parameter(Mandatory = $true)]
    [string]$PolicyAttemptId,
    [Parameter(Mandatory = $true)]
    [string]$ReferenceAttemptId,
    [string]$ProjectRoot,
    [string]$AttemptHistoryPath
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")
. (Join-Path $PSScriptRoot "routing_attempt_history.ps1")

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
$PolicyResultsPath = (Resolve-Path -LiteralPath $PolicyResultsPath).Path
$ReferenceResultsPath = (Resolve-Path -LiteralPath $ReferenceResultsPath).Path
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot "evidence\attempts.json"
}
$AttemptHistoryPath = (Resolve-Path -LiteralPath $AttemptHistoryPath).Path
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory) -or -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Output directory must already exist: $outputDirectory"
}

$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$routing = Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$policy = Get-Content -LiteralPath $PolicyResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
$references = Get-Content -LiteralPath $ReferenceResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing | Out-Null
Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -PolicyResults $policy | Out-Null
Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing -ReferenceResults $references | Out-Null

$stageEvaluatorIds = @(
    [string]$routing.evaluator.id
    [string]$policy.evaluator.id
    [string]$references.evaluator.id
)
if (@($stageEvaluatorIds | Sort-Object -Unique).Count -ne 3) {
    throw "Routing, behavior-policy, and routing-reference evidence must originate from distinct evaluator runs"
}

$history = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
if ($null -eq $history -or [int]$history.schema_version -ne (Get-AgentBaseRoutingAttemptHistorySchema)) {
    throw "A current-schema routing attempt ledger is required before evidence merge"
}
$generation = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $ProjectRoot -Contract $contract
if ([string]$history.active_cycle_id -ne $generation) {
    throw "Routing attempt ledger belongs to a different evaluation generation"
}
$stageReceipts = @(
    [pscustomobject]@{ phase = 'Routing'; attempt_id = $RoutingAttemptId; result = $routing; path = $RoutingResultsPath },
    [pscustomobject]@{ phase = 'Policy'; attempt_id = $PolicyAttemptId; result = $policy; path = $PolicyResultsPath },
    [pscustomobject]@{ phase = 'References'; attempt_id = $ReferenceAttemptId; result = $references; path = $ReferenceResultsPath }
)
foreach ($stage in $stageReceipts) {
    $semanticHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $stage.phase -Results $stage.result
    $receipt = @($history.attempts | Where-Object {
        [string]$_.attempt_id -eq [string]$stage.attempt_id -and
        [string]$_.phase -eq [string]$stage.phase -and
        [string]$_.outcome -eq 'passed' -and
        [string]$_.stage_result_sha256 -eq $semanticHash -and
        [string]$_.evaluator_id -eq [string]$stage.result.evaluator.id -and
        [string]$_.candidate_bundle_sha256 -eq [string]$stage.result.candidate_bundle_sha256 -and
        [string]$_.evaluation_input_sha256 -eq [string]$stage.result.evaluation_input_sha256 -and
        [string]$_.evaluation_capsule_sha256 -eq [string]$stage.result.evaluation_capsule_sha256
    })
    if ($receipt.Count -ne 1) {
        throw "$($stage.phase) result is not bound to the supplied passed receipt id: $($stage.attempt_id)"
    }
    if ([string]$receipt[0].origin -in @('formal', 'baseline_import', 'staged_carry_forward')) {
        $resultHash = (Get-FileHash -LiteralPath $stage.path -Algorithm SHA256).Hash
        if ([string]$receipt[0].result_sha256 -ne $resultHash) {
            throw "$($stage.phase) formal result file does not match its recorded hash"
        }
    }
    elseif ([string]$receipt[0].origin -eq 'evidence_reuse') {
        if ([string]$receipt[0].source_evidence_sha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
            [string]$receipt[0].source_receipt_id -notmatch '^[0-9a-f]{32}$') {
            throw "$($stage.phase) reuse receipt lacks its source evidence link"
        }
    }
    else {
        throw "$($stage.phase) receipt has an unsupported origin"
    }
}

$routing | Add-Member -NotePropertyName "receipt_id" -NotePropertyValue $RoutingAttemptId -Force
$policy | Add-Member -NotePropertyName "receipt_id" -NotePropertyValue $PolicyAttemptId -Force
$references | Add-Member -NotePropertyName "receipt_id" -NotePropertyValue $ReferenceAttemptId -Force
$routing | Add-Member -NotePropertyName "evaluation_generation_sha256" -NotePropertyValue $generation -Force
$routing | Add-Member -NotePropertyName "policy_evaluation" -NotePropertyValue $policy -Force
$routing | Add-Member -NotePropertyName "reference_evaluation" -NotePropertyValue $references -Force

$json = $routing | ConvertTo-Json -Depth 100
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$temporaryPath = Join-Path $outputDirectory (".{0}.{1}.tmp" -f ([IO.Path]::GetFileName($OutputPath)), [guid]::NewGuid().ToString("N"))
try {
    [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, $utf8NoBom)
    & (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $ProjectRoot -ResultsPath $temporaryPath | Out-Null
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $ProjectRoot -AttemptHistoryPath $AttemptHistoryPath -CurrentEvidencePath $temporaryPath | Out-Null
    [IO.File]::Move($temporaryPath, $OutputPath, $true)
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        [IO.File]::Delete($temporaryPath)
    }
}

[pscustomobject][ordered]@{
    path = (Resolve-Path -LiteralPath $OutputPath).Path
    evaluation_generation_sha256 = $generation
    routing_case_count = @($routing.cases).Count
    policy_case_count = @($policy.cases).Count
    reference_case_count = @($references.cases).Count
    routing_attempt_id = $RoutingAttemptId
    policy_attempt_id = $PolicyAttemptId
    reference_attempt_id = $ReferenceAttemptId
}
