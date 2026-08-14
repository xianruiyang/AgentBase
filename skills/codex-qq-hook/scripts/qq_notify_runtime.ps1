function Test-AgentBaseQqConfigValue {
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

function Select-AgentBaseQqConfigValue {
    param(
        $Primary,
        $Fallback,
        $Default = $null
    )

    if (Test-AgentBaseQqConfigValue $Primary) {
        return $Primary
    }
    if (Test-AgentBaseQqConfigValue $Fallback) {
        return $Fallback
    }
    return $Default
}

function Set-AgentBaseQqEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        $Value,
        [string]$Default = $null
    )

    if ($null -ne $Value) {
        Set-Item -Path "Env:\$Name" -Value ([string]$Value)
    }
    elseif ($null -ne $Default) {
        Set-Item -Path "Env:\$Name" -Value $Default
    }
}

function Import-AgentBaseQqSecret {
    if (-not [string]::IsNullOrWhiteSpace($env:QQ_BOT_APP_SECRET)) {
        return
    }

    $secret = [Environment]::GetEnvironmentVariable("QQ_BOT_APP_SECRET", "User")
    if ([string]::IsNullOrWhiteSpace($secret)) {
        $secret = [Environment]::GetEnvironmentVariable("QQ_BOT_APP_SECRET", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($secret)) {
        $env:QQ_BOT_APP_SECRET = $secret
    }
}

function Set-AgentBaseQqBotEnvironment {
    param(
        $GlobalBot,
        $WorkspaceBot
    )

    Import-AgentBaseQqSecret
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_APP_ID" -Value (Select-AgentBaseQqConfigValue $GlobalBot.app_id $WorkspaceBot.app_id)
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_TARGET_TYPE" -Value (Select-AgentBaseQqConfigValue $GlobalBot.target_type $WorkspaceBot.target_type "user")
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_OPENID" -Value (Select-AgentBaseQqConfigValue $GlobalBot.openid $WorkspaceBot.openid)
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_GROUP_OPENID" -Value (Select-AgentBaseQqConfigValue $GlobalBot.group_openid $WorkspaceBot.group_openid)
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_CHANNEL_ID" -Value (Select-AgentBaseQqConfigValue $GlobalBot.channel_id $WorkspaceBot.channel_id)
    Set-AgentBaseQqEnvironmentValue -Name "QQ_BOT_IS_WAKEUP" -Value (Select-AgentBaseQqConfigValue $GlobalBot.is_wakeup $WorkspaceBot.is_wakeup "false")
}
