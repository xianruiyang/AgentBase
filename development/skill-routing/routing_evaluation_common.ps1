$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")

function Get-AgentBaseRoutingResultSchemaVersion {
    return 4
}

function Get-AgentBaseSkillDescription {
    param(
        [string]$Content,
        [string]$SkillName
    )

    $match = [regex]::Match($Content, '(?m)^description:\s*(?<value>.+?)\s*$')
    if (-not $match.Success) {
        throw "Skill frontmatter is missing its description: $SkillName"
    }
    $value = $match.Groups["value"].Value.Trim()
    if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Get-AgentBaseRoutingCandidate {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
    $globalContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($globalPath, [Text.Encoding]::UTF8))
    $skills = @($Contract.required_skills | ForEach-Object {
        $skillName = [string]$_
        $skillPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $skillName) "SKILL.md"
        $skillContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($skillPath, [Text.Encoding]::UTF8))
        [pscustomobject][ordered]@{
            name = $skillName
            description = Get-AgentBaseSkillDescription -Content $skillContent -SkillName $skillName
        }
    })
    return [pscustomobject]@{
        global_content = $globalContent
        skills = $skills
        fingerprint = Get-AgentBaseRoutingCandidateFingerprint -GlobalContent $globalContent -SkillCatalog $skills
    }
}

function Get-AgentBasePolicyCandidate {
    param(
        [string]$ProjectRoot
    )

    $globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
    $globalContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($globalPath, [Text.Encoding]::UTF8))
    return [pscustomobject]@{
        global_content = $globalContent
        fingerprint = Get-AgentBasePolicyCandidateFingerprint -GlobalContent $globalContent
    }
}

function Get-AgentBaseReferenceSkillCandidate {
    param(
        [string]$ProjectRoot,
        [string]$SkillName
    )

    $skillPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $SkillName) "SKILL.md"
    $skillContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($skillPath, [Text.Encoding]::UTF8))
    return [pscustomobject][ordered]@{
        name = $SkillName
        logical_path = "skills/$SkillName/SKILL.md"
        content = $skillContent
        available_references = @([regex]::Matches($skillContent, '\]\(references/(?<name>[^)#]+\.md)(?:#[^)]+)?\)') | ForEach-Object {
            $_.Groups["name"].Value
        } | Sort-Object -Unique)
    }
}

function Get-AgentBaseReferenceUniverseFingerprint {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $candidates = @($Contract.reference_evaluation_skills | ForEach-Object {
        Get-AgentBaseReferenceSkillCandidate -ProjectRoot $ProjectRoot -SkillName ([string]$_)
    })
    return Get-AgentBaseReferenceCandidateFingerprint -SkillCandidates $candidates
}

function Complete-AgentBaseRoutingCapsule {
    param(
        [System.Collections.IDictionary]$Payload
    )

    $coreJson = $Payload | ConvertTo-Json -Depth 20
    $fingerprint = Get-AgentBaseRoutingSha256 (ConvertTo-AgentBaseCanonicalText $coreJson)
    $Payload.evaluation_capsule_sha256 = $fingerprint
    return [pscustomobject]@{
        payload = [pscustomobject]$Payload
        sha256 = $fingerprint
        candidate_bundle_sha256 = [string]$Payload.candidate_bundle_sha256
        evaluation_input_sha256 = [string]$Payload.evaluation_input_sha256
    }
}

function Get-AgentBaseRoutingEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $candidate = Get-AgentBaseRoutingCandidate -ProjectRoot $ProjectRoot -Contract $Contract
    $cases = @($Contract.cases | ForEach-Object {
        [pscustomobject][ordered]@{
            id = [string]$_.id
            request = [string]$_.request
            available_peer_skills = @(ConvertTo-AgentBaseStringArray $_.available_peer_skills)
        }
    })
    $peerSkills = @($Contract.peer_skills | ForEach-Object {
        [pscustomobject][ordered]@{
            name = [string]$_.name
            description = [string]$_.description
        }
    })
    $payload = [ordered]@{
        schema_version = Get-AgentBaseRoutingResultSchemaVersion
        evaluation_kind = "skill-routing"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        evaluator_protocol = Get-AgentBaseRoutingEvaluatorProtocol
        purpose = "Blind first-stage evaluation of AgentBase skill routing using only information available before a skill is loaded."
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = Get-AgentBaseRoutingInputFingerprint -Cases $cases -PeerSkills $peerSkills
        candidate = [ordered]@{
            global = [ordered]@{
                logical_path = "global/AGENTS.md"
                content = $candidate.global_content
            }
            skills = $candidate.skills
        }
        peer_skills = $peerSkills
        instructions = @(
            "Use only this detached capsule. Do not inspect repositories, tests, hidden expectations, or other files."
            "For every case, select only the project skills and available peer skills that must be loaded before task actions."
            "The skill catalog intentionally exposes descriptions only. Policy labels, post-selection skill bodies, and reference choices are intentionally unavailable in this stage."
            "Before returning, internally compare every case with every description's positive and explicit non-trigger boundaries; include every applicable skill and exclude skills that are only mentioned. Do not emit this check."
            "Do not execute requests or call tools. Return only the cases-only JSON object required by the enforced schema."
        )
        result_contract = [ordered]@{
            mode = "cases-only-v1"
            fields = @("id", "selected_skills", "selected_peer_skills")
            rationale = "omitted"
        }
        cases = $cases
    }
    return Complete-AgentBaseRoutingCapsule -Payload $payload
}

