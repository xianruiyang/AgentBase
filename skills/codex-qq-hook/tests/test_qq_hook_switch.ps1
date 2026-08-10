param()

$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-qq-hook-test-" + [Guid]::NewGuid().ToString("N"))
$resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a test directory outside the system temp root: $resolvedTestRoot"
}

$scriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\qq_hook_switch.ps1"
$configPath = Join-Path $resolvedTestRoot ".codex\qq-hook-settings.json"

try {
    New-Item -ItemType Directory -Path $resolvedTestRoot | Out-Null

    $missingStatus = & $scriptPath status -ProjectRoot $resolvedTestRoot -Id "thread-a" | Out-String | ConvertFrom-Json
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $resolvedTestRoot ".codex"))) "status created the .codex directory"
    Assert-True (-not $missingStatus.config_exists) "status must report a missing configuration"
    Assert-True (-not $missingStatus.default_enabled) "the in-memory default must remain disabled"
    Assert-True (-not $missingStatus.thread_enabled) "a missing configuration must not enable the thread"
    Assert-True (-not $missingStatus.thread_disabled) "a missing configuration must not disable the thread"

    & $scriptPath enable -ProjectRoot $resolvedTestRoot -Id "thread-a" | Out-Null
    Assert-True (Test-Path -LiteralPath $configPath -PathType Leaf) "enable did not create the configuration"
    $enabled = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json
    Assert-True (@($enabled.enabled_thread_ids) -contains "thread-a") "enable did not add the thread"
    Assert-True (@($enabled.disabled_thread_ids) -notcontains "thread-a") "enable did not remove the disabled entry"

    $sentinelTime = [DateTime]::SpecifyKind([DateTime]::Parse("2001-02-03T04:05:06"), [DateTimeKind]::Utc)
    [IO.File]::SetLastWriteTimeUtc($configPath, $sentinelTime)
    $existingStatus = & $scriptPath status -ProjectRoot $resolvedTestRoot -Id "thread-a" | Out-String | ConvertFrom-Json
    Assert-True ($existingStatus.config_exists) "status must report the existing configuration"
    Assert-True ($existingStatus.thread_enabled) "status did not report the enabled thread"
    Assert-True (-not $existingStatus.thread_disabled) "status incorrectly reported the thread as disabled"
    Assert-True ([IO.File]::GetLastWriteTimeUtc($configPath) -eq $sentinelTime) "status rewrote the existing configuration"

    & $scriptPath disable -ProjectRoot $resolvedTestRoot -Id "thread-a" | Out-Null
    $disabled = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json
    Assert-True (@($disabled.enabled_thread_ids) -notcontains "thread-a") "disable did not remove the enabled entry"
    Assert-True (@($disabled.disabled_thread_ids) -contains "thread-a") "disable did not add the disabled entry"

    Write-Output "QQ hook switch tests passed: 3/3"
}
finally {
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
