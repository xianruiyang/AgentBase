param([Parameter(Mandatory = $true)][string]$Workspace)
[IO.File]::WriteAllText((Join-Path $Workspace 'evo-hook-observed.txt'), 'EVO_HOOK_VALUE=31')