function Get-AgentBasePolicyEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $candidate = Get-AgentBasePolicyCandidate -ProjectRoot $ProjectRoot
    $cases = @($Contract.cases | ForEach-Object {
        [pscustomobject][ordered]@{
            id = [string]$_.id
            request = [string]$_.request
        }
    })
    $behaviorTags = @($Contract.allowed_behavior_tags | ForEach-Object {
        $tag = [string]$_
        [pscustomobject][ordered]@{
            tag = $tag
            description = [string]$Contract.behavior_tag_definitions.$tag
        }
    })
    $payload = [ordered]@{
        schema_version = Get-AgentBaseRoutingResultSchemaVersion
        evaluation_kind = "behavior-policy"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        evaluator_protocol = Get-AgentBaseRoutingEvaluatorProtocol
        purpose = "Blind evaluation of coarse AgentBase behavior policy, independent of skill-routing output."
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = Get-AgentBasePolicyInputFingerprint -Cases $cases -AllowedBehaviorTags @($Contract.allowed_behavior_tags) -BehaviorTagDefinitions $Contract.behavior_tag_definitions
        candidate = [ordered]@{
            global = [ordered]@{
                logical_path = "global/AGENTS.md"
                content = $candidate.global_content
            }
        }
        allowed_behavior_tags = @(ConvertTo-AgentBaseStringArray $Contract.allowed_behavior_tags)
        behavior_tag_definitions = $behaviorTags
        instructions = @(
            "Use only this detached capsule. Do not inspect repositories, tests, hidden expectations, other capsules, or results."
            "For every case, select all applicable coarse behavior tags using only the supplied definitions."
            "Before returning, internally check every case against every tag definition, including policies that govern a requested operation even when the request does not restate the policy. Do not emit this check."
            "Do not predict skill routing or skill references. Do not execute requests or call tools."
            "Return only the cases-only JSON object required by the enforced schema."
        )
        result_contract = [ordered]@{
            mode = "cases-only-v1"
            fields = @("id", "behavior_tags")
            rationale = "omitted"
        }
        cases = $cases
    }
    return Complete-AgentBaseRoutingCapsule -Payload $payload
}

function Get-AgentBaseReferenceEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $referenceSkills = @(ConvertTo-AgentBaseStringArray $Contract.reference_evaluation_skills)
    $routingById = @{}
    foreach ($routingCase in @($RoutingResults.cases)) {
        $routingById[[string]$routingCase.id] = $routingCase
    }
    $cases = @($Contract.cases | Where-Object {
        $routingCase = $routingById[[string]$_.id]
        $null -ne $routingCase -and @(ConvertTo-AgentBaseStringArray $routingCase.selected_skills | Where-Object {
            $referenceSkills -contains $_
        }).Count -gt 0
    } | ForEach-Object {
        $routingCase = $routingById[[string]$_.id]
        [pscustomobject][ordered]@{
            id = [string]$_.id
            request = [string]$_.request
            selected_reference_skills = @(ConvertTo-AgentBaseStringArray $routingCase.selected_skills | Where-Object {
                $referenceSkills -contains $_
            } | Sort-Object)
        }
    })
    $selectedSkillNames = @($cases.selected_reference_skills | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    $skillCandidates = @($selectedSkillNames | ForEach-Object {
        Get-AgentBaseReferenceSkillCandidate -ProjectRoot $ProjectRoot -SkillName $_
    })
    $selectionFingerprint = Get-AgentBaseRoutingReferenceSelectionFingerprint -RoutingResults $RoutingResults -ReferenceSkillNames $referenceSkills
    $payload = [ordered]@{
        schema_version = Get-AgentBaseRoutingResultSchemaVersion
        evaluation_kind = "routing-reference-policy"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        evaluator_protocol = Get-AgentBaseRoutingEvaluatorProtocol
        purpose = "Blind post-routing evaluation of conditional skill-reference selection for the selected reference-aware skills."
        candidate_bundle_sha256 = Get-AgentBaseReferenceCandidateFingerprint -SkillCandidates $skillCandidates
        evaluation_input_sha256 = Get-AgentBaseReferenceInputFingerprint -Cases $cases
        routing_reference_selection_sha256 = $selectionFingerprint
        candidate = [ordered]@{
            skills = $skillCandidates
        }
        instructions = @(
            "Use only this detached capsule. Do not inspect repositories, tests, hidden expectations, earlier capsules, or results."
            "For every case, select all references that must be read for each selected_reference_skill before task actions."
            "Before returning, internally compare every selected skill's routing rules with the case and include all applicable references without adding unselected skills. Do not emit this check."
            "Do not execute requests or call tools. Return only the cases-only JSON object required by the enforced schema."
        )
        result_contract = [ordered]@{
            mode = "cases-only-v1"
            fields = @("id", "selected_references")
            rationale = "omitted"
        }
        cases = $cases
    }
    return Complete-AgentBaseRoutingCapsule -Payload $payload
}

