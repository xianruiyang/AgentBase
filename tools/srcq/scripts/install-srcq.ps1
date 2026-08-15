param(
    [Parameter(Position = 0)]
    [ValidateSet("Install", "Upgrade", "Uninstall", "Status")]
    [string] $Action = "Install",

    [string] $Archive,
    [string] $Checksum,
    [string] $InstallRoot,

    [ValidateSet("User", "File", "None")]
    [string] $PathBackend = "User",

    [string] $PathValueFile,
    [switch] $RemoveCache
)

$ErrorActionPreference = "Stop"
$StateSchema = "srcq.install/v1"
$ExpectedMembers = @(
    "LICENSE"
    "LICENSE-APACHE"
    "LICENSE-MIT"
    "NOTICE"
    "README.md"
    "THIRD_PARTY_LICENSES.txt"
    "manifest.json"
    "sbom.spdx.json"
)

function Write-Utf8NoBom {
    param([string] $Path, [string] $Text)
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Get-FullPath {
    param([string] $Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-SafeInstallRoot {
    param([string] $Root)
    $full = Get-FullPath $Root
    $volume = [IO.Path]::GetPathRoot($full).TrimEnd('\')
    if (-not $full -or $full -eq $volume -or $full.Length -le ($volume.Length + 2)) {
        throw "Unsafe install root: $full"
    }
    $full
}

function Get-Sha256 {
    param([string] $Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-ManagedFilesMatch {
    param([string] $ExpectedRoot, [string] $ActualRoot, [string[]] $Members)
    foreach ($leaf in $Members) {
        $expected = Join-Path $ExpectedRoot $leaf
        $actual = Join-Path $ActualRoot $leaf
        if (-not (Test-Path -LiteralPath $actual -PathType Leaf) -or
            (Get-Item -LiteralPath $expected).Length -ne (Get-Item -LiteralPath $actual).Length -or
            (Get-Sha256 $expected) -ne (Get-Sha256 $actual)) {
            return $false
        }
    }
    $true
}

function Get-NormalizedPathEntry {
    param([string] $Path)
    (Get-FullPath $Path).ToLowerInvariant()
}

function Get-PathValue {
    param([string] $Backend, [string] $ValueFile)
    switch ($Backend) {
        "User" {
            $value = [Environment]::GetEnvironmentVariable("Path", "User")
            if ($null -eq $value) { return "" }
            return $value
        }
        "File" {
            if (-not $ValueFile) { throw "-PathValueFile is required for PathBackend=File" }
            if (-not (Test-Path -LiteralPath $ValueFile)) { return "" }
            return [IO.File]::ReadAllText((Get-FullPath $ValueFile), [Text.Encoding]::UTF8)
        }
        "None" { return "" }
        default { throw "Unsupported PATH backend: $Backend" }
    }
}

function Set-PathValue {
    param([string] $Backend, [string] $ValueFile, [string] $Value)
    switch ($Backend) {
        "User" { [Environment]::SetEnvironmentVariable("Path", $Value, "User") }
        "File" {
            if (-not $ValueFile) { throw "-PathValueFile is required for PathBackend=File" }
            $parent = Split-Path -Parent (Get-FullPath $ValueFile)
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            Write-Utf8NoBom -Path (Get-FullPath $ValueFile) -Text $Value
        }
        "None" { }
        default { throw "Unsupported PATH backend: $Backend" }
    }
}

function Ensure-PathEntry {
    param([string] $Backend, [string] $ValueFile, [string] $Entry)
    if ($Backend -eq "None") {
        return [pscustomobject]@{ Value = ""; Added = $false }
    }
    $value = Get-PathValue -Backend $Backend -ValueFile $ValueFile
    $normalized = Get-NormalizedPathEntry $Entry
    $present = $false
    foreach ($part in ($value -split ';')) {
        if (-not [string]::IsNullOrWhiteSpace($part)) {
            try {
                if ((Get-NormalizedPathEntry $part.Trim()) -eq $normalized) {
                    $present = $true
                    break
                }
            } catch {
                # Preserve malformed unrelated PATH entries without treating them as ours.
            }
        }
    }
    if ($present) {
        return [pscustomobject]@{ Value = $value; Added = $false }
    }
    $updated = if ([string]::IsNullOrWhiteSpace($value)) { $Entry } else { $value.TrimEnd(';') + ';' + $Entry }
    Set-PathValue -Backend $Backend -ValueFile $ValueFile -Value $updated
    [pscustomobject]@{ Value = $updated; Added = $true }
}

function Remove-OnePathEntry {
    param([string] $Backend, [string] $ValueFile, [string] $Entry)
    if ($Backend -eq "None") { return }
    $value = Get-PathValue -Backend $Backend -ValueFile $ValueFile
    $normalized = Get-NormalizedPathEntry $Entry
    $removed = $false
    $kept = foreach ($part in ($value -split ';')) {
        if (-not $removed -and -not [string]::IsNullOrWhiteSpace($part)) {
            $matches = $false
            try { $matches = (Get-NormalizedPathEntry $part.Trim()) -eq $normalized } catch { }
            if ($matches) {
                $removed = $true
                continue
            }
        }
        $part
    }
    if ($removed) {
        Set-PathValue -Backend $Backend -ValueFile $ValueFile -Value ($kept -join ';')
    }
}

function Get-ExpectedWindowsTarget {
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    switch ($architecture.ToUpperInvariant()) {
        "AMD64" { "x86_64-pc-windows-msvc" }
        "ARM64" { "aarch64-pc-windows-msvc" }
        default { throw "Unsupported Windows architecture: $architecture" }
    }
}

function Read-ZipEntryText {
    param($Entry)
    $stream = $Entry.Open()
    try {
        $reader = [IO.StreamReader]::new($stream, [Text.UTF8Encoding]::new($false), $true)
        try { $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally {
        $stream.Dispose()
    }
}

function Copy-ZipEntry {
    param($Entry, [string] $Destination)
    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $source = $Entry.Open()
    try {
        $target = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $source.CopyTo($target) } finally { $target.Dispose() }
    } finally {
        $source.Dispose()
    }
}

function Expand-VerifiedPackage {
    param([string] $ArchivePath, [string] $ChecksumPath, [string] $StagingRoot)
    $archiveFull = Get-FullPath $ArchivePath
    $checksumFull = Get-FullPath $ChecksumPath
    if (-not (Test-Path -LiteralPath $archiveFull -PathType Leaf)) { throw "Archive not found: $archiveFull" }
    if (-not (Test-Path -LiteralPath $checksumFull -PathType Leaf)) { throw "Checksum not found: $checksumFull" }
    $archiveName = Split-Path -Leaf $archiveFull
    $checksumLine = [IO.File]::ReadAllText($checksumFull, [Text.Encoding]::UTF8).Trim()
    if ($checksumLine -notmatch '^([0-9a-fA-F]{64})  ([^/\\]+)$' -or $Matches[2] -ne $archiveName) {
        throw "Invalid checksum sidecar"
    }
    $actualArchiveHash = Get-Sha256 $archiveFull
    if ($actualArchiveHash -ne $Matches[1].ToLowerInvariant()) { throw "Archive SHA-256 mismatch" }
    if (-not $archiveName.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) { throw "Release archive must be ZIP" }
    $stem = $archiveName.Substring(0, $archiveName.Length - 4)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archiveFull)
    try {
        $byName = @{}
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if (-not $name -or $name.Contains('\') -or $name.StartsWith('/') -or $name.Contains(':')) {
                throw "Unsafe ZIP member: $name"
            }
            $segments = $name -split '/'
            if ($segments.Count -ne 2 -or $segments[0] -ne $stem -or $segments[1] -in @('', '.', '..')) {
                throw "Unexpected ZIP layout: $name"
            }
            if ($byName.ContainsKey($name)) { throw "Duplicate ZIP member: $name" }
            $byName[$name] = $entry
        }
        $manifestEntryName = "$stem/manifest.json"
        if (-not $byName.ContainsKey($manifestEntryName)) { throw "Package manifest is missing" }
        $manifestText = Read-ZipEntryText $byName[$manifestEntryName]
        $manifest = $manifestText | ConvertFrom-Json
        if ($manifest.schema -ne "srcq.release/v1" -or $manifest.archive -ne $archiveName) {
            throw "Package manifest identity mismatch"
        }
        if ($manifest.target -ne (Get-ExpectedWindowsTarget)) {
            throw "Package target $($manifest.target) does not match this host"
        }
        if ($manifest.binary -notin @('srcq.exe')) { throw "Unexpected package binary: $($manifest.binary)" }
        $expectedLeaves = @($ExpectedMembers + $manifest.binary | Sort-Object)
        $actualLeaves = @($byName.Keys | ForEach-Object { ($_ -split '/')[1] } | Sort-Object)
        if (Compare-Object $expectedLeaves $actualLeaves) { throw "Package member set is not exact" }

        $packageRoot = Join-Path $StagingRoot "package"
        New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
        foreach ($leaf in $expectedLeaves) {
            Copy-ZipEntry -Entry $byName["$stem/$leaf"] -Destination (Join-Path $packageRoot $leaf)
        }

        $manifestFiles = @{}
        foreach ($file in $manifest.files) {
            if ($file.path -notin @($manifest.binary, 'README.md', 'LICENSE', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'THIRD_PARTY_LICENSES.txt', 'sbom.spdx.json')) {
                throw "Unexpected manifest file: $($file.path)"
            }
            if ($manifestFiles.ContainsKey($file.path)) { throw "Duplicate manifest file: $($file.path)" }
            $manifestFiles[$file.path] = $file
        }
        if ($manifestFiles.Count -ne 8) { throw "Manifest file set is incomplete" }
        foreach ($leaf in $manifestFiles.Keys) {
            $path = Join-Path $packageRoot $leaf
            $record = $manifestFiles[$leaf]
            if ((Get-Item -LiteralPath $path).Length -ne [Int64]$record.bytes -or (Get-Sha256 $path) -ne $record.sha256) {
                throw "Manifest hash/size mismatch: $leaf"
            }
        }
        $versionLine = & (Join-Path $packageRoot $manifest.binary) --version
        if ($LASTEXITCODE -ne 0 -or ($versionLine | Select-Object -First 1) -ne "srcq $($manifest.version)") {
            throw "Package binary version does not match manifest"
        }
        [pscustomobject]@{
            Root = $packageRoot
            Manifest = $manifest
            Members = $expectedLeaves
            ArchiveSha256 = $actualArchiveHash
        }
    } finally {
        $zip.Dispose()
    }
}

function Read-InstallState {
    param([string] $StatePath, [string] $Root)
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { return $null }
    $state = [IO.File]::ReadAllText($StatePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($state.schema -ne $StateSchema -or (Get-FullPath $state.installRoot) -ne $Root) {
        throw "Install state does not belong to this install root"
    }
    if ((Get-FullPath $state.currentDir) -ne (Get-FullPath (Join-Path $Root 'current'))) {
        throw "Install state currentDir is outside the managed location"
    }
    if ($state.binary -ne 'srcq.exe' -or $state.version -notmatch '^[A-Za-z0-9.+_-]+$' -or $state.target -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Install state identity is invalid"
    }
    $expectedManaged = @($ExpectedMembers + $state.binary | Sort-Object)
    $actualManaged = @($state.managedFiles | Sort-Object)
    if (Compare-Object $expectedManaged $actualManaged) { throw "Install state managed file set is invalid" }
    if ($state.path.backend -notin @('User', 'File', 'None')) { throw "Install state PATH backend is invalid" }
    if ((Get-NormalizedPathEntry $state.path.entry) -ne (Get-NormalizedPathEntry (Join-Path $Root 'current'))) {
        throw "Install state PATH entry is outside the managed location"
    }
    if ($state.path.backend -eq 'File' -and -not $state.path.valueFile) { throw "Install state PATH file is missing" }
    if ($state.path.backend -ne 'File' -and $state.path.valueFile) { throw "Install state has an unexpected PATH file" }
    $state
}

function Get-PathEntryCount {
    param([string] $Backend, [string] $ValueFile, [string] $Entry)
    if ($Backend -eq "None") { return 0 }
    $value = Get-PathValue -Backend $Backend -ValueFile $ValueFile
    $normalized = Get-NormalizedPathEntry $Entry
    $count = 0
    foreach ($part in ($value -split ';')) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        try {
            if ((Get-NormalizedPathEntry $part.Trim()) -eq $normalized) { $count += 1 }
        } catch {
            # Preserve malformed unrelated PATH entries without treating them as ours.
        }
    }
    $count
}

function Get-InstalledPackageHealth {
    param($State, [string] $Root)
    $currentDir = Get-FullPath (Join-Path $Root 'current')
    if (-not (Test-Path -LiteralPath $currentDir -PathType Container)) {
        throw "Installed current directory is missing"
    }
    foreach ($leaf in @($State.managedFiles)) {
        if (-not (Test-Path -LiteralPath (Join-Path $currentDir $leaf) -PathType Leaf)) {
            throw "Managed install file is missing: $leaf"
        }
    }

    $manifestPath = Join-Path $currentDir 'manifest.json'
    $manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($manifest.schema -ne 'srcq.release/v1' -or $manifest.version -ne $State.version -or
        $manifest.target -ne $State.target -or $manifest.binary -ne $State.binary) {
        throw "Installed manifest identity does not match install state"
    }
    if ($manifest.target -ne (Get-ExpectedWindowsTarget)) {
        throw "Installed target $($manifest.target) does not match this host"
    }

    $allowedFiles = @($manifest.binary, 'README.md', 'LICENSE', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'THIRD_PARTY_LICENSES.txt', 'sbom.spdx.json')
    $manifestFiles = @{}
    foreach ($file in @($manifest.files)) {
        if ($file.path -notin $allowedFiles -or $manifestFiles.ContainsKey([string]$file.path)) {
            throw "Installed manifest file set is invalid"
        }
        $manifestFiles[[string]$file.path] = $file
    }
    if ($manifestFiles.Count -ne 8) { throw "Installed manifest file set is incomplete" }
    foreach ($leaf in $manifestFiles.Keys) {
        $path = Join-Path $currentDir $leaf
        $record = $manifestFiles[$leaf]
        if ((Get-Item -LiteralPath $path).Length -ne [Int64]$record.bytes -or
            (Get-Sha256 $path) -ne ([string]$record.sha256).ToLowerInvariant()) {
            throw "Installed file hash/size mismatch: $leaf"
        }
    }

    $binary = Join-Path $currentDir $manifest.binary
    $versionLine = @(& $binary --version)
    if ($LASTEXITCODE -ne 0 -or $versionLine.Count -eq 0 -or $versionLine[0] -ne "srcq $($manifest.version)") {
        throw "Installed binary version does not match manifest"
    }
    $pathEntryCount = Get-PathEntryCount -Backend $State.path.backend -ValueFile $State.path.valueFile -Entry $State.path.entry
    $pathReady = if ($State.path.backend -eq 'None') { $null } else { $pathEntryCount -eq 1 }
    if ($State.path.backend -ne 'None' -and -not $pathReady) {
        throw "Managed PATH entry count is $pathEntryCount; expected exactly one"
    }
    [pscustomobject]@{
        Binary = $binary
        BinaryVersion = $versionLine[0]
        PathEntryCount = $pathEntryCount
        PathReady = $pathReady
    }
}

function Write-InstallState {
    param([string] $StatePath, $State)
    $temporary = "$StatePath.tmp"
    Write-Utf8NoBom -Path $temporary -Text (($State | ConvertTo-Json -Depth 8) + "`n")
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }
    Move-Item -LiteralPath $temporary -Destination $StatePath
}

function Remove-ManagedCache {
    if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is required to remove the cache" }
    $local = Get-FullPath $env:LOCALAPPDATA
    $cache = Get-FullPath (Join-Path $local "srcq\cache\v1")
    $prefix = $local.TrimEnd('\') + '\'
    if (-not $cache.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing cache removal outside LOCALAPPDATA"
    }
    if (Test-Path -LiteralPath $cache) { Remove-Item -LiteralPath $cache -Recurse -Force }
}

if (-not $InstallRoot) {
    if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is required when -InstallRoot is omitted" }
    $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\srcq"
}
$InstallRoot = Assert-SafeInstallRoot $InstallRoot
$CurrentDir = Join-Path $InstallRoot "current"
$StatePath = Join-Path $InstallRoot ".srcq-install-state.json"
if ($PathValueFile) { $PathValueFile = Get-FullPath $PathValueFile }

if ($Action -eq "Status") {
    try {
        $state = Read-InstallState -StatePath $StatePath -Root $InstallRoot
        if ($null -eq $state) {
            [pscustomobject]@{ schema = $StateSchema; installed = $false; ready = $false; installRoot = $InstallRoot; recovery = "install a validated srcq release archive" } | ConvertTo-Json -Depth 4
            exit 1
        }
        $health = Get-InstalledPackageHealth -State $state -Root $InstallRoot
        [pscustomobject]@{
            schema = $StateSchema
            installed = $true
            ready = $true
            integrity = "verified"
            version = $state.version
            target = $state.target
            installRoot = $InstallRoot
            binary = $health.Binary
            binaryVersion = $health.BinaryVersion
            path = $state.path
            pathReady = $health.PathReady
            pathEntryCount = $health.PathEntryCount
        } | ConvertTo-Json -Depth 6
        exit 0
    } catch {
        [pscustomobject]@{
            schema = $StateSchema
            installed = (Test-Path -LiteralPath $StatePath -PathType Leaf)
            ready = $false
            integrity = "invalid"
            installRoot = $InstallRoot
            error = $_.Exception.Message
            recovery = "reinstall from a validated release archive and repair the managed PATH entry"
        } | ConvertTo-Json -Depth 5
        exit 2
    }
}

if ($Action -eq "Uninstall") {
    $state = Read-InstallState -StatePath $StatePath -Root $InstallRoot
    if ($null -eq $state) {
        if ($RemoveCache) { Remove-ManagedCache }
        [pscustomobject]@{ schema = $StateSchema; removed = $false; reason = "not-installed" } | ConvertTo-Json
        exit 0
    }
    if ($state.path.backend -ne $PathBackend) { throw "PATH backend does not match install state" }
    if ($state.path.backend -eq 'File' -and (Get-FullPath $state.path.valueFile) -ne $PathValueFile) {
        throw "PATH value file does not match install state"
    }
    if ($state.path.addedByInstaller) {
        Remove-OnePathEntry -Backend $state.path.backend -ValueFile $state.path.valueFile -Entry $state.path.entry
    }
    foreach ($leaf in $state.managedFiles) {
        if ($leaf -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe managed file in install state: $leaf" }
        $path = Join-Path $CurrentDir $leaf
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
    }
    if ((Test-Path -LiteralPath $CurrentDir) -and -not (Get-ChildItem -LiteralPath $CurrentDir -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $CurrentDir -Force
    }
    Remove-Item -LiteralPath $StatePath -Force
    if ($RemoveCache) { Remove-ManagedCache }
    if ((Test-Path -LiteralPath $InstallRoot) -and -not (Get-ChildItem -LiteralPath $InstallRoot -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $InstallRoot -Force
    }
    [pscustomobject]@{ schema = $StateSchema; removed = $true; cacheRemoved = [bool]$RemoveCache } | ConvertTo-Json
    exit 0
}

if (-not $Archive) { throw "-Archive is required for $Action" }
if (-not $Checksum) { $Checksum = "$Archive.sha256" }
if ($PathBackend -eq "File" -and -not $PathValueFile) { throw "-PathValueFile is required for PathBackend=File" }
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$existingState = Read-InstallState -StatePath $StatePath -Root $InstallRoot
if ($Action -eq "Upgrade" -and -not $existingState) {
    throw "Source Query Gateway is not installed; run Install first"
}
if ($existingState -and ($existingState.path.backend -ne $PathBackend -or $existingState.path.valueFile -ne $PathValueFile)) {
    throw "PATH backend cannot change during upgrade; uninstall first"
}

$stagingRoot = Join-Path $InstallRoot (".staging-" + [guid]::NewGuid().ToString("N"))
$backupDir = Join-Path $InstallRoot (".backup-" + [guid]::NewGuid().ToString("N"))
$oldPathValue = Get-PathValue -Backend $PathBackend -ValueFile $PathValueFile
$oldStateBytes = if (Test-Path -LiteralPath $StatePath) { [IO.File]::ReadAllBytes($StatePath) } else { $null }
$currentMoved = $false
$newCurrentCommitted = $false
try {
    New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
    $package = Expand-VerifiedPackage -ArchivePath $Archive -ChecksumPath $Checksum -StagingRoot $stagingRoot
    if ($existingState -and $existingState.version -eq $package.Manifest.version -and $existingState.target -eq $package.Manifest.target -and
        (Test-ManagedFilesMatch -ExpectedRoot $package.Root -ActualRoot $CurrentDir -Members @($package.Members))) {
        $pathResult = Ensure-PathEntry -Backend $PathBackend -ValueFile $PathValueFile -Entry $CurrentDir
        [pscustomobject]@{ schema = $StateSchema; changed = [bool]$pathResult.Added; version = $existingState.version; installRoot = $InstallRoot; pathEntryAdded = [bool]$pathResult.Added } | ConvertTo-Json
        exit 0
    }
    if (Test-Path -LiteralPath $CurrentDir) {
        Move-Item -LiteralPath $CurrentDir -Destination $backupDir
        $currentMoved = $true
    }
    Move-Item -LiteralPath $package.Root -Destination $CurrentDir
    $newCurrentCommitted = $true
    $pathResult = Ensure-PathEntry -Backend $PathBackend -ValueFile $PathValueFile -Entry $CurrentDir
    $addedByInstaller = if ($existingState) {
        [bool]$existingState.path.addedByInstaller -or [bool]$pathResult.Added
    } else {
        [bool]$pathResult.Added
    }
    $state = [ordered]@{
        schema = $StateSchema
        version = $package.Manifest.version
        target = $package.Manifest.target
        installRoot = $InstallRoot
        currentDir = $CurrentDir
        binary = $package.Manifest.binary
        archiveSha256 = $package.ArchiveSha256
        managedFiles = @($package.Members)
        path = [ordered]@{
            backend = $PathBackend
            valueFile = $PathValueFile
            entry = $CurrentDir
            addedByInstaller = $addedByInstaller
        }
    }
    Write-InstallState -StatePath $StatePath -State $state
    if (Test-Path -LiteralPath $backupDir) { Remove-Item -LiteralPath $backupDir -Recurse -Force }
    [pscustomobject]@{
        schema = $StateSchema
        changed = $true
        version = $state.version
        target = $state.target
        installRoot = $InstallRoot
        binary = (Join-Path $CurrentDir $state.binary)
        pathEntryAdded = $pathResult.Added
    } | ConvertTo-Json -Depth 5
} catch {
    Set-PathValue -Backend $PathBackend -ValueFile $PathValueFile -Value $oldPathValue
    if ($newCurrentCommitted -and (Test-Path -LiteralPath $CurrentDir)) { Remove-Item -LiteralPath $CurrentDir -Recurse -Force }
    if ($currentMoved -and (Test-Path -LiteralPath $backupDir)) { Move-Item -LiteralPath $backupDir -Destination $CurrentDir }
    if ($null -ne $oldStateBytes) {
        [IO.File]::WriteAllBytes($StatePath, $oldStateBytes)
    } elseif (Test-Path -LiteralPath $StatePath) {
        Remove-Item -LiteralPath $StatePath -Force
    }
    throw
} finally {
    if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }
    if (Test-Path -LiteralPath $backupDir) { Remove-Item -LiteralPath $backupDir -Recurse -Force }
}
