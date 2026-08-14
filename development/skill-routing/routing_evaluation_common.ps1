$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")

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
    $candidateFiles = @($globalPath)
    $skillCatalog = @($Contract.required_skills | ForEach-Object {
        $skillName = [string]$_
        $skillPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $skillName) "SKILL.md"
        $metadataPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $skillName) "agents\openai.yaml"
        $skillContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($skillPath, [Text.Encoding]::UTF8))
        $candidateFiles += @($skillPath, $metadataPath)
        [ordered]@{
            name = $skillName
            description = Get-AgentBaseSkillDescription -Content $skillContent -SkillName $skillName
        }
    })
    $fingerprint = Get-AgentBaseRoutingCandidateFingerprint -ProjectRoot $ProjectRoot -CandidateFiles @($candidateFiles | Sort-Object -Unique)
    return [pscustomobject]@{
        global_path = $globalPath
        skills = $skillCatalog
        fingerprint = $fingerprint
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
        [ordered]@{
            id = [string]$_.id
            request = [string]$_.request
            available_peer_skills = @($_.available_peer_skills | ForEach-Object { [string]$_ })
        }
    })
    $peerSkills = @($Contract.peer_skills | ForEach-Object {
        [ordered]@{
            name = [string]$_.name
            description = [string]$_.description
        }
    })

    $candidateFingerprint = $candidate.fingerprint
    $evaluationInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases @($Contract.cases) -PeerSkills @($Contract.peer_skills)

    $capsule = [ordered]@{
        schema_version = 3
        evaluation_kind = "skill-routing"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        purpose = "Blind first-stage evaluation of AgentBase skill routing using only the information available before a skill is loaded."
        candidate_bundle_sha256 = $candidateFingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
        candidate = [ordered]@{
            global = [ordered]@{
                logical_path = "global/AGENTS.md"
                content = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($candidate.global_path, [Text.Encoding]::UTF8))
            }
            skills = $candidate.skills
        }
        peer_skills = $peerSkills
        instructions = @(
            "Use only the candidate and peer_skills content embedded in this detached capsule."
            "Hidden expected and forbidden selections are not present in this capsule; do not inspect the source repository or its tests."
            "For every case, predict only the project skills and available peer skills that must be loaded before task actions."
            "The skill catalog intentionally exposes descriptions only. Policy labels, post-selection skill bodies, and reference choices are intentionally unavailable in this stage."
            "Do not execute the requests, call tools, or modify files. This is skill-routing evaluation, not execution-behavior evaluation."
            "Return one result for every id using the declared output schema."
        )
        output_schema = [ordered]@{
            schema_version = 3
            evaluation_kind = "skill-routing"
            fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
            evaluator = [ordered]@{
                id = "unique evaluator run identifier"
                model = "actual model identifier"
                runtime = "actual isolated runtime identifier"
                evaluated_at_utc = "ISO-8601 UTC timestamp"
                isolation_mode = "detached-capsule"
                repository_accessed = $false
                hidden_expectations_accessed = $false
            }
            evaluation_capsule_sha256 = "echo the capsule field with this name"
            candidate_bundle_sha256 = $candidateFingerprint
            evaluation_input_sha256 = $evaluationInputFingerprint
            cases = @(
                [ordered]@{
                    id = "case id"
                    selected_skills = @("project-skill-name")
                    selected_peer_skills = @("peer-skill-name")
                    note = "one concise rationale"
                }
            )
        }
        cases = $cases
    }

    $capsuleCoreJson = $capsule | ConvertTo-Json -Depth 12
    $capsuleFingerprint = Get-AgentBaseRoutingSha256 (ConvertTo-AgentBaseCanonicalText $capsuleCoreJson)
    $capsule.evaluation_capsule_sha256 = $capsuleFingerprint

    return [pscustomobject]@{
        payload = $capsule
        sha256 = $capsuleFingerprint
        candidate_bundle_sha256 = $candidateFingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
    }
}

