param(
    [Parameter(Position = 0)]
    [ValidateSet("low", "medium", "high", "xhigh", "max", "ultra")]
    [string] $Effort,

    [switch] $Status,

    [switch] $Hook,

    [string] $ThreadId = $env:CODEX_THREAD_ID,

    [string] $HostId,

    [ValidateSet("model", "machine")]
    [string] $View = "model",

    [switch] $DebugLog
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeScript = Join-Path $scriptDir $(if ($Hook) { "reasoning-session-hook.mjs" } else { "reasoning-governor.mjs" })

if (-not (Test-Path -LiteralPath $nodeScript)) {
    throw "Missing node helper: $nodeScript"
}

$nodeCandidates = @()
if ($env:NODE_EXE) {
    $nodeCandidates += $env:NODE_EXE
}
$nodeCandidates += "node"
if ($env:LOCALAPPDATA) {
    $nodeCandidates += (Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin\node.exe")
}

$nodeExe = $null
foreach ($candidate in $nodeCandidates) {
    if ($candidate -eq "node") {
        $cmd = Get-Command node -ErrorAction SilentlyContinue
        if ($cmd) {
            $nodeExe = $cmd.Source
            break
        }
    } elseif (Test-Path -LiteralPath $candidate) {
        $nodeExe = $candidate
        break
    }
}

if (-not $nodeExe) {
    throw "Could not find node.exe."
}

if ($Hook -and ($Status -or -not [string]::IsNullOrWhiteSpace($Effort))) {
    throw "Use -Hook by itself."
}
if ($Status -and -not [string]::IsNullOrWhiteSpace($Effort)) {
    throw "Use either -Status or -Effort, not both."
}
if (-not $Hook -and -not $Status -and [string]::IsNullOrWhiteSpace($Effort)) {
    throw "Effort is required unless -Status is used."
}

$argsList = @($nodeScript)
if ($Hook) {
    # The hook helper reads Codex's SessionStart JSON directly from stdin.
} elseif ($Status) {
    $argsList += "status"
} else {
    $argsList += @("set", "--effort", $Effort)
}

if (-not $Hook) {
    if ($ThreadId) {
        $argsList += @("--thread-id", $ThreadId)
    }

    if ($HostId) {
        $argsList += @("--host-id", $HostId)
    }

    $argsList += @("--view", $View.ToLowerInvariant())

    if ($DebugLog) {
        $argsList += "--debug"
    }
}

& $nodeExe @argsList
exit $LASTEXITCODE
