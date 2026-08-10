param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("low", "medium", "high", "xhigh", "max", "ultra")]
    [string] $Effort,

    [string] $ThreadId = $env:CODEX_THREAD_ID,

    [string] $HostId,

    [switch] $DebugLog
)

$ErrorActionPreference = "Stop"

$taskTableSkillRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Split-Path -Parent $taskTableSkillRoot
$governorScript = Join-Path $skillsRoot "reasoning-governor\scripts\reasoning-governor.ps1"

if (-not (Test-Path -LiteralPath $governorScript -PathType Leaf)) {
    throw "Missing reasoning-governor compatibility target: $governorScript"
}

$forward = @{
    Effort = $Effort
}
if (-not [string]::IsNullOrWhiteSpace($ThreadId)) {
    $forward.ThreadId = $ThreadId
}
if (-not [string]::IsNullOrWhiteSpace($HostId)) {
    $forward.HostId = $HostId
}
if ($DebugLog) {
    $forward.DebugLog = $true
}

& $governorScript @forward
exit $LASTEXITCODE