function Get-AgentBasePolicyEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $candidate = Get-AgentBaseRoutingCandidate -ProjectRoot $ProjectRoot -Contract $Contract
    $routingResultFingerprint = Get-AgentBaseRoutingResultFingerprint -RoutingResults $RoutingResults
    $cases = @($Contract.cases | ForEach-Object {
        [ordered]@{
            id = [string]$_.id
            request = [string]$_.request
        }
    })
    $behaviorTags = @($Contract.allowed_behavior_tags | ForEach-Object {
        $tag = [string]$_
        [ordered]@{
            tag = $tag
            description = [string]$Contract.behavior_tag_definitions.$tag
        }
    })
    $evaluationInputFingerprint = Get-AgentBasePolicyInputFingerprint -Cases $cases -AllowedBehaviorTags @($Contract.allowed_behavior_tags) -BehaviorTagDefinitions $Contract.behavior_tag_definitions
    $capsule = [ordered]@{
        schema_version = 3
        evaluation_kind = "behavior-policy"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        purpose = "Blind post-routing evaluation of coarse AgentBase behavior policy after skill selection has been independently validated."
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
        routing_evaluation_capsule_sha256 = [string]$RoutingResults.evaluation_capsule_sha256
        routing_result_sha256 = $routingResultFingerprint
        candidate = [ordered]@{
            global = [ordered]@{
                logical_path = "global/AGENTS.md"
                content = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($candidate.global_path, [Text.Encoding]::UTF8))
            }
        }
        allowed_behavior_tags = @($Contract.allowed_behavior_tags)
        behavior_tag_definitions = $behaviorTags
        instructions = @(
            "Use only the global rules, behavior-tag definitions, and cases embedded in this detached capsule."
            "Skill routing was validated in a separate first-stage capsule whose identity is bound here, but its selections and post-selection skill bodies are intentionally unavailable. Hidden expected and forbidden behavior tags are not present; do not inspect the source repository, other capsules, results, or tests."
            "For every case, select all applicable coarse behavior tags. Do not predict skill routing or skill references in this stage."
            "Apply tags only by their supplied definitions. Do not execute requests, call tools, or modify files. Return one result per id using the declared output schema."
        )
        output_schema = [ordered]@{
            schema_version = 3
            evaluation_kind = "behavior-policy"
            fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
            evaluator = [ordered]@{
                id = "unique evaluator run identifier"
                model = "actual model identifier"
                runtime = "actual isolated runtime identifier"
                evaluated_at_utc = "ISO-8601 UTC timestamp"
                isolation_mode = "detached-capsule"
                repository_accessed = $false
                hidden_expectations_accessed = $false
            }
            evaluation_capsule_sha256 = "echo the capsule field with this name"
            candidate_bundle_sha256 = $candidate.fingerprint
            evaluation_input_sha256 = $evaluationInputFingerprint
            routing_evaluation_capsule_sha256 = [string]$RoutingResults.evaluation_capsule_sha256
            routing_result_sha256 = $routingResultFingerprint
            cases = @(
                [ordered]@{
                    id = "case id"
                    behavior_tags = @("allowed_behavior_tag")
                    note = "one concise rationale"
                }
            )
        }
        cases = $cases
    }
    $capsuleCoreJson = $capsule | ConvertTo-Json -Depth 12
    $capsuleFingerprint = Get-AgentBaseRoutingSha256 (ConvertTo-AgentBaseCanonicalText $capsuleCoreJson)
    $capsule.evaluation_capsule_sha256 = $capsuleFingerprint
    return [pscustomobject]@{
        payload = $capsule
        sha256 = $capsuleFingerprint
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
    }
}

