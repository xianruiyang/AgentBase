[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Archive,

    [Parameter(Mandatory = $true)]
    [string] $ExpectedVersion
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseInstaller = Join-Path $scriptRoot "install-srcq-release.ps1"
$archiveFull = [IO.Path]::GetFullPath($Archive)
$checksumFull = "$archiveFull.sha256"
$powershellExe = (Get-Process -Id $PID).Path
$root = Join-Path ([IO.Path]::GetTempPath()) ("srcq-release-install-test-" + [guid]::NewGuid().ToString("N"))
$resolvedRoot = [IO.Path]::GetFullPath($root)
$temporaryPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$oldFakeAssetRoot = $env:SRCQ_FAKE_RELEASE_ASSET_ROOT
$oldFakeScript = $env:SRCQ_FAKE_GH_SCRIPT
$oldTestPwsh = $env:SRCQ_TEST_PWSH

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

Assert-True ($resolvedRoot.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase)) "fixture root is outside the system temporary directory"
Assert-True (Test-Path -LiteralPath $archiveFull -PathType Leaf) "release archive is missing: $archiveFull"
Assert-True (Test-Path -LiteralPath $checksumFull -PathType Leaf) "release checksum is missing: $checksumFull"

try {
    $assetsRoot = Join-Path $resolvedRoot "assets"
    $installRoot = Join-Path $resolvedRoot "install"
    $pathFile = Join-Path $resolvedRoot "path.txt"
    $fakeGhScript = Join-Path $resolvedRoot "fake-gh.ps1"
    $fakeGhCommand = Join-Path $resolvedRoot "gh.cmd"
    New-Item -ItemType Directory -Path $assetsRoot -Force | Out-Null
    Copy-Item -LiteralPath $archiveFull -Destination (Join-Path $assetsRoot (Split-Path -Leaf $archiveFull))
    Copy-Item -LiteralPath $checksumFull -Destination (Join-Path $assetsRoot (Split-Path -Leaf $checksumFull))
    Copy-Item -LiteralPath (Join-Path $scriptRoot "install-srcq.ps1") -Destination (Join-Path $assetsRoot "install-srcq.ps1")
    [IO.File]::WriteAllText($pathFile, "C:\existing", [Text.UTF8Encoding]::new($false))

    $fakeGhSource = @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]] $Arguments)
$ErrorActionPreference = "Stop"
$destination = $null
$patterns = @()
for ($index = 0; $index -lt $Arguments.Count; $index++) {
    if ($Arguments[$index] -eq "--dir") {
        $index++
        $destination = $Arguments[$index]
    } elseif ($Arguments[$index] -eq "--pattern") {
        $index++
        $patterns += $Arguments[$index]
    }
}
if (-not $destination -or $patterns.Count -eq 0) { throw "fake gh received an invalid download request" }
foreach ($pattern in $patterns) {
    $source = Join-Path $env:SRCQ_FAKE_RELEASE_ASSET_ROOT $pattern
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "fake release asset is missing: $pattern" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $destination $pattern)
}
'@
    [IO.File]::WriteAllText($fakeGhScript, $fakeGhSource, [Text.UTF8Encoding]::new($false))
    $fakeGhCommandText = "@echo off`r`n`"%SRCQ_TEST_PWSH%`" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"%SRCQ_FAKE_GH_SCRIPT%`" %*`r`nexit /b %ERRORLEVEL%`r`n"
    [IO.File]::WriteAllText($fakeGhCommand, $fakeGhCommandText, [Text.ASCIIEncoding]::new())

    $env:SRCQ_FAKE_RELEASE_ASSET_ROOT = $assetsRoot
    $env:SRCQ_FAKE_GH_SCRIPT = $fakeGhScript
    $env:SRCQ_TEST_PWSH = $powershellExe

    $wrapperArguments = @(
        "Install",
        "-Version", $ExpectedVersion,
        "-Repository", "owner/private-repository",
        "-Tag", "srcq-v$ExpectedVersion",
        "-GitHubCli", $fakeGhCommand,
        "-InstallRoot", $installRoot,
        "-PathBackend", "File",
        "-PathValueFile", $pathFile,
        "-View", "Machine"
    )
    $installOutput = @(
        & $powershellExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $releaseInstaller @wrapperArguments 2>&1
    )
    Assert-True ($LASTEXITCODE -eq 0) "release download installer failed: $($installOutput -join [Environment]::NewLine)"
    $install = ($installOutput -join "`n") | ConvertFrom-Json
    Assert-True ([bool]$install.changed -and $install.version -eq $ExpectedVersion) "release download did not install the expected version"

    $statusOutput = @(
        & $powershellExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File (Join-Path $scriptRoot "install-srcq.ps1") Status `
            -InstallRoot $installRoot -PathBackend File -PathValueFile $pathFile -View Machine 2>&1
    )
    Assert-True ($LASTEXITCODE -eq 0) "installed release status failed: $($statusOutput -join [Environment]::NewLine)"
    $status = ($statusOutput -join "`n") | ConvertFrom-Json
    Assert-True ([bool]$status.ready -and $status.version -eq $ExpectedVersion) "installed release status did not verify the expected version"
    Assert-True ((& $status.binary --version) -eq "srcq $ExpectedVersion") "downloaded release binary version mismatch"

    Remove-Item -LiteralPath (Join-Path $assetsRoot (Split-Path -Leaf $checksumFull)) -Force
    $failedRoot = Join-Path $resolvedRoot "failed-install"
    $failureOutput = @(
        & $powershellExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $releaseInstaller Install -Version $ExpectedVersion `
            -Repository "owner/private-repository" -Tag "srcq-v$ExpectedVersion" `
            -GitHubCli $fakeGhCommand -InstallRoot $failedRoot -PathBackend None 2>&1
    )
    Assert-True ($LASTEXITCODE -ne 0) "release download unexpectedly succeeded without the checksum asset"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $failedRoot "current"))) "failed release download changed installation state"

    $uninstallOutput = @(
        & $powershellExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File (Join-Path $scriptRoot "install-srcq.ps1") Uninstall `
            -InstallRoot $installRoot -PathBackend File -PathValueFile $pathFile -View Machine 2>&1
    )
    Assert-True ($LASTEXITCODE -eq 0) "release download test uninstall failed: $($uninstallOutput -join [Environment]::NewLine)"

    [pscustomobject]@{
        schema = "srcq.release-install-test/v1"
        authenticatedDownloadBoundary = $true
        requiredDownloadAssets = $true
        installStatusReadback = $true
        missingChecksumRejected = $true
        version = $ExpectedVersion
    } | ConvertTo-Json -Depth 4
} finally {
    $env:SRCQ_FAKE_RELEASE_ASSET_ROOT = $oldFakeAssetRoot
    $env:SRCQ_FAKE_GH_SCRIPT = $oldFakeScript
    $env:SRCQ_TEST_PWSH = $oldTestPwsh
    if (Test-Path -LiteralPath $resolvedRoot) {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
