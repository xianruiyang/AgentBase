param(
    [Parameter(Mandatory = $true)]
    [string] $ArchiveV1,

    [Parameter(Mandatory = $true)]
    [string] $ArchiveV2,

    [Parameter(Mandatory = $true)]
    [string] $Engine,

    [string] $Output
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $scriptDir "install-sgy.ps1"
$powershellExe = (Get-Process -Id $PID).Path
$root = Join-Path ([IO.Path]::GetTempPath()) ("sgy-install-test-" + [guid]::NewGuid().ToString("N"))
$installRoot = Join-Path $root "managed-install"
$pathFile = Join-Path $root "user-path.txt"
$config = Join-Path $root "appdata\sgy\config.yml"
$cache = Join-Path $root "localappdata\sgy\cache\v1\sentinel.bin"
$oldAppData = $env:APPDATA
$oldLocalAppData = $env:LOCALAPPDATA

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-InstallerJson {
    param([string[]] $Arguments)
    $text = & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $installer @Arguments
    if ($LASTEXITCODE -ne 0) { throw "installer failed: $text" }
    ($text -join "`n") | ConvertFrom-Json
}

try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $config) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cache) | Out-Null
    [IO.File]::WriteAllText($config, "schema: sgy.config/v1`nprofile: files`n", [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllBytes($cache, [byte[]](1, 3, 3, 7))
    [IO.File]::WriteAllText($pathFile, "C:\existing", [Text.UTF8Encoding]::new($false))
    $configHash = (Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash
    $cacheHash = (Get-FileHash -LiteralPath $cache -Algorithm SHA256).Hash
    $env:APPDATA = Split-Path -Parent (Split-Path -Parent $config)
    $env:LOCALAPPDATA = Join-Path $root "localappdata"

    $common = @("-InstallRoot", $installRoot, "-PathBackend", "File", "-PathValueFile", $pathFile)
    $first = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV1) + $common)
    Assert-True ($first.changed -eq $true) "first install did not change state"
    $pathAfterFirst = [IO.File]::ReadAllText($pathFile)
    $entry = Join-Path $installRoot "current"
    Assert-True ((@($pathAfterFirst -split ';' | Where-Object { $_ -eq $entry }).Count) -eq 1) "PATH entry was not added exactly once"

    $second = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV1) + $common)
    Assert-True ($second.changed -eq $false) "repeat install was not idempotent"
    Assert-True ([IO.File]::ReadAllText($pathFile) -eq $pathAfterFirst) "repeat install changed PATH"

    $stateTemporaryBlocker = Join-Path $installRoot ".sgy-install-state.json.tmp"
    New-Item -ItemType Directory -Force -Path $stateTemporaryBlocker | Out-Null
    $rollbackObserved = $false
    try {
        $null = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV2) + $common)
    } catch {
        $rollbackObserved = $true
    }
    Assert-True $rollbackObserved "upgrade commit failure was not surfaced"
    Assert-True ((& (Join-Path $installRoot "current\sgy.exe") --version) -eq "sgy 0.1.0") "failed upgrade did not restore the old binary"
    Assert-True ([IO.File]::ReadAllText($pathFile) -eq $pathAfterFirst) "failed upgrade changed PATH"
    Remove-Item -LiteralPath $stateTemporaryBlocker -Recurse -Force

    $maliciousDir = Join-Path $root "malicious"
    New-Item -ItemType Directory -Force -Path $maliciousDir | Out-Null
    $maliciousArchive = Join-Path $maliciousDir (Split-Path -Leaf $ArchiveV2)
    Copy-Item -LiteralPath $ArchiveV2 -Destination $maliciousArchive
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $maliciousZip = [IO.Compression.ZipFile]::Open($maliciousArchive, [IO.Compression.ZipArchiveMode]::Update)
    try {
        $readmeEntry = $maliciousZip.Entries | Where-Object { $_.FullName.EndsWith('/README.md') } | Select-Object -First 1
        $readmeEntry.Delete()
        $stem = [IO.Path]::GetFileNameWithoutExtension($maliciousArchive)
        $null = $maliciousZip.CreateEntry("$stem/../escape.txt")
    } finally {
        $maliciousZip.Dispose()
    }
    $maliciousHash = (Get-FileHash -LiteralPath $maliciousArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$maliciousArchive.sha256", "$maliciousHash  $(Split-Path -Leaf $maliciousArchive)`n", [Text.UTF8Encoding]::new($false))
    $maliciousRejected = $false
    try {
        $null = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $maliciousArchive) + $common)
    } catch {
        $maliciousRejected = $true
    }
    Assert-True $maliciousRejected "unsafe ZIP member was accepted"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $root "escape.txt"))) "unsafe ZIP member escaped staging"
    Assert-True ((& (Join-Path $installRoot "current\sgy.exe") --version) -eq "sgy 0.1.0") "rejected package changed the installed version"

    $upgrade = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV2) + $common)
    Assert-True ($upgrade.version -eq "0.1.1") "upgrade did not install 0.1.1"
    $binary = Join-Path $entry "sgy.exe"
    $version = & $binary --version
    Assert-True ($version -eq "sgy 0.1.1") "upgraded binary version mismatch"
    Assert-True ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) "upgrade changed user config"
    Assert-True ((Get-FileHash -LiteralPath $cache -Algorithm SHA256).Hash -eq $cacheHash) "upgrade changed cache"

    $doctor = & $binary doctor --engine $Engine
    Assert-True ($LASTEXITCODE -eq 0) "doctor could not use the explicit ast-grep engine"
    $doctorText = $doctor -join "`n"
    Assert-True ($doctorText.Contains('"source": "explicit"')) "doctor did not use the explicit engine"
    Assert-True ($doctorText.Contains('"compatibility": "version_reported')) "doctor did not report engine compatibility"

    [IO.File]::WriteAllText((Join-Path $entry "user-owned.txt"), "keep", [Text.UTF8Encoding]::new($false))
    $pathWithConcurrentEdit = [IO.File]::ReadAllText($pathFile) + ";C:\after-install"
    [IO.File]::WriteAllText($pathFile, $pathWithConcurrentEdit, [Text.UTF8Encoding]::new($false))
    $removed = Invoke-InstallerJson -Arguments (@("Uninstall") + $common)
    Assert-True ($removed.removed -eq $true) "uninstall did not report removal"
    Assert-True (Test-Path -LiteralPath (Join-Path $entry "user-owned.txt")) "uninstall deleted an unknown user file"
    Assert-True (-not (Test-Path -LiteralPath $binary)) "uninstall kept the managed binary"
    $pathAfterUninstall = [IO.File]::ReadAllText($pathFile)
    Assert-True (-not (@($pathAfterUninstall -split ';') -contains $entry)) "uninstall did not roll back its PATH entry"
    Assert-True ($pathAfterUninstall.Contains("C:\existing")) "uninstall removed the pre-existing PATH entry"
    Assert-True ($pathAfterUninstall.Contains("C:\after-install")) "uninstall lost a concurrent PATH edit"
    Assert-True ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) "uninstall changed user config"
    Assert-True ((Get-FileHash -LiteralPath $cache -Algorithm SHA256).Hash -eq $cacheHash) "default uninstall changed cache"

    Remove-Item -LiteralPath (Join-Path $entry "user-owned.txt") -Force
    if (-not (Get-ChildItem -LiteralPath $entry -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $entry -Force }
    $again = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV2) + $common)
    Assert-True ($again.changed -eq $true) "reinstall after uninstall failed"
    $cacheRemoval = Invoke-InstallerJson -Arguments (@("Uninstall", "-RemoveCache") + $common)
    Assert-True ($cacheRemoval.cacheRemoved -eq $true) "explicit cache removal was not reported"
    Assert-True (-not (Test-Path -LiteralPath (Split-Path -Parent $cache))) "explicit cache removal kept cache v1"
    Assert-True ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) "cache removal changed config"

    $preexistingRoot = Join-Path $root "preexisting-install"
    $preexistingEntry = Join-Path $preexistingRoot "current"
    $preexistingPathFile = Join-Path $root "preexisting-path.txt"
    $preexistingPath = "C:\before;$preexistingEntry;C:\after"
    [IO.File]::WriteAllText($preexistingPathFile, $preexistingPath, [Text.UTF8Encoding]::new($false))
    $preexistingCommon = @("-InstallRoot", $preexistingRoot, "-PathBackend", "File", "-PathValueFile", $preexistingPathFile)
    $preexistingInstall = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV2) + $preexistingCommon)
    Assert-True ($preexistingInstall.pathEntryAdded -eq $false) "installer claimed a pre-existing PATH entry"
    $null = Invoke-InstallerJson -Arguments (@("Uninstall") + $preexistingCommon)
    Assert-True ([IO.File]::ReadAllText($preexistingPathFile) -eq $preexistingPath) "uninstall removed a pre-existing PATH entry"

    $tamperRoot = Join-Path $root "tampered-state-install"
    $tamperCommon = @("-InstallRoot", $tamperRoot, "-PathBackend", "None")
    $null = Invoke-InstallerJson -Arguments (@("Install", "-Archive", $ArchiveV2) + $tamperCommon)
    $victim = Join-Path $tamperRoot "current\victim.txt"
    [IO.File]::WriteAllText($victim, "do-not-delete", [Text.UTF8Encoding]::new($false))
    $tamperStatePath = Join-Path $tamperRoot ".sgy-install-state.json"
    $validStateText = [IO.File]::ReadAllText($tamperStatePath, [Text.Encoding]::UTF8)
    $tamperedState = $validStateText | ConvertFrom-Json
    $tamperedState.managedFiles = @($tamperedState.managedFiles) + "victim.txt"
    [IO.File]::WriteAllText($tamperStatePath, (($tamperedState | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
    $tamperedStateRejected = $false
    try {
        $null = Invoke-InstallerJson -Arguments (@("Uninstall") + $tamperCommon)
    } catch {
        $tamperedStateRejected = $true
    }
    Assert-True $tamperedStateRejected "tampered managed file state was accepted"
    Assert-True (Test-Path -LiteralPath $victim) "tampered state deleted an undeclared user file"
    [IO.File]::WriteAllText($tamperStatePath, $validStateText, [Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $victim -Force
    $null = Invoke-InstallerJson -Arguments (@("Uninstall") + $tamperCommon)

    $report = [ordered]@{
        schema = "sgy.install-test/v1"
        firstInstall = $first.changed
        repeatInstallChanged = $second.changed
        failedUpgradeRolledBack = $rollbackObserved
        unsafeZipRejected = $maliciousRejected
        tamperedStateRejected = $tamperedStateRejected
        upgradedVersion = $upgrade.version
        doctorCompatible = $true
        pathEntryCountAfterInstall = 1
        concurrentPathEditPreserved = $true
        preexistingPathEntryPreserved = $true
        unknownInstallFilePreserved = $true
        configPreserved = $true
        cachePreservedByDefault = $true
        cacheRemovedExplicitly = $true
    }
    $json = $report | ConvertTo-Json -Depth 5
    if ($Output) {
        $parent = Split-Path -Parent ([IO.Path]::GetFullPath($Output))
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        [IO.File]::WriteAllText([IO.Path]::GetFullPath($Output), $json + "`n", [Text.UTF8Encoding]::new($false))
    }
    $json
} finally {
    $env:APPDATA = $oldAppData
    $env:LOCALAPPDATA = $oldLocalAppData
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