function Get-AgentBaseReferenceEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $candidate = Get-AgentBaseRoutingCandidate -ProjectRoot $ProjectRoot -Contract $Contract
    $routingResultFingerprint = Get-AgentBaseRoutingResultFingerprint -RoutingResults $RoutingResults
    $selectedIds = @($RoutingResults.cases | Where-Object {
        @($_.selected_skills | ForEach-Object { [string]$_ }) -contains "change-governance"
    } | ForEach-Object { [string]$_.id })
    $cases = @($Contract.cases | Where-Object { $selectedIds -contains [string]$_.id } | ForEach-Object {
        [ordered]@{
            id = [string]$_.id
            request = [string]$_.request
        }
    })
    $skillPath = Join-Path $ProjectRoot "skills\change-governance\SKILL.md"
    $skillContent = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($skillPath, [Text.Encoding]::UTF8))
    $availableReferences = @([regex]::Matches($skillContent, '\]\(references/(?<name>[^)#]+\.md)(?:#[^)]+)?\)') | ForEach-Object {
        $_.Groups["name"].Value
    } | Sort-Object -Unique)
    $evaluationInputFingerprint = Get-AgentBaseReferenceInputFingerprint -Cases $cases
    $capsule = [ordered]@{
        schema_version = 3
        evaluation_kind = "routing-reference-policy"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        purpose = "Blind post-routing evaluation of change-governance reference selection after the routing stage has selected that skill."
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
        routing_evaluation_capsule_sha256 = [string]$RoutingResults.evaluation_capsule_sha256
        routing_result_sha256 = $routingResultFingerprint
        candidate = [ordered]@{
            skill = [ordered]@{
                name = "change-governance"
                logical_path = "skills/change-governance/SKILL.md"
                content = $skillContent
            }
        }
        available_references = $availableReferences
        instructions = @(
            "Use only the selected skill and cases embedded in this detached capsule."
            "The cases are derived from the validated first-stage routing result; hidden expected references are not present. Do not inspect the source repository, earlier capsules, results, or tests."
            "For every case, select all change-governance references that must be read before task actions."
            "Do not execute requests, call tools, or modify files. Return one result per id using the declared output schema."
        )
        output_schema = [ordered]@{
            schema_version = 3
            evaluation_kind = "routing-reference-policy"
            fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
            evaluator = [ordered]@{
                id = "unique evaluator run identifier"
                model = "actual model identifier"
                runtime = "actual isolated runtime identifier"
                evaluated_at_utc = "ISO-8601 UTC timestamp"
                isolation_mode = "detached-capsule"
                repository_accessed = $false
                hidden_expectations_accessed = $false
            }
            evaluation_capsule_sha256 = "echo the capsule field with this name"
            candidate_bundle_sha256 = $candidate.fingerprint
            evaluation_input_sha256 = $evaluationInputFingerprint
            routing_evaluation_capsule_sha256 = [string]$RoutingResults.evaluation_capsule_sha256
            routing_result_sha256 = $routingResultFingerprint
            cases = @(
                [ordered]@{
                    id = "case id"
                    selected_change_governance_references = @("reference.md")
                    note = "one concise rationale"
                }
            )
        }
        cases = $cases
    }
    $capsuleCoreJson = $capsule | ConvertTo-Json -Depth 12
    $capsuleFingerprint = Get-AgentBaseRoutingSha256 (ConvertTo-AgentBaseCanonicalText $capsuleCoreJson)
    $capsule.evaluation_capsule_sha256 = $capsuleFingerprint
    return [pscustomobject]@{
        payload = $capsule
        sha256 = $capsuleFingerprint
        candidate_bundle_sha256 = $candidate.fingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
    }
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
        if (-not ($Evaluator.PSObject.Properties.Name -contains $field) -or $Evaluator.$field.GetType().FullName -ne "System.Boolean" -or [bool]$Evaluator.$field) {
            throw "$Label evaluator has an invalid input attestation: $field"
        }
    }
    $evaluatedAt = [DateTimeOffset]::MinValue
    $evaluatedAtText = [string]$Evaluator.evaluated_at_utc
    if (-not [DateTimeOffset]::TryParse($evaluatedAtText, [ref]$evaluatedAt) -or
        $evaluatedAt.Offset -ne [TimeSpan]::Zero -or
        $evaluatedAt -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
        throw "$Label evaluator timestamp must be a valid non-future UTC ISO-8601 value"
    }
}

