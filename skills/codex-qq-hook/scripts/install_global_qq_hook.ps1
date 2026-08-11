param(
    [string]$ProjectRoot,
    [string]$AppId,
    [ValidateSet("user", "group", "channel")]
    [string]$TargetType,
    [string]$OpenId,
    [string]$GroupOpenId,
    [string]$ChannelId,
    [switch]$ForceSettings
)

$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$skillRoot = Split-Path -Parent $PSScriptRoot
$skillsDir = Split-Path -Parent $skillRoot
$codexHome = Split-Path -Parent $skillsDir
$globalHooksPath = Join-Path $codexHome "hooks.json"
$globalSettingsPath = Join-Path $codexHome "qq-hook-global-settings.json"
$configTomlPath = Join-Path $codexHome "config.toml"
$stopScript = Join-Path $PSScriptRoot "codex_stop_qq_notify.ps1"
$templatePath = Join-Path $skillRoot "templates\qq-hook-settings.template.json"
$globalTemplatePath = Join-Path $skillRoot "templates\qq-hook-global-settings.template.json"

if (-not (Test-Path -LiteralPath $stopScript)) {
    throw "Global Stop hook script not found: $stopScript"
}
if (-not (Test-Path -LiteralPath $templatePath)) {
    throw "Settings template not found: $templatePath"
}
if (-not (Test-Path -LiteralPath $globalTemplatePath)) {
    throw "Global settings template not found: $globalTemplatePath"
}

function Set-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
        return
    }
    $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
}

function Test-QqStopHandler {
    param([object]$Handler)

    foreach ($propertyName in @("command", "commandWindows")) {
        if ($Handler.PSObject.Properties.Name -contains $propertyName) {
            $commandText = [string]$Handler.$propertyName
            if ($commandText -match '(?i)(^|[\\/])codex_stop_qq_notify\.ps1(?:["'']|\s|$)') {
                return $true
            }
        }
    }
    return $false
}

function Write-JsonAtomically {
    param(
        [string]$Path,
        [object]$Value
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporaryPath = Join-Path $directory ("." + [IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $text = ($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine
        [IO.File]::WriteAllText($temporaryPath, $text, [Text.UTF8Encoding]::new($false))
        Get-Content -LiteralPath $temporaryPath -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
        [IO.File]::Move($temporaryPath, $Path, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

if (Test-Path -LiteralPath $globalHooksPath -PathType Leaf) {
    try {
        $hooksDocument = Get-Content -LiteralPath $globalHooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Existing hooks.json is invalid; refusing to replace it: $($_.Exception.Message)"
    }
}
else {
    $hooksDocument = [pscustomobject]@{}
}
if ($null -eq $hooksDocument -or $hooksDocument -isnot [pscustomobject]) {
    throw "Existing hooks.json must contain a JSON object"
}
if (-not ($hooksDocument.PSObject.Properties.Name -contains "hooks")) {
    Set-ObjectProperty -Object $hooksDocument -Name "hooks" -Value ([pscustomobject]@{})
}
if ($null -eq $hooksDocument.hooks -or $hooksDocument.hooks -isnot [pscustomobject]) {
    throw "Existing hooks.json hooks field must contain a JSON object"
}

$remainingStopGroups = [Collections.Generic.List[object]]::new()
if ($hooksDocument.hooks.PSObject.Properties.Name -contains "Stop") {
    foreach ($group in @($hooksDocument.hooks.Stop)) {
        if ($null -eq $group -or -not ($group.PSObject.Properties.Name -contains "hooks")) {
            $remainingStopGroups.Add($group)
            continue
        }
        $originalHandlers = @($group.hooks)
        $remainingHandlers = @($originalHandlers | Where-Object { -not (Test-QqStopHandler -Handler $_) })
        $removedCount = $originalHandlers.Count - $remainingHandlers.Count
        if ($removedCount -eq 0) {
            $remainingStopGroups.Add($group)
            continue
        }
        if ($remainingHandlers.Count -gt 0) {
            Set-ObjectProperty -Object $group -Name "hooks" -Value $remainingHandlers
            $remainingStopGroups.Add($group)
        }
    }
}

$command = "pwsh.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$stopScript`""
$qqStopGroup = [pscustomobject][ordered]@{
    hooks = @(
        [pscustomobject][ordered]@{
            type = "command"
            command = $command
            commandWindows = $command
            timeout = 30
            statusMessage = "Sending QQ completion notification"
        }
    )
}
$remainingStopGroups.Add($qqStopGroup)
Set-ObjectProperty -Object $hooksDocument.hooks -Name "Stop" -Value $remainingStopGroups.ToArray()
Write-JsonAtomically -Path $globalHooksPath -Value $hooksDocument

function Enable-HooksFeature {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        "[features]`nhooks = true`n" | Set-Content -LiteralPath $Path -Encoding UTF8
        return
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $lines.Add($line)
    }

    $featuresStart = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[features\]\s*$') {
            $featuresStart = $i
            break
        }
    }

    if ($featuresStart -lt 0) {
        if ($lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($lines[$lines.Count - 1])) {
            $lines.Add("")
        }
        $lines.Add("[features]")
        $lines.Add("hooks = true")
        [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.UTF8Encoding]::new($false))
        return
    }

    $sectionEnd = $lines.Count
    for ($i = $featuresStart + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[[^\]]+\]\s*$') {
            $sectionEnd = $i
            break
        }
    }

    for ($i = $featuresStart + 1; $i -lt $sectionEnd; $i++) {
        if ($lines[$i] -match '^\s*hooks\s*=') {
            $lines[$i] = "hooks = true"
            [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.UTF8Encoding]::new($false))
            return
        }
    }

    $lines.Insert($featuresStart + 1, "hooks = true")
    [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.UTF8Encoding]::new($false))
}

Enable-HooksFeature -Path $configTomlPath

if (-not (Test-Path -LiteralPath $globalSettingsPath)) {
    Copy-Item -LiteralPath $globalTemplatePath -Destination $globalSettingsPath -Force
}
$globalSettings = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [string]::IsNullOrWhiteSpace($AppId)) {
    $globalSettings.bot.app_id = $AppId
}
if (-not [string]::IsNullOrWhiteSpace($TargetType)) {
    $globalSettings.bot.target_type = $TargetType
}
if (-not [string]::IsNullOrWhiteSpace($OpenId)) {
    $globalSettings.bot.openid = $OpenId
}
if (-not [string]::IsNullOrWhiteSpace($GroupOpenId)) {
    $globalSettings.bot.group_openid = $GroupOpenId
}
if (-not [string]::IsNullOrWhiteSpace($ChannelId)) {
    $globalSettings.bot.channel_id = $ChannelId
}
$globalSettings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $globalSettingsPath -Encoding UTF8
Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Get-Location).Path
} else {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}

$settingsPath = Join-Path $ProjectRoot ".codex\qq-hook-settings.json"
if ($ForceSettings -or -not (Test-Path -LiteralPath $settingsPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $settingsPath) | Out-Null
    $settings = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}
Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null

Write-Output "Installed global QQ hook:"
Write-Output "  global hooks: $globalHooksPath"
Write-Output "  global bot settings: $globalSettingsPath"
Write-Output "  hooks feature: $configTomlPath"
Write-Output "  workspace settings: $settingsPath"
Write-Output "Next: set QQ_BOT_APP_SECRET as a user environment variable, fill global bot settings, trust the global hook if Codex asks, and add thread IDs to workspace enabled_thread_ids."