function Get-AgentBaseRoutingEvaluationGeneration {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    $policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    $referenceUniverse = Get-AgentBaseReferenceUniverseFingerprint -ProjectRoot $ProjectRoot -Contract $Contract
    return Get-AgentBaseRoutingGenerationFingerprint -RoutingCapsuleSha256 $routingCapsule.sha256 -PolicyCapsuleSha256 $policyCapsule.sha256 -ReferenceUniverseSha256 $referenceUniverse
}

function Get-AgentBaseRoutingOutputJsonSchema {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$Phase,
        [object]$Capsule
    )

    $caseIds = @($Capsule.payload.cases | ForEach-Object { [string]$_.id })
    $caseProperties = [ordered]@{
        id = [ordered]@{ type = "string"; enum = $caseIds }
    }
    $requiredFields = New-Object 'System.Collections.Generic.List[string]'
    $requiredFields.Add("id")
    switch ($Phase) {
        "Routing" {
            $skillNames = @($Capsule.payload.candidate.skills | ForEach-Object { [string]$_.name })
            $peerNames = @($Capsule.payload.peer_skills | ForEach-Object { [string]$_.name })
            $caseProperties.selected_skills = [ordered]@{
                type = "array"
                items = [ordered]@{ type = "string"; enum = $skillNames }
            }
            $caseProperties.selected_peer_skills = [ordered]@{
                type = "array"
                items = [ordered]@{ type = "string"; enum = $peerNames }
            }
            $requiredFields.Add("selected_skills")
            $requiredFields.Add("selected_peer_skills")
        }
        "Policy" {
            $caseProperties.behavior_tags = [ordered]@{
                type = "array"
                items = [ordered]@{ type = "string"; enum = @($Capsule.payload.allowed_behavior_tags) }
            }
            $requiredFields.Add("behavior_tags")
        }
        "References" {
            $skillNames = @($Capsule.payload.candidate.skills | ForEach-Object { [string]$_.name })
            $referenceNames = @($Capsule.payload.candidate.skills.available_references | ForEach-Object { [string]$_ } | Sort-Object -Unique)
            $caseProperties.selected_references = [ordered]@{
                type = "array"
                items = [ordered]@{
                    type = "object"
                    additionalProperties = $false
                    required = @("skill", "references")
                    properties = [ordered]@{
                        skill = [ordered]@{ type = "string"; enum = $skillNames }
                        references = [ordered]@{
                            type = "array"
                            items = [ordered]@{ type = "string"; enum = $referenceNames }
                        }
                    }
                }
            }
            $requiredFields.Add("selected_references")
        }
    }
    return [pscustomobject][ordered]@{
        type = "object"
        additionalProperties = $false
        required = @("cases")
        properties = [ordered]@{
            cases = [ordered]@{
                type = "array"
                items = [ordered]@{
                    type = "object"
                    additionalProperties = $false
                    required = @($requiredFields)
                    properties = $caseProperties
                }
            }
        }
    }
}

