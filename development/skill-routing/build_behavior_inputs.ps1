param(
    [string]$ProjectRoot,
    [string]$OutputPath
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

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path ([IO.Path]::GetTempPath()) "AgentBase-skill-routing-inputs.json"
}
$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory) -or -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Output directory must already exist: $outputDirectory"
}

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null

$contractPath = Join-Path $PSScriptRoot "trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$skillSources = @($contract.required_skills | ForEach-Object {
    [ordered]@{
        name = [string]$_
        skill_path = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") ([string]$_)) "SKILL.md"
        metadata_path = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") ([string]$_)) "agents\openai.yaml"
    }
})
$cases = @($contract.cases | ForEach-Object {
    [ordered]@{
        id = [string]$_.id
        request = [string]$_.request
    }
})

$candidateFiles = @(Join-Path $ProjectRoot "global\AGENTS.md")
foreach ($skill in @($contract.required_skills)) {
    $skillRoot = Join-Path (Join-Path $ProjectRoot "skills") ([string]$skill)
    $candidateFiles += @(Get-ChildItem -LiteralPath $skillRoot -Recurse -Force -File | Select-Object -ExpandProperty FullName)
}
$candidateRecords = @($candidateFiles | Sort-Object -Unique | ForEach-Object {
    $item = Get-Item -LiteralPath $_
    $relativePath = $item.FullName.Substring($ProjectRoot.Length + 1).Replace('\', '/')
    "$relativePath|$($item.Length)|$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash)"
})
$candidateFingerprint = Get-TextSha256 ($candidateRecords -join [Environment]::NewLine)
$inputRecords = @($cases | ForEach-Object { "$($_.id)|$($_.request)" })
$inputRecords += @($contract.allowed_behavior_tags | ForEach-Object { "behavior|$_" })
$evaluationInputFingerprint = Get-TextSha256 ($inputRecords -join [Environment]::NewLine)

$payload = [ordered]@{
    schema_version = 1
    purpose = "Blind forward evaluation of candidate AgentBase skill routing and global behavior."
    candidate_global_path = Join-Path $ProjectRoot "global\AGENTS.md"
    candidate_bundle_sha256 = $candidateFingerprint
    evaluation_input_sha256 = $evaluationInputFingerprint
    skill_sources = $skillSources
    prohibited_source = $contractPath
    instructions = @(
        "Read only candidate_global_path and the listed skill_path/metadata_path files."
        "Do not read prohibited_source or infer hidden expected answers from repository tests."
        "For every case, predict the skills that must be loaded before task actions, the change-governance references that must be read, and all applicable behavior tags."
        "Do not execute the requests and do not modify files."
        "Return one result for every id using the declared output schema."
    )
    allowed_behavior_tags = @($contract.allowed_behavior_tags)
    output_schema = [ordered]@{
        schema_version = 1
        evaluator = "free-form identifier"
        candidate_bundle_sha256 = $candidateFingerprint
        evaluation_input_sha256 = $evaluationInputFingerprint
        cases = @(
            [ordered]@{
                id = "case id"
                selected_skills = @("skill-name")
                selected_change_governance_references = @("reference.md")
                behavior_tags = @("allowed_behavior_tag")
                note = "one concise rationale"
            }
        )
    }
    cases = $cases
}

$json = $payload | ConvertTo-Json -Depth 8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($OutputPath, $json + [Environment]::NewLine, $utf8NoBom)
Write-Output (Resolve-Path -LiteralPath $OutputPath).Path
