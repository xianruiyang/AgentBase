param(
    [string] $OutputRoot = (Join-Path $PSScriptRoot '..\dist'),
    [string] $ProjectRoot = (Join-Path $PSScriptRoot '..')
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBom {
    param([string] $Path, [string] $Text)
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Full([string] $Path) { [IO.Path]::GetFullPath($Path).TrimEnd('\') }

$project = Full $ProjectRoot
$output = Full $OutputRoot
$Version = ([IO.File]::ReadAllText((Join-Path $project 'VERSION'), [Text.Encoding]::UTF8)).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid version: $Version" }
$archiveName = "workflow-cli-$Version.zip"
$stageParent = Join-Path $output '.staging'
$stage = Join-Path $stageParent ("workflow-cli-$Version-" + [guid]::NewGuid().ToString('N'))
$packageRoot = Join-Path $stage "workflow-cli-$Version"
$archive = Join-Path $output $archiveName
$checksum = "$archive.sha256"

try {
    New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
    $files = @(
        'src/workctl.py',
        'src/taskctl.py',
        'workctl.cmd',
        'taskctl.cmd',
        'VERSION',
        'assets/templates/current-state.md',
        'assets/templates/deferred-changes.md',
        'assets/templates/design.md',
        'assets/templates/requirements.md',
        'assets/templates/solution.md',
        'assets/templates/user-design.md'
    )
    foreach ($leaf in $files) {
        $source = if ($leaf -match '^src/') { Join-Path $project ($leaf -replace '^src/', 'src\') } elseif ($leaf -match '\.cmd$') { Join-Path $project "launchers\$leaf" } elseif ($leaf -match '^assets/') { Join-Path $project ($leaf -replace '/', '\') } else { Join-Path $project $leaf }
        $destination = Join-Path $packageRoot ($leaf -replace '/', '\')
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing package source: $leaf" }
        $destinationParent = Split-Path -Parent $destination
        if ($destinationParent) { New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null }
        Copy-Item -LiteralPath $source -Destination $destination
    }
    $records = foreach ($leaf in $files) {
        $file = Get-Item -LiteralPath (Join-Path $packageRoot $leaf)
        [ordered]@{ path = $leaf; bytes = [int64]$file.Length; sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $manifest = [ordered]@{
        schema = 'workflow-cli.package/v1'
        version = $Version
        archive = $archiveName
        commands = @('workctl', 'taskctl')
        files = @($records)
    }
    Write-Utf8NoBom (Join-Path $packageRoot 'manifest.json') (($manifest | ConvertTo-Json -Depth 8) + "`n")
    $zipTemp = Join-Path $stage "$archiveName.tmp"
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipTemp -CompressionLevel Optimal
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    Move-Item -LiteralPath $zipTemp -Destination $archive
    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Utf8NoBom $checksum "$archiveHash  $archiveName`n"
    [pscustomobject]@{ ok = $true; version = $Version; archive = $archive; checksum = $checksum; files = $files } | ConvertTo-Json -Compress
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    if ((Test-Path -LiteralPath $stageParent) -and -not (Get-ChildItem -LiteralPath $stageParent -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $stageParent -Force }
}
