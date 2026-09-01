param(
    [string] $Output
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$targetMatrix = Get-Content -LiteralPath (Join-Path $scriptDir "release-targets.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$allowed = @(
    "MIT OR Apache-2.0"
    "Apache-2.0 OR MIT"
    "MIT/Apache-2.0"
    "Apache-2.0/MIT"
    "MIT"
    "Unlicense OR MIT"
    "BSD-2-Clause"
    "BSD-3-Clause"
    "(Apache-2.0 OR MIT) AND BSD-3-Clause"
    "BSD-2-Clause OR Apache-2.0 OR MIT"
    "(MIT OR Apache-2.0) AND Unicode-3.0"
    "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT"
    "Apache-2.0 OR MIT OR Zlib"
    "MIT OR Apache-2.0 OR Zlib"
    "ISC"
    "Zlib"
    "CC0-1.0"
)

Push-Location $root
try {
    $targetReports = foreach ($targetEntry in $targetMatrix.targets) {
        $target = $targetEntry.triple
        $metadataText = (& cargo metadata --locked --format-version 1 --filter-platform $target) -join "`n"
        if ($LASTEXITCODE -ne 0) { throw "cargo metadata failed for $target" }
        $metadata = $metadataText | ConvertFrom-Json
        $packageById = @{}
        foreach ($package in $metadata.packages) { $packageById[$package.id] = $package }
        $nodeById = @{}
        foreach ($node in $metadata.resolve.nodes) { $nodeById[$node.id] = $node }
        $rootPackage = $metadata.packages | Where-Object { $_.name -eq "srcq-cli" } | Select-Object -First 1
        if (-not $rootPackage) { throw "srcq-cli is missing from metadata for $target" }
        $reachable = @{}
        $queue = [Collections.Generic.Queue[string]]::new()
        $queue.Enqueue($rootPackage.id)
        while ($queue.Count -gt 0) {
            $id = $queue.Dequeue()
            if ($reachable.ContainsKey($id)) { continue }
            $reachable[$id] = $true
            $node = $nodeById[$id]
            if (-not $node) { continue }
            foreach ($dependency in $node.deps) {
                $include = @($dependency.dep_kinds).Count -eq 0
                foreach ($kind in @($dependency.dep_kinds)) {
                    if ($null -eq $kind.kind -or $kind.kind -eq "build") { $include = $true }
                }
                if ($include -and -not $reachable.ContainsKey($dependency.pkg)) { $queue.Enqueue($dependency.pkg) }
            }
        }
        $packages = foreach ($id in $reachable.Keys) {
            $package = $packageById[$id]
            if (-not $package.source) { continue }
            if ($package.license -notin $allowed) {
                throw "$($package.name) $($package.version) has unreviewed license $($package.license) on $target"
            }
            $packageRoot = Split-Path -Parent $package.manifest_path
            $licenseFiles = @(Get-ChildItem -LiteralPath $packageRoot -File | Where-Object {
                $_.Name.ToUpperInvariant() -match '^(LICENSE|LICENCE|COPYING|UNLICENSE|NOTICE)'
            } | Sort-Object Name | Select-Object -ExpandProperty Name)
            if ($licenseFiles.Count -eq 0) {
                throw "$($package.name) $($package.version) has no packaged license file on $target"
            }
            [ordered]@{
                name = $package.name
                version = $package.version
                license = $package.license
                licenseFiles = $licenseFiles
            }
        }
        $packages = @($packages | Sort-Object name, version)
        [ordered]@{
            target = $target
            thirdPartyPackages = $packages.Count
            licenseExpressions = @($packages.license | Sort-Object -Unique)
            packages = $packages
        }
    }
    $report = [ordered]@{
        schema = "srcq.license-audit/v1"
        policy = "reviewed-permissive-expressions-and-packaged-license-files"
        targets = @($targetReports)
        result = "pass"
    }
    $json = $report | ConvertTo-Json -Depth 8
    if ($Output) {
        $path = [IO.Path]::GetFullPath($Output)
        $parent = Split-Path -Parent $path
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        [IO.File]::WriteAllText($path, $json + "`n", [Text.UTF8Encoding]::new($false))
    }
    $json
} finally {
    Pop-Location
}