function Assert-AgentBasePolicyEvaluationResults {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults,
        [object]$PolicyResults,
        [switch]$FailOnUnexpectedSelections,
        [switch]$ShowWarnings
    )

    if ($PolicyResults.schema_version -ne 3 -or [string]$PolicyResults.evaluation_kind -ne "behavior-policy") {
        throw "Unsupported behavior-policy result schema or kind"
    }
    if ([string]$PolicyResults.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
        throw "Unsupported behavior-policy fingerprint schema"
    }
    $capsule = Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $RoutingResults
    if ([string]$PolicyResults.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256 -or
        [string]$PolicyResults.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256 -or
        [string]$PolicyResults.evaluation_capsule_sha256 -ne $capsule.sha256 -or
        [string]$PolicyResults.routing_evaluation_capsule_sha256 -ne [string]$RoutingResults.evaluation_capsule_sha256 -or
        [string]$PolicyResults.routing_result_sha256 -ne (Get-AgentBaseRoutingResultFingerprint -RoutingResults $RoutingResults)) {
        throw "Behavior-policy result belongs to a different candidate, input set, routing result, or detached capsule"
    }
    Assert-AgentBaseDetachedEvaluator -Evaluator $PolicyResults.evaluator -Label "Behavior-policy"

    $contractById = @{}
    foreach ($case in @($Contract.cases)) {
        $contractById[[string]$case.id] = $case
    }
    $allowedTags = @($Contract.allowed_behavior_tags | ForEach-Object { [string]$_ })
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
        foreach ($otherStageField in @("selected_skills", "selected_peer_skills", "selected_change_governance_references")) {
            if ($result.PSObject.Properties.Name -contains $otherStageField) {
                $failures.Add("$id returned another stage's field during behavior-policy evaluation: $otherStageField")
            }
        }
    }
    foreach ($id in $contractById.Keys) {
        if (-not $resultById.ContainsKey($id)) {
            $failures.Add("Missing behavior-policy result: $id")
            continue
        }
        $selected = @($resultById[$id].behavior_tags | ForEach-Object { [string]$_ })
        $expected = @($contractById[$id].expected_behavior_tags | ForEach-Object { [string]$_ })
        $forbidden = @($contractById[$id].forbidden_behavior_tags | ForEach-Object { [string]$_ })
        foreach ($tag in $selected) {
            if ($allowedTags -notcontains $tag) {
                $failures.Add("$id selected an unknown behavior tag: $tag")
            }
        }
        foreach ($tag in $expected) {
            if ($selected -notcontains $tag) {
                $failures.Add("$id missed expected behavior tag: $tag")
            }
        }
        foreach ($tag in $forbidden) {
            if ($selected -contains $tag) {
                $failures.Add("$id selected forbidden behavior tag: $tag")
            }
        }
        foreach ($tag in @($selected | Where-Object { $expected -notcontains $_ -and $forbidden -notcontains $_ })) {
            if ($FailOnUnexpectedSelections) {
                $failures.Add("$id selected an unspecified behavior tag: $tag")
            }
            else {
                $diagnostics.Add("$id selected an unspecified policy label: $tag")
            }
        }
    }
    if ($failures.Count -gt 0) {
        throw ("Behavior-policy evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
    }
    if ($diagnostics.Count -gt 0) {
        if ($ShowWarnings) {
            Write-Information ($diagnostics -join [Environment]::NewLine) -InformationAction Continue
        }
        else {
            Write-Verbose "Behavior-policy evaluation recorded $($diagnostics.Count) additional compatible policy labels. Use -ShowWarnings to list them."
        }
    }
    return "Behavior-policy evaluation valid: $($resultById.Count)/$($contractById.Count) cases satisfy the declared policy-label constraints."
}

