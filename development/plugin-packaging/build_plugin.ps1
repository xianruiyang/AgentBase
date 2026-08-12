param(
    [string]$ProjectRoot,
    [string]$OutputRoot,
    [string]$PluginValidatorPath,
    [switch]$SkipOfficialValidation
)

$ErrorActionPreference = "Stop"

$payloadContractPath = Join-Path (Split-Path -Parent $PSScriptRoot) "common\payload_contract.ps1"
. $payloadContractPath

function Get-TextSha256 {
    param(
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "")
    }
    finally {
        $algorithm.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$outputRootWasSpecified = -not [string]::IsNullOrWhiteSpace($OutputRoot)
if ($SkipOfficialValidation -and -not $outputRootWasSpecified) {
    throw "SkipOfficialValidation requires an explicit isolated OutputRoot; the marketplace dist must remain officially validated"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $PSScriptRoot "dist"
}
if (-not $SkipOfficialValidation -and [string]::IsNullOrWhiteSpace($PluginValidatorPath)) {
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
if (-not $SkipOfficialValidation -and -not (Test-Path -LiteralPath $PluginValidatorPath -PathType Leaf)) {
    throw "Official plugin validator is missing: $PluginValidatorPath"
}

$sourceSkillsRoot = Join-Path $ProjectRoot "skills"

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
    Copy-AgentBasePayloadDirectory -SourcePath $templateRoot -DestinationPath $stageRoot
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
        Copy-AgentBasePayloadDirectory -SourcePath $sourceSkill -DestinationPath $targetSkill
    }

    $sourceSkillRecords = @($contract.required_skills | ForEach-Object {
        $skillName = [string]$_
        $sourceSkill = Join-Path $sourceSkillsRoot $skillName
        Get-AgentBasePayloadFiles -Root $sourceSkill | ForEach-Object {
            $relativePath = $_.FullName.Substring($sourceSkillsRoot.Length + 1).Replace('\', '/')
            "$relativePath|$($_.Length)|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
        }
    } | Sort-Object)
    $sourceSkillFingerprint = Get-TextSha256 ($sourceSkillRecords -join [Environment]::NewLine)

    $payloadFiles = @(Get-AgentBasePayloadFiles -Root $stageRoot | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($stageRoot.Length + 1).Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            bytes = $_.Length
        }
    })
    $buildManifest = [ordered]@{
        schema_version = 2
        plugin = $pluginName
        skill_count = @($contract.required_skills).Count
        source_skill_bundle_sha256 = $sourceSkillFingerprint
        payload_contract = "development/common/payload_contract.ps1"
        official_plugin_validation = -not [bool]$SkipOfficialValidation
        files = $payloadFiles
    } | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $stageRoot "build-manifest.json"), $buildManifest + [Environment]::NewLine, $utf8NoBom)

    $forbiddenArtifacts = @(Get-ChildItem -LiteralPath $stageRoot -Recurse -Force | Where-Object {
        $relativePath = $_.FullName.Substring($stageRoot.Length + 1).Replace('\', '/')
        Test-AgentBaseExcludedArtifact -RelativePath $relativePath
    })
    if ($forbiddenArtifacts.Count -gt 0) {
        throw "Plugin package contains an excluded runtime artifact: $($forbiddenArtifacts[0].FullName)"
    }

    if (-not $SkipOfficialValidation) {
        $validatorOutput = @(& python -X utf8 $PluginValidatorPath $stageRoot 2>&1)
        $validatorExitCode = $LASTEXITCODE
        if ($validatorExitCode -ne 0) {
            throw ("Official plugin validation failed:" + [Environment]::NewLine + ($validatorOutput -join [Environment]::NewLine))
        }
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
