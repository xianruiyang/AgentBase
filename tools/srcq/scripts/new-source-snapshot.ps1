param(
    [string] $Output
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$excludedRoots = @(".git", "dist", "target")

if (-not $Output) {
    $Output = Join-Path $root "dist\srcq-source-snapshot.json"
}
$Output = [IO.Path]::GetFullPath($Output)

$files = [Collections.Generic.List[IO.FileInfo]]::new()
foreach ($entry in Get-ChildItem -LiteralPath $root -Force) {
    if ($entry.PSIsContainer) {
        if ($entry.Name -in $excludedRoots) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $entry.FullName -Recurse -File -Force) {
            $files.Add($file)
        }
    } else {
        $files.Add($entry)
    }
}

$byPath = @{}
$paths = [string[]]@($files | ForEach-Object {
    $relative = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
    $byPath[$relative] = $_
    $relative
})
[Array]::Sort($paths, [StringComparer]::Ordinal)

$canonical = [Text.StringBuilder]::new()
$records = foreach ($path in $paths) {
    $file = $byPath[$path]
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    [void]$canonical.Append($path).Append([char]0).Append($file.Length).Append([char]0).Append($hash).Append("`n")
    [ordered]@{
        path = $path
        size = [UInt64]$file.Length
        sha256 = $hash
    }
}

$sha = [Security.Cryptography.SHA256]::Create()
try {
    $digest = ([BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($canonical.ToString()))) -replace '-', '').ToLowerInvariant()
} finally {
    $sha.Dispose()
}

$report = [ordered]@{
    schema = "srcq.source-snapshot/v1"
    sourceRevision = "sha256:$digest"
    algorithm = "sha256(path + NUL + size + NUL + fileSha256 + LF), paths sorted ordinal"
    root = "."
    excludedRoots = $excludedRoots
    fileCount = $records.Count
    files = @($records)
}

$parent = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $parent | Out-Null
[IO.File]::WriteAllText(
    $Output,
    ($report | ConvertTo-Json -Depth 6) + "`n",
    [Text.UTF8Encoding]::new($false)
)
$report | Select-Object schema, sourceRevision, fileCount
