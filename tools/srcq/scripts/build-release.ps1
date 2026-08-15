param(
    [string] $Target,
    [string] $Version,
    [string] $SourceRevision,
    [UInt64] $SourceDateEpoch = 0,
    [string] $OutDir,
    [switch] $Clean
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$targetRoot = [IO.Path]::GetFullPath((Join-Path $root "target\release-build"))

Push-Location $root
try {
    $hostLine = & rustc -vV | Select-String -Pattern '^host: '
    if ($LASTEXITCODE -ne 0 -or -not $hostLine) {
        throw "rustc -vV did not report a host target"
    }
    $hostTarget = $hostLine.Line.Substring(6).Trim()
    if (-not $Target) {
        $Target = $hostTarget
    }
    if ($Target -notmatch '^[A-Za-z0-9_.-]+$') {
        throw "Target is not a release-safe Rust target triple: $Target"
    }

    $workspaceMetadataText = (& cargo metadata --locked --no-deps --format-version 1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "cargo metadata failed"
    }
    $workspaceMetadata = $workspaceMetadataText | ConvertFrom-Json
    $cliPackage = $workspaceMetadata.packages | Where-Object { $_.name -eq "srcq-cli" } | Select-Object -First 1
    if (-not $cliPackage) {
        throw "cargo metadata does not contain srcq-cli"
    }
    if (-not $Version) {
        $Version = $cliPackage.version
    }
    if ($Version -notmatch '^[A-Za-z0-9.+_-]+$') {
        throw "Version is not release-safe: $Version"
    }

    if (-not $SourceRevision) {
        $SourceRevision = $env:SRCQ_SOURCE_REVISION
    }
    if (-not $SourceRevision) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            $candidate = (& git -C $root rev-parse --verify HEAD 2>$null)
            if ($LASTEXITCODE -eq 0) {
                $SourceRevision = ($candidate | Select-Object -First 1).Trim()
            }
        }
    }
    if (-not $SourceRevision) {
        $SourceRevision = "unversioned-workspace"
    }

    $buildRoot = [IO.Path]::GetFullPath((Join-Path $targetRoot $Target))
    $targetPrefix = $targetRoot.TrimEnd('\') + '\'
    if (-not $buildRoot.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing build directory outside target/release-build: $buildRoot"
    }
    if ($Clean -and (Test-Path -LiteralPath $buildRoot)) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    if (-not $OutDir) {
        $OutDir = Join-Path $root "dist"
    }
    $OutDir = [IO.Path]::GetFullPath($OutDir)
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

    $separator = [char]0x1f
    $releaseRustFlags = @("--remap-path-prefix=$root=.")
    if ($Target -like '*-msvc') {
        $releaseRustFlags += '-C'
        $releaseRustFlags += 'link-arg=/Brepro'
    }
    $encodedReleaseRustFlags = $releaseRustFlags -join $separator
    if ($env:CARGO_ENCODED_RUSTFLAGS) {
        $env:CARGO_ENCODED_RUSTFLAGS = $env:CARGO_ENCODED_RUSTFLAGS + $separator + $encodedReleaseRustFlags
    } else {
        $env:CARGO_ENCODED_RUSTFLAGS = $encodedReleaseRustFlags
    }
    $env:CARGO_TARGET_DIR = $buildRoot
    $env:SRCQ_BUILD_VERSION = $Version
    $env:SOURCE_DATE_EPOCH = [string]$SourceDateEpoch

    & cargo build --release --locked -p srcq-release
    if ($LASTEXITCODE -ne 0) {
        throw "failed to build the host release packager"
    }
    & cargo build --release --locked --target $Target -p srcq-cli --bin srcq
    if ($LASTEXITCODE -ne 0) {
        throw "failed to build srcq for $Target"
    }

    $helperSuffix = if ($hostTarget -like '*windows*') { '.exe' } else { '' }
    $binarySuffix = if ($Target -like '*windows*') { '.exe' } else { '' }
    $helper = Join-Path $buildRoot "release\srcq-release$helperSuffix"
    $binary = Join-Path $buildRoot "$Target\release\srcq$binarySuffix"
    if (-not (Test-Path -LiteralPath $helper)) {
        throw "release packager not found: $helper"
    }
    if (-not (Test-Path -LiteralPath $binary)) {
        throw "release binary not found: $binary"
    }

    if ($Target -eq $hostTarget) {
        $actualVersion = (& $binary --version)
        if ($LASTEXITCODE -ne 0 -or ($actualVersion | Select-Object -First 1) -ne "srcq $Version") {
            throw "binary version does not match requested release version: $actualVersion"
        }
    }

    $metadataPath = Join-Path $buildRoot "cargo-metadata-$Target.json"
    $releaseMetadataText = (& cargo metadata --locked --format-version 1 --filter-platform $Target) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "target-filtered cargo metadata failed"
    }
    [IO.File]::WriteAllText(
        $metadataPath,
        $releaseMetadataText + "`n",
        [Text.UTF8Encoding]::new($false)
    )
    $rustcVersionOutput = & rustc --version
    $rustcVersionExitCode = $LASTEXITCODE
    if ($rustcVersionExitCode -ne 0) {
        throw "rustc --version failed"
    }
    $rustcVersion = $rustcVersionOutput | Select-Object -First 1

    & $helper package `
        --metadata $metadataPath `
        --cargo-lock (Join-Path $root "Cargo.lock") `
        --binary $binary `
        --readme (Join-Path $root "README.md") `
        --license (Join-Path $root "LICENSE") `
        --license-mit (Join-Path $root "LICENSE-MIT") `
        --license-apache (Join-Path $root "LICENSE-APACHE") `
        --notice (Join-Path $root "NOTICE") `
        --out-dir $OutDir `
        --version $Version `
        --target $Target `
        --source-revision $SourceRevision `
        --source-date-epoch $SourceDateEpoch `
        --rustc $rustcVersion
    if ($LASTEXITCODE -ne 0) {
        throw "release packaging failed"
    }
} finally {
    Pop-Location
}