function New-AgentBaseRoutingResultEnvelope {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$Phase,
        [object]$Capsule,
        [object]$Evaluator,
        [object[]]$Cases
    )

    $result = [ordered]@{
        schema_version = Get-AgentBaseRoutingResultSchemaVersion
        evaluation_kind = [string]$Capsule.payload.evaluation_kind
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        evaluator = $Evaluator
        evaluation_capsule_sha256 = [string]$Capsule.sha256
        candidate_bundle_sha256 = [string]$Capsule.candidate_bundle_sha256
        evaluation_input_sha256 = [string]$Capsule.evaluation_input_sha256
    }
    if ($Phase -eq "References") {
        $result.routing_reference_selection_sha256 = [string]$Capsule.payload.routing_reference_selection_sha256
    }
    $result.cases = @($Cases)
    return [pscustomobject]$result
}

function Assert-AgentBaseDetachedEvaluator {
    param(
        [object]$Evaluator,
        [string]$Label
    )

    foreach ($field in @("id", "model", "runtime", "evaluated_at_utc", "isolation_mode")) {
        if ($null -eq $Evaluator -or [string]::IsNullOrWhiteSpace([string]$Evaluator.$field)) {
            throw "$Label evaluator is missing required field: $field"
        }
    }
    if ([string]$Evaluator.isolation_mode -ne "detached-capsule") {
        throw "$Label result was not produced from the detached capsule"
    }
    foreach ($field in @("repository_accessed", "hidden_expectations_accessed")) {
        if (-not ($Evaluator.PSObject.Properties.Name -contains $field) -or
            $Evaluator.$field.GetType().FullName -ne "System.Boolean" -or [bool]$Evaluator.$field) {
            throw "$Label evaluator has an invalid input attestation: $field"
        }
    }
    if ([string]$Evaluator.auth_mode -ne "read-only-hardlink") {
        throw "$Label evaluator has an invalid authentication isolation mode"
    }
    if ([string]$Evaluator.model_catalog_sha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "$Label evaluator is missing its sanitized model catalog identity"
    }
    $expectedDisabledFeatures = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    $actualDisabledFeatures = @(ConvertTo-AgentBaseStringArray $Evaluator.disabled_features)
    if ($actualDisabledFeatures.Count -ne $expectedDisabledFeatures.Count -or
        @($actualDisabledFeatures | Where-Object { $expectedDisabledFeatures -notcontains $_ }).Count -ne 0) {
        throw "$Label evaluator did not disable the required non-evaluation capabilities"
    }
    $evaluatedAt = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$Evaluator.evaluated_at_utc, [ref]$evaluatedAt) -or
        $evaluatedAt.Offset -ne [TimeSpan]::Zero -or $evaluatedAt -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
        throw "$Label evaluator timestamp must be a valid non-future UTC ISO-8601 value"
    }
}

