$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")

$lfCatalog = @([pscustomobject]@{ name = "sample"; description = "line one`nline two" })
$crlfCatalog = @([pscustomobject]@{ name = "sample"; description = "line one`r`nline two" })
$lfCandidate = Get-AgentBaseRoutingCandidateFingerprint -GlobalContent "first`nsecond`n" -SkillCatalog $lfCatalog
$crlfCandidate = Get-AgentBaseRoutingCandidateFingerprint -GlobalContent "first`r`nsecond`r`n" -SkillCatalog $crlfCatalog
if ($lfCandidate -ne $crlfCandidate) {
    throw "Routing candidate fingerprint changes across LF and CRLF text"
}

$lfCases = @([pscustomobject]@{ id = "sample"; request = "line one`nline two"; available_peer_skills = @("peer-sample") })
$crlfCases = @([pscustomobject]@{ id = "sample"; request = "line one`r`nline two"; available_peer_skills = @("peer-sample") })
$lfPeers = @([pscustomobject]@{ name = "peer-sample"; description = "line one`nline two" })
$crlfPeers = @([pscustomobject]@{ name = "peer-sample"; description = "line one`r`nline two" })
if ((Get-AgentBaseRoutingInputFingerprint -Cases $lfCases -PeerSkills $lfPeers) -ne
    (Get-AgentBaseRoutingInputFingerprint -Cases $crlfCases -PeerSkills $crlfPeers)) {
    throw "Routing input fingerprint changes across LF and CRLF text"
}

$lfDefinitions = [pscustomobject]@{ read_only = "line one`nline two" }
$crlfDefinitions = [pscustomobject]@{ read_only = "line one`r`nline two" }
$policyCases = @([pscustomobject]@{ id = "sample"; request = "request" })
$lfPolicy = Get-AgentBasePolicyInputFingerprint -Cases $policyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions $lfDefinitions
$crlfPolicy = Get-AgentBasePolicyInputFingerprint -Cases $policyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions $crlfDefinitions
if ($lfPolicy -ne $crlfPolicy) {
    throw "Policy input fingerprint changes across LF and CRLF definitions"
}
if ($lfPolicy -eq (Get-AgentBasePolicyInputFingerprint -Cases $policyCases -AllowedBehaviorTags @("read_only") -BehaviorTagDefinitions ([pscustomobject]@{ read_only = "changed" }))) {
    throw "Policy input fingerprint does not bind behavior-tag definitions"
}

$lfReferenceCandidates = @([pscustomobject]@{ name = "sample"; content = "first`nsecond`n" })
$crlfReferenceCandidates = @([pscustomobject]@{ name = "sample"; content = "first`r`nsecond`r`n" })
if ((Get-AgentBaseReferenceCandidateFingerprint -SkillCandidates $lfReferenceCandidates) -ne
    (Get-AgentBaseReferenceCandidateFingerprint -SkillCandidates $crlfReferenceCandidates)) {
    throw "Reference candidate fingerprint changes across LF and CRLF skill bodies"
}

$routingResults = [pscustomobject]@{
    candidate_bundle_sha256 = "A" * 64
    evaluation_input_sha256 = "B" * 64
    evaluation_capsule_sha256 = "C" * 64
    cases = @([pscustomobject]@{ id = "sample"; selected_skills = @("sample"); selected_peer_skills = @("peer-sample") })
}
$selectionFingerprint = Get-AgentBaseRoutingReferenceSelectionFingerprint -RoutingResults $routingResults -ReferenceSkillNames @("sample")
$changedRoutingResults = $routingResults | ConvertTo-Json -Depth 10 | ConvertFrom-Json -Depth 10
$changedRoutingResults.cases[0].selected_skills = @()
if ($selectionFingerprint -eq (Get-AgentBaseRoutingReferenceSelectionFingerprint -RoutingResults $changedRoutingResults -ReferenceSkillNames @("sample"))) {
    throw "Reference dependency fingerprint does not bind relevant routing selections"
}

$semanticFingerprint = Get-AgentBaseStageSemanticResultFingerprint -Phase Routing -Results $routingResults
$sameResultDifferentOrder = $routingResults | ConvertTo-Json -Depth 10 | ConvertFrom-Json -Depth 10
$sameResultDifferentOrder.cases[0].selected_skills = @("sample")
if ($semanticFingerprint -ne (Get-AgentBaseStageSemanticResultFingerprint -Phase Routing -Results $sameResultDifferentOrder)) {
    throw "Stage semantic result fingerprint changes without a semantic change"
}

Write-Output "Routing fingerprint tests passed: phase-visible identities are line-ending neutral and bind routing, policy, reference-selection, and semantic-result inputs."
