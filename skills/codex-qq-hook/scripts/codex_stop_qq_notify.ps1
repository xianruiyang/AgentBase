$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONIOENCODING = "utf-8"

$stdinPayload = [Console]::In.ReadToEnd()

function Get-JsonValue {
    param(
        $Object,
        [string[]]$Names
    )
    if ($null -eq $Object) {
        return $null
    }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties[$name] -and -not [string]::IsNullOrWhiteSpace([string]$Object.$name)) {
            return [string]$Object.$name
        }
    }
    return $null
}

function Resolve-WorkspaceRoot {
    param([string]$Payload)

    if (-not [string]::IsNullOrWhiteSpace($env:QQ_BOT_PROJECT_ROOT)) {
        return (Resolve-Path -LiteralPath $env:QQ_BOT_PROJECT_ROOT).Path
    }

    $hookData = $null
    if (-not [string]::IsNullOrWhiteSpace($Payload)) {
        try {
            $hookData = $Payload | ConvertFrom-Json -ErrorAction Stop
        } catch {
            $hookData = $null
        }
    }

    $candidate = Get-JsonValue $hookData @(
        "cwd",
        "workspace_root",
        "workspaceRoot",
        "working_directory",
        "workingDirectory",
        "repo_path",
        "repoPath",
        "project_dir",
        "projectDir"
    )
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = (Get-Location).Path
    }

    try {
        return (Resolve-Path -LiteralPath $candidate).Path
    } catch {
        return (Get-Location).Path
    }
}

function Set-EnvFromConfig {
    param(
        [string]$EnvName,
        $Value,
        [string]$Default = $null
    )
    if ($null -ne $Value) {
        Set-Item -Path "Env:\$EnvName" -Value ([string]$Value)
    } elseif ($null -ne $Default) {
        Set-Item -Path "Env:\$EnvName" -Value $Default
    }
}

function Test-RealConfigValue {
    param($Value)
    if ($null -eq $Value) {
        return $false
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $false
    }
    return -not ($text -match "替换为|QQ 开放平台 AppID|目标用户 QQ_BOT_OPENID")
}

function Select-ConfigValue {
    param(
        $Primary,
        $Fallback,
        $Default = $null
    )
    if (Test-RealConfigValue $Primary) {
        return $Primary
    }
    if (Test-RealConfigValue $Fallback) {
        return $Fallback
    }
    return $Default
}

$workspaceRoot = Resolve-WorkspaceRoot $stdinPayload
$workspaceCodexDir = Join-Path $workspaceRoot ".codex"
$configPath = Join-Path $workspaceCodexDir "qq-hook-settings.json"
$workspaceDebugPath = Join-Path $workspaceCodexDir "qq-hook-debug.jsonl"
$skillRoot = Split-Path -Parent $PSScriptRoot
$skillsDir = Split-Path -Parent $skillRoot
$codexHome = Split-Path -Parent $skillsDir
$globalSettingsPath = Join-Path $codexHome "qq-hook-global-settings.json"
$globalDebugPath = Join-Path $codexHome "qq-hook-debug.jsonl"
$templatePath = Join-Path $skillRoot "templates\qq-hook-settings.template.json"
$globalTemplatePath = Join-Path $skillRoot "templates\qq-hook-global-settings.template.json"

function Write-HookDebug {
    param(
        [string]$Event,
        [hashtable]$Fields = @{}
    )
    $record = [ordered]@{
        ts = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        event = $Event
        workspace_root = $workspaceRoot
        config_path = $configPath
        global_config_path = $globalSettingsPath
    }
    foreach ($key in $Fields.Keys) {
        $record[$key] = $Fields[$key]
    }
    $line = $record | ConvertTo-Json -Depth 20 -Compress
    foreach ($path in @($globalDebugPath, $workspaceDebugPath)) {
        try {
            $dir = Split-Path -Parent $path
            if (-not [string]::IsNullOrWhiteSpace($dir)) {
                New-Item -ItemType Directory -Force -Path $dir | Out-Null
            }
            Add-Content -LiteralPath $path -Value $line -Encoding UTF8
        } catch {
        }
    }
}