function Assert-AgentBaseRoutingEvaluationResults {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults,
        [switch]$FailOnUnexpectedSelections,
        [switch]$ShowWarnings
    )

    if ([int]$RoutingResults.schema_version -ne (Get-AgentBaseRoutingResultSchemaVersion) -or
        [string]$RoutingResults.evaluation_kind -ne "skill-routing" -or
        [string]$RoutingResults.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
        throw "Unsupported skill-routing result schema, kind, or fingerprint schema"
    }
    $capsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    if ([string]$RoutingResults.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256 -or
        [string]$RoutingResults.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256 -or
        [string]$RoutingResults.evaluation_capsule_sha256 -ne $capsule.sha256) {
        throw "Skill-routing result belongs to a different visible candidate, input set, or detached capsule"
    }
    Assert-AgentBaseDetachedEvaluator -Evaluator $RoutingResults.evaluator -Label "Skill-routing"

    $requiredSkills = @(ConvertTo-AgentBaseStringArray $Contract.required_skills)
    $peerSkillNames = @($Contract.peer_skills | ForEach-Object { [string]$_.name })
    $strictCaseIds = @(ConvertTo-AgentBaseStringArray $Contract.strict_routing_case_ids)
    $contractById = @{}
    foreach ($case in @($Contract.cases)) {
        $contractById[[string]$case.id] = $case
    }
    $resultById = @{}
    $failures = New-Object 'System.Collections.Generic.List[string]'
    $diagnostics = New-Object 'System.Collections.Generic.List[string]'
    foreach ($result in @($RoutingResults.cases)) {
        $id = [string]$result.id
        if ([string]::IsNullOrWhiteSpace($id) -or $resultById.ContainsKey($id) -or -not $contractById.ContainsKey($id)) {
            $failures.Add("Invalid, duplicate, or unknown skill-routing result id: $id")
            continue
        }
        $resultById[$id] = $result
        foreach ($otherStageField in @("behavior_tags", "selected_references", "note")) {
            if ($result.PSObject.Properties.Name -contains $otherStageField) {
                $failures.Add("$id returned a forbidden field during skill-routing evaluation: $otherStageField")
            }
        }
    }
    foreach ($id in $contractById.Keys) {
        if (-not $resultById.ContainsKey($id)) {
            $failures.Add("Missing skill-routing result: $id")
            continue
        }
        $case = $contractById[$id]
        $result = $resultById[$id]
        $selectedSkills = @(ConvertTo-AgentBaseStringArray $result.selected_skills)
        $expectedSkills = @(ConvertTo-AgentBaseStringArray $case.expected_skills)
        $forbiddenSkills = @(ConvertTo-AgentBaseStringArray $case.forbidden_skills)
        $selectedPeers = @(ConvertTo-AgentBaseStringArray $result.selected_peer_skills)
        $availablePeers = @(ConvertTo-AgentBaseStringArray $case.available_peer_skills)
        $expectedPeers = @(ConvertTo-AgentBaseStringArray $case.expected_peer_skills)
        $forbiddenPeers = @(ConvertTo-AgentBaseStringArray $case.forbidden_peer_skills)
        if (@($selectedSkills | Sort-Object -Unique).Count -ne $selectedSkills.Count) {
            $failures.Add("$id returned duplicate selected skills")
        }
        if (@($selectedPeers | Sort-Object -Unique).Count -ne $selectedPeers.Count) {
            $failures.Add("$id returned duplicate selected peer skills")
        }
        foreach ($skill in $selectedSkills) {
            if ($requiredSkills -notcontains $skill) { $failures.Add("$id selected an unknown skill: $skill") }
        }
        foreach ($skill in $expectedSkills) {
            if ($selectedSkills -notcontains $skill) { $failures.Add("$id missed expected skill: $skill") }
        }
        foreach ($skill in $forbiddenSkills) {
            if ($selectedSkills -contains $skill) { $failures.Add("$id selected forbidden skill: $skill") }
        }
        foreach ($skill in @($selectedSkills | Where-Object { $expectedSkills -notcontains $_ -and $forbiddenSkills -notcontains $_ })) {
            $message = "$id selected an unspecified skill: $skill"
            if ($strictCaseIds -contains $id -or $FailOnUnexpectedSelections) { $failures.Add($message) } else { $diagnostics.Add($message) }
        }
        foreach ($peer in $selectedPeers) {
            if ($peerSkillNames -notcontains $peer -or $availablePeers -notcontains $peer) { $failures.Add("$id selected an unavailable peer skill: $peer") }
        }
        foreach ($peer in $expectedPeers) {
            if ($selectedPeers -notcontains $peer) { $failures.Add("$id missed expected peer skill: $peer") }
        }
        foreach ($peer in $forbiddenPeers) {
            if ($selectedPeers -contains $peer) { $failures.Add("$id selected forbidden peer skill: $peer") }
        }
        foreach ($peer in @($selectedPeers | Where-Object { $expectedPeers -notcontains $_ -and $forbiddenPeers -notcontains $_ })) {
            $message = "$id selected an unspecified peer skill: $peer"
            if ($strictCaseIds -contains $id -or $FailOnUnexpectedSelections) { $failures.Add($message) } else { $diagnostics.Add($message) }
        }
    }
    if ($failures.Count -gt 0) {
        throw ("Skill-routing evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
    }
    if ($diagnostics.Count -gt 0) {
        if ($ShowWarnings) {
            Write-Information ($diagnostics -join [Environment]::NewLine) -InformationAction Continue
        }
        else {
            Write-Verbose "Skill-routing evaluation recorded $($diagnostics.Count) compatible unspecified selections."
        }
    }
    return "Skill-routing evaluation valid: $($resultById.Count)/$($contractById.Count) cases."
}

