[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("Install", "Upgrade")]
    [string] $Action = "Install",

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$')]
    [string] $Version,

    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string] $Repository = "xianruiyang/AgentBase",

    [ValidatePattern('^[A-Za-z0-9._+-]+$')]
    [string] $Tag,

    [string] $GitHubCli = "gh.exe",
    [string] $InstallRoot,

    [ValidateSet("User", "File", "None")]
    [string] $PathBackend = "User",

    [string] $PathValueFile,

    [ValidateSet("Model", "Machine")]
    [string] $View = "Model"
)

$ErrorActionPreference = "Stop"
$target = "x86_64-pc-windows-msvc"
$releaseTag = if ($Tag) { $Tag } else { "srcq-v$Version" }
$archiveName = "srcq-$Version-$target.zip"
$checksumName = "$archiveName.sha256"
$installerName = "install-srcq.ps1"
$downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ("srcq-release-download-" + [guid]::NewGuid().ToString("N"))
$resolvedDownloadRoot = [IO.Path]::GetFullPath($downloadRoot)
$temporaryPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$outputLines = @()
$resultExitCode = 0

if (-not $resolvedDownloadRoot.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release download directory is outside the system temporary directory: $resolvedDownloadRoot"
}
if ($PathBackend -eq "File" -and -not $PathValueFile) {
    throw "-PathValueFile is required for PathBackend=File"
}

try {
    $githubCommand = Get-Command $GitHubCli -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $githubCommand) {
        throw "GitHub CLI was not found: $GitHubCli. Install gh and run 'gh auth login --hostname github.com'."
    }

    New-Item -ItemType Directory -Path $resolvedDownloadRoot | Out-Null
    $downloadOutput = @(
        & $githubCommand.Source release download $releaseTag `
            --repo $Repository `
            --dir $resolvedDownloadRoot `
            --pattern $archiveName `
            --pattern $checksumName `
            --pattern $installerName 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        $detail = ($downloadOutput | Select-Object -First 8) -join [Environment]::NewLine
        throw "GitHub Release download failed for $Repository@$releaseTag. Confirm repository access and run 'gh auth login --hostname github.com'.`n$detail"
    }

    $archive = Join-Path $resolvedDownloadRoot $archiveName
    $checksum = Join-Path $resolvedDownloadRoot $checksumName
    $installer = Join-Path $resolvedDownloadRoot $installerName
    foreach ($asset in @($archive, $checksum, $installer)) {
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
            throw "GitHub Release omitted required asset: $(Split-Path -Leaf $asset)"
        }
    }

    $installerArguments = @(
        $Action,
        "-Archive", $archive,
        "-Checksum", $checksum,
        "-PathBackend", $PathBackend,
        "-View", $View
    )
    if ($InstallRoot) {
        $installerArguments += @("-InstallRoot", $InstallRoot)
    }
    if ($PathValueFile) {
        $installerArguments += @("-PathValueFile", $PathValueFile)
    }

    $powershellExe = (Get-Process -Id $PID).Path
    $outputLines = @(
        & $powershellExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $installer @installerArguments 2>&1
    )
    $resultExitCode = $LASTEXITCODE
} catch {
    $outputLines = @("srcq release install failed: $($_.Exception.Message)")
    $resultExitCode = 2
} finally {
    if (Test-Path -LiteralPath $resolvedDownloadRoot) {
        Remove-Item -LiteralPath $resolvedDownloadRoot -Recurse -Force
    }
}

$outputLines | Write-Output
exit $resultExitCode
