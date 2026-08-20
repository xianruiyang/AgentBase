$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

function New-TestEvaluator {
    param(
        [string]$Id
    )

    return [pscustomobject][ordered]@{
        id = $Id
        model = "test-model"
        runtime = "test/windows/read-only/ephemeral"
        evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        isolation_mode = "detached-capsule"
        repository_accessed = $false
        hidden_expectations_accessed = $false
        auth_mode = "read-only-hardlink"
        model_catalog_sha256 = ('A' * 64)
        disabled_features = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    }
}

$routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
$routingRaw = $routingCapsule.payload | ConvertTo-Json -Depth 20
if ([int]$routingCapsule.payload.schema_version -ne 4 -or [string]$routingCapsule.payload.evaluation_kind -ne "skill-routing") {
    throw "Routing capsule has the wrong schema or kind"
}
foreach ($skill in @($routingCapsule.payload.candidate.skills)) {
    $unexpected = @($skill.PSObject.Properties.Name | Where-Object { @("name", "description") -notcontains $_ })
    if ($unexpected.Count -gt 0 -or [string]::IsNullOrWhiteSpace([string]$skill.description)) {
        throw "Routing capsule exposes more than a skill description: $($skill.name)"
    }
}
if ($routingRaw.Contains('agents/openai.yaml') -or $routingRaw.Contains('expected_skills') -or $routingRaw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Routing capsule leaks metadata, hidden expectations, or the repository path"
}
if ([string]$routingCapsule.payload.result_contract.mode -ne "cases-only-v1" -or $routingRaw.Contains('"note"')) {
    throw "Routing capsule still requests redundant rationales or evaluator envelopes"
}
if (-not $routingRaw.Contains('internally compare every case') -or -not $routingRaw.Contains('Do not emit this check')) {
    throw "Routing capsule does not require a private completeness check before cases-only output"
}
$routingSchema = Get-AgentBaseRoutingOutputJsonSchema -Phase Routing -Capsule $routingCapsule
$routingSchemaJson = $routingSchema | ConvertTo-Json -Depth 30 | ConvertFrom-Json -Depth 30
$routingSchemaProperties = @($routingSchemaJson.properties.PSObject.Properties.Name)
if ($routingSchemaProperties.Count -ne 1 -or $routingSchemaProperties[0] -ne "cases") {
    throw "Routing model output schema is not cases-only"
}
$routingSchemaText = $routingSchema | ConvertTo-Json -Depth 30
if ($routingSchemaText.Contains('"uniqueItems"') -or $routingSchemaText.Contains('"minItems"') -or $routingSchemaText.Contains('"maxItems"')) {
    throw "Routing model output schema uses an array keyword unsupported by the Responses structured-output subset"
}

$routingCases = @($contract.cases | ForEach-Object {
    [pscustomobject][ordered]@{
        id = [string]$_.id
        selected_skills = @(ConvertTo-AgentBaseStringArray $_.expected_skills)
        selected_peer_skills = @(ConvertTo-AgentBaseStringArray $_.expected_peer_skills)
    }
})
$routingResults = New-AgentBaseRoutingResultEnvelope -Phase Routing -Capsule $routingCapsule -Evaluator (New-TestEvaluator "routing-capsule-test") -Cases $routingCases
Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults | Out-Null
$duplicateRouting = $routingResults | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100 -DateKind String
$duplicateRoutingCase = @($duplicateRouting.cases | Where-Object { @($_.selected_skills).Count -gt 0 })[0]
$duplicateRoutingCase.selected_skills = @($duplicateRoutingCase.selected_skills) + [string]$duplicateRoutingCase.selected_skills[0]
$duplicateRoutingRejected = $false
try {
    Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $projectRoot -Contract $contract -RoutingResults $duplicateRouting | Out-Null
}
catch {
    $duplicateRoutingRejected = $_.Exception.Message.Contains('duplicate selected skills')
}
if (-not $duplicateRoutingRejected) { throw "Local routing validation accepted a duplicate selection" }

$policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract
$policyRaw = $policyCapsule.payload | ConvertTo-Json -Depth 20
if ($policyRaw.Contains('selected_skills') -or $policyRaw.Contains('routing_result_sha256') -or $policyRaw.Contains('routing_evaluation_capsule_sha256')) {
    throw "Policy capsule remains coupled to routing output"
}
if (@($policyCapsule.payload.behavior_tag_definitions).Count -ne @($policyCapsule.payload.allowed_behavior_tags).Count) {
    throw "Policy capsule does not define every allowed behavior tag"
}
if (-not $policyRaw.Contains('internally check every case against every tag definition') -or -not $policyRaw.Contains('Do not emit this check')) {
    throw "Policy capsule does not require a private completeness check before cases-only output"
}
$policyCases = @($contract.cases | ForEach-Object {
    [pscustomobject][ordered]@{
        id = [string]$_.id
        behavior_tags = @(ConvertTo-AgentBaseStringArray $_.expected_behavior_tags)
    }
})
$policyResults = New-AgentBaseRoutingResultEnvelope -Phase Policy -Capsule $policyCapsule -Evaluator (New-TestEvaluator "policy-capsule-test") -Cases $policyCases
Assert-AgentBasePolicyEvaluationResults -ProjectRoot $projectRoot -Contract $contract -PolicyResults $policyResults | Out-Null
$policySchemaJson = Get-AgentBaseRoutingOutputJsonSchema -Phase Policy -Capsule $policyCapsule | ConvertTo-Json -Depth 30
if ($policySchemaJson.Contains('"uniqueItems"') -or $policySchemaJson.Contains('"minItems"') -or $policySchemaJson.Contains('"maxItems"')) {
    throw "Policy model output schema uses an array keyword unsupported by the Responses structured-output subset"
}
$duplicatePolicy = $policyResults | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100 -DateKind String
$duplicatePolicyCase = @($duplicatePolicy.cases | Where-Object { @($_.behavior_tags).Count -gt 0 })[0]
$duplicatePolicyCase.behavior_tags = @($duplicatePolicyCase.behavior_tags) + [string]$duplicatePolicyCase.behavior_tags[0]
$duplicatePolicyRejected = $false
try {
    Assert-AgentBasePolicyEvaluationResults -ProjectRoot $projectRoot -Contract $contract -PolicyResults $duplicatePolicy | Out-Null
}
catch {
    $duplicatePolicyRejected = $_.Exception.Message.Contains('duplicate behavior tags')
}
if (-not $duplicatePolicyRejected) { throw "Local policy validation accepted a duplicate tag" }

$referenceCapsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults
$referenceRaw = $referenceCapsule.payload | ConvertTo-Json -Depth 20
$selectedReferenceSkillNames = @($referenceCapsule.payload.cases.selected_reference_skills | ForEach-Object { [string]$_ } | Sort-Object -Unique)
$candidateReferenceSkillNames = @($referenceCapsule.payload.candidate.skills | ForEach-Object { [string]$_.name } | Sort-Object -Unique)
if (($selectedReferenceSkillNames -join '|') -ne ($candidateReferenceSkillNames -join '|')) {
    throw "Reference capsule exposes skill bodies that were not selected by routing"
}
if ($referenceRaw.Contains('routing_result_sha256') -or $referenceRaw.Contains('routing_evaluation_capsule_sha256') -or
    -not $referenceRaw.Contains('routing_reference_selection_sha256')) {
    throw "Reference capsule binds a full routing result instead of the relevant selection projection"
}
if ($referenceRaw.Contains('expected_change_governance_references') -or $referenceRaw.Contains('strict_reference_case_ids') -or
    $referenceRaw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Reference capsule leaks hidden expectations or the repository path"
}
if (-not $referenceRaw.Contains("internally compare every selected skill's routing rules") -or -not $referenceRaw.Contains('Do not emit this check')) {
    throw "Reference capsule does not require a private completeness check before cases-only output"
}
$contractById = @{}
foreach ($case in @($contract.cases)) { $contractById[[string]$case.id] = $case }
$referenceCases = @($referenceCapsule.payload.cases | ForEach-Object {
    $capsuleCase = $_
    $contractCase = $contractById[[string]$capsuleCase.id]
    [pscustomobject][ordered]@{
        id = [string]$capsuleCase.id
        selected_references = @($capsuleCase.selected_reference_skills | ForEach-Object {
            $skillName = [string]$_
            $expectedProperty = "expected_$($skillName.Replace('-', '_'))_references"
            [pscustomobject][ordered]@{
                skill = $skillName
                references = @(ConvertTo-AgentBaseStringArray $contractCase.$expectedProperty)
            }
        })
    }
})
$referenceResults = New-AgentBaseRoutingResultEnvelope -Phase References -Capsule $referenceCapsule -Evaluator (New-TestEvaluator "references-capsule-test") -Cases $referenceCases
Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults -ReferenceResults $referenceResults | Out-Null
$referenceSchemaJson = Get-AgentBaseRoutingOutputJsonSchema -Phase References -Capsule $referenceCapsule | ConvertTo-Json -Depth 30
if ($referenceSchemaJson.Contains('"uniqueItems"') -or $referenceSchemaJson.Contains('"minItems"') -or $referenceSchemaJson.Contains('"maxItems"')) {
    throw "Reference model output schema uses an array keyword unsupported by the Responses structured-output subset"
}
$duplicateReferences = $referenceResults | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100 -DateKind String
$duplicateReferenceSelection = @($duplicateReferences.cases.selected_references | Where-Object { @($_.references).Count -gt 0 })[0]
$duplicateReferenceSelection.references = @($duplicateReferenceSelection.references) + [string]$duplicateReferenceSelection.references[0]
$duplicateReferencesRejected = $false
try {
    Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults -ReferenceResults $duplicateReferences | Out-Null
}
catch {
    $duplicateReferencesRejected = $_.Exception.Message.Contains('duplicate') -and $_.Exception.Message.Contains('references')
}
if (-not $duplicateReferencesRejected) { throw "Local reference validation accepted a duplicate reference" }

$generation = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $projectRoot -Contract $contract
if ($generation -notmatch '^[0-9A-F]{64}$') {
    throw "Evaluation generation is not a stable SHA-256 identity"
}

Write-Output "Routing capsule tests passed: phase inputs are minimal, Policy is independent, References bind only selected skill bodies and routing selections, schemas use the supported cases-only subset, local uniqueness is enforced, and all hidden oracles remain detached."
