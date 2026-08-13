$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")

function Get-AgentBaseRoutingEvaluationCapsule {
    param(
        [string]$ProjectRoot,
        [object]$Contract
    )

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
    $skillSources = @($Contract.required_skills | ForEach-Object {
        $skillName = [string]$_
        $skillPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $skillName) "SKILL.md"
        $metadataPath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $skillName) "agents\openai.yaml"
        [ordered]@{
            name = $skillName
            skill = [ordered]@{
                logical_path = "skills/$skillName/SKILL.md"
                content = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($skillPath, [Text.Encoding]::UTF8))
            }
            metadata = [ordered]@{
                logical_path = "skills/$skillName/agents/openai.yaml"
                content = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($metadataPath, [Text.Encoding]::UTF8))
            }
        }
    })
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

    $candidateFiles = @($globalPath)
    foreach ($skillSource in $skillSources) {
        $candidateFiles += @(
            Join-Path $ProjectRoot ([string]$skillSource.skill.logical_path).Replace('/', '\')
            Join-Path $ProjectRoot ([string]$skillSource.metadata.logical_path).Replace('/', '\')
        )
    }
    $candidateFingerprint = Get-AgentBaseRoutingCandidateFingerprint -ProjectRoot $ProjectRoot -CandidateFiles @($candidateFiles | Sort-Object -Unique)
    $evaluationInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases @($Contract.cases) -AllowedBehaviorTags @($Contract.allowed_behavior_tags) -PeerSkills @($Contract.peer_skills)

    $capsule = [ordered]@{
        schema_version = 2
        evaluation_kind = "routing-policy"
        fingerprint_schema = Get-AgentBaseRoutingFingerprintSchema
        purpose = "Blind evaluation of AgentBase skill routing and coarse policy labels. It does not execute requests or prove skill execution behavior."
        candidate_bundle_sha256 = $candidateFingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
        candidate = [ordered]@{
            global = [ordered]@{
                logical_path = "global/AGENTS.md"
                content = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($globalPath, [Text.Encoding]::UTF8))
            }
            skills = $skillSources
        }
        peer_skills = $peerSkills
        instructions = @(
            "Use only the candidate and peer_skills content embedded in this detached capsule."
            "Hidden expected and forbidden selections are not present in this capsule; do not inspect the source repository or its tests."
            "For every case, predict the project skills and available peer skills that must be loaded before task actions, the change-governance references that must be read, and all applicable coarse policy tags."
            "Do not execute the requests, call tools, or modify files. This is routing-policy evaluation, not execution-behavior evaluation."
            "Return one result for every id using the declared output schema."
        )
        allowed_behavior_tags = @($Contract.allowed_behavior_tags)
        output_schema = [ordered]@{
            schema_version = 2
            evaluation_kind = "routing-policy"
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
                    selected_change_governance_references = @("reference.md")
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
        candidate_bundle_sha256 = $candidateFingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
    }
}