New-Item -ItemType Directory -Force -Path $workspaceCodexDir | Out-Null
if (-not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath $templatePath -Destination $configPath -Force
    Write-HookDebug "config_created"
}
if (-not (Test-Path -LiteralPath $globalSettingsPath)) {
    Copy-Item -LiteralPath $globalTemplatePath -Destination $globalSettingsPath -Force
    Write-HookDebug "global_config_created"
}
Write-HookDebug "start"

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$globalConfig = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($env:QQ_BOT_APP_SECRET)) {
    $secret = [Environment]::GetEnvironmentVariable("QQ_BOT_APP_SECRET", "User")
    if ([string]::IsNullOrWhiteSpace($secret)) {
        $secret = [Environment]::GetEnvironmentVariable("QQ_BOT_APP_SECRET", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($secret)) {
        $env:QQ_BOT_APP_SECRET = $secret
    }
}

$globalBot = $globalConfig.bot
$workspaceBot = $config.bot
$message = $config.message
$goal = $config.goal

Set-EnvFromConfig "QQ_BOT_APP_ID" (Select-ConfigValue $globalBot.app_id $workspaceBot.app_id)
Set-EnvFromConfig "QQ_BOT_TARGET_TYPE" (Select-ConfigValue $globalBot.target_type $workspaceBot.target_type "user")
Set-EnvFromConfig "QQ_BOT_OPENID" (Select-ConfigValue $globalBot.openid $workspaceBot.openid)
Set-EnvFromConfig "QQ_BOT_GROUP_OPENID" (Select-ConfigValue $globalBot.group_openid $workspaceBot.group_openid)
Set-EnvFromConfig "QQ_BOT_CHANNEL_ID" (Select-ConfigValue $globalBot.channel_id $workspaceBot.channel_id)
Set-EnvFromConfig "QQ_BOT_IS_WAKEUP" (Select-ConfigValue $globalBot.is_wakeup $workspaceBot.is_wakeup "false")

$env:QQ_BOT_ENABLE = "1"
$env:QQ_BOT_NOTIFY_EVENTS = "*"
$env:QQ_BOT_PROJECT_ROOT = $workspaceRoot
Set-EnvFromConfig "QQ_BOT_STOP_TEMPLATE" $message.stop_template "work_complete"
Set-EnvFromConfig "QQ_BOT_MESSAGE_PREFIX" $message.prefix " "
Set-EnvFromConfig "QQ_BOT_MAX_CHARS" $message.max_chars "1200"
Set-EnvFromConfig "QQ_BOT_COMPLETION_MAX_CHARS" $message.completion_max_chars "700"
Set-EnvFromConfig "QQ_BOT_GOAL_AWARE" $goal.aware "true"
$env:QQ_BOT_THREAD_SWITCH_CONFIG = $configPath
$env:QQ_BOT_DEBUG_LOG = "$globalDebugPath;$workspaceDebugPath"

$scriptPath = Join-Path $PSScriptRoot "codex_qq_notify.py"
Push-Location -LiteralPath $workspaceRoot
try {
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $pythonExe = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $pythonExe = "py -3"
        $stdinPayload | & py -3 $scriptPath --hook-mode 1> $stdoutFile 2> $stderrFile
    } else {
        $pythonExe = "python"
        $stdinPayload | & python $scriptPath --hook-mode 1> $stdoutFile 2> $stderrFile
    }
    $exitCode = $LASTEXITCODE
    $stdoutText = Get-Content -LiteralPath $stdoutFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    $stderrText = Get-Content -LiteralPath $stderrFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue

    Write-HookDebug "python_exit" @{
        python = $pythonExe
        exit_code = $exitCode
        stdout_len = if ($null -eq $stdoutText) { 0 } else { $stdoutText.Length }
        stderr = if ([string]::IsNullOrWhiteSpace($stderrText)) { "" } else { $stderrText.Trim() }
    }

    $printResultFlag = ([string]$env:QQ_BOT_PRINT_RESULT).ToLowerInvariant()
    $dryRunFlag = ([string]$env:QQ_BOT_DRY_RUN).ToLowerInvariant()
    if (("1","true","yes","on") -contains $printResultFlag -or
        ("1","true","yes","on") -contains $dryRunFlag) {
        if (-not [string]::IsNullOrWhiteSpace($stdoutText)) {
            Write-Output $stdoutText
        }
    } else {
        @{ continue = $true; suppressOutput = $true } | ConvertTo-Json -Compress
    }

    exit $exitCode
} finally {
    Pop-Location
}
