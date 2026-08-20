$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-routing-plan-{0}" -f [guid]::NewGuid().ToString('N'))
$utf8NoBom = [Text.UTF8Encoding]::new($false)

function Write-TestText {
    param(
        [string]$Path,
        [string]$Text
    )

    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

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

try {
    $globalPath = Join-Path $testRoot "global\AGENTS.md"
    $plainSkillPath = Join-Path $testRoot "skills\plain-skill\SKILL.md"
    $referenceSkillPath = Join-Path $testRoot "skills\ref-skill\SKILL.md"
    $globalText = "must: follow the applicable skill descriptions`n"
    $plainText = "---`nname: plain-skill`ndescription: Use for plain requests.`n---`n`n# Plain`n`nBody version one.`n"
    $referenceText = "---`nname: ref-skill`ndescription: Use for reference-aware requests.`n---`n`n# Reference`n`nRead [details](references/details.md) when details are needed.`n"
    Write-TestText -Path $globalPath -Text $globalText
    Write-TestText -Path $plainSkillPath -Text $plainText
    Write-TestText -Path $referenceSkillPath -Text $referenceText

    $contract = [pscustomobject][ordered]@{
        required_skills = @("plain-skill", "ref-skill")
        reference_evaluation_skills = @("ref-skill")
        peer_skills = @()
        allowed_behavior_tags = @("read_only")
        behavior_tag_definitions = [pscustomobject]@{ read_only = "The request changes no state." }
        strict_routing_case_ids = @("case-1")
        strict_reference_case_ids = @("case-1")
        cases = @([pscustomobject][ordered]@{
            id = "case-1"
            request = "Inspect the reference-aware contract."
            available_peer_skills = @()
            expected_skills = @("ref-skill")
            forbidden_skills = @()
            expected_peer_skills = @()
            forbidden_peer_skills = @()
            expected_behavior_tags = @("read_only")
            forbidden_behavior_tags = @()
            expected_ref_skill_references = @("details.md")
        })
    }
    $routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $testRoot -Contract $contract
    $policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $testRoot -Contract $contract
    $routing = New-AgentBaseRoutingResultEnvelope -Phase Routing -Capsule $routingCapsule -Evaluator (New-TestEvaluator "plan-routing") -Cases @(
        [pscustomobject]@{ id = "case-1"; selected_skills = @("ref-skill"); selected_peer_skills = @() }
    )
    $policy = New-AgentBaseRoutingResultEnvelope -Phase Policy -Capsule $policyCapsule -Evaluator (New-TestEvaluator "plan-policy") -Cases @(
        [pscustomobject]@{ id = "case-1"; behavior_tags = @("read_only") }
    )
    $referenceCapsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $testRoot -Contract $contract -RoutingResults $routing
    $references = New-AgentBaseRoutingResultEnvelope -Phase References -Capsule $referenceCapsule -Evaluator (New-TestEvaluator "plan-references") -Cases @(
        [pscustomobject]@{ id = "case-1"; selected_references = @([pscustomobject]@{ skill = "ref-skill"; references = @("details.md") }) }
    )
    $routing | Add-Member -NotePropertyName receipt_id -NotePropertyValue ('1' * 32)
    $policy | Add-Member -NotePropertyName receipt_id -NotePropertyValue ('2' * 32)
    $references | Add-Member -NotePropertyName receipt_id -NotePropertyValue ('3' * 32)
    $routing | Add-Member -NotePropertyName evaluation_generation_sha256 -NotePropertyValue (Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $testRoot -Contract $contract)
    $routing | Add-Member -NotePropertyName policy_evaluation -NotePropertyValue $policy
    $routing | Add-Member -NotePropertyName reference_evaluation -NotePropertyValue $references

    $baseline = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $testRoot -Contract $contract -SourceEvidence $routing
    if (@($baseline.phases.PSObject.Properties.Value | Where-Object { [string]$_.action -ne "reuse" }).Count -ne 0) {
        throw "Unchanged phase-visible evidence was not fully reused"
    }
    $baselineGeneration = [string]$baseline.evaluation_generation_sha256

    Write-TestText -Path $plainSkillPath -Text ($plainText + "Body-only change outside the description.`n")
    $plainBodyPlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $testRoot -Contract $contract -SourceEvidence $routing
    if ([string]$plainBodyPlan.evaluation_generation_sha256 -ne $baselineGeneration -or
        @($plainBodyPlan.phases.PSObject.Properties.Value | Where-Object { [string]$_.action -ne "reuse" }).Count -ne 0) {
        throw "A non-reference skill body change invalidated an invisible evaluation phase"
    }

    Write-TestText -Path $referenceSkillPath -Text ($referenceText + "Selected reference behavior changed.`n")
    $referenceBodyPlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $testRoot -Contract $contract -SourceEvidence $routing
    if ([string]$referenceBodyPlan.phases.Routing.action -ne "reuse" -or
        [string]$referenceBodyPlan.phases.Policy.action -ne "reuse" -or
        [string]$referenceBodyPlan.phases.References.action -ne "evaluate") {
        throw "A selected reference skill body change did not invalidate References only"
    }

    Write-TestText -Path $plainSkillPath -Text $plainText
    Write-TestText -Path $referenceSkillPath -Text $referenceText
    Write-TestText -Path $globalPath -Text ($globalText + "must: apply one more global rule`n")
    $globalPlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $testRoot -Contract $contract -SourceEvidence $routing
    if ([string]$globalPlan.phases.Routing.action -ne "evaluate" -or
        [string]$globalPlan.phases.Policy.action -ne "evaluate" -or
        [string]$globalPlan.phases.References.action -ne "pending-routing" -or
        @($globalPlan.parallel_first_wave).Count -ne 2) {
        throw "A global rule change did not schedule Routing and Policy in parallel before References"
    }

    Write-TestText -Path $globalPath -Text $globalText
    $changedOracle = $contract | ConvertTo-Json -Depth 20 | ConvertFrom-Json -Depth 20
    $changedOracle.cases[0].expected_skills = @("plain-skill", "ref-skill")
    $oraclePlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $testRoot -Contract $changedOracle -SourceEvidence $routing
    if ([string]$oraclePlan.phases.Routing.action -ne "blocked" -or
        [string]$oraclePlan.phases.Routing.reason -ne "oracle_changed_without_visible_input_change") {
        throw "A hidden-oracle-only change incorrectly requested another evaluator sample"
    }

    Write-Output "Routing evaluation plan tests passed: unchanged and non-reference body changes cost zero runs, reference bodies invalidate References only, global rules parallelize Routing and Policy, and oracle-only drift blocks reruns."
}
finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $approvedBase = $tempBase.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($approvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $resolved).StartsWith('AgentBase-routing-plan-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
