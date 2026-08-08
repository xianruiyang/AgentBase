param(
    [string]$ProjectRoot,
    [string]$OutputRoot,
    [string]$PluginValidatorPath
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $PSScriptRoot "dist"
}
if ([string]::IsNullOrWhiteSpace($PluginValidatorPath)) {
    if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        throw "PluginValidatorPath is required when USERPROFILE is unavailable"
    }
    $PluginValidatorPath = Join-Path $env:USERPROFILE ".codex\skills\.system\plugin-creator\scripts\validate_plugin.py"
}

$routingValidator = Join-Path $ProjectRoot "development\skill-routing\validate_contract.ps1"
& $routingValidator -ProjectRoot $ProjectRoot | Out-Null

$contractPath = Join-Path $ProjectRoot "development\skill-routing\trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$templateRoot = Join-Path $PSScriptRoot "template\agentbase-core"
$templateManifestPath = Join-Path $templateRoot ".codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $templateManifestPath -PathType Leaf)) {
    throw "Plugin template manifest is missing: $templateManifestPath"
}
if (-not (Test-Path -LiteralPath $PluginValidatorPath -PathType Leaf)) {
    throw "Official plugin validator is missing: $PluginValidatorPath"
}

$sourceSkillsRoot = Join-Path $ProjectRoot "skills"
$sourceLinks = @(Get-ChildItem -LiteralPath $sourceSkillsRoot -Recurse -Force | Where-Object {
    ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
})
if ($sourceLinks.Count -gt 0) {
    throw "Skill source contains reparse points; refusing to package: $($sourceLinks[0].FullName)"
}

$outputParent = Split-Path -Parent $OutputRoot
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $OutputRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
}
$OutputRoot = (Resolve-Path -LiteralPath $OutputRoot).Path

$pluginName = "agentbase-core"
$targetRoot = Join-Path $OutputRoot $pluginName
$stageRoot = Join-Path $OutputRoot (".stage-" + [guid]::NewGuid().ToString("N"))
$oldRoot = Join-Path $OutputRoot (".previous-" + [guid]::NewGuid().ToString("N"))

try {
    Copy-Item -LiteralPath $templateRoot -Destination $stageRoot -Recurse -Force
    $stageSkillsRoot = Join-Path $stageRoot "skills"
    if (-not (Test-Path -LiteralPath $stageSkillsRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $stageSkillsRoot | Out-Null
    }
    $placeholderPath = Join-Path $stageSkillsRoot ".gitkeep"
    if (Test-Path -LiteralPath $placeholderPath -PathType Leaf) {
        Remove-Item -LiteralPath $placeholderPath -Force
    }
    foreach ($skill in @($contract.required_skills)) {
        $sourceSkill = Join-Path $sourceSkillsRoot ([string]$skill)
        $targetSkill = Join-Path $stageSkillsRoot ([string]$skill)
        if (-not (Test-Path -LiteralPath (Join-Path $sourceSkill "SKILL.md") -PathType Leaf)) {
            throw "Required skill source is missing: $skill"
        }
        Copy-Item -LiteralPath $sourceSkill -Destination $targetSkill -Recurse -Force
    }

    $payloadFiles = @(Get-ChildItem -LiteralPath $stageRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($stageRoot.Length + 1).Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            bytes = $_.Length
        }
    })
    $buildManifest = [ordered]@{
        schema_version = 1
        plugin = $pluginName
        source = $ProjectRoot
        skill_count = @($contract.required_skills).Count
        files = $payloadFiles
    } | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $stageRoot "build-manifest.json"), $buildManifest + [Environment]::NewLine, $utf8NoBom)

    & python -X utf8 $PluginValidatorPath $stageRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Official plugin validation failed"
    }

    if (Test-Path -LiteralPath $targetRoot) {
        Move-Item -LiteralPath $targetRoot -Destination $oldRoot
    }
    try {
        Move-Item -LiteralPath $stageRoot -Destination $targetRoot
    }
    catch {
        if (Test-Path -LiteralPath $oldRoot) {
            Move-Item -LiteralPath $oldRoot -Destination $targetRoot
        }
        throw
    }
    if (Test-Path -LiteralPath $oldRoot) {
        Remove-Item -LiteralPath $oldRoot -Recurse -Force
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}

Write-Output $targetRoot
