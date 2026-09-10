param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-StringArray {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { [string]$_ })
}

function Assert-UniqueStrings {
    param(
        [string[]]$Values,
        [string]$Label
    )

    Assert-True (($Values | Sort-Object -Unique).Count -eq $Values.Count) "$Label contains duplicate values"
}

function Assert-Disjoint {
    param(
        [string[]]$Left,
        [string[]]$Right,
        [string]$Context
    )

    foreach ($item in $Left) {
        Assert-True ($Right -notcontains $item) "$Context contains the same value in expected and forbidden sets: $item"
    }
}

function Assert-MarkdownRelativeLinks {
    param([string]$Path)

    $markdown = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $directory = Split-Path -Parent $Path
    foreach ($linkMatch in [regex]::Matches($markdown, '\[[^\]]+\]\((?<target>[^)]+)\)')) {
        $target = $linkMatch.Groups["target"].Value.Trim()
        if ($target.StartsWith("#") -or $target -match '^[a-zA-Z][a-zA-Z0-9+.-]*:') {
            continue
        }
        $targetPath = ($target -split '#', 2)[0].Trim('<', '>')
        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            continue
        }
        $resolvedTarget = Join-Path $directory ([Uri]::UnescapeDataString($targetPath))
        Assert-True (Test-Path -LiteralPath $resolvedTarget) "Broken relative Markdown link in $Path`: $target"
    }
}

$contractPath = Join-Path $PSScriptRoot "trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($contract.schema_version -eq 3) "Unsupported trigger contract schema: $($contract.schema_version)"

$requiredSkills = @(Get-StringArray $contract.required_skills)
Assert-True ($requiredSkills.Count -gt 0) "Trigger contract has no required skills"
Assert-UniqueStrings $requiredSkills "Required skill catalog"

$referenceEvaluationSkills = @(Get-StringArray $contract.reference_evaluation_skills)
Assert-True ($referenceEvaluationSkills.Count -gt 0) "Trigger contract has no conditional-reference skills"
Assert-UniqueStrings $referenceEvaluationSkills "Conditional-reference skill catalog"
foreach ($referenceSkill in $referenceEvaluationSkills) {
    Assert-True ($requiredSkills -contains $referenceSkill) "Conditional-reference skill is not in the required skill catalog: $referenceSkill"
}

$globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
$projectAgentsPath = Join-Path $ProjectRoot "AGENTS.md"
Assert-True (Test-Path -LiteralPath $globalPath -PathType Leaf) "Global AGENTS.md is missing"
Assert-True (Test-Path -LiteralPath $projectAgentsPath -PathType Leaf) "Project AGENTS.md is missing"
$globalItem = Get-Item -LiteralPath $globalPath
$projectAgentsItem = Get-Item -LiteralPath $projectAgentsPath
Assert-True ($globalItem.Length -le [int]$contract.global_max_bytes) "Global AGENTS.md is $($globalItem.Length) bytes; contract limit is $($contract.global_max_bytes)"
Assert-True (($globalItem.Length + $projectAgentsItem.Length) -le 28672) "Global and project AGENTS.md exceed the reserved Codex instruction budget"

$globalText = Get-Content -LiteralPath $globalPath -Raw -Encoding UTF8
Assert-True (-not [string]::IsNullOrWhiteSpace($globalText)) "Global AGENTS.md is empty"
# Natural-language instructions have no required normative prefix. Check exact
# repeated paragraphs without interpreting their strength or semantic wording.
$globalParagraphs = @($globalText -split '(?:\r?\n)[ \t]*(?:\r?\n)' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notmatch '^#{1,6}\s+[^\r\n]+$' })
$duplicateParagraphs = @($globalParagraphs | Group-Object | Where-Object { $_.Count -gt 1 })
Assert-True ($duplicateParagraphs.Count -eq 0) "Global AGENTS.md contains duplicate paragraphs"