function Assert-AgentBasePolicyEvaluationResults {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$PolicyResults,
        [switch]$FailOnUnexpectedSelections,
        [switch]$ShowWarnings
    )

    if ([int]$PolicyResults.schema_version -ne (Get-AgentBaseRoutingResultSchemaVersion) -or
        [string]$PolicyResults.evaluation_kind -ne "behavior-policy" -or
        [string]$PolicyResults.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
        throw "Unsupported behavior-policy result schema, kind, or fingerprint schema"
    }
    $capsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    if ([string]$PolicyResults.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256 -or
        [string]$PolicyResults.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256 -or
        [string]$PolicyResults.evaluation_capsule_sha256 -ne $capsule.sha256) {
        throw "Behavior-policy result belongs to a different visible candidate, input set, or detached capsule"
    }
    Assert-AgentBaseDetachedEvaluator -Evaluator $PolicyResults.evaluator -Label "Behavior-policy"

    $contractById = @{}
    foreach ($case in @($Contract.cases)) { $contractById[[string]$case.id] = $case }
    $allowedTags = @(ConvertTo-AgentBaseStringArray $Contract.allowed_behavior_tags)
    $resultById = @{}
    $failures = New-Object 'System.Collections.Generic.List[string]'
    $diagnostics = New-Object 'System.Collections.Generic.List[string]'
    foreach ($result in @($PolicyResults.cases)) {
        $id = [string]$result.id
        if ([string]::IsNullOrWhiteSpace($id) -or $resultById.ContainsKey($id) -or -not $contractById.ContainsKey($id)) {
            $failures.Add("Invalid, duplicate, or unknown behavior-policy result id: $id")
            continue
        }
        $resultById[$id] = $result
        foreach ($otherStageField in @("selected_skills", "selected_peer_skills", "selected_references", "note")) {
            if ($result.PSObject.Properties.Name -contains $otherStageField) {
                $failures.Add("$id returned a forbidden field during behavior-policy evaluation: $otherStageField")
            }
        }
    }
    foreach ($id in $contractById.Keys) {
        if (-not $resultById.ContainsKey($id)) {
            $failures.Add("Missing behavior-policy result: $id")
            continue
        }
        $selected = @(ConvertTo-AgentBaseStringArray $resultById[$id].behavior_tags)
        $expected = @(ConvertTo-AgentBaseStringArray $contractById[$id].expected_behavior_tags)
        $forbidden = @(ConvertTo-AgentBaseStringArray $contractById[$id].forbidden_behavior_tags)
        if (@($selected | Sort-Object -Unique).Count -ne $selected.Count) {
            $failures.Add("$id returned duplicate behavior tags")
        }
        foreach ($tag in $selected) {
            if ($allowedTags -notcontains $tag) { $failures.Add("$id selected an unknown behavior tag: $tag") }
        }
        foreach ($tag in $expected) {
            if ($selected -notcontains $tag) { $failures.Add("$id missed expected behavior tag: $tag") }
        }
        foreach ($tag in $forbidden) {
            if ($selected -contains $tag) { $failures.Add("$id selected forbidden behavior tag: $tag") }
        }
        foreach ($tag in @($selected | Where-Object { $expected -notcontains $_ -and $forbidden -notcontains $_ })) {
            if ($FailOnUnexpectedSelections) { $failures.Add("$id selected an unspecified behavior tag: $tag") } else { $diagnostics.Add("$id selected an unspecified behavior tag: $tag") }
        }
    }
    if ($failures.Count -gt 0) {
        throw ("Behavior-policy evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
    }
    if ($diagnostics.Count -gt 0) {
        if ($ShowWarnings) { Write-Information ($diagnostics -join [Environment]::NewLine) -InformationAction Continue } else { Write-Verbose "Behavior-policy evaluation recorded $($diagnostics.Count) compatible unspecified labels." }
    }
    return "Behavior-policy evaluation valid: $($resultById.Count)/$($contractById.Count) cases."
}

