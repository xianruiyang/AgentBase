param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
& git.exe -C $ProjectRoot diff --quiet HEAD --
if ($LASTEXITCODE -ne 0) { throw 'Commit the reviewed release sources before building' }
$commit = (& git.exe -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve release commit' }
$pluginRelative = 'development/plugin-packaging/template/agentbase-core/.codex-plugin/plugin.json'
$plugin = (& git.exe -C $ProjectRoot show "HEAD:$pluginRelative") -join "`n" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Unable to read committed plugin version' }
$version = [string]$plugin.version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Release requires a stable semantic version' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot "dist\$version" }
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'Release output already exists; choose a new directory instead of overwriting assets' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
$stage = Join-Path $output '.stage'
$source = Join-Path $stage 'AgentBase'
$sourceArchive = Join-Path $output '.source.zip'
$successful = $false
try {
    & git.exe -C $ProjectRoot archive --format=zip --output=$sourceArchive $commit
    if ($LASTEXITCODE -ne 0) { throw 'Git source export failed' }
    [IO.Compression.ZipFile]::ExtractToDirectory($sourceArchive, $source)
    & (Join-Path $source 'development/codex-deployment/manage_agentbase.ps1') -Action Validate -ProjectRoot $source | Out-Null
    $pluginRoot = & (Join-Path $source 'development/plugin-packaging/build_plugin.ps1') -ProjectRoot $source
    $recovery = Join-Path $source 'recovery'
    & (Join-Path $source 'development/codex-deployment/build_recovery_bundle.ps1') -OutputDirectory $recovery | Out-Null

    $archives = @(
        [pscustomobject]@{ name = "agentbase-$version-windows.zip"; source = $source },
        [pscustomobject]@{ name = "agentbase-core-$version.zip"; source = [string]$pluginRoot },
        [pscustomobject]@{ name = "agentbase-recovery-$version-windows.zip"; source = $recovery }
    )
    $assets = @()
    foreach ($archive in $archives) {
        $path = Join-Path $output $archive.name
        [IO.Compression.ZipFile]::CreateFromDirectory($archive.source, $path, [IO.Compression.CompressionLevel]::Optimal, $false)
        $assets += [ordered]@{
            name = $archive.name
            bytes = (Get-Item -LiteralPath $path).Length
            sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $srcqCargo = [IO.File]::ReadAllText((Join-Path $source 'tools/srcq/Cargo.toml'))
    $srcqVersion = [regex]::Match($srcqCargo, '(?m)^version\s*=\s*"([0-9.]+)"').Groups[1].Value
    if (-not $srcqVersion) { throw 'Unable to resolve srcq source version' }
    $manifest = [ordered]@{
        schema = 'agentbase.release/v1'; version = $version; tag = "agentbase-v$version"
        source_commit = $commit
        component_source_versions = [ordered]@{
            srcq = $srcqVersion
            workflow_cli = [IO.File]::ReadAllText((Join-Path $source 'tools/workflow-cli/VERSION')).Trim()
        }
        bundled_cli_binaries = $false
        official_plugin_validation = $true
        assets = $assets
    }
    $utf8 = [Text.UTF8Encoding]::new($false)
    $manifestPath = Join-Path $output 'manifest.json'
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8) + "`n", $utf8)
    $checksums = @($assets | ForEach-Object { $_.sha256 + '  ' + $_.name })
    $checksums += (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() + '  manifest.json'
    [IO.File]::WriteAllText((Join-Path $output 'SHA256SUMS'), ($checksums -join "`n") + "`n", $utf8)
    $successful = $true
} finally {
    # Only generated staging inside this invocation's new output directory is removed.
    $prefix = $output.TrimEnd('\') + '\'
    foreach ($generated in @($stage, $sourceArchive)) {
        if (-not [IO.Path]::GetFullPath($generated).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe release staging cleanup' }
        if (Test-Path -LiteralPath $generated) { Remove-Item -LiteralPath $generated -Recurse -Force }
    }
}
if ($successful) {
    [pscustomobject]@{ built = $true; version = $version; directory = $output; assets = @($assets.name) + @('manifest.json', 'SHA256SUMS') }
}