foreach ($skill in $requiredSkills) {
    $skillRoot = Join-Path (Join-Path $ProjectRoot "skills") $skill
    $skillPath = Join-Path $skillRoot "SKILL.md"
    $metadataPath = Join-Path $skillRoot "agents\openai.yaml"
    Assert-True (Test-Path -LiteralPath $skillPath -PathType Leaf) "Missing SKILL.md for required skill: $skill"
    Assert-True (Test-Path -LiteralPath $metadataPath -PathType Leaf) "Missing agents/openai.yaml for required skill: $skill"

    $skillItem = Get-Item -LiteralPath $skillPath
    Assert-True ($skillItem.Length -le [int]$contract.skill_main_max_bytes) "SKILL.md for $skill is $($skillItem.Length) bytes; main-skill limit is $($contract.skill_main_max_bytes)"
    $skillContent = Get-Content -LiteralPath $skillPath -Raw -Encoding UTF8
    $frontmatterMatch = [regex]::Match($skillContent, '(?s)\A---\r?\n(?<frontmatter>.*?)\r?\n---')
    Assert-True $frontmatterMatch.Success "Invalid or missing frontmatter in skill: $skill"
    $frontmatter = $frontmatterMatch.Groups["frontmatter"].Value
    $nameMatch = [regex]::Match($frontmatter, '(?m)^name:\s*(?<name>[^\r\n]+)\s*$')
    $descriptionMatch = [regex]::Match($frontmatter, '(?m)^description:\s*(?<description>.+?)\s*$')
    Assert-True ($nameMatch.Success -and $nameMatch.Groups["name"].Value.Trim('"') -eq $skill) "Skill name does not match folder: $skill"
    Assert-True ($descriptionMatch.Success -and -not [string]::IsNullOrWhiteSpace($descriptionMatch.Groups["description"].Value)) "Missing skill description: $skill"

    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8
    foreach ($field in @("display_name", "short_description", "default_prompt")) {
        Assert-True ($metadata -match "(?m)^\s{2}$field`:\s*\S") "Missing interface.$field in agents/openai.yaml: $skill"
    }

    foreach ($markdownFile in @(Get-ChildItem -LiteralPath $skillRoot -Recurse -File -Filter "*.md")) {
        Assert-MarkdownRelativeLinks -Path $markdownFile.FullName
    }
}

$allowedBehaviorTags = @(Get-StringArray $contract.allowed_behavior_tags)
Assert-True ($allowedBehaviorTags.Count -gt 0) "Trigger contract has no behavior tags"
Assert-UniqueStrings $allowedBehaviorTags "Behavior tag catalog"
$definedBehaviorTags = @($contract.behavior_tag_definitions.PSObject.Properties.Name | ForEach-Object { [string]$_ })
Assert-UniqueStrings $definedBehaviorTags "Behavior tag definitions"
Assert-True ((($definedBehaviorTags | Sort-Object) -join "`n") -ceq (($allowedBehaviorTags | Sort-Object) -join "`n")) "Behavior tag definitions do not exactly match allowed behavior tags"
foreach ($tag in $allowedBehaviorTags) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$contract.behavior_tag_definitions.$tag)) "Behavior tag has an empty definition: $tag"
}

$peerSkills = @($contract.peer_skills)
$peerSkillNames = @($peerSkills | ForEach-Object { [string]$_.name })
Assert-True ($peerSkillNames.Count -gt 0) "Trigger contract has no peer-skill coexistence catalog"
Assert-UniqueStrings $peerSkillNames "Peer-skill catalog"
foreach ($peerSkill in $peerSkills) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$peerSkill.name)) "Peer-skill catalog contains an empty name"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$peerSkill.description)) "Peer-skill catalog contains an empty description: $($peerSkill.name)"
}

$strictRoutingCaseIds = @(Get-StringArray $contract.strict_routing_case_ids)
$strictReferenceCaseIds = @(Get-StringArray $contract.strict_reference_case_ids)
Assert-UniqueStrings $strictRoutingCaseIds "Strict routing case list"
Assert-UniqueStrings $strictReferenceCaseIds "Strict reference case list"

$cases = @($contract.cases)
Assert-True ($cases.Count -gt 0) "Trigger contract has no cases"
$seenCases = @{}
$positiveCoverage = @{}
$negativeCoverage = @{}
foreach ($skill in $requiredSkills) {
    $positiveCoverage[$skill] = 0
    $negativeCoverage[$skill] = 0
}