function Assert-AgentBaseReferenceEvaluationResults {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults,
        [object]$ReferenceResults
    )

    if ([int]$ReferenceResults.schema_version -ne (Get-AgentBaseRoutingResultSchemaVersion) -or
        [string]$ReferenceResults.evaluation_kind -ne "routing-reference-policy" -or
        [string]$ReferenceResults.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
        throw "Unsupported routing-reference result schema, kind, or fingerprint schema"
    }
    $capsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $RoutingResults
    if ([string]$ReferenceResults.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256 -or
        [string]$ReferenceResults.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256 -or
        [string]$ReferenceResults.evaluation_capsule_sha256 -ne $capsule.sha256 -or
        [string]$ReferenceResults.routing_reference_selection_sha256 -ne [string]$capsule.payload.routing_reference_selection_sha256) {
        throw "Routing-reference result belongs to a different selected skill body, input set, routing selection, or detached capsule"
    }
    Assert-AgentBaseDetachedEvaluator -Evaluator $ReferenceResults.evaluator -Label "Routing-reference"

    $contractById = @{}
    foreach ($case in @($Contract.cases)) { $contractById[[string]$case.id] = $case }
    $capsuleById = @{}
    foreach ($case in @($capsule.payload.cases)) { $capsuleById[[string]$case.id] = $case }
    $resultById = @{}
    $failures = New-Object 'System.Collections.Generic.List[string]'
    foreach ($result in @($ReferenceResults.cases)) {
        $id = [string]$result.id
        if ([string]::IsNullOrWhiteSpace($id) -or $resultById.ContainsKey($id) -or -not $capsuleById.ContainsKey($id)) {
            $failures.Add("Invalid, duplicate, or unselected routing-reference result id: $id")
            continue
        }
        $resultById[$id] = $result
        foreach ($otherStageField in @("selected_skills", "selected_peer_skills", "behavior_tags", "note")) {
            if ($result.PSObject.Properties.Name -contains $otherStageField) {
                $failures.Add("$id returned a forbidden field during routing-reference evaluation: $otherStageField")
            }
        }
    }
    foreach ($id in $capsuleById.Keys) {
        if (-not $resultById.ContainsKey($id)) {
            $failures.Add("Missing routing-reference result: $id")
            continue
        }
        $requiredSkills = @(ConvertTo-AgentBaseStringArray $capsuleById[$id].selected_reference_skills)
        $selectedBySkill = @{}
        foreach ($selection in @($resultById[$id].selected_references)) {
            $skillName = [string]$selection.skill
            if ([string]::IsNullOrWhiteSpace($skillName) -or $selectedBySkill.ContainsKey($skillName) -or $requiredSkills -notcontains $skillName) {
                $failures.Add("$id returned an invalid, duplicate, or unselected reference skill: $skillName")
                continue
            }
            $selectedBySkill[$skillName] = @(ConvertTo-AgentBaseStringArray $selection.references)
        }
        foreach ($skillName in $requiredSkills) {
            if (-not $selectedBySkill.ContainsKey($skillName)) {
                $failures.Add("$id is missing reference selection for skill: $skillName")
                continue
            }
            $candidate = @($capsule.payload.candidate.skills | Where-Object { [string]$_.name -eq $skillName })[0]
            $available = @(ConvertTo-AgentBaseStringArray $candidate.available_references)
            $selected = @($selectedBySkill[$skillName])
            if (@($selected | Sort-Object -Unique).Count -ne $selected.Count) {
                $failures.Add("$id returned duplicate $skillName references")
            }
            $expectedProperty = "expected_$($skillName.Replace('-', '_'))_references"
            $expected = @(ConvertTo-AgentBaseStringArray $contractById[$id].$expectedProperty)
            foreach ($reference in $selected) {
                if ($available -notcontains $reference) { $failures.Add("$id selected an unavailable $skillName reference: $reference") }
            }
            foreach ($reference in $expected) {
                if ($selected -notcontains $reference) { $failures.Add("$id missed expected $skillName reference: $reference") }
            }
            if (@($Contract.strict_reference_case_ids) -contains $id) {
                foreach ($reference in @($selected | Where-Object { $expected -notcontains $_ })) {
                    $failures.Add("$id selected an unspecified $skillName reference: $reference")
                }
            }
        }
    }
    if ($failures.Count -gt 0) {
        throw ("Routing-reference evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
    }
    return "Routing-reference evaluation valid: $($resultById.Count)/$($capsuleById.Count) selected cases."
}

function Test-AgentBaseStageIdentity {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$Phase,
        [object]$Results,
        [object]$Capsule
    )

    if ($null -eq $Results -or [int]$Results.schema_version -ne (Get-AgentBaseRoutingResultSchemaVersion) -or
        [string]$Results.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema) -or
        [string]$Results.evaluation_kind -ne [string]$Capsule.payload.evaluation_kind -or
        [string]$Results.candidate_bundle_sha256 -ne [string]$Capsule.candidate_bundle_sha256 -or
        [string]$Results.evaluation_input_sha256 -ne [string]$Capsule.evaluation_input_sha256 -or
        [string]$Results.evaluation_capsule_sha256 -ne [string]$Capsule.sha256) {
        return $false
    }
    if ($Phase -eq "References" -and
        [string]$Results.routing_reference_selection_sha256 -ne [string]$Capsule.payload.routing_reference_selection_sha256) {
        return $false
    }
    return $true
}

function Get-AgentBaseStagePlanDecision {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$Phase,
        [object]$SourceResults,
        [object]$Capsule,
        [scriptblock]$Validate
    )

    if ($null -eq $SourceResults) {
        return [pscustomobject]@{ action = "evaluate"; reason = "missing_evidence"; detail = $null }
    }
    if (-not (Test-AgentBaseStageIdentity -Phase $Phase -Results $SourceResults -Capsule $Capsule)) {
        return [pscustomobject]@{ action = "evaluate"; reason = "visible_identity_changed"; detail = $null }
    }
    try {
        & $Validate | Out-Null
        return [pscustomobject]@{ action = "reuse"; reason = "visible_identity_and_oracle_valid"; detail = $null }
    }
    catch {
        $message = $_.Exception.Message
        if ($message -match 'evaluation failed with \d+ violation') {
            return [pscustomobject]@{ action = "blocked"; reason = "oracle_changed_without_visible_input_change"; detail = $message }
        }
        return [pscustomobject]@{ action = "evaluate"; reason = "invalid_evidence_envelope"; detail = $message }
    }
}

