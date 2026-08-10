[CmdletBinding()]
param(
    [ValidateSet("Check", "Install")]
    [string]$Action = "Check"
)

$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "bootstrap_windows.ps1 supports Windows only"
}

function Get-ApplicationCommand {
    param(
        [string]$Name
    )

    return Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-PwshState {
    $command = Get-ApplicationCommand -Name "pwsh.exe"
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "PowerShell 7"
            command = "pwsh.exe"
            package_id = "Microsoft.PowerShell"
            available = $false
            supported = $false
            path = $null
            version = $null
        }
    }

    $versionOutput = @(& $command.Source -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.ToString()' 2>$null)
    $versionExit = $LASTEXITCODE
    $version = $null
    if ($versionExit -eq 0 -and $versionOutput.Count -gt 0) {
        try {
            $version = [version]([string]$versionOutput[-1])
        }
        catch {
            $version = $null
        }
    }

    return [pscustomobject]@{
        name = "PowerShell 7"
        command = "pwsh.exe"
        package_id = "Microsoft.PowerShell"
        available = $true
        supported = ($null -ne $version -and $version.Major -ge 7)
        path = $command.Source
        version = if ($null -eq $version) { $null } else { $version.ToString() }
    }
}

function Get-FdState {
    $command = Get-ApplicationCommand -Name "fd.exe"
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "fd"
            command = "fd.exe"
            package_id = "sharkdp.fd"
            available = $false
            supported = $false
            path = $null
            version = $null
        }
    }

    $versionOutput = @(& $command.Source --version 2>$null)
    $versionExit = $LASTEXITCODE
    $helpOutput = @(& $command.Source --help 2>$null)
    $helpExit = $LASTEXITCODE
    $version = if ($versionExit -eq 0 -and $versionOutput.Count -gt 0) { [string]$versionOutput[-1] } else { $null }
    $supportsMaxResults = $helpExit -eq 0 -and (($helpOutput -join [Environment]::NewLine) -match '--max-results')

    return [pscustomobject]@{
        name = "fd"
        command = "fd.exe"
        package_id = "sharkdp.fd"
        available = $true
        supported = [bool]$supportsMaxResults
        path = $command.Source
        version = $version
    }
}

function Get-HostPrerequisiteState {
    $states = @(
        Get-PwshState
        Get-FdState
    )
    return $states
}

function Add-PersistedPathEntries {
    $pathValues = @(
        $env:PATH
        [Environment]::GetEnvironmentVariable("Path", "Machine")
        [Environment]::GetEnvironmentVariable("Path", "User")
    ) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:PATH = $pathValues -join ";"
}

function Invoke-WingetPackageAction {
    param(
        [ValidateSet("install", "upgrade")]
        [string]$PackageAction,
        [string]$PackageId
    )

    $winget = Get-ApplicationCommand -Name "winget.exe"
    if ($null -eq $winget) {
        throw "winget.exe is required to install AgentBase host prerequisites"
    }

    $arguments = @(
        $PackageAction
        "--id"
        $PackageId
        "--exact"
        "--source"
        "winget"
        "--accept-source-agreements"
        "--accept-package-agreements"
        "--disable-interactivity"
    )
    & $winget.Source @arguments
    $wingetExit = $LASTEXITCODE
    if ($wingetExit -ne 0) {
        throw "winget $PackageAction failed for $PackageId with exit code $wingetExit"
    }
}

function Write-HostPrerequisiteState {
    param(
        [object[]]$States,
        [string]$RequestedAction
    )

    $ready = @($States | Where-Object { -not $_.supported }).Count -eq 0
    [ordered]@{
        action = $RequestedAction
        ready = $ready
        tools = $States
    } | ConvertTo-Json -Depth 5
}

$states = @(Get-HostPrerequisiteState)
if ($Action -eq "Install") {
    foreach ($state in $states) {
        if (-not $state.available) {
            Invoke-WingetPackageAction -PackageAction "install" -PackageId $state.package_id
        }
        elseif (-not $state.supported) {
            Invoke-WingetPackageAction -PackageAction "upgrade" -PackageId $state.package_id
        }
    }
    Add-PersistedPathEntries
    $states = @(Get-HostPrerequisiteState)
}

$ready = @($states | Where-Object { -not $_.supported }).Count -eq 0
Write-HostPrerequisiteState -States $states -RequestedAction $Action
if (-not $ready) {
    if ($Action -eq "Check") {
        throw "AgentBase host prerequisites are missing or unsupported; rerun with -Action Install"
    }
    throw "Host prerequisite installation completed but the required commands are not available yet; restart Codex and rerun -Action Check"
}
