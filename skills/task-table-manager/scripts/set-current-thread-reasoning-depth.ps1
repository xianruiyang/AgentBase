param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("low", "medium", "high", "xhigh", "max", "ultra")]
    [string] $Effort,

    [string] $ThreadId = $env:CODEX_THREAD_ID,

    [string] $HostId,

    [switch] $DebugLog
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeScript = Join-Path $scriptDir "set-current-thread-reasoning-depth.mjs"

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

$argsList = @($nodeScript, "--effort", $Effort)

if ($ThreadId) {
    $argsList += @("--thread-id", $ThreadId)
}

if ($HostId) {
    $argsList += @("--host-id", $HostId)
}

if ($DebugLog) {
    $argsList += "--debug"
}

& $nodeExe @argsList
exit $LASTEXITCODE