function Assert-AgentBaseReferenceEvaluationResults {
    param(
        [string]$ProjectRoot,
        [object]$Contract,
        [object]$RoutingResults,
        [object]$ReferenceResults
    )

    if ($ReferenceResults.schema_version -ne 3 -or [string]$ReferenceResults.evaluation_kind -ne "routing-reference-policy") {
        throw "Unsupported routing-reference-policy result schema or kind"
    }
    if ([string]$ReferenceResults.fingerprint_schema -ne (Get-AgentBaseRoutingFingerprintSchema)) {
        throw "Unsupported routing-reference fingerprint schema"
    }
    $capsule = Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $Contract -RoutingResults $RoutingResults
    if ([string]$ReferenceResults.candidate_bundle_sha256 -ne $capsule.candidate_bundle_sha256 -or
        [string]$ReferenceResults.evaluation_input_sha256 -ne $capsule.evaluation_input_sha256 -or
        [string]$ReferenceResults.evaluation_capsule_sha256 -ne $capsule.sha256 -or
        [string]$ReferenceResults.routing_evaluation_capsule_sha256 -ne [string]$RoutingResults.evaluation_capsule_sha256 -or
        [string]$ReferenceResults.routing_result_sha256 -ne (Get-AgentBaseRoutingResultFingerprint -RoutingResults $RoutingResults)) {
        throw "Routing-reference result belongs to a different candidate, input set, routing result, or detached capsule"
    }

    Assert-AgentBaseDetachedEvaluator -Evaluator $ReferenceResults.evaluator -Label "Routing-reference"

    $contractById = @{}
    foreach ($case in @($Contract.cases)) {
        $contractById[[string]$case.id] = $case
    }
    $capsuleIds = @($capsule.payload.cases | ForEach-Object { [string]$_.id })
    $resultById = @{}
    $failures = New-Object 'System.Collections.Generic.List[string]'
    foreach ($result in @($ReferenceResults.cases)) {
        $id = [string]$result.id
        if ([string]::IsNullOrWhiteSpace($id) -or $resultById.ContainsKey($id) -or $capsuleIds -notcontains $id) {
            $failures.Add("Invalid, duplicate, or unselected routing-reference result id: $id")
            continue
        }
        $resultById[$id] = $result
        foreach ($otherStageField in @("selected_skills", "selected_peer_skills", "behavior_tags")) {
            if ($result.PSObject.Properties.Name -contains $otherStageField) {
                $failures.Add("$id returned another stage's field during routing-reference evaluation: $otherStageField")
            }
        }
    }
    foreach ($id in $capsuleIds) {
        if (-not $resultById.ContainsKey($id)) {
            $failures.Add("Missing routing-reference result: $id")
            continue
        }
        $selected = @($resultById[$id].selected_change_governance_references | ForEach-Object { [string]$_ })
        $expected = @($contractById[$id].expected_change_governance_references | ForEach-Object { [string]$_ })
        foreach ($reference in $selected) {
            if (@($capsule.payload.available_references) -notcontains $reference) {
                $failures.Add("$id selected an unavailable change-governance reference: $reference")
            }
        }
        foreach ($reference in $expected) {
            if ($selected -notcontains $reference) {
                $failures.Add("$id missed expected change-governance reference: $reference")
            }
        }
        if (@($Contract.strict_routing_case_ids) -contains $id) {
            foreach ($reference in @($selected | Where-Object { $expected -notcontains $_ })) {
                $failures.Add("$id selected an unspecified change-governance reference: $reference")
            }
        }
    }
    if ($failures.Count -gt 0) {
        throw ("Routing-reference-policy evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
    }
    return "Routing-reference-policy evaluation valid: $($resultById.Count)/$($capsuleIds.Count) selected change-governance cases satisfy the reference constraints."
}
