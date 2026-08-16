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

function Get-StringArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { [string]$_ })
}

function Add-Failure {
    param(
        [System.Collections.Generic.List[string]]$Failures,
        [string]$Message
    )

    $Failures.Add($Message)
}

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null

$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$results = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
if ($results.schema_version -ne 3) {
    throw "Unsupported skill-routing result schema: $($results.schema_version)"
}
if ([string]$results.evaluation_kind -ne "skill-routing") {
    throw "Unsupported evaluation kind: $($results.evaluation_kind)"
}
if ([string]$results.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
    throw "Unsupported routing fingerprint schema: $($results.fingerprint_schema)"
}

$requiredSkills = @(Get-StringArray $contract.required_skills)
$peerSkillNames = @($contract.peer_skills | ForEach-Object { [string]$_.name })
$strictRoutingCaseIds = @(Get-StringArray $contract.strict_routing_case_ids)
$capsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract
if ([string]$results.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256) {
    throw "Routing result belongs to a different candidate bundle"
}
if ([string]$results.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256) {
    throw "Routing result belongs to a different evaluation input set"
}
if ([string]$results.evaluation_capsule_sha256 -ne $capsule.sha256) {
    throw "Routing result belongs to a different detached capsule"
}

$evaluator = $results.evaluator
Assert-AgentBaseDetachedEvaluator -Evaluator $evaluator -Label "Skill-routing"
$contractById = @{}
foreach ($case in @($contract.cases)) {
    $contractById[[string]$case.id] = $case
}

$resultById = @{}
$failures = New-Object 'System.Collections.Generic.List[string]'
$routingWarnings = New-Object 'System.Collections.Generic.List[string]'
foreach ($result in @($results.cases)) {
    $id = [string]$result.id
    if ([string]::IsNullOrWhiteSpace($id)) {
        Add-Failure $failures "Result contains a case without an id"
        continue
    }
    if ($resultById.ContainsKey($id)) {
        Add-Failure $failures "Duplicate result id: $id"
        continue
    }
    if (-not $contractById.ContainsKey($id)) {
        Add-Failure $failures "Unknown result id: $id"
        continue
    }
    $resultById[$id] = $result
}

foreach ($id in $contractById.Keys) {
    if (-not $resultById.ContainsKey($id)) {
        Add-Failure $failures "Missing behavior result: $id"
        continue
    }

    $case = $contractById[$id]
    $result = $resultById[$id]
    $expectedSkills = @(Get-StringArray $case.expected_skills)
    $forbiddenSkills = @(Get-StringArray $case.forbidden_skills)
    $selectedSkills = @(Get-StringArray $result.selected_skills)
    $availablePeerSkills = @(Get-StringArray $case.available_peer_skills)
    $expectedPeerSkills = @(Get-StringArray $case.expected_peer_skills)
    $forbiddenPeerSkills = @(Get-StringArray $case.forbidden_peer_skills)
    $selectedPeerSkills = @(Get-StringArray $result.selected_peer_skills)
    $strictRouting = $strictRoutingCaseIds -contains $id

    foreach ($postRoutingField in @("behavior_tags", "selected_references")) {
        if ($result.PSObject.Properties.Name -contains $postRoutingField) {
            Add-Failure $failures "$id returned post-routing field during the skill-routing stage: $postRoutingField"
        }
    }

    foreach ($skill in $selectedSkills) {
        if ($requiredSkills -notcontains $skill) {
            Add-Failure $failures "$id selected an unknown skill: $skill"
        }
    }
    foreach ($skill in $expectedSkills) {
        if ($selectedSkills -notcontains $skill) {
            Add-Failure $failures "$id missed expected skill: $skill"
        }
    }
    foreach ($skill in $forbiddenSkills) {
        if ($selectedSkills -contains $skill) {
            Add-Failure $failures "$id selected forbidden skill: $skill"
        }
    }

    $unexpectedSkills = @($selectedSkills | Where-Object { $expectedSkills -notcontains $_ -and $forbiddenSkills -notcontains $_ })
    foreach ($skill in $unexpectedSkills) {
        $message = "$id selected an unspecified skill: $skill"
        if ($strictRouting -or $FailOnUnexpectedSelections) {
            Add-Failure $failures $message
        }
        else {
            $routingWarnings.Add($message)
        }
    }

    foreach ($peerSkill in $selectedPeerSkills) {
        if ($peerSkillNames -notcontains $peerSkill -or $availablePeerSkills -notcontains $peerSkill) {
            Add-Failure $failures "$id selected an unavailable peer skill: $peerSkill"
        }
    }
    foreach ($peerSkill in $expectedPeerSkills) {
        if ($selectedPeerSkills -notcontains $peerSkill) {
            Add-Failure $failures "$id missed expected peer skill: $peerSkill"
        }
    }
    foreach ($peerSkill in $forbiddenPeerSkills) {
        if ($selectedPeerSkills -contains $peerSkill) {
            Add-Failure $failures "$id selected forbidden peer skill: $peerSkill"
        }
    }
    $unexpectedPeerSkills = @($selectedPeerSkills | Where-Object { $expectedPeerSkills -notcontains $_ -and $forbiddenPeerSkills -notcontains $_ })
    foreach ($peerSkill in $unexpectedPeerSkills) {
        $message = "$id selected an unspecified peer skill: $peerSkill"
        if ($strictRouting -or $FailOnUnexpectedSelections) {
            Add-Failure $failures $message
        }
        else {
            $routingWarnings.Add($message)
        }
    }

}