foreach ($case in $cases) {
    $caseId = [string]$case.id
    Assert-True (-not [string]::IsNullOrWhiteSpace($caseId)) "Trigger contract contains a case without an id"
    Assert-True ($caseId -match '^[a-z0-9][a-z0-9-]*$') "Invalid trigger case id: $caseId"
    Assert-True (-not $seenCases.ContainsKey($caseId)) "Duplicate trigger case id: $caseId"
    $seenCases[$caseId] = $case
    Assert-True (@("positive", "negative", "boundary", "behavior") -contains [string]$case.kind) "Invalid kind for trigger case $caseId`: $($case.kind)"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$case.request)) "Trigger case $caseId has an empty request"

    $expectedSkills = @(Get-StringArray $case.expected_skills)
    $forbiddenSkills = @(Get-StringArray $case.forbidden_skills)
    $availablePeerSkills = @(Get-StringArray $case.available_peer_skills)
    $expectedPeerSkills = @(Get-StringArray $case.expected_peer_skills)
    $forbiddenPeerSkills = @(Get-StringArray $case.forbidden_peer_skills)
    $expectedBehaviors = @(Get-StringArray $case.expected_behavior_tags)
    $forbiddenBehaviors = @(Get-StringArray $case.forbidden_behavior_tags)

    Assert-Disjoint $expectedSkills $forbiddenSkills "Case $caseId skill contract"
    Assert-Disjoint $expectedPeerSkills $forbiddenPeerSkills "Case $caseId peer-skill contract"
    Assert-Disjoint $expectedBehaviors $forbiddenBehaviors "Case $caseId behavior contract"

    foreach ($skill in @($expectedSkills + $forbiddenSkills)) {
        Assert-True ($requiredSkills -contains $skill) "Case $caseId references undeclared skill: $skill"
    }
    foreach ($skill in $expectedSkills) { $positiveCoverage[$skill]++ }
    foreach ($skill in $forbiddenSkills) { $negativeCoverage[$skill]++ }

    foreach ($peerSkill in @($availablePeerSkills + $expectedPeerSkills + $forbiddenPeerSkills)) {
        Assert-True ($peerSkillNames -contains $peerSkill) "Case $caseId references undeclared peer skill: $peerSkill"
    }
    foreach ($peerSkill in @($expectedPeerSkills + $forbiddenPeerSkills)) {
        Assert-True ($availablePeerSkills -contains $peerSkill) "Case $caseId constrains unavailable peer skill: $peerSkill"
    }

    foreach ($referenceSkill in $referenceEvaluationSkills) {
        $expectedProperty = "expected_$($referenceSkill.Replace('-', '_'))_references"
        $references = @(Get-StringArray $case.$expectedProperty)
        if ($references.Count -gt 0) {
            Assert-True ($expectedSkills -contains $referenceSkill) "Case $caseId expects $referenceSkill references without selecting the skill"
        }
        foreach ($reference in $references) {
            $referencePath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $referenceSkill) ("references\" + $reference)
            Assert-True (Test-Path -LiteralPath $referencePath -PathType Leaf) "Case $caseId references missing $referenceSkill file: $reference"
        }
    }

    foreach ($tag in @($expectedBehaviors + $forbiddenBehaviors)) {
        Assert-True ($allowedBehaviorTags -contains $tag) "Case $caseId uses undeclared behavior tag: $tag"
    }
}

foreach ($strictRoutingCaseId in $strictRoutingCaseIds) {
    Assert-True ($seenCases.ContainsKey($strictRoutingCaseId)) "Strict routing policy references missing case: $strictRoutingCaseId"
}
foreach ($strictReferenceCaseId in $strictReferenceCaseIds) {
    Assert-True ($seenCases.ContainsKey($strictReferenceCaseId)) "Strict reference policy references missing case: $strictReferenceCaseId"
    $strictReferenceCase = $seenCases[$strictReferenceCaseId]
    $selectedReferenceSkills = @($strictReferenceCase.expected_skills | ForEach-Object { [string]$_ } | Where-Object { $referenceEvaluationSkills -contains $_ })
    Assert-True ($selectedReferenceSkills.Count -gt 0) "Strict reference case selects no conditional-reference skill: $strictReferenceCaseId"
}

foreach ($skill in $requiredSkills) {
    Assert-True ($positiveCoverage[$skill] -gt 0) "Required skill has no positive route case: $skill"
    Assert-True ($negativeCoverage[$skill] -gt 0) "Required skill has no non-trigger case: $skill"
}

Write-Output "Routing contract valid: $($seenCases.Count) cases; $($strictRoutingCaseIds.Count) strict routing and $($strictReferenceCaseIds.Count) strict reference cases; $($requiredSkills.Count)/$($requiredSkills.Count) skills have positive and non-trigger coverage; structure, references, peer skills, and policy tags resolve."
