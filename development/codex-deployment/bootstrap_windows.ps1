[CmdletBinding()]
param(
    [ValidateSet("Check", "Install")]
    [string]$Action = "Check",

    [ValidateSet("Model", "Machine")]
    [string]$View = "Model"
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

function Get-SccState {
    $command = Get-ApplicationCommand -Name "scc.exe"
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "scc"
            command = "scc.exe"
            package_id = "BenBoyter.scc"
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
    $version = $null
    if ($versionExit -eq 0 -and $versionOutput.Count -gt 0 -and ([string]$versionOutput[-1]) -match '^scc version (?<version>\d+\.\d+\.\d+)$') {
        $version = $Matches.version
    }
    $help = $helpOutput -join [Environment]::NewLine
    $supportsGateway = $helpExit -eq 0 -and $help.Contains("--by-file") -and $help.Contains("--format string") -and $help.Contains("json2")

    return [pscustomobject]@{
        name = "scc"
        command = "scc.exe"
        package_id = "BenBoyter.scc"
        installer = "winget"
        remediation = "upgrade"
        available = $true
        supported = ($null -ne $version -and $supportsGateway)
        path = $command.Source
        version = $version
    }
}

function Get-HyperfineState {
    $command = Get-ApplicationCommand -Name "hyperfine.exe"
    if ($null -eq $command) {
        return [pscustomobject]@{
            name = "hyperfine"
            command = "hyperfine.exe"
            package_id = "sharkdp.hyperfine"
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
    $version = $null
    if ($versionExit -eq 0 -and $versionOutput.Count -gt 0 -and ([string]$versionOutput[-1]) -match '^hyperfine (?<version>\d+\.\d+\.\d+)$') {
        $version = $Matches.version
    }
    $help = $helpOutput -join [Environment]::NewLine
    $supportsBenchmarkContract = $helpExit -eq 0 -and $help.Contains("--warmup") -and $help.Contains("--export-json")

    return [pscustomobject]@{
        name = "hyperfine"
        command = "hyperfine.exe"
        package_id = "sharkdp.hyperfine"
        installer = "winget"
        remediation = "upgrade"
        available = $true
        supported = ($null -ne $version -and $supportsBenchmarkContract)
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
        Get-SccState
        Get-HyperfineState
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

function ConvertTo-ModelLiteral {
    param([object]$Value)

    if ($null -eq $Value) {
        return "null"
    }
    if ($Value -is [string] -and $Value -match '^[A-Za-z0-9._/@+-]+$') {
        return [string]$Value
    }
    return ConvertTo-Json -InputObject $Value -Compress
}

function New-HostPrerequisiteResult {
    param(
        [object[]]$States,
        [string]$RequestedAction
    )

    $ready = @($States | Where-Object { -not $_.supported }).Count -eq 0
    return [pscustomobject][ordered]@{
        action = $RequestedAction
        ready = $ready
        tools = $States
    }
}

function Format-HostPrerequisiteModelResult {
    param([object]$Result)

    if ([bool]$Result.ready) {
        return "{ready:true}"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Result.error)) {
        return "{ready:false error:$(ConvertTo-ModelLiteral $Result.error)}"
    }

    $unsupported = @()
    foreach ($state in @($Result.tools)) {
        if ([bool]$state.supported) {
            continue
        }
        $fields = @("name:$(ConvertTo-ModelLiteral $state.name)")
        if (-not [string]::IsNullOrWhiteSpace([string]$state.version)) {
            $fields += "version:$(ConvertTo-ModelLiteral $state.version)"
        }
        $toolRecovery = if ([bool]$state.available) { [string]$state.remediation } else { "install" }
        $fields += "next:$(ConvertTo-ModelLiteral $toolRecovery)"
        $unsupported += "{$($fields -join ' ')}"
    }
    $next = if ([string]$Result.action -eq "Check") {
        "rerun with -Action Install"
    }
    else {
        "restart Codex; rerun with -Action Check"
    }
    return "{ready:false tools:[$($unsupported -join ',')] next:$(ConvertTo-ModelLiteral $next)}"
}

function Write-HostPrerequisiteResult {
    param(
        [object]$Result,
        [ValidateSet("Model", "Machine")]
        [string]$ResultView
    )

    if ($ResultView -eq "Machine") {
        $Result | ConvertTo-Json -Depth 5
        return
    }
    Format-HostPrerequisiteModelResult -Result $Result
}

trap {
    $failure = [pscustomobject][ordered]@{
        action = $Action
        ready = $false
        error = $_.Exception.Message
    }
    Write-HostPrerequisiteResult -Result $failure -ResultView $View
    exit 2
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
$result = New-HostPrerequisiteResult -States $states -RequestedAction $Action
Write-HostPrerequisiteResult -Result $result -ResultView $View
if (-not $ready) {
    exit 1
}
