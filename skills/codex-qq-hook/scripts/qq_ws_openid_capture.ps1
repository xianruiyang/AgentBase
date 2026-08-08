$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Require-Env {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing environment variable: $Name"
    }
    return $value
}

function Send-Json {
    param(
        [System.Net.WebSockets.ClientWebSocket]$Socket,
        [object]$Payload
    )
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $segment = [ArraySegment[byte]]::new($bytes)
    $null = $Socket.SendAsync(
        $segment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()
}

function Receive-Json {
    param([System.Net.WebSockets.ClientWebSocket]$Socket)
    $buffer = New-Object byte[] 16384
    $stream = [System.IO.MemoryStream]::new()
    try {
        do {
            $segment = [ArraySegment[byte]]::new($buffer)
            $result = $Socket.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
            if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                throw "WebSocket closed by server: $($Socket.CloseStatus) $($Socket.CloseStatusDescription)"
            }
            if ($result.Count -gt 0) {
                $stream.Write($buffer, 0, $result.Count)
            }
        } while (-not $result.EndOfMessage)

        $text = [System.Text.Encoding]::UTF8.GetString($stream.ToArray())
        return $text | ConvertFrom-Json
    }
    finally {
        $stream.Dispose()
    }
}

function Get-Field {
    param($Object, [string[]]$Path)
    $current = $Object
    foreach ($part in $Path) {
        if ($null -eq $current) {
            return $null
        }
        $prop = $current.PSObject.Properties[$part]
        if ($null -eq $prop) {
            return $null
        }
        $current = $prop.Value
    }
    return $current
}

$appId = Require-Env "QQ_BOT_APP_ID"
$appSecret = Require-Env "QQ_BOT_APP_SECRET"

Write-Host "Getting QQ Bot AccessToken..."
$tokenBody = @{
    appId        = $appId
    clientSecret = $appSecret
} | ConvertTo-Json -Compress
$tokenResp = Invoke-RestMethod `
    -Method Post `
    -Uri "https://bots.qq.com/app/getAppAccessToken" `
    -ContentType "application/json" `
    -Body $tokenBody

if ([string]::IsNullOrWhiteSpace($tokenResp.access_token)) {
    throw "Token response does not contain access_token: $($tokenResp | ConvertTo-Json -Depth 10)"
}
$accessToken = [string]$tokenResp.access_token

Write-Host "Getting QQ Bot WebSocket gateway..."
$gatewayResp = Invoke-RestMethod `
    -Method Get `
    -Uri "https://api.sgroup.qq.com/gateway" `
    -Headers @{ Authorization = "QQBot $accessToken" }

if ([string]::IsNullOrWhiteSpace($gatewayResp.url)) {
    throw "Gateway response does not contain url: $($gatewayResp | ConvertTo-Json -Depth 10)"
}

$ws = [System.Net.WebSockets.ClientWebSocket]::new()
$lastSeq = $null

try {
    Write-Host "Connecting: $($gatewayResp.url)"
    $null = $ws.ConnectAsync([Uri]$gatewayResp.url, [Threading.CancellationToken]::None).GetAwaiter().GetResult()

    $hello = Receive-Json $ws
    if ($hello.op -ne 10) {
        throw "Expected Hello op=10, got: $($hello | ConvertTo-Json -Depth 20)"
    }
    Write-Host "WebSocket connected. Heartbeat interval: $($hello.d.heartbeat_interval) ms"

    # GROUP_AND_C2C_EVENT = 1 << 25, covers C2C_MESSAGE_CREATE and FRIEND_ADD.
    $identify = @{
        op = 2
        d  = @{
            token      = "QQBot $accessToken"
            intents    = (1 -shl 25)
            shard      = @(0, 1)
            properties = @{
                '$os'      = "windows"
                '$browser' = "codex-qq-openid-capture"
                '$device'  = "codex-qq-openid-capture"
            }
        }
    }
    Send-Json -Socket $ws -Payload $identify
    Write-Host "Identify sent. Now click '扫码聊天' in QQ Open Platform, scan it with mobile QQ, then send one private message to the bot."

    while ($true) {
        $msg = Receive-Json $ws
        if ($null -ne $msg.s) {
            $lastSeq = $msg.s
        }

        if ($msg.op -eq 11) {
            continue
        }

        if ($msg.op -eq 7) {
            Write-Warning "Server requested reconnect. Stop and run this script again."
            break
        }

        if ($msg.op -eq 9) {
            throw "Invalid session: $($msg | ConvertTo-Json -Depth 20)"
        }

        if ($msg.op -eq 0) {
            Write-Host "Event: $($msg.t)"

            $userOpenId = Get-Field $msg @("d", "author", "user_openid")
            if ([string]::IsNullOrWhiteSpace($userOpenId)) {
                $userOpenId = Get-Field $msg @("d", "openid")
            }

            if (-not [string]::IsNullOrWhiteSpace($userOpenId)) {
                Write-Host ""
                Write-Host "======== COPY THIS ========"
                Write-Host "QQ_BOT_OPENID=$userOpenId"
                Write-Host "==========================="
                Write-Host ""
                Write-Host "PowerShell config:"
                Write-Host "`$env:QQ_BOT_TARGET_TYPE = `"user`""
                Write-Host "`$env:QQ_BOT_OPENID = `"$userOpenId`""
                break
            }

            if ($msg.t -ne "READY") {
                Write-Host ($msg | ConvertTo-Json -Depth 20)
            }
        }

        # Keep the short-lived capture connection alive while waiting for your message.
        if ($null -ne $lastSeq) {
            Send-Json -Socket $ws -Payload @{ op = 1; d = $lastSeq }
        }
    }
}
finally {
    if ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        $null = $ws.CloseAsync(
            [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
            "done",
            [Threading.CancellationToken]::None
        ).GetAwaiter().GetResult()
    }
    $ws.Dispose()
}
