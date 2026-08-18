[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $scriptRoot "install-srcq.ps1"
$powershellExe = (Get-Process -Id $PID).Path

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-InstallerProcess {
    param([string[]]$Arguments)

    $output = @(& $powershellExe -NoLogo -NoProfile -NonInteractive -File $installer @Arguments 2>&1)
    return [pscustomobject]@{
        exit_code = $LASTEXITCODE
        text = ($output -join [Environment]::NewLine).Trim()
    }
}

$modelReady = Invoke-InstallerProcess -Arguments @("Status")
Assert-True ($modelReady.exit_code -eq 0) "default srcq installation is not ready"
Assert-True ($modelReady.text.StartsWith("{ready:true version:")) "default status output omitted the compact readiness receipt"
Assert-True ($modelReady.text.Contains(" binary:")) "default status output omitted the exact doctor binary"
Assert-True (-not $modelReady.text.Contains("schema") -and -not $modelReady.text.Contains("installRoot") -and -not $modelReady.text.Contains("pathReady")) "default status output exposed machine-only fields"

$machineReady = Invoke-InstallerProcess -Arguments @("Status", "-View", "Machine")
Assert-True ($machineReady.exit_code -eq 0) "machine srcq installation status failed"
$machineReadyResult = $machineReady.text | ConvertFrom-Json
Assert-True ([bool]$machineReadyResult.ready -and $machineReadyResult.integrity -eq "verified") "machine status lost installation health"
Assert-True ($machineReadyResult.path.backend -eq "User" -and [int]$machineReadyResult.pathEntryCount -eq 1) "machine status lost the managed PATH contract"

$missingRoot = Join-Path ([IO.Path]::GetTempPath()) ("srcq-view-test-" + [guid]::NewGuid().ToString("N"))
$modelMissing = Invoke-InstallerProcess -Arguments @("Status", "-InstallRoot", $missingRoot, "-PathBackend", "None")
Assert-True ($modelMissing.exit_code -eq 1) "not-installed status lost its failure exit code"
Assert-True ($modelMissing.text -eq '{ready:false reason:not_installed next:"install a validated srcq release archive"}') "not-installed model output is not the compact recovery receipt"

$machineMissing = Invoke-InstallerProcess -Arguments @("Status", "-InstallRoot", $missingRoot, "-PathBackend", "None", "-View", "Machine")
Assert-True ($machineMissing.exit_code -eq 1) "not-installed machine status lost its failure exit code"
$machineMissingResult = $machineMissing.text | ConvertFrom-Json
Assert-True (-not [bool]$machineMissingResult.installed -and -not [bool]$machineMissingResult.ready) "not-installed machine status changed semantics"
Assert-True ($machineMissingResult.installRoot -eq $missingRoot) "not-installed machine status lost the exact install root"

$unsafeRoot = [IO.Path]::GetPathRoot($missingRoot)
$modelError = Invoke-InstallerProcess -Arguments @("Status", "-InstallRoot", $unsafeRoot, "-PathBackend", "None")
Assert-True ($modelError.exit_code -eq 2) "unsafe-root model failure lost its error exit code"
Assert-True ($modelError.text.StartsWith("{ok:false op:status error:")) "unsafe-root model failure was not compacted"
Assert-True (-not $modelError.text.Contains("ScriptStackTrace")) "unsafe-root model failure exposed a PowerShell stack"

$machineError = Invoke-InstallerProcess -Arguments @("Status", "-InstallRoot", $unsafeRoot, "-PathBackend", "None", "-View", "Machine")
Assert-True ($machineError.exit_code -eq 2) "unsafe-root machine failure lost its error exit code"
$machineErrorResult = $machineError.text | ConvertFrom-Json
Assert-True (-not [bool]$machineErrorResult.ok -and $machineErrorResult.action -eq "status") "unsafe-root machine failure lost the structured error contract"

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("srcq-view-lifecycle-" + [guid]::NewGuid().ToString("N"))
$resolvedFixtureRoot = [IO.Path]::GetFullPath($fixtureRoot)
$tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
Assert-True ($resolvedFixtureRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) "fixture root is outside the system temporary directory"
try {
    $sourceCurrent = Split-Path -Parent ([string]$machineReadyResult.binary)
    $manifest = Get-Content -LiteralPath (Join-Path $sourceCurrent "manifest.json") -Raw | ConvertFrom-Json
    $archive = Join-Path $fixtureRoot ([string]$manifest.archive)
    $packageContainer = Join-Path $fixtureRoot "package"
    $packageStem = [IO.Path]::GetFileNameWithoutExtension($archive)
    $packageRoot = Join-Path $packageContainer $packageStem
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    $members = @("manifest.json", "LICENSE", "LICENSE-APACHE", "LICENSE-MIT", "NOTICE", "README.md", "THIRD_PARTY_LICENSES.txt", "sbom.spdx.json", [string]$manifest.binary)
    foreach ($member in $members) {
        Copy-Item -LiteralPath (Join-Path $sourceCurrent $member) -Destination (Join-Path $packageRoot $member)
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($packageContainer, $archive, [IO.Compression.CompressionLevel]::Optimal, $false)
    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$archive.sha256", "$archiveHash  $([IO.Path]::GetFileName($archive))`n", [Text.UTF8Encoding]::new($false))

    $isolatedInstallRoot = Join-Path $fixtureRoot "install"
    $isolatedPathFile = Join-Path $fixtureRoot "path.txt"
    [IO.File]::WriteAllText($isolatedPathFile, "C:\existing", [Text.UTF8Encoding]::new($false))
    $common = @("-Archive", $archive, "-InstallRoot", $isolatedInstallRoot, "-PathBackend", "File", "-PathValueFile", $isolatedPathFile)

    $installModel = Invoke-InstallerProcess -Arguments (@("Install") + $common)
    Assert-True ($installModel.exit_code -eq 0) "isolated model install failed"
    Assert-True ($installModel.text.StartsWith("{ok:true op:install changed:true version:$($manifest.version) restart:true binary:")) "model install omitted the PATH restart receipt"
    Assert-True (-not $installModel.text.Contains("schema") -and -not $installModel.text.Contains("installRoot")) "model install exposed machine-only fields"

    $installMachine = Invoke-InstallerProcess -Arguments (@("Install") + $common + @("-View", "Machine"))
    Assert-True ($installMachine.exit_code -eq 0) "isolated machine idempotent install failed"
    $installMachineResult = $installMachine.text | ConvertFrom-Json
    Assert-True (-not [bool]$installMachineResult.changed -and $installMachineResult.version -eq $manifest.version) "machine idempotent install changed semantics"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$installMachineResult.binary)) "machine install omitted the exact binary"

    $upgradeModel = Invoke-InstallerProcess -Arguments (@("Upgrade") + $common)
    Assert-True ($upgradeModel.exit_code -eq 0) "isolated model upgrade failed"
    Assert-True ($upgradeModel.text -eq "{ok:true op:upgrade changed:false version:$($manifest.version)}") "model upgrade is not the compact receipt"

    $uninstallArguments = @("Uninstall", "-InstallRoot", $isolatedInstallRoot, "-PathBackend", "File", "-PathValueFile", $isolatedPathFile)
    $uninstallModel = Invoke-InstallerProcess -Arguments $uninstallArguments
    Assert-True ($uninstallModel.exit_code -eq 0) "isolated model uninstall failed"
    Assert-True ($uninstallModel.text -eq "{ok:true op:uninstall removed:true}") "model uninstall is not the compact receipt"
    Assert-True ([IO.File]::ReadAllText($isolatedPathFile) -eq "C:\existing") "isolated uninstall did not restore the managed PATH value"
}
finally {
    if (Test-Path -LiteralPath $resolvedFixtureRoot) {
        Remove-Item -LiteralPath $resolvedFixtureRoot -Recurse -Force
    }
}

"tests : pass"
