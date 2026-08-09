param(
    [string]$ProjectRoot,
    [string]$RetainedTestRootToClean
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$sandboxRoot = Join-Path $ProjectRoot "development\codex-deployment\sandbox"
$testRoot = Join-Path $sandboxRoot ("portable-settings-test-" + [guid]::NewGuid().ToString("N"))
$codexRoot = Join-Path $testRoot "codex"
$manage = Join-Path $ProjectRoot "development\codex-deployment\manage_agentbase.ps1"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$succeeded = $false

function Write-FixtureText {
    param(
        [string]$Path,
        [string]$Text
    )

    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Remove-TestRootSafely {
    param(
        [string]$Path
    )

    $approvedRoot = [IO.Path]::GetFullPath($sandboxRoot).TrimEnd('\') + '\'
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not $resolvedPath.StartsWith($approvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing sandbox cleanup outside approved root: $resolvedPath"
    }
    if (-not (Split-Path -Leaf $resolvedPath).StartsWith("portable-settings-test-", [StringComparison]::Ordinal)) {
        throw "Refusing sandbox cleanup for an unrelated directory: $resolvedPath"
    }
    if (Test-Path -LiteralPath $resolvedPath) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
}

if (-not [string]::IsNullOrWhiteSpace($RetainedTestRootToClean)) {
    Remove-TestRootSafely -Path $RetainedTestRootToClean
}

try {
    New-Item -ItemType Directory -Path (Join-Path $codexRoot "skills\user-skill") -Force | Out-Null
    Write-FixtureText -Path (Join-Path $codexRoot "AGENTS.md") -Text ("old agents" + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "config.toml") -Text ((@(
        'model = "old-model"'
        '[mcp_servers.keep]'
        'command = "keep"'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "hooks.json") -Text ((@(
        '{'
        '  "hooks": {}'
        '}'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Write-FixtureText -Path (Join-Path $codexRoot "skills\user-skill\SKILL.md") -Text ((@(
        '---'
        'name: user-skill'
        'description: keep'
        '---'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)

    $originalAgentsHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash
    $originalConfigHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash
    $originalHooksHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash

    $defaultPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot
    if ([bool]$defaultPublish.portable_settings_installed) {
        throw "Default publish unexpectedly installed portable settings"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash -ne $originalConfigHash) {
        throw "Default publish changed config.toml"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash -ne $originalHooksHash) {
        throw "Default publish changed hooks.json"
    }
    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $defaultPublish.backup_path | Out-Null

    $settingsPublish = & $manage -Action Publish -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -InstallPortableSettings
    if (-not [bool]$settingsPublish.portable_settings_installed) {
        throw "Portable-settings publish did not report settings installation"
    }
    $sourceConfigHash = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "global\config.toml") -Algorithm SHA256).Hash
    $installedConfigHash = (Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash
    if ($sourceConfigHash -ne $installedConfigHash) {
        throw "Installed config.toml does not match the portable source"
    }
    $installedHooksText = Get-Content -LiteralPath (Join-Path $codexRoot "hooks.json") -Raw -Encoding UTF8
    if ($installedHooksText.Contains("{{CODEX_ROOT}}")) {
        throw "Installed hooks contain an unresolved placeholder"
    }
    $installedHooks = $installedHooksText | ConvertFrom-Json
    $firstCommand = [string]$installedHooks.hooks.UserPromptSubmit[0].hooks[0].commandWindows
    if (-not $firstCommand.Contains($codexRoot)) {
        throw "Installed hooks do not reference the selected Codex root"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\user-skill\SKILL.md") -PathType Leaf)) {
        throw "Unrelated user skill was removed"
    }
    $manifest = Get-Content -LiteralPath (Join-Path $settingsPublish.backup_path "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifestTargets = @($manifest.targets.relative_path | Sort-Object)
    if ($manifestTargets -notcontains "config.toml" -or $manifestTargets -notcontains "hooks.json") {
        throw "Portable settings are missing from the rollback manifest"
    }

    & $manage -Action Rollback -ProjectRoot $ProjectRoot -CodexRoot $codexRoot -BackupPath $settingsPublish.backup_path | Out-Null
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "AGENTS.md") -Algorithm SHA256).Hash -ne $originalAgentsHash) {
        throw "Rollback did not restore AGENTS.md"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "config.toml") -Algorithm SHA256).Hash -ne $originalConfigHash) {
        throw "Rollback did not restore config.toml"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $codexRoot "hooks.json") -Algorithm SHA256).Hash -ne $originalHooksHash) {
        throw "Rollback did not restore hooks.json"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $codexRoot "skills\user-skill\SKILL.md") -PathType Leaf)) {
        throw "Rollback removed the unrelated user skill"
    }

    $succeeded = $true
    [pscustomobject]@{
        default_publish_preserved_settings = $true
        explicit_publish_installed_settings = $true
        hooks_root_resolved = $true
        rollback_restored_settings = $true
        unrelated_skill_preserved = $true
        explicit_target_count = $manifestTargets.Count
    }
}
finally {
    if ($succeeded -and (Test-Path -LiteralPath $testRoot)) {
        Remove-TestRootSafely -Path $testRoot
    }
    elseif (-not $succeeded) {
        Write-Warning "Deployment test sandbox retained for diagnosis: $testRoot"
    }
}
