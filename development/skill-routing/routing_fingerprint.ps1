$ErrorActionPreference = "Stop"

function Get-AgentBaseRoutingFingerprintSchema {
    return "phase-visible-lf-v2"
}

function Get-AgentBaseRoutingEvaluatorProtocol {
    return "isolated-codex-exec-cases-only-v4"
}

function Get-AgentBaseRoutingEvaluatorDisabledFeatures {
    return @(
        "apps"
        "browser_use"
        "browser_use_external"
        "browser_use_full_cdp_access"
        "code_mode_host"
        "computer_use"
        "goals"
        "hooks"
        "image_generation"
        "in_app_browser"
        "multi_agent"
        "plugins"
        "plugin_sharing"
        "recommended_plugins"
        "remote_plugin"
        "shell_snapshot"
        "shell_tool"
        "skill_mcp_dependency_install"
        "skill_search"
        "tool_suggest"
        "unified_exec"
        "view_image"
        "workspace_dependencies"
    )
}

function Get-AgentBaseRoutingSha256 {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $algorithm.Dispose()
    }
}

function ConvertTo-AgentBaseCanonicalText {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    return $Text.Replace("`r`n", "`n").Replace("`r", "`n")
}

function ConvertTo-AgentBaseStringArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-AgentBaseCanonicalTextRecord {
    param(
        [string]$Name,
        [AllowEmptyString()]
        [string]$Text
    )

    $canonical = ConvertTo-AgentBaseCanonicalText $Text
    $byteCount = [Text.UTF8Encoding]::new($false).GetByteCount($canonical)
    return "$Name|$byteCount|$(Get-AgentBaseRoutingSha256 $canonical)"
}

function Get-AgentBaseRoutingCandidateFingerprint {
    param(
        [string]$GlobalContent,
        [object[]]$SkillCatalog
    )

    $records = @(
        "phase|skill-routing"
        "protocol|$(Get-AgentBaseRoutingEvaluatorProtocol)"
        Get-AgentBaseCanonicalTextRecord -Name "global/AGENTS.md" -Text $GlobalContent
    )
    $records += @($SkillCatalog | ForEach-Object {
        $name = [string]$_.name
        $description = ConvertTo-AgentBaseCanonicalText ([string]$_.description)
        "skill|$name|$description"
    } | Sort-Object)
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBasePolicyCandidateFingerprint {
    param(
        [string]$GlobalContent
    )

    $records = @(
        "phase|behavior-policy"
        "protocol|$(Get-AgentBaseRoutingEvaluatorProtocol)"
        Get-AgentBaseCanonicalTextRecord -Name "global/AGENTS.md" -Text $GlobalContent
    )
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseReferenceCandidateFingerprint {
    param(
        [object[]]$SkillCandidates
    )

    $records = @(
        "phase|routing-reference-policy"
        "protocol|$(Get-AgentBaseRoutingEvaluatorProtocol)"
    )
    $records += @($SkillCandidates | ForEach-Object {
        Get-AgentBaseCanonicalTextRecord -Name "skills/$([string]$_.name)/SKILL.md" -Text ([string]$_.content)
    } | Sort-Object)
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseRoutingInputFingerprint {
    param(
        [object[]]$Cases,
        [object[]]$PeerSkills = @()
    )

    $records = @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        $availablePeers = @(ConvertTo-AgentBaseStringArray $_.available_peer_skills | Sort-Object)
        "$([string]$_.id)|$request|peers=$($availablePeers -join ',')"
    })
    $records += @($PeerSkills | ForEach-Object {
        $description = ConvertTo-AgentBaseCanonicalText ([string]$_.description)
        "peer|$([string]$_.name)|$description"
    } | Sort-Object)
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBasePolicyInputFingerprint {
    param(
        [object[]]$Cases,
        [object[]]$AllowedBehaviorTags,
        [object]$BehaviorTagDefinitions
    )

    $records = @("phase|behavior-policy")
    $records += @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        "$([string]$_.id)|$request"
    })
    $records += @($AllowedBehaviorTags | ForEach-Object {
        $tag = [string]$_
        $description = ConvertTo-AgentBaseCanonicalText ([string]$BehaviorTagDefinitions.$tag)
        "behavior|$tag|$description"
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseRoutingReferenceSelectionFingerprint {
    param(
        [object]$RoutingResults,
        [string[]]$ReferenceSkillNames
    )

    $records = @("dependency|routing-reference-selection")
    $records += @($RoutingResults.cases | ForEach-Object {
        $selected = @(ConvertTo-AgentBaseStringArray $_.selected_skills | Where-Object {
            $ReferenceSkillNames -contains $_
        } | Sort-Object)
        "$([string]$_.id)|skills=$($selected -join ',')"
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseReferenceInputFingerprint {
    param(
        [object[]]$Cases
    )

    $records = @("phase|routing-reference-policy")
    $records += @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        $selectedReferenceSkills = @(ConvertTo-AgentBaseStringArray $_.selected_reference_skills | Sort-Object)
        "$([string]$_.id)|skills=$($selectedReferenceSkills -join ',')|$request"
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseStageSemanticResultFingerprint {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$Phase,
        [object]$Results
    )

    $records = @(
        "phase|$($Phase.ToLowerInvariant())"
        "candidate|$([string]$Results.candidate_bundle_sha256)"
        "input|$([string]$Results.evaluation_input_sha256)"
        "capsule|$([string]$Results.evaluation_capsule_sha256)"
    )
    if ($Phase -eq "References") {
        $records += "routing-selection|$([string]$Results.routing_reference_selection_sha256)"
    }
    $records += @($Results.cases | Sort-Object { [string]$_.id } | ForEach-Object {
        $id = [string]$_.id
        switch ($Phase) {
            "Routing" {
                $skills = @(ConvertTo-AgentBaseStringArray $_.selected_skills | Sort-Object)
                $peers = @(ConvertTo-AgentBaseStringArray $_.selected_peer_skills | Sort-Object)
                "$id|skills=$($skills -join ',')|peers=$($peers -join ',')"
            }
            "Policy" {
                $tags = @(ConvertTo-AgentBaseStringArray $_.behavior_tags | Sort-Object)
                "$id|tags=$($tags -join ',')"
            }
            "References" {
                $selections = @($_.selected_references | Sort-Object { [string]$_.skill } | ForEach-Object {
                    $references = @(ConvertTo-AgentBaseStringArray $_.references | Sort-Object)
                    "$([string]$_.skill)=$($references -join ',')"
                })
                "$id|references=$($selections -join ';')"
            }
        }
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseRoutingGenerationFingerprint {
    param(
        [string]$RoutingCapsuleSha256,
        [string]$PolicyCapsuleSha256,
        [string]$ReferenceUniverseSha256
    )

    return Get-AgentBaseRoutingSha256 (@(
        "schema|$(Get-AgentBaseRoutingFingerprintSchema)"
        "protocol|$(Get-AgentBaseRoutingEvaluatorProtocol)"
        "routing|$RoutingCapsuleSha256"
        "policy|$PolicyCapsuleSha256"
        "reference-universe|$ReferenceUniverseSha256"
    ) -join "`n")
}
