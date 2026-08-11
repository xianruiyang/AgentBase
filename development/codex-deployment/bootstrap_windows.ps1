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
            installer = "winget"
            remediation = "upgrade"
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
        installer = "winget"
        remediation = "upgrade"
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
            installer = "winget"
            remediation = "upgrade"
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
        installer = "winget"
        remediation = "upgrade"
        available = $true
        supported = [bool]$supportsMaxResults
        path = $command.Source
        version = $version
    }
}

function Get-NodeState {
    $command = Get-ApplicationCommand -Name "node.exe"
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "Node.js LTS"
            command = "node.exe"
            package_id = "OpenJS.NodeJS.LTS"
            installer = "winget"
            remediation = "install"
            available = $false
            supported = $false
            path = $null
            version = $null
        }
    }

    $versionOutput = @(& $command.Source --version 2>$null)
    $versionExit = $LASTEXITCODE
    $version = $null
    if ($versionExit -eq 0 -and $versionOutput.Count -gt 0) {
        try {
            $version = [version](([string]$versionOutput[-1]).Trim().TrimStart('v'))
        }
        catch {
            $version = $null
        }
    }

    return [pscustomobject]@{
        name = "Node.js LTS"
        command = "node.exe"
        package_id = "OpenJS.NodeJS.LTS"
        installer = "winget"
        remediation = "install"
        available = $true
        supported = ($null -ne $version -and $version -ge [version]"22.9.0" -and $version.Major -lt 27)
        path = $command.Source
        version = if ($null -eq $version) { $null } else { $version.ToString() }
    }
}

function Get-PythonState {
    $probes = @(
        [pscustomobject]@{ name = "python.exe"; arguments = @("--version") }
        [pscustomobject]@{ name = "py.exe"; arguments = @("-3", "--version") }
    )
    $observed = @()
    foreach ($probe in $probes) {
        $command = Get-ApplicationCommand -Name $probe.name
        if ($null -eq $command) {
            continue
        }
        $versionOutput = @(& $command.Source @($probe.arguments) 2>&1)
        $versionExit = $LASTEXITCODE
        $version = $null
        if ($versionExit -eq 0 -and $versionOutput.Count -gt 0 -and ([string]$versionOutput[-1]) -match 'Python\s+(?<version>\d+\.\d+\.\d+)') {
            try {
                $version = [version]$Matches.version
            }
            catch {
                $version = $null
            }
        }
        $observed += [pscustomobject]@{
            path = $command.Source
            command = ((@($command.Source) + @($probe.arguments)) -join " ").Trim()
            version_object = $version
            supported = ($null -ne $version -and $version -ge [version]"3.11.0" -and $version.Major -eq 3)
        }
    }

    $selected = @($observed | Where-Object { $_.supported } | Select-Object -First 1)
    if ($selected.Count -eq 0) {
        $selected = @($observed | Select-Object -First 1)
    }
    if ($selected.Count -eq 0) {
        return [pscustomobject]@{
            name = "Python 3"
            command = "python.exe"
            package_id = "Python.Python.3.13"
            installer = "winget"
            remediation = "install"
            available = $false
            supported = $false
            path = $null
            version = $null
        }
    }

    $chosen = $selected[0]
    return [pscustomobject]@{
        name = "Python 3"
        command = $chosen.command
        package_id = "Python.Python.3.13"
        installer = "winget"
        remediation = "install"
        available = $true
        supported = [bool]$chosen.supported
        path = $chosen.path
        version = if ($null -eq $chosen.version_object) { $null } else { $chosen.version_object.ToString() }
    }
}

function Get-AstGrepState {
    $command = Get-ApplicationCommand -Name "ast-grep.exe"
    if ($null -eq $command) {
        $command = Get-ApplicationCommand -Name "ast-grep.cmd"
    }
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "ast-grep"
            command = "ast-grep.exe"
            package_id = "@ast-grep/cli@0.44.1"
            installer = "npm"
            remediation = "install"
            available = $false
            supported = $false
            path = $null
            version = $null
        }
    }

    $versionOutput = @(& $command.Source --version 2>$null)
    $versionExit = $LASTEXITCODE
    $version = $null
    if ($versionExit -eq 0 -and $versionOutput.Count -gt 0 -and ([string]$versionOutput[-1]) -match '^ast-grep\s+(?<version>\d+\.\d+\.\d+)') {
        $version = $Matches.version
    }
    return [pscustomobject]@{
        name = "ast-grep"
        command = "ast-grep.exe"
        package_id = "@ast-grep/cli@0.44.1"
        installer = "npm"
        remediation = "install"
        available = $true
        supported = ($version -eq "0.44.1")
        path = $command.Source
        version = $version
    }
}

function Get-HostPrerequisiteState {
    $states = @(
        Get-PwshState
        Get-FdState
        Get-PythonState
        Get-NodeState
        Get-AstGrepState
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

function Install-AstGrep {
    $npm = Get-ApplicationCommand -Name "npm.cmd"
    if ($null -eq $npm) {
        $npm = Get-ApplicationCommand -Name "npm.exe"
    }
    if ($null -eq $npm) {
        throw "npm is required to install the verified ast-grep runtime"
    }
    & $npm.Source install --global "@ast-grep/cli@0.44.1" --no-audit --no-fund
    $npmExit = $LASTEXITCODE
    if ($npmExit -ne 0) {
        throw "npm install failed for @ast-grep/cli@0.44.1 with exit code $npmExit"
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
    foreach ($state in @($states | Where-Object { $_.installer -eq "winget" })) {
        if (-not $state.available) {
            Invoke-WingetPackageAction -PackageAction "install" -PackageId $state.package_id
        }
        elseif (-not $state.supported) {
            Invoke-WingetPackageAction -PackageAction $state.remediation -PackageId $state.package_id
        }
    }
    Add-PersistedPathEntries
    $nodeState = Get-NodeState
    if (-not $nodeState.supported) {
        throw "Node.js installation completed but the supported runtime is not available yet; restart Codex and rerun -Action Install"
    }
    $astGrepState = Get-AstGrepState
    if (-not $astGrepState.supported) {
        Install-AstGrep
        Add-PersistedPathEntries
    }
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