if ($routingWarnings.Count -gt 0) {
    if ($ShowWarnings) {
        Write-Warning ($routingWarnings -join [Environment]::NewLine)
    }
    else {
        Write-Warning "Skill-routing evaluation recorded $($routingWarnings.Count) unspecified routing selections in non-strict cases. Use -ShowWarnings to list them or -FailOnUnexpectedSelections to make every unspecified selection blocking."
    }
}
if ($failures.Count -gt 0) {
    throw ("Skill-routing evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
}

if (-not $RoutingOnly) {
    if (-not ($results.PSObject.Properties.Name -contains "policy_evaluation") -or $null -eq $results.policy_evaluation) {
        throw "Skill-routing evidence is missing its post-routing behavior-policy evaluation"
    }
    if (-not ($results.PSObject.Properties.Name -contains "reference_evaluation") -or $null -eq $results.reference_evaluation) {
        throw "Skill-routing evidence is missing its post-routing conditional reference evaluation"
    }
    $policyMessage = Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $results -PolicyResults $results.policy_evaluation -FailOnUnexpectedSelections:$FailOnUnexpectedSelections -ShowWarnings:$ShowWarnings
    Write-Verbose $policyMessage
    $referenceMessage = Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $results -ReferenceResults $results.reference_evaluation
    Write-Verbose $referenceMessage
    $stageEvaluatorIds = @(
        [string]$results.evaluator.id
        [string]$results.policy_evaluation.evaluator.id
        [string]$results.reference_evaluation.evaluator.id
    )
    if (@($stageEvaluatorIds | Sort-Object -Unique).Count -ne 3) {
        throw "Routing, behavior-policy, and routing-reference evidence must come from distinct evaluator runs"
    }
}

if ($RoutingOnly) {
    Write-Output "Skill-routing evaluation valid: $($resultById.Count)/$($contractById.Count) cases satisfy the declared project-skill and peer-skill constraints."
}
else {
    Write-Output "Staged routing evidence valid: $($resultById.Count)/$($contractById.Count) skill-routing cases, $(@($results.policy_evaluation.cases).Count) behavior-policy cases, and $(@($results.reference_evaluation.cases).Count) routing-reference cases satisfy their declared constraints."
}
