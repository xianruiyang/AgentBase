$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$testRoot = Join-Path $tempBase ("AgentBase-routing-capsule-" + [guid]::NewGuid().ToString("N"))
$outputPath = Join-Path $testRoot "capsule.json"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $receipt = & (Join-Path $PSScriptRoot "build_routing_evaluation.ps1") -ProjectRoot $projectRoot -OutputPath $outputPath
    $raw = Get-Content -LiteralPath $outputPath -Raw -Encoding UTF8
    $capsule = $raw | ConvertFrom-Json -Depth 100

    if ([int]$capsule.schema_version -ne 3 -or [string]$capsule.evaluation_kind -ne "skill-routing") {
        throw "Detached capsule has the wrong schema or evaluation kind"
    }
    if ([string]$capsule.evaluation_capsule_sha256 -ne [string]$receipt.evaluation_capsule_sha256) {
        throw "Detached capsule receipt does not match its embedded identity"
    }
    if ([string]::IsNullOrWhiteSpace([string]$capsule.candidate.global.content) -or @($capsule.candidate.skills).Count -eq 0) {
        throw "Detached capsule does not embed the routing candidate"
    }
    foreach ($skill in @($capsule.candidate.skills)) {
        $unexpectedProperties = @($skill.PSObject.Properties.Name | Where-Object { @("name", "description") -notcontains $_ })
        if ($unexpectedProperties.Count -gt 0 -or [string]::IsNullOrWhiteSpace([string]$skill.description)) {
            throw "First-stage routing capsule exposes more than the skill description: $($skill.name)"
        }
    }
    if ($raw.Contains('"skill"') -or $raw.Contains('"metadata"')) {
        throw "First-stage routing capsule embeds post-selection skill or metadata content"
    }
    foreach ($postRoutingField in @("allowed_behavior_tags", "behavior_tag_definitions")) {
        if ($capsule.PSObject.Properties.Name -contains $postRoutingField -or $raw.Contains(('"' + $postRoutingField + '"'))) {
            throw "First-stage routing capsule exposes post-routing policy input: $postRoutingField"
        }
    }
    if ($raw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Detached capsule leaks the source repository path"
    }
    foreach ($case in @($capsule.cases)) {
        $unexpectedProperties = @($case.PSObject.Properties.Name | Where-Object { @("id", "request", "available_peer_skills") -notcontains $_ })
        if ($unexpectedProperties.Count -gt 0) {
            throw "Detached capsule leaks hidden case fields for $($case.id): $($unexpectedProperties -join ', ')"
        }
    }
    foreach ($hiddenField in @("expected_skills", "forbidden_skills", "expected_behavior_tags", "forbidden_behavior_tags", "strict_routing_case_ids")) {
        if ($capsule.PSObject.Properties.Name -contains $hiddenField) {
            throw "Detached capsule exposes hidden top-level field: $hiddenField"
        }
    }
    if ([string]$capsule.output_schema.evaluator.isolation_mode -ne "detached-capsule") {
        throw "Detached capsule output schema does not require isolation metadata"
    }
    if ([bool]$capsule.output_schema.evaluator.repository_accessed -or [bool]$capsule.output_schema.evaluator.hidden_expectations_accessed) {
        throw "Detached capsule output schema does not require a clean input attestation"
    }
    $offsetUtcEvaluator = [pscustomobject]@{
        id = "offset-utc-test"
        model = "test-model"
        runtime = "test-runtime"
        evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        isolation_mode = "detached-capsule"
        repository_accessed = $false
        hidden_expectations_accessed = $false
    }
    Assert-AgentBaseDetachedEvaluator -Evaluator $offsetUtcEvaluator -Label "Test"

    $contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $referenceCases = @($contract.cases | Where-Object {
        @($_.expected_skills | ForEach-Object { [string]$_ }) -contains "change-governance"
    })
    if ($referenceCases.Count -eq 0) {
        throw "Routing contract does not provide a change-governance case for the reference-stage capsule test"
    }
    $routingCases = @($contract.cases | ForEach-Object {
        [pscustomobject]@{
            id = [string]$_.id
            selected_skills = @($_.expected_skills | ForEach-Object { [string]$_ })
            selected_peer_skills = @($_.expected_peer_skills | ForEach-Object { [string]$_ })
        }
    })
    $routingResults = [pscustomobject]@{
        evaluation_capsule_sha256 = [string]$capsule.evaluation_capsule_sha256
        cases = $routingCases
    }
    $policyCapsuleResult = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults
    $policyCapsule = $policyCapsuleResult.payload
    $policyRaw = $policyCapsule | ConvertTo-Json -Depth 12
    if ([string]$policyCapsule.evaluation_kind -ne "behavior-policy" -or @($policyCapsule.cases).Count -ne @($contract.cases).Count) {
        throw "Policy-stage capsule has the wrong kind or case set"
    }
    if ([string]$policyCapsule.routing_evaluation_capsule_sha256 -ne [string]$capsule.evaluation_capsule_sha256) {
        throw "Policy-stage capsule is not bound to the first-stage capsule"
    }
    if ([string]$policyCapsule.routing_result_sha256 -ne (Get-AgentBaseRoutingResultFingerprint -RoutingResults $routingResults)) {
        throw "Policy-stage capsule is not bound to the first-stage result"
    }
    if (@($policyCapsule.behavior_tag_definitions).Count -ne @($policyCapsule.allowed_behavior_tags).Count) {
        throw "Policy-stage capsule does not define every allowed behavior tag"
    }
    if ($policyCapsule.candidate.PSObject.Properties.Name -contains "selected_skills" -or $policyRaw.Contains('"selected_skills"') -or $policyRaw.Contains('"selected_peer_skills"')) {
        throw "Policy-stage capsule exposes first-stage selections or post-selection skill bodies"
    }
    foreach ($hiddenField in @("expected_behavior_tags", "forbidden_behavior_tags", "strict_routing_case_ids")) {
        if ($policyRaw.Contains(('"' + $hiddenField + '"'))) {
            throw "Policy-stage capsule exposes hidden field: $hiddenField"
        }
    }
    if ($policyRaw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Policy-stage capsule leaks the source repository path"
    }

    $referenceCapsuleResult = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $projectRoot -Contract $contract -RoutingResults $routingResults
    $referenceCapsule = $referenceCapsuleResult.payload
    $referenceRaw = $referenceCapsule | ConvertTo-Json -Depth 12
    if ([string]$referenceCapsule.evaluation_kind -ne "routing-reference-policy" -or @($referenceCapsule.cases).Count -ne $referenceCases.Count) {
        throw "Reference-stage capsule has the wrong kind or selected case set"
    }
    if ([string]$referenceCapsule.routing_evaluation_capsule_sha256 -ne [string]$capsule.evaluation_capsule_sha256) {
        throw "Reference-stage capsule is not bound to the first-stage capsule"
    }
    if ([string]$referenceCapsule.routing_result_sha256 -ne (Get-AgentBaseRoutingResultFingerprint -RoutingResults $routingResults)) {
        throw "Reference-stage capsule is not bound to the first-stage result"
    }
    if ([string]$referenceCapsule.candidate.skill.name -ne "change-governance" -or [string]::IsNullOrWhiteSpace([string]$referenceCapsule.candidate.skill.content)) {
        throw "Reference-stage capsule does not expose the selected change-governance skill"
    }
    if ($referenceCapsule.candidate.PSObject.Properties.Name -contains "global" -or $referenceCapsule.candidate.PSObject.Properties.Name -contains "skills") {
        throw "Reference-stage capsule exposes first-stage candidate content"
    }
    foreach ($hiddenField in @("expected_skills", "expected_change_governance_references", "strict_routing_case_ids")) {
        if ($referenceRaw.Contains(('"' + $hiddenField + '"'))) {
            throw "Reference-stage capsule exposes hidden field: $hiddenField"
        }
    }
    if ($referenceRaw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Reference-stage capsule leaks the source repository path"
    }

    Write-Output "Routing capsule tests passed: routing exposes descriptions without policy hints, policy and reference stages expose only their post-routing inputs, every stage hides expectations and repository paths, and identities are bound."
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $resolvedTestRoot).StartsWith("AgentBase-routing-capsule-", [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolvedTestRoot"
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
