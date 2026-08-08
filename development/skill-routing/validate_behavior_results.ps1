param(
    [Parameter(Mandatory = $true)]
    [string]$ResultsPath,
    [string]$ProjectRoot,
    [switch]$FailOnUnexpectedSelections,
    [switch]$ShowWarnings
)

$ErrorActionPreference = "Stop"

function Get-TextSha256 {
    param(
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $algorithm.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$ResultsPath = (Resolve-Path -LiteralPath $ResultsPath).Path

function Get-StringArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { [string]$_ })
}

function Add-Failure {
    param(
        [System.Collections.Generic.List[string]]$Failures,
        [string]$Message
    )

    $Failures.Add($Message)
}

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null

$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$results = Get-Content -LiteralPath $ResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($results.schema_version -ne 1) {
    throw "Unsupported behavior result schema: $($results.schema_version)"
}

$requiredSkills = @(Get-StringArray $contract.required_skills)
$allowedBehaviorTags = @(Get-StringArray $contract.allowed_behavior_tags)
$candidateFiles = @(Join-Path $ProjectRoot "global\AGENTS.md")
foreach ($skill in $requiredSkills) {
    $skillRoot = Join-Path (Join-Path $ProjectRoot "skills") $skill
    $candidateFiles += @(Get-ChildItem -LiteralPath $skillRoot -Recurse -Force -File | Select-Object -ExpandProperty FullName)
}
$candidateRecords = @($candidateFiles | Sort-Object -Unique | ForEach-Object {
    $item = Get-Item -LiteralPath $_
    $relativePath = $item.FullName.Substring($ProjectRoot.Length + 1).Replace('\', '/')
    "$relativePath|$($item.Length)|$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash)"
})
$candidateFingerprint = Get-TextSha256 ($candidateRecords -join [Environment]::NewLine)
$inputRecords = @($contract.cases | ForEach-Object { "$($_.id)|$($_.request)" })
$inputRecords += @($contract.allowed_behavior_tags | ForEach-Object { "behavior|$_" })
$evaluationInputFingerprint = Get-TextSha256 ($inputRecords -join [Environment]::NewLine)
if ([string]$results.candidate_bundle_sha256 -ne $candidateFingerprint) {
    throw "Behavior result belongs to a different candidate bundle"
}
if ([string]$results.evaluation_input_sha256 -ne $evaluationInputFingerprint) {
    throw "Behavior result belongs to a different evaluation input set"
}
$contractById = @{}
foreach ($case in @($contract.cases)) {
    $contractById[[string]$case.id] = $case
}

$resultById = @{}
$failures = New-Object 'System.Collections.Generic.List[string]'
$warnings = New-Object 'System.Collections.Generic.List[string]'
foreach ($result in @($results.cases)) {
    $id = [string]$result.id
    if ([string]::IsNullOrWhiteSpace($id)) {
        Add-Failure $failures "Result contains a case without an id"
        continue
    }
    if ($resultById.ContainsKey($id)) {
        Add-Failure $failures "Duplicate result id: $id"
        continue
    }
    if (-not $contractById.ContainsKey($id)) {
        Add-Failure $failures "Unknown result id: $id"
        continue
    }
    $resultById[$id] = $result
}

foreach ($id in $contractById.Keys) {
    if (-not $resultById.ContainsKey($id)) {
        Add-Failure $failures "Missing behavior result: $id"
        continue
    }

    $case = $contractById[$id]
    $result = $resultById[$id]
    $expectedSkills = @(Get-StringArray $case.expected_skills)
    $forbiddenSkills = @(Get-StringArray $case.forbidden_skills)
    $selectedSkills = @(Get-StringArray $result.selected_skills)
    $expectedReferences = @(Get-StringArray $case.expected_change_governance_references)
    $selectedReferences = @(Get-StringArray $result.selected_change_governance_references)
    $expectedBehaviors = @(Get-StringArray $case.expected_behavior_tags)
    $forbiddenBehaviors = @(Get-StringArray $case.forbidden_behavior_tags)
    $selectedBehaviors = @(Get-StringArray $result.behavior_tags)

    foreach ($skill in $selectedSkills) {
        if ($requiredSkills -notcontains $skill) {
            Add-Failure $failures "$id selected an unknown skill: $skill"
        }
    }
    foreach ($skill in $expectedSkills) {
        if ($selectedSkills -notcontains $skill) {
            Add-Failure $failures "$id missed expected skill: $skill"
        }
    }
    foreach ($skill in $forbiddenSkills) {
        if ($selectedSkills -contains $skill) {
            Add-Failure $failures "$id selected forbidden skill: $skill"
        }
    }

    $unexpectedSkills = @($selectedSkills | Where-Object { $expectedSkills -notcontains $_ -and $forbiddenSkills -notcontains $_ })
    foreach ($skill in $unexpectedSkills) {
        $message = "$id selected an unspecified skill: $skill"
        if ($FailOnUnexpectedSelections) {
            Add-Failure $failures $message
        }
        else {
            $warnings.Add($message)
        }
    }

    foreach ($reference in $expectedReferences) {
        if ($selectedReferences -notcontains $reference) {
            Add-Failure $failures "$id missed expected change-governance reference: $reference"
        }
    }
    if ($selectedReferences.Count -gt 0 -and $selectedSkills -notcontains "change-governance") {
        Add-Failure $failures "$id selected change-governance references without selecting the skill"
    }

    foreach ($tag in $selectedBehaviors) {
        if ($allowedBehaviorTags -notcontains $tag) {
            Add-Failure $failures "$id selected an unknown behavior tag: $tag"
        }
    }
    foreach ($tag in $expectedBehaviors) {
        if ($selectedBehaviors -notcontains $tag) {
            Add-Failure $failures "$id missed expected behavior tag: $tag"
        }
    }
    foreach ($tag in $forbiddenBehaviors) {
        if ($selectedBehaviors -contains $tag) {
            Add-Failure $failures "$id selected forbidden behavior tag: $tag"
        }
    }

    $unexpectedBehaviors = @($selectedBehaviors | Where-Object { $expectedBehaviors -notcontains $_ -and $forbiddenBehaviors -notcontains $_ })
    if ($FailOnUnexpectedSelections) {
        foreach ($tag in $unexpectedBehaviors) {
            Add-Failure $failures "$id selected an unspecified behavior tag: $tag"
        }
    }
}

if ($warnings.Count -gt 0) {
    if ($ShowWarnings) {
        Write-Warning ($warnings -join [Environment]::NewLine)
    }
    else {
        Write-Warning "Behavior evaluation recorded $($warnings.Count) unspecified selections; they are informational. Use -ShowWarnings to list them or -FailOnUnexpectedSelections to make them blocking."
    }
}
if ($failures.Count -gt 0) {
    throw ("Behavior evaluation failed with $($failures.Count) violation(s):" + [Environment]::NewLine + ($failures -join [Environment]::NewLine))
}

Write-Output "Behavior evaluation valid: $($resultById.Count)/$($contractById.Count) cases satisfy all expected and forbidden routing/behavior constraints."
