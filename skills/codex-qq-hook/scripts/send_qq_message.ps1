[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("enable", "disable", "status", "send")]
    [string]$Action,

    [string]$Message,
    [string]$Reason,
    [string]$ProjectRoot,
    [string]$CodexRoot,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "resolve_codex_home.ps1")
. (Join-Path $PSScriptRoot "qq_notify_runtime.ps1")

$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$codexHome = Resolve-AgentBaseCodexHome -RequestedRoot $CodexRoot
$globalSettingsPath = Join-Path $codexHome "qq-hook-global-settings.json"
$globalDebugPath = Join-Path $codexHome "qq-hook-debug.jsonl"
$skillRoot = Split-Path -Parent $PSScriptRoot
$globalTemplatePath = Join-Path $skillRoot "templates\qq-hook-global-settings.template.json"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Get-Location).Path
}
else {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}
$workspaceDebugPath = Join-Path $ProjectRoot ".codex\qq-hook-debug.jsonl"

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

function Read-GlobalSettings {
    if (-not (Test-Path -LiteralPath $globalSettingsPath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-DirectSendEnabled {
    param($Settings)

    if ($null -eq $Settings -or -not ($Settings.PSObject.Properties.Name -contains "direct_send")) {
        return $false
    }
    if ($null -eq $Settings.direct_send -or -not ($Settings.direct_send.PSObject.Properties.Name -contains "enabled")) {
        return $false
    }
    return [bool]$Settings.direct_send.enabled
}

function Get-SecretConfigured {
    if (-not [string]::IsNullOrWhiteSpace($env:QQ_BOT_APP_SECRET)) {
        return $true
    }
    foreach ($scope in @("User", "Machine")) {
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("QQ_BOT_APP_SECRET", $scope))) {
            return $true
        }
    }
    return $false
}

function Get-GlobalBotTargetType {
    param($Bot)

    if ($null -eq $Bot) {
        return "user"
    }
    return [string](Select-AgentBaseQqConfigValue $Bot.target_type $null "user")
}

function Test-GlobalBotTargetConfigured {
    param($Bot)

    if ($null -eq $Bot) {
        return $false
    }
    $targetType = Get-GlobalBotTargetType $Bot
    switch ($targetType.ToLowerInvariant()) {
        { $_ -in @("user", "c2c", "private") } { return [bool](Test-AgentBaseQqConfigValue $Bot.openid) }
        { $_ -in @("group", "qq_group") } { return [bool](Test-AgentBaseQqConfigValue $Bot.group_openid) }
        { $_ -in @("channel", "guild_channel") } { return [bool](Test-AgentBaseQqConfigValue $Bot.channel_id) }
        default { return $false }
    }
}

function Write-DirectStatus {
    param($Settings)

    $bot = if ($null -ne $Settings -and $Settings.PSObject.Properties.Name -contains "bot") { $Settings.bot } else { $null }
    [ordered]@{
        config_exists = [bool](Test-Path -LiteralPath $globalSettingsPath -PathType Leaf)
        config_path = $globalSettingsPath
        direct_send_enabled = [bool](Test-DirectSendEnabled $Settings)
        app_id_configured = [bool](Test-AgentBaseQqConfigValue $bot.app_id)
        target_type = if ($null -ne $bot) { Get-GlobalBotTargetType $bot } else { $null }
        target_configured = [bool](Test-GlobalBotTargetConfigured $bot)
        app_secret_configured = [bool](Get-SecretConfigured)
    } | ConvertTo-Json -Depth 10
}

$settings = Read-GlobalSettings
if ($Action -eq "status") {
    Write-DirectStatus $settings
    return
}

if ($Action -in @("enable", "disable")) {
    if ($null -eq $settings) {
        if ($Action -eq "disable") {
            Write-DirectStatus $null
            return
        }
        if (-not (Test-Path -LiteralPath $globalTemplatePath -PathType Leaf)) {
            throw "Global QQ settings template not found: $globalTemplatePath"
        }
        $settings = Get-Content -LiteralPath $globalTemplatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    if (-not ($settings.PSObject.Properties.Name -contains "direct_send") -or $null -eq $settings.direct_send) {
        Set-ObjectProperty -Object $settings -Name "direct_send" -Value ([pscustomobject]@{ enabled = $false })
    }
    Set-ObjectProperty -Object $settings.direct_send -Name "enabled" -Value ($Action -eq "enable")
    Write-JsonAtomically -Path $globalSettingsPath -Value $settings
    Write-DirectStatus $settings
    return
}

if ($null -eq $settings) {
    throw "Global QQ settings do not exist: $globalSettingsPath"
}
if (-not (Test-DirectSendEnabled $settings)) {
    throw "Direct QQ sending is disabled; enable it explicitly before sending"
}
if ([string]::IsNullOrWhiteSpace($Message)) {
    throw "send requires -Message"
}
if ([string]::IsNullOrWhiteSpace($Reason)) {
    throw "send requires a non-sensitive -Reason explaining why delayed notice would materially matter"
}

$Message = $Message.Trim()
$Reason = $Reason.Trim()
$maxMessageChars = 700
$maxReasonChars = 240
if ($Message.Length -gt $maxMessageChars) {
    throw "Message exceeds $maxMessageChars characters; shorten it before sending"
}
if ($Reason.Length -gt $maxReasonChars) {
    throw "Reason exceeds $maxReasonChars characters; keep only the decision-relevant explanation"
}

$globalBot = if ($settings.PSObject.Properties.Name -contains "bot") { $settings.bot } else { $null }
if ($null -eq $globalBot -or -not (Test-AgentBaseQqConfigValue $globalBot.app_id)) {
    throw "Global QQ bot AppID is not configured"
}
$targetType = Get-GlobalBotTargetType $globalBot
if (-not (Test-GlobalBotTargetConfigured $globalBot)) {
    throw "Global QQ bot target is not configured for target_type=$targetType"
}
if (-not $DryRun -and -not (Get-SecretConfigured)) {
    throw "QQ_BOT_APP_SECRET is not configured in the process, user, or machine environment"
}

$environmentNames = @(
    "PYTHONIOENCODING",
    "QQ_BOT_APP_ID",
    "QQ_BOT_APP_SECRET",
    "QQ_BOT_TARGET_TYPE",
    "QQ_BOT_OPENID",
    "QQ_BOT_GROUP_OPENID",
    "QQ_BOT_CHANNEL_ID",
    "QQ_BOT_IS_WAKEUP",
    "QQ_BOT_ENABLE",
    "QQ_BOT_DIRECT_SEND_AUTHORIZED",
    "QQ_BOT_PROJECT_ROOT",
    "QQ_BOT_MESSAGE_PREFIX",
    "QQ_BOT_MAX_CHARS",
    "QQ_BOT_DEBUG_LOG"
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:PYTHONIOENCODING = "utf-8"
    foreach ($name in @("QQ_BOT_APP_ID", "QQ_BOT_TARGET_TYPE", "QQ_BOT_OPENID", "QQ_BOT_GROUP_OPENID", "QQ_BOT_CHANNEL_ID", "QQ_BOT_IS_WAKEUP")) {
        Remove-Item -Path "Env:\$name" -ErrorAction SilentlyContinue
    }
    Set-AgentBaseQqBotEnvironment -GlobalBot $globalBot -WorkspaceBot $null
    $env:QQ_BOT_ENABLE = "1"
    $env:QQ_BOT_DIRECT_SEND_AUTHORIZED = "1"
    $env:QQ_BOT_PROJECT_ROOT = $ProjectRoot
    $env:QQ_BOT_MESSAGE_PREFIX = "[Codex]"
    $env:QQ_BOT_MAX_CHARS = [string]$maxMessageChars
    $env:QQ_BOT_DEBUG_LOG = "$globalDebugPath;$workspaceDebugPath"

    $pythonScript = Join-Path $PSScriptRoot "codex_qq_notify.py"
    if (-not (Test-Path -LiteralPath $pythonScript -PathType Leaf)) {
        throw "QQ notification transport not found: $pythonScript"
    }
    $pythonArguments = @(
        $pythonScript,
        "--message", $Message,
        "--direct-reason", $Reason,
        "--print-result"
    )
    if ($DryRun) {
        $pythonArguments += "--dry-run"
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 @pythonArguments
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python @pythonArguments
    }
    else {
        throw "Python 3 is required to send QQ messages"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "QQ direct message transport failed with exit code $LASTEXITCODE"
    }
}
finally {
    foreach ($name in $environmentNames) {
        $original = $originalEnvironment[$name]
        if ($null -eq $original) {
            Remove-Item -Path "Env:\$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:\$name" -Value $original
        }
    }
}
