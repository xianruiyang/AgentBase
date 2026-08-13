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
    $lfInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases $lfCases -AllowedBehaviorTags @("read_only") -PeerSkills $lfPeers
    $crlfInputFingerprint = Get-AgentBaseRoutingInputFingerprint -Cases $crlfCases -AllowedBehaviorTags @("read_only") -PeerSkills $crlfPeers
    if ($lfInputFingerprint -ne $crlfInputFingerprint) {
        throw "Evaluation input fingerprint changes across LF and CRLF text"
    }

    Write-Output "Routing fingerprint tests passed: candidate, peer-catalog, and request hashes are line-ending neutral."
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