function Get-AgentBaseRoutingEvaluationPlan {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$SourceEvidence,
        [object]$RoutingResultsForReferences
    )

    $routingCapsule = Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    $policyCapsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract
    $generation = Get-AgentBaseRoutingEvaluationGeneration -ProjectRoot $ProjectRoot -Contract $Contract
    $sourceRouting = if ($null -eq $SourceEvidence) { $null } else { $SourceEvidence }
    $sourcePolicy = if ($null -eq $SourceEvidence) { $null } else { $SourceEvidence.policy_evaluation }
    $sourceReferences = if ($null -eq $SourceEvidence) { $null } else { $SourceEvidence.reference_evaluation }
    $routingDecision = Get-AgentBaseStagePlanDecision -Phase Routing -SourceResults $sourceRouting -Capsule $routingCapsule -Validate {
        Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $sourceRouting
    }
    $policyDecision = Get-AgentBaseStagePlanDecision -Phase Policy -SourceResults $sourcePolicy -Capsule $policyCapsule -Validate {
        Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $Contract -PolicyResults $sourcePolicy
    }

    $referenceCapsule = $null
    $referenceDecision = $null
    $referenceRouting = $RoutingResultsForReferences
    if ($null -eq $referenceRouting -and $routingDecision.action -eq "reuse") {
        $referenceRouting = $sourceRouting
    }
    if ($null -eq $referenceRouting) {
        $referenceDecision = [pscustomobject]@{
            action = if ($routingDecision.action -eq "blocked") { "blocked" } else { "pending-routing" }
            reason = if ($routingDecision.action -eq "blocked") { "routing_blocked" } else { "routing_result_required" }
            detail = $null
        }
    }
    else {
        Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $referenceRouting | Out-Null
        $referenceCapsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $referenceRouting
        $referenceDecision = Get-AgentBaseStagePlanDecision -Phase References -SourceResults $sourceReferences -Capsule $referenceCapsule -Validate {
            Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $referenceRouting -ReferenceResults $sourceReferences
        }
    }
    $phases = [ordered]@{
        Routing = [pscustomobject][ordered]@{
            action = [string]$routingDecision.action
            reason = [string]$routingDecision.reason
            detail = $routingDecision.detail
            capsule_sha256 = [string]$routingCapsule.sha256
            candidate_bundle_sha256 = [string]$routingCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$routingCapsule.evaluation_input_sha256
        }
        Policy = [pscustomobject][ordered]@{
            action = [string]$policyDecision.action
            reason = [string]$policyDecision.reason
            detail = $policyDecision.detail
            capsule_sha256 = [string]$policyCapsule.sha256
            candidate_bundle_sha256 = [string]$policyCapsule.candidate_bundle_sha256
            evaluation_input_sha256 = [string]$policyCapsule.evaluation_input_sha256
        }
        References = [pscustomobject][ordered]@{
            action = [string]$referenceDecision.action
            reason = [string]$referenceDecision.reason
            detail = $referenceDecision.detail
            capsule_sha256 = if ($null -eq $referenceCapsule) { $null } else { [string]$referenceCapsule.sha256 }
            candidate_bundle_sha256 = if ($null -eq $referenceCapsule) { $null } else { [string]$referenceCapsule.candidate_bundle_sha256 }
            evaluation_input_sha256 = if ($null -eq $referenceCapsule) { $null } else { [string]$referenceCapsule.evaluation_input_sha256 }
            routing_reference_selection_sha256 = if ($null -eq $referenceCapsule) { $null } else { [string]$referenceCapsule.payload.routing_reference_selection_sha256 }
        }
    }
    $actions = @($phases.Values | ForEach-Object { [string]$_.action })
    return [pscustomobject][ordered]@{
        schema_version = 1
        evaluation_generation_sha256 = $generation
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        evaluator_protocol = Get-AgentBaseRoutingEvaluatorProtocol
        phases = [pscustomobject]$phases
        parallel_first_wave = @(@("Routing", "Policy") | Where-Object { [string]$phases.$_.action -eq "evaluate" })
        evaluation_count = @($actions | Where-Object { $_ -eq "evaluate" }).Count
        reuse_count = @($actions | Where-Object { $_ -eq "reuse" }).Count
        blocked_count = @($actions | Where-Object { $_ -eq "blocked" }).Count
        pending_count = @($actions | Where-Object { $_ -eq "pending-routing" }).Count
    }
}
