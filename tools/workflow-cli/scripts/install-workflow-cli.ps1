param(
    [ValidateSet('Install','Upgrade','Status','Uninstall')][string] $Action = 'Install',
    [string] $Archive,
    [string] $Checksum,
    [string] $InstallRoot,
    [ValidateSet('User','File','None')][string] $PathBackend = 'User',
    [string] $PathValueFile,
    [ValidateSet('Model','Machine')][string] $View = 'Model'
)

$ErrorActionPreference = 'Stop'
$StateSchema = 'workflow-cli.install/v1'
$Managed = @('src/workctl.py','src/taskctl.py','workctl.cmd','taskctl.cmd','VERSION','manifest.json','assets/templates/current-state.md','assets/templates/deferred-changes.md','assets/templates/design.md','assets/templates/requirements.md','assets/templates/solution.md','assets/templates/user-design.md')

function Full([string] $Path) { [IO.Path]::GetFullPath($Path).TrimEnd('\') }
function Write-Text([string] $Path, [string] $Text) { [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false)) }
function Hash([string] $Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Literal([object] $Value) { if ($null -eq $Value) { return 'null' }; ConvertTo-Json -InputObject ([string]$Value) -Compress }
function Model([object] $Result) {
    if ($View -eq 'Machine') { return $Result | ConvertTo-Json -Depth 10 }
    $fields = [System.Collections.Generic.List[string]]::new()
    if ($Result.ok -eq $false) { $fields.Add('ok:false'); $fields.Add("error:$(Literal $Result.error)") }
    elseif ($Action -eq 'Status') {
        $fields.Add("ready:$(([bool]$Result.ready).ToString().ToLowerInvariant())")
        if ($Result.version) { $fields.Add("version:$(Literal $Result.version)") }
        if ($Result.reason) { $fields.Add("reason:$(Literal $Result.reason)") }
        if ($Result.next) { $fields.Add("next:$(Literal $Result.next)") }
    } else {
        $fields.Add('ok:true'); $fields.Add("op:$($Action.ToLowerInvariant())")
        if ($null -ne $Result.changed) { $fields.Add("changed:$(([bool]$Result.changed).ToString().ToLowerInvariant())") }
        if ($Result.version) { $fields.Add("version:$(Literal $Result.version)") }
        if ($Result.restart) { $fields.Add('restart:true') }
        if ($Result.removed -ne $null) { $fields.Add("removed:$(([bool]$Result.removed).ToString().ToLowerInvariant())") }
        if ($Result.next) { $fields.Add("next:$(Literal $Result.next)") }
    }
    '{' + ($fields -join ' ') + '}'
}
function Emit([object] $Result) { Model $Result | Write-Output }
function SafeRoot([string] $Root) {
    $full = Full $Root
    $volume = [IO.Path]::GetPathRoot($full).TrimEnd('\')
    if (-not $full -or $full -eq $volume -or $full.Length -lt $volume.Length + 4) { throw "Unsafe install root" }
    $full
}
function Get-PathText([string] $Backend, [string] $File) {
    if ($Backend -eq 'None') { return '' }
    if ($Backend -eq 'User') { return [Environment]::GetEnvironmentVariable('Path','User') ?? '' }
    if (-not $File) { throw '-PathValueFile is required for File backend' }
    if (-not (Test-Path -LiteralPath $File)) { return '' }
    [IO.File]::ReadAllText((Full $File), [Text.Encoding]::UTF8)
}
function Set-PathText([string] $Backend, [string] $File, [string] $Value) {
    if ($Backend -eq 'None') { return }
    if ($Backend -eq 'User') { [Environment]::SetEnvironmentVariable('Path',$Value,'User'); return }
    $parent = Split-Path -Parent (Full $File)
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Write-Text (Full $File) $Value
}
function PathEqual([string] $A, [string] $B) { try { (Full $A).ToLowerInvariant() -eq (Full $B).ToLowerInvariant() } catch { $false } }
function Add-Path([string] $Backend, [string] $File, [string] $Entry) {
    if ($Backend -eq 'None') { return $false }
    $old = Get-PathText $Backend $File
    foreach ($part in ($old -split ';')) { if ($part.Trim() -and (PathEqual $part.Trim() $Entry)) { return $false } }
    Set-PathText $Backend $File $(if ($old.Trim()) { $old.TrimEnd(';') + ';' + $Entry } else { $Entry })
    $true
}
function Remove-Path([string] $Backend, [string] $File, [string] $Entry) {
    if ($Backend -eq 'None') { return }
    $old = Get-PathText $Backend $File
    $kept = @($old -split ';' | Where-Object { -not $_.Trim() -or -not (PathEqual $_.Trim() $Entry) })
    Set-PathText $Backend $File ($kept -join ';')
}
function Read-State([string] $Path, [string] $Root) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $state = [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($state.schema -ne $StateSchema -or -not (PathEqual $state.installRoot $Root)) { throw 'install state identity mismatch' }
    $expectedCurrent = Full (Join-Path $Root 'current')
    if (-not $state.currentDir -or -not (PathEqual $state.currentDir $expectedCurrent)) { throw 'install state current directory is invalid' }
    $actualManaged = @($state.managedFiles | ForEach-Object { [string]$_ } | Sort-Object)
    $expectedManaged = @($Managed | Sort-Object)
    if (Compare-Object $expectedManaged $actualManaged) { throw 'install state managed file set is invalid' }
    if ($state.path.backend -notin @('User','File','None') -or -not $state.path.entry -or -not (PathEqual $state.path.entry $expectedCurrent)) { throw 'install state PATH entry is invalid' }
    if ($state.path.backend -eq 'File' -and -not $state.path.valueFile) { throw 'install state PATH value file is missing' }
    if ($state.path.backend -ne 'File' -and $state.path.valueFile) { throw 'install state PATH value file is unexpected' }
    $state
}
function Verify-Current($State, [string] $Root) {
    $current = Full (Join-Path $Root 'current')
    if (-not (Test-Path -LiteralPath $current -PathType Container)) { throw 'current directory is missing' }
    $manifest = [IO.File]::ReadAllText((Join-Path $current 'manifest.json'),[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($manifest.schema -ne 'workflow-cli.package/v1' -or $manifest.version -ne $State.version) { throw 'manifest identity mismatch' }
    $expectedPayload = @($Managed | Where-Object { $_ -ne 'manifest.json' } | ForEach-Object { $_ -replace '\\','/' } | Sort-Object)
    $actualPayload = @($manifest.files | ForEach-Object { [string]$_.path } | Sort-Object)
    if (Compare-Object $expectedPayload $actualPayload) { throw 'manifest member set is invalid' }
    foreach ($file in $manifest.files) {
        $path = Join-Path $current $file.path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -ne [int64]$file.bytes -or (Hash $path) -ne $file.sha256) { throw "managed file integrity mismatch: $($file.path)" }
    }
    foreach ($cmd in @('workctl','taskctl')) { $line = @(& (Join-Path $current "$cmd.cmd") --version); if ($LASTEXITCODE -ne 0 -or $line[0] -ne "$cmd $($State.version)") { throw "command version mismatch: $cmd" } }
    $count = @((Get-PathText $State.path.backend $State.path.valueFile) -split ';' | Where-Object { $_.Trim() -and (PathEqual $_.Trim() $current) }).Count
    if ($State.path.backend -ne 'None' -and $count -ne 1) { throw "managed PATH entry count is $count" }
    [pscustomobject]@{ current = $current; manifest = $manifest; pathCount = $count }
}
function Assert-ZipLayout([string] $ArchivePath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead((Full $ArchivePath))
    try {
        $files = [System.Collections.Generic.List[string]]::new()
        $roots = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($entry in $zip.Entries) {
            $name = [string]$entry.FullName
            if (-not $name -or $name.Contains('\') -or $name.StartsWith('/') -or $name.Contains(':')) { throw 'unsafe ZIP member path' }
            $parts = $name -split '/'
            if ($parts.Count -lt 2 -or $parts[0] -in @('', '.', '..') -or $parts[1..($parts.Count - 1)] -contains '..' -or $parts[1..($parts.Count - 1)] -contains '.') { throw 'unsafe ZIP member path' }
            $roots.Add($parts[0]) | Out-Null
            if (-not $name.EndsWith('/')) { if ($files.Contains($name)) { throw 'duplicate ZIP member' }; $files.Add($name) }
        }
        if ($roots.Count -ne 1) { throw 'ZIP root is not unique' }
        $root = @($roots)[0]
        $expected = @($Managed | ForEach-Object { "$root/$_" -replace '\\','/' } | Sort-Object)
        $actual = @($files | Sort-Object)
        if (Compare-Object $expected $actual) { throw 'ZIP file set is invalid' }
    } finally { $zip.Dispose() }
}
function Expand-Package([string] $ArchivePath, [string] $ChecksumPath, [string] $Destination) {
    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) { throw 'archive not found' }
    if (-not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) { throw 'checksum sidecar not found' }
    $name = Split-Path -Leaf (Full $ArchivePath)
    $line = [IO.File]::ReadAllText((Full $ChecksumPath),[Text.Encoding]::UTF8).Trim()
    if ($line -notmatch '^([0-9a-fA-F]{64})  ([^/\\]+)$' -or $Matches[2] -ne $name -or $Matches[1].ToLowerInvariant() -ne (Hash (Full $ArchivePath))) { throw 'archive checksum mismatch' }
    Assert-ZipLayout $ArchivePath
    Expand-Archive -LiteralPath (Full $ArchivePath) -DestinationPath $Destination -Force
    $roots = @(Get-ChildItem -LiteralPath $Destination -Directory)
    if ($roots.Count -ne 1) { throw 'package root is not unique' }
    $root = $roots[0].FullName
    $manifest = [IO.File]::ReadAllText((Join-Path $root 'manifest.json'),[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($manifest.schema -ne 'workflow-cli.package/v1' -or $manifest.archive -ne $name) { throw 'package manifest identity mismatch' }
    $expectedPayload = @($Managed | Where-Object { $_ -ne 'manifest.json' } | ForEach-Object { $_ -replace '\\','/' } | Sort-Object)
    $actualPayload = @($manifest.files | ForEach-Object { [string]$_.path } | Sort-Object)
    if (Compare-Object $expectedPayload $actualPayload) { throw 'package member set is invalid' }
    $expectedMembers = @($expectedPayload + 'manifest.json' | Sort-Object)
    $actualMembers = @(Get-ChildItem -LiteralPath $root -File -Recurse | ForEach-Object { $_.FullName.Substring($root.Length + 1) -replace '\\','/' } | Sort-Object)
    if (Compare-Object $expectedMembers $actualMembers) { throw 'package file set is invalid' }
    foreach ($file in $manifest.files) { $path = Join-Path $root $file.path; if (-not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -ne [int64]$file.bytes -or (Hash $path) -ne $file.sha256) { throw "package file mismatch: $($file.path)" } }
    $root
}

if (-not $InstallRoot) { if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required' }; $InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\AgentBase\workflow-cli' }
$InstallRoot = SafeRoot $InstallRoot
$current = Join-Path $InstallRoot 'current'
$statePath = Join-Path $InstallRoot '.workflow-cli-install-state.json'
if ($PathValueFile) { $PathValueFile = Full $PathValueFile }

try {
    $state = Read-State $statePath $InstallRoot
    if ($Action -eq 'Status') {
        if ($null -eq $state) { Emit ([ordered]@{ schema=$StateSchema; installed=$false; ready=$false; reason='not_installed'; next='install a validated workflow-cli package' }); exit 1 }
        try { $health = Verify-Current $state $InstallRoot; Emit ([ordered]@{ schema=$StateSchema; installed=$true; ready=$true; version=$state.version; installRoot=$InstallRoot; path=$state.path; files=$state.managedFiles; health=$health }); exit 0 }
        catch { Emit ([ordered]@{ schema=$StateSchema; installed=$true; ready=$false; reason='integrity_invalid'; error=$_.Exception.Message; next='reinstall a validated workflow-cli package' }); exit 2 }
    }
    if ($Action -eq 'Uninstall') {
        if ($null -eq $state) { Emit ([ordered]@{ schema=$StateSchema; removed=$false; reason='not_installed' }); exit 0 }
        if ($state.path.addedByInstaller) { Remove-Path $state.path.backend $state.path.valueFile $state.path.entry }
        foreach ($leaf in $state.managedFiles) { $file = Join-Path $current $leaf; if (Test-Path -LiteralPath $file -PathType Leaf) { Remove-Item -LiteralPath $file -Force } }
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath -Force }
        Emit ([ordered]@{ schema=$StateSchema; removed=$true }); exit 0
    }
    if (-not $Archive) { throw '-Archive is required for Install or Upgrade' }
    if (-not $Checksum) { $Checksum = "$Archive.sha256" }
    if ($Action -eq 'Upgrade' -and $null -eq $state) { throw 'not installed; use Install' }
    if ($state -and ($state.path.backend -ne $PathBackend -or [string]$state.path.valueFile -ne [string]$PathValueFile)) { throw 'PATH backend cannot change during upgrade' }
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $temp = Join-Path $InstallRoot ('.staging-' + [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $InstallRoot ('.backup-' + [guid]::NewGuid().ToString('N'))
    $oldPath = Get-PathText $PathBackend $PathValueFile
    $oldState = if (Test-Path -LiteralPath $statePath) { [IO.File]::ReadAllBytes($statePath) } else { $null }
    $currentMoved = $false
    $newCurrent = $false
    try {
        New-Item -ItemType Directory -Force -Path $temp | Out-Null
        $packageRoot = Expand-Package $Archive $Checksum $temp
        if ($state) {
            $candidateManifest = [IO.File]::ReadAllText((Join-Path $packageRoot 'manifest.json'),[Text.Encoding]::UTF8) | ConvertFrom-Json
            $same = $candidateManifest.version -eq $state.version
            if ($same -and (Test-Path -LiteralPath $current -PathType Container)) {
                foreach ($file in $candidateManifest.files) {
                    $existing = Join-Path $current $file.path
                    if (-not (Test-Path -LiteralPath $existing -PathType Leaf) -or (Get-Item -LiteralPath $existing).Length -ne [int64]$file.bytes -or (Hash $existing) -ne $file.sha256) { $same = $false; break }
                }
            } else { $same = $false }
            if ($same) {
                $pathAdded = Add-Path $PathBackend $PathValueFile $current
                Emit ([ordered]@{ schema=$StateSchema; ok=$true; changed=([bool]$pathAdded); version=$state.version; restart=([bool]$pathAdded) }); exit 0
            }
        }
        if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination $backup; $currentMoved = $true }
        Move-Item -LiteralPath $packageRoot -Destination $current
        $newCurrent = $true
        $added = Add-Path $PathBackend $PathValueFile $current
        $manifest = [IO.File]::ReadAllText((Join-Path $current 'manifest.json'),[Text.Encoding]::UTF8) | ConvertFrom-Json
        $newState = [ordered]@{ schema=$StateSchema; version=$manifest.version; installRoot=$InstallRoot; currentDir=$current; managedFiles=$Managed; path=[ordered]@{ backend=$PathBackend; valueFile=$PathValueFile; entry=$current; addedByInstaller=([bool]$added -or [bool]$state.path.addedByInstaller) } }
        Write-Text $statePath (($newState | ConvertTo-Json -Depth 8) + "`n")
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
        Emit ([ordered]@{ schema=$StateSchema; ok=$true; changed=$true; version=$manifest.version; restart=([bool]$added) }); exit 0
    } catch {
        Set-PathText $PathBackend $PathValueFile $oldPath
        if ($newCurrent -and (Test-Path -LiteralPath $current)) { Remove-Item -LiteralPath $current -Recurse -Force }
        if ($currentMoved -and (Test-Path -LiteralPath $backup)) { Move-Item -LiteralPath $backup -Destination $current }
        if ($null -ne $oldState) { [IO.File]::WriteAllBytes($statePath,$oldState) } elseif (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath -Force }
        throw
    } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }; if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force } }
} catch {
    Emit ([ordered]@{ schema=$StateSchema; ok=$false; error=$_.Exception.Message; next='repair the package input and retry' }); exit 2
}
