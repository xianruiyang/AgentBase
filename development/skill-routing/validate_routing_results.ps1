[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ResultsPath,
    [string]$ProjectRoot,
    [switch]$FailOnUnexpectedSelections,
    [switch]$ShowWarnings
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
if ($results.schema_version -ne 2) {
    throw "Unsupported routing-policy result schema: $($results.schema_version)"
}
if ([string]$results.evaluation_kind -ne "routing-policy") {
    throw "Unsupported evaluation kind: $($results.evaluation_kind)"
}
if ([string]$results.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
    throw "Unsupported routing fingerprint schema: $($results.fingerprint_schema)"
}

$requiredSkills = @(Get-StringArray $contract.required_skills)
$peerSkillNames = @($contract.peer_skills | ForEach-Object { [string]$_.name })
$allowedBehaviorTags = @(Get-StringArray $contract.allowed_behavior_tags)
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
foreach ($field in @("id", "model", "runtime", "evaluated_at_utc", "isolation_mode")) {
    if ($null -eq $evaluator -or [string]::IsNullOrWhiteSpace([string]$evaluator.$field)) {
        throw "Routing result evaluator is missing required field: $field"
    }
}
if ([string]$evaluator.isolation_mode -ne "detached-capsule") {
    throw "Routing result was not produced from the detached capsule"
}
foreach ($attestationField in @("repository_accessed", "hidden_expectations_accessed")) {
    if ($null -eq $evaluator -or -not ($evaluator.PSObject.Properties.Name -contains $attestationField) -or $evaluator.$attestationField.GetType().FullName -ne "System.Boolean") {
        throw "Routing result evaluator is missing boolean input attestation: $attestationField"
    }
    if ([bool]$evaluator.$attestationField) {
        throw "Routing result evaluator attested that prohibited input was accessed: $attestationField"
    }
}
$evaluatedAtText = [string]$evaluator.evaluated_at_utc
$evaluatedAt = [DateTimeOffset]::MinValue
if (-not $evaluatedAtText.EndsWith("Z", [StringComparison]::OrdinalIgnoreCase) -or -not [DateTimeOffset]::TryParse($evaluatedAtText, [ref]$evaluatedAt) -or $evaluatedAt.Offset -ne [TimeSpan]::Zero) {
    throw "Routing evaluator timestamp must be a valid UTC ISO-8601 value"
}
if ($evaluatedAt -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
    throw "Routing evaluator timestamp is unexpectedly in the future"
}
$contractById = @{}
foreach ($case in @($contract.cases)) {
    $contractById[[string]$case.id] = $case
}

$resultById = @{}
$failures = New-Object 'System.Collections.Generic.List[string]'
$routingWarnings = New-Object 'System.Collections.Generic.List[string]'
$policyDiagnostics = New-Object 'System.Collections.Generic.List[string]'
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
    $expectedReferences = @(Get-StringArray $case.expected_change_governance_references)
    $selectedReferences = @(Get-StringArray $result.selected_change_governance_references)
    $expectedBehaviors = @(Get-StringArray $case.expected_behavior_tags)
    $forbiddenBehaviors = @(Get-StringArray $case.forbidden_behavior_tags)
    $selectedBehaviors = @(Get-StringArray $result.behavior_tags)
    $strictRouting = $strictRoutingCaseIds -contains $id

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

    foreach ($reference in $expectedReferences) {
        if ($selectedReferences -notcontains $reference) {
            Add-Failure $failures "$id missed expected change-governance reference: $reference"
        }
    }
    if ($selectedReferences.Count -gt 0 -and $selectedSkills -notcontains "change-governance") {
        Add-Failure $failures "$id selected change-governance references without selecting the skill"
    }
    if ($strictRouting) {
        foreach ($reference in @($selectedReferences | Where-Object { $expectedReferences -notcontains $_ })) {
            Add-Failure $failures "$id selected an unspecified change-governance reference: $reference"
        }
    }

    foreach ($tag in $selectedBehaviors) {
        if ($allowedBehaviorTags -notcontains $tag) {
            Add-Failure $failures "$id selected an unknown behavior tag: $tag"
        }
    }
    foreach ($tag in $expectedBehaviors) {
        if ($selectedBehaviors -notcontains $tag) {
            Add-Failure $failures "$id missed expected behavior tag: $tag"
        }
    }
    foreach ($tag in $forbiddenBehaviors) {
        if ($selectedBehaviors -contains $tag) {
            Add-Failure $failures "$id selected forbidden behavior tag: $tag"
        }
    }

    $unexpectedBehaviors = @($selectedBehaviors | Where-Object { $expectedBehaviors -notcontains $_ -and $forbiddenBehaviors -notcontains $_ })
    foreach ($tag in $unexpectedBehaviors) {
        if ($FailOnUnexpectedSelections) {
            Add-Failure $failures "$id selected an unspecified behavior tag: $tag"
        }
        else {
            $policyDiagnostics.Add("$id selected an unspecified policy label: $tag")
        }
    }
}

if ($routingWarnings.Count -gt 0 -or $policyDiagnostics.Count -gt 0) {
    if ($ShowWarnings) {
        if ($routingWarnings.Count -gt 0) {
            Write-Warning ($routingWarnings -join [Environment]::NewLine)
        }
        if ($policyDiagnostics.Count -gt 0) {
            Write-Information ($policyDiagnostics -join [Environment]::NewLine) -InformationAction Continue
        }
    }
    else {
        if ($routingWarnings.Count -gt 0) {
            Write-Warning "Routing-policy evaluation recorded $($routingWarnings.Count) unspecified routing selections in non-strict cases. Use -ShowWarnings to list them or -FailOnUnexpectedSelections to make every unspecified selection blocking."
        }
        if ($policyDiagnostics.Count -gt 0) {
            Write-Verbose "Routing-policy evaluation recorded $($policyDiagnostics.Count) additional compatible policy labels. Use -ShowWarnings to list them."
        }
    }
}
if ($failures.Count -gt 0) {
    throw ("Routing-policy evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
}

Write-Output "Routing-policy evaluation valid: $($resultById.Count)/$($contractById.Count) cases satisfy the declared project-skill, peer-skill, reference, and policy-label constraints."
