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

function Write-FixtureText {
    param(
        [string]$Path,
        [string]$Text
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-qq-installer-test-" + [guid]::NewGuid().ToString("N"))
$resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a test directory outside the system temp root: $resolvedTestRoot"
}

$sourceSkillRoot = Split-Path -Parent $PSScriptRoot
$codexRoot = Join-Path $resolvedTestRoot "codex"
$installedSkillRoot = Join-Path $resolvedTestRoot "plugin-cache\agentbase-core\skills\codex-qq-hook"
$workspaceRoot = Join-Path $resolvedTestRoot "workspace"
$hooksPath = Join-Path $codexRoot "hooks.json"
$configPath = Join-Path $codexRoot "config.toml"
$globalSettingsPath = Join-Path $codexRoot "qq-hook-global-settings.json"

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $installedSkillRoot "scripts") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $installedSkillRoot "templates") | Out-Null
    New-Item -ItemType Directory -Force -Path $workspaceRoot | Out-Null
    foreach ($name in @("install_global_qq_hook.ps1", "codex_stop_qq_notify.ps1", "resolve_codex_home.ps1")) {
        Copy-Item -LiteralPath (Join-Path $sourceSkillRoot "scripts\$name") -Destination (Join-Path $installedSkillRoot "scripts\$name")
    }
    foreach ($name in @("qq-hook-settings.template.json", "qq-hook-global-settings.template.json")) {
        Copy-Item -LiteralPath (Join-Path $sourceSkillRoot "templates\$name") -Destination (Join-Path $installedSkillRoot "templates\$name")
    }

    $hooksFixture = @{
        description = "preserve"
        custom_root = @{ keep = $true }
        hooks = @{
            UserPromptSubmit = @(@{ hooks = @(@{ type = "command"; command = "custom-prompt"; commandWindows = "custom-prompt" }) })
            Stop = @(
                @{
                    matcher = "keep-matcher"
                    hooks = @(
                        @{ type = "command"; command = "custom-stop"; commandWindows = "custom-stop" }
                        @{ type = "command"; command = 'powershell -File "C:\old\codex_stop_qq_notify.ps1"'; commandWindows = 'powershell -File "C:\old\codex_stop_qq_notify.ps1"' }
                    )
                }
                @{ hooks = @(@{ type = "command"; command = 'powershell -File "C:\older\codex_stop_qq_notify.ps1"'; commandWindows = 'powershell -File "C:\older\codex_stop_qq_notify.ps1"' }) }
            )
        }
    }
    Write-FixtureText -Path $hooksPath -Text (($hooksFixture | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
    Write-FixtureText -Path $configPath -Text ((@(
        'model = "keep-model"'
        ''
        '[features]'
        'hooks = false'
        'keep = "yes"'
        ''
        '[desktop]'
        'keep = true'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    $settingsFixture = @{
        custom_root = "keep"
        bot = @{
            app_id = "existing-app"
            target_type = "group"
            openid = ""
            group_openid = "existing-group"
            channel_id = ""
            is_wakeup = $false
        }
    }
    Write-FixtureText -Path $globalSettingsPath -Text (($settingsFixture | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    $installer = Join-Path $installedSkillRoot "scripts\install_global_qq_hook.ps1"
    & $installer -ProjectRoot $workspaceRoot -CodexRoot $codexRoot | Out-Null

    $installedHooks = Get-Content -LiteralPath $hooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$installedHooks.description -eq "preserve" -and [bool]$installedHooks.custom_root.keep) "installer changed unrelated top-level hook fields"
    Assert-True (@($installedHooks.hooks.UserPromptSubmit).Count -eq 1) "installer changed an unrelated hook event"
    $stopGroups = @($installedHooks.hooks.Stop)
    $allStopHandlers = @($stopGroups | ForEach-Object { @($_.hooks) })
    $qqHandlers = @($allStopHandlers | Where-Object { ([string]$_.command) -match 'codex_stop_qq_notify\.ps1' })
    Assert-True ($qqHandlers.Count -eq 1) "installer did not converge old QQ handlers to one handler"
    Assert-True (([string]$qqHandlers[0].command).StartsWith("pwsh.exe -NoLogo -NoProfile -NonInteractive", [StringComparison]::Ordinal)) "installer did not use the PowerShell 7 hook command"
    Assert-True (([string]$qqHandlers[0].command).Contains("-CodexRoot `"$codexRoot`"")) "installer did not bind the hook to the explicit Codex root"
    Assert-True (@($allStopHandlers | Where-Object { [string]$_.command -eq "custom-stop" }).Count -eq 1) "installer removed an unrelated Stop handler"
    Assert-True (@($stopGroups | Where-Object { [string]$_.matcher -eq "keep-matcher" }).Count -eq 1) "installer removed an unrelated Stop matcher"

    $configText = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
    Assert-True ($configText -match '(?m)^hooks = true\r?$') "installer did not enable the hooks feature"
    Assert-True ($configText.Contains('keep = "yes"') -and $configText.Contains('keep = true')) "installer changed unrelated config.toml settings"
    $globalSettings = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$globalSettings.custom_root -eq "keep" -and [string]$globalSettings.bot.target_type -eq "group") "installer changed unrelated global QQ settings"

    $firstHooksHash = (Get-FileHash -LiteralPath $hooksPath -Algorithm SHA256).Hash
    & $installer -ProjectRoot $workspaceRoot -CodexRoot $codexRoot | Out-Null
    $secondHooksHash = (Get-FileHash -LiteralPath $hooksPath -Algorithm SHA256).Hash
    Assert-True ($firstHooksHash -eq $secondHooksHash) "installer is not idempotent"

    & $installer -ProjectRoot $workspaceRoot -CodexRoot $codexRoot -AppId "new-app" | Out-Null
    $updatedSettings = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$updatedSettings.bot.app_id -eq "new-app" -and [string]$updatedSettings.bot.target_type -eq "group") "targeted AppID update changed another bot field"

    Write-Output "Global QQ hook installer tests passed: 6/6"
}
finally {
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
