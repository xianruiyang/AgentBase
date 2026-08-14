$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$testRoot = Join-Path $tempBase ("AgentBase-behavior-fingerprint-" + [guid]::NewGuid().ToString("N"))
$lfRoot = Join-Path $testRoot "lf"
$crlfRoot = Join-Path $testRoot "crlf"
$utf8NoBom = [Text.UTF8Encoding]::new($false)

function Write-TestText {
    param(
        [string]$Path,
        [string]$Text
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

try {
    $relativeFiles = @("global\AGENTS.md", "skills\sample\SKILL.md")
    foreach ($relativePath in $relativeFiles) {
        Write-TestText -Path (Join-Path $lfRoot $relativePath) -Text "first`nsecond`n"
        Write-TestText -Path (Join-Path $crlfRoot $relativePath) -Text "first`r`nsecond`r`n"
    }

    $lfFingerprint = Get-AgentBaseRoutingCandidateFingerprint -ProjectRoot $lfRoot -CandidateFiles @($relativeFiles | ForEach-Object { Join-Path $lfRoot $_ })
    $crlfFingerprint = Get-AgentBaseRoutingCandidateFingerprint -ProjectRoot $crlfRoot -CandidateFiles @($relativeFiles | ForEach-Object { Join-Path $crlfRoot $_ })
    if ($lfFingerprint -ne $crlfFingerprint) {
        throw "Candidate fingerprint changes across LF and CRLF checkouts"
    }

    $lfCases = @([pscustomobject]@{ id = "sample"; request = "line one`nline two"; available_peer_skills = @("peer-sample") })
    $crlfCases = @([pscustomobject]@{ id = "sample"; request = "line one`r`nline two"; available_peer_skills = @("peer-sample") })
    $lfPeers = @([pscustomobject]@{ name = "peer-sample"; description = "line one`nline two" })
    $crlfPeers = @([pscustomobject]@{ name = "peer-sample"; description = "line one`r`nline two" })
    $lfInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases $lfCases -PeerSkills $lfPeers
    $crlfInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases $crlfCases -PeerSkills $crlfPeers
    if ($lfInputFingerprint -ne $crlfInputFingerprint) {
        throw "Evaluation input fingerprint changes across LF and CRLF text"
    }

    $lfTagDefinitions = [pscustomobject]@{ read_only = "line one`nline two" }
    $crlfTagDefinitions = [pscustomobject]@{ read_only = "line one`r`nline two" }
    $lfPolicyCases = @([pscustomobject]@{ id = "sample"; request = "line one`nline two" })
    $crlfPolicyCases = @([pscustomobject]@{ id = "sample"; request = "line one`r`nline two" })
    $lfPolicyFingerprint = Get-AgentBasePolicyInputFingerprint -Cases $lfPolicyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions $lfTagDefinitions
    $crlfPolicyFingerprint = Get-AgentBasePolicyInputFingerprint -Cases $crlfPolicyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions $crlfTagDefinitions
    if ($lfPolicyFingerprint -ne $crlfPolicyFingerprint) {
        throw "Policy-stage input fingerprint changes across LF and CRLF text"
    }
    $changedTagDefinitions = [pscustomobject]@{ read_only = "different definition" }
    $changedPolicyFingerprint = Get-AgentBasePolicyInputFingerprint -Cases $lfPolicyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions $changedTagDefinitions
    if ($lfPolicyFingerprint -eq $changedPolicyFingerprint) {
        throw "Policy-stage input fingerprint does not include behavior tag definitions"
    }

    $lfRoutingResult = [pscustomobject]@{
        schema_version = 3
        evaluation_kind = "skill-routing"
        evaluation_capsule_sha256 = "capsule"
        candidate_bundle_sha256 = "candidate"
        evaluation_input_sha256 = "input"
        evaluator = [pscustomobject]@{ id = "run"; model = "model"; runtime = "runtime"; evaluated_at_utc = "2026-08-14T00:00:00Z" }
        cases = @([pscustomobject]@{ id = "sample"; selected_skills = @("sample"); selected_peer_skills = @("peer-sample") })
    }
    $sameRoutingResultDifferentOrder = [pscustomobject]@{
        schema_version = 3
        evaluation_kind = "skill-routing"
        evaluation_capsule_sha256 = "capsule"
        candidate_bundle_sha256 = "candidate"
        evaluation_input_sha256 = "input"
        evaluator = [pscustomobject]@{ id = "run"; model = "model"; runtime = "runtime"; evaluated_at_utc = "2026-08-14T00:00:00Z" }
        cases = @([pscustomobject]@{ id = "sample"; selected_skills = @("sample"); selected_peer_skills = @("peer-sample") })
    }
    $routingResultFingerprint = Get-AgentBaseRoutingResultFingerprint -RoutingResults $lfRoutingResult
    if ($routingResultFingerprint -ne (Get-AgentBaseRoutingResultFingerprint -RoutingResults $sameRoutingResultDifferentOrder)) {
        throw "Routing-result fingerprint changes without a semantic input change"
    }
    $changedRoutingResult = $lfRoutingResult | ConvertTo-Json -Depth 10 | ConvertFrom-Json -Depth 10
    $changedRoutingResult.cases[0].selected_skills = @("different-skill")
    if ($routingResultFingerprint -eq (Get-AgentBaseRoutingResultFingerprint -RoutingResults $changedRoutingResult)) {
        throw "Routing-result fingerprint does not bind selected skills"
    }

    $lfReferenceFingerprint = Get-AgentBaseReferenceInputFingerprint -Cases $lfCases
    $crlfReferenceFingerprint = Get-AgentBaseReferenceInputFingerprint -Cases $crlfCases
    if ($lfReferenceFingerprint -ne $crlfReferenceFingerprint) {
        throw "Reference-stage input fingerprint changes across LF and CRLF text"
    }
    $changedReferenceCases = @([pscustomobject]@{ id = "sample"; request = "different request" })
    if ($lfReferenceFingerprint -eq (Get-AgentBaseReferenceInputFingerprint -Cases $changedReferenceCases)) {
        throw "Reference-stage input fingerprint does not include case requests"
    }

    Write-Output "Routing fingerprint tests passed: candidate, routing-input, policy-input, and reference-input hashes are line-ending neutral and bind their semantic inputs."
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $resolvedTestRoot).StartsWith("AgentBase-behavior-fingerprint-", [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolvedTestRoot"
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
