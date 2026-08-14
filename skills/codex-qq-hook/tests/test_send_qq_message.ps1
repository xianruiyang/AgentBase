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

function Write-FixtureJson {
    param(
        [string]$Path,
        [object]$Value
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-qq-direct-test-" + [guid]::NewGuid().ToString("N"))
$resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a test directory outside the system temp root: $resolvedTestRoot"
}

$skillRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $skillRoot "scripts\send_qq_message.ps1"
$stopScriptPath = Join-Path $skillRoot "scripts\codex_stop_qq_notify.ps1"
$transportPath = Join-Path $skillRoot "scripts\codex_qq_notify.py"
$codexRoot = Join-Path $resolvedTestRoot "codex"
$workspaceRoot = Join-Path $resolvedTestRoot "workspace"
$globalSettingsPath = Join-Path $codexRoot "qq-hook-global-settings.json"
$globalDebugPath = Join-Path $codexRoot "qq-hook-debug.jsonl"

try {
    New-Item -ItemType Directory -Force -Path $codexRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $workspaceRoot | Out-Null

    $missing = & $scriptPath status -CodexRoot $codexRoot -ProjectRoot $workspaceRoot | Out-String | ConvertFrom-Json
    Assert-True (-not $missing.config_exists) "status must not create a missing global configuration"
    Assert-True (-not $missing.direct_send_enabled) "missing configuration must keep direct sending disabled"
    Assert-True (-not (Test-Path -LiteralPath $globalSettingsPath)) "status created the global configuration"

    & $scriptPath enable -CodexRoot $codexRoot -ProjectRoot $workspaceRoot | Out-Null
    $created = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([bool]$created.direct_send.enabled) "enable did not opt in to direct sending"

    $fixture = [ordered]@{
        custom_root = "preserve"
        bot = [ordered]@{
            app_id = "test-app"
            target_type = "user"
            openid = "test-user"
            group_openid = ""
            channel_id = ""
            is_wakeup = $false
        }
        direct_send = [ordered]@{ enabled = $true }
    }
    Write-FixtureJson -Path $globalSettingsPath -Value $fixture

    $missingReasonRejected = $false
    try {
        & $scriptPath send -CodexRoot $codexRoot -ProjectRoot $workspaceRoot -Message "需要处理" -DryRun | Out-Null
    }
    catch {
        $missingReasonRejected = $_.Exception.Message -match "requires a non-sensitive -Reason"
    }
    Assert-True $missingReasonRejected "send accepted a message without an audit reason"

    & $scriptPath disable -CodexRoot $codexRoot -ProjectRoot $workspaceRoot | Out-Null
    $disabledRejected = $false
    try {
        & $scriptPath send -CodexRoot $codexRoot -ProjectRoot $workspaceRoot -Message "需要处理" -Reason "延迟获知会影响必要裁决" -DryRun | Out-Null
    }
    catch {
        $disabledRejected = $_.Exception.Message -match "Direct QQ sending is disabled"
    }
    Assert-True $disabledRejected "send ignored the explicit direct-send opt-in"

    & $scriptPath enable -CodexRoot $codexRoot -ProjectRoot $workspaceRoot | Out-Null
    $dryRun = & $scriptPath send `
        -CodexRoot $codexRoot `
        -ProjectRoot $workspaceRoot `
        -Message "需要用户尽快裁决" `
        -Reason "延迟获知会提高不可逆操作风险" `
        -DryRun |
        Out-String |
        ConvertFrom-Json
    Assert-True ([bool]$dryRun.dry_run) "dry run called the live QQ API"
    Assert-True ([string]$dryRun.endpoint -eq "https://api.sgroup.qq.com/v2/users/<openid>/messages") "dry run exposed or changed the target endpoint"
    Assert-True ([string]$dryRun.payload.content -eq "[Codex] 需要用户尽快裁决") "direct message formatting changed"

    $debugRecord = Get-Content -LiteralPath $globalDebugPath -Encoding UTF8 | Select-Object -Last 1 | ConvertFrom-Json
    Assert-True ([string]$debugRecord.event -eq "sent" -and [string]$debugRecord.mode -eq "direct") "direct send did not write a distinct audit event"
    Assert-True ([string]$debugRecord.direct_reason -eq "延迟获知会提高不可逆操作风险") "direct send did not preserve the non-sensitive audit reason"

    $workspaceSettingsPath = Join-Path $workspaceRoot ".codex\qq-hook-settings.json"
    $workspaceBotFixture = [ordered]@{
        bot = [ordered]@{
            app_id = "workspace-app"
            target_type = "user"
            openid = "workspace-user"
        }
    }
    Write-FixtureJson -Path $workspaceSettingsPath -Value $workspaceBotFixture
    $missingGlobalBot = $fixture | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $missingGlobalBot.bot.app_id = ""
    $missingGlobalBot.bot.openid = ""
    Write-FixtureJson -Path $globalSettingsPath -Value $missingGlobalBot
    $workspaceTargetRejected = $false
    try {
        & $scriptPath send `
            -CodexRoot $codexRoot `
            -ProjectRoot $workspaceRoot `
            -Message "不得继承工作区目标" `
            -Reason "验证主动直发目标的授权边界" `
            -DryRun | Out-Null
    }
    catch {
        $workspaceTargetRejected = $_.Exception.Message -match "Global QQ bot AppID is not configured"
    }
    Assert-True $workspaceTargetRejected "direct sending inherited a workspace-controlled bot target"
    Write-FixtureJson -Path $globalSettingsPath -Value $fixture

    $oldTransportDryRun = $env:QQ_BOT_DRY_RUN
    $oldTransportAuthorization = $env:QQ_BOT_DIRECT_SEND_AUTHORIZED
    $transportErrorPath = Join-Path $resolvedTestRoot "transport-error.txt"
    try {
        Remove-Item -Path "Env:\QQ_BOT_DRY_RUN" -ErrorAction SilentlyContinue
        Remove-Item -Path "Env:\QQ_BOT_DIRECT_SEND_AUTHORIZED" -ErrorAction SilentlyContinue
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 $transportPath --message "禁止绕过" --direct-reason "验证底层入口边界" 2> $transportErrorPath | Out-Null
        }
        elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python $transportPath --message "禁止绕过" --direct-reason "验证底层入口边界" 2> $transportErrorPath | Out-Null
        }
        else {
            throw "Python 3 is required for the direct message regression test"
        }
        $transportExit = $LASTEXITCODE
        $transportError = Get-Content -LiteralPath $transportErrorPath -Raw -Encoding UTF8
        Assert-True ($transportExit -eq 1 -and $transportError.Contains("requires the authorized wrapper")) "the Python transport can bypass the formal direct entry"
    }
    finally {
        $env:QQ_BOT_DRY_RUN = $oldTransportDryRun
        $env:QQ_BOT_DIRECT_SEND_AUTHORIZED = $oldTransportAuthorization
    }

    $workspaceFixture = [ordered]@{
        default_enabled = $true
        enabled_thread_ids = @()
        disabled_thread_ids = @()
        enabled_thread_names = @()
        disabled_thread_names = @()
        message = [ordered]@{
            stop_template = "work_complete"
            prefix = " "
            max_chars = 1200
            completion_max_chars = 700
        }
        goal = [ordered]@{ aware = $false }
    }
    Write-FixtureJson -Path $workspaceSettingsPath -Value $workspaceFixture
    $oldDryRun = $env:QQ_BOT_DRY_RUN
    $oldPrintResult = $env:QQ_BOT_PRINT_RESULT
    $oldProjectRoot = $env:QQ_BOT_PROJECT_ROOT
    try {
        $env:QQ_BOT_DRY_RUN = "1"
        $env:QQ_BOT_PRINT_RESULT = "1"
        $env:QQ_BOT_PROJECT_ROOT = $workspaceRoot
        $hookPayload = [ordered]@{
            hook_event_name = "Stop"
            cwd = $workspaceRoot
            thread_id = "thread-shared-runtime"
            final_response = "共享运行时回归"
        } | ConvertTo-Json -Compress
        $hookDryRun = $hookPayload |
            & $stopScriptPath -CodexRoot $codexRoot |
            Out-String |
            ConvertFrom-Json
        Assert-True ([bool]$hookDryRun.dry_run) "shared runtime regression called the live QQ API"
        Assert-True ([string]$hookDryRun.endpoint -eq "https://api.sgroup.qq.com/v2/users/<openid>/messages") "Hook no longer uses the shared target configuration"
    }
    finally {
        $env:QQ_BOT_DRY_RUN = $oldDryRun
        $env:QQ_BOT_PRINT_RESULT = $oldPrintResult
        $env:QQ_BOT_PROJECT_ROOT = $oldProjectRoot
    }

    $finalSettings = Get-Content -LiteralPath $globalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$finalSettings.custom_root -eq "preserve") "direct-send actions changed unrelated global settings"
    Assert-True ([string]$finalSettings.bot.app_id -eq "test-app") "direct-send actions changed bot settings"

    Write-Output "QQ direct message tests passed: 9/9"
}
finally {
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
