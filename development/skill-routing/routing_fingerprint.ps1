$ErrorActionPreference = "Stop"

function Get-AgentBaseRoutingFingerprintSchema {
    return "text-lf-v1"
}

function Get-AgentBaseRoutingSha256 {
    param(
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

function Get-AgentBaseRoutingCandidateFingerprint {
    param(
        [string]$ProjectRoot,
        [object[]]$CandidateFiles
    )

    $rootFull = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $records = @($CandidateFiles | ForEach-Object {
        $item = Get-Item -LiteralPath ([string]$_) -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Behavior candidate must be a real file: $($item.FullName)"
        }
        $relativePath = $item.FullName.Substring($rootFull.Length + 1).Replace('\', '/')
        $canonicalText = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($item.FullName, [Text.Encoding]::UTF8))
        $canonicalBytes = [Text.UTF8Encoding]::new($false).GetBytes($canonicalText)
        $contentHash = Get-AgentBaseRoutingSha256 $canonicalText
        "$relativePath|$($canonicalBytes.Length)|$contentHash"
    })
    [Array]::Sort([string[]]$records, [StringComparer]::Ordinal)
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseRoutingInputFingerprint {
    param(
        [object[]]$Cases,
        [object[]]$PeerSkills = @()
    )

    $records = @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        $availablePeers = @($_.available_peer_skills | ForEach-Object { [string]$_ } | Sort-Object)
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

    $records = @("phase|post-routing-policy")
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

function Get-AgentBaseRoutingResultFingerprint {
    param(
        [object]$RoutingResults
    )

    $records = @(
        "schema|$([string]$RoutingResults.schema_version)|kind=$([string]$RoutingResults.evaluation_kind)"
        "capsule|$([string]$RoutingResults.evaluation_capsule_sha256)"
        "candidate|$([string]$RoutingResults.candidate_bundle_sha256)"
        "input|$([string]$RoutingResults.evaluation_input_sha256)"
        "evaluator|$([string]$RoutingResults.evaluator.id)|$([string]$RoutingResults.evaluator.model)|$([string]$RoutingResults.evaluator.runtime)|$([string]$RoutingResults.evaluator.evaluated_at_utc)"
    )
    $records += @($RoutingResults.cases | ForEach-Object {
        $selectedSkills = @($_.selected_skills | ForEach-Object { [string]$_ } | Sort-Object)
        $selectedPeers = @($_.selected_peer_skills | ForEach-Object { [string]$_ } | Sort-Object)
        "$([string]$_.id)|skills=$($selectedSkills -join ',')|peers=$($selectedPeers -join ',')"
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}

function Get-AgentBaseReferenceInputFingerprint {
    param(
        [object[]]$Cases
    )

    $records = @("phase|change-governance-references")
    $records += @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        "$([string]$_.id)|$request"
    })
    return Get-AgentBaseRoutingSha256 ($records -join "`n")
}
