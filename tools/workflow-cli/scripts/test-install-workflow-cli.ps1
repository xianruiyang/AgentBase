$ErrorActionPreference = 'Stop'
$root = Join-Path ([IO.Path]::GetTempPath()) ('workflow-cli-test-' + [guid]::NewGuid().ToString('N'))
$install = Join-Path $root 'install'
$pathFile = Join-Path $root 'PATH.txt'
$dist = Join-Path $root 'dist'
$archive = Join-Path $dist 'workflow-cli-0.1.1.zip'
function Assert([bool] $Condition, [string] $Message) { if (-not $Condition) { throw "FAIL: $Message" } }
try {
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    & (Join-Path $PSScriptRoot 'build-workflow-cli.ps1') -OutputRoot $dist | Out-Null
    Set-Content -LiteralPath $pathFile -Value 'C:\Other;C:\Other' -Encoding utf8NoBOM
    $installArgs = @('-NoProfile','-File',(Join-Path $PSScriptRoot 'install-workflow-cli.ps1'),'Install','-Archive',$archive,'-InstallRoot',$install,'-PathBackend','File','-PathValueFile',$pathFile,'-View','Machine')
    $first = & pwsh @installArgs | ConvertFrom-Json
    Assert ($first.ok -eq $true) 'first install'
    $second = & pwsh @installArgs | ConvertFrom-Json
    Assert ($second.changed -eq $false) 'idempotent install'
    $status = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Status -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | ConvertFrom-Json
    Assert ($status.ready -eq $true -and $status.health.pathCount -eq 1) 'healthy status'
    $statePath = Join-Path $install '.workflow-cli-install-state.json'
    $stateBytes = [IO.File]::ReadAllBytes($statePath)
    $state = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
    $state.currentDir = (Split-Path -Parent $install)
    [IO.File]::WriteAllText($statePath,($state | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    $stateFailure = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Uninstall -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine
    Assert ($LASTEXITCODE -ne 0) 'tampered state rejected before uninstall'
    [IO.File]::WriteAllBytes($statePath,$stateBytes)
    $evil = Join-Path $root 'evil.zip'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $stream = [IO.File]::Open($evil,[IO.FileMode]::CreateNew)
    try { $zip = [IO.Compression.ZipArchive]::new($stream,[IO.Compression.ZipArchiveMode]::Create,$false); try { $entry = $zip.CreateEntry('workflow-cli-0.1.1/../evil.txt'); $writer = [IO.StreamWriter]::new($entry.Open()); try { $writer.Write('bad') } finally { $writer.Dispose() } } finally { $zip.Dispose() } } finally { $stream.Dispose() }
    $evilHash = (Get-FileHash -LiteralPath $evil -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$evil.sha256", "$evilHash  evil.zip`n", [Text.UTF8Encoding]::new($false))
    $evilInstall = Join-Path $root 'evil-install'
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Install -Archive $evil -InstallRoot $evilInstall -PathBackend None -View Machine | Out-Null
    Assert ($LASTEXITCODE -ne 0 -and -not (Test-Path -LiteralPath (Join-Path $evilInstall 'current'))) 'malicious ZIP rejected before install'

    $upgradeSource = Join-Path $root 'upgrade-source'
    New-Item -ItemType Directory -Force -Path $upgradeSource | Out-Null
    foreach ($leaf in @('src','launchers','assets')) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot '..') $leaf) -Destination $upgradeSource -Recurse
    }
    [IO.File]::WriteAllText((Join-Path $upgradeSource 'VERSION'), "0.1.2`n", [Text.UTF8Encoding]::new($false))
    $upgradeDist = Join-Path $root 'upgrade-dist'
    & (Join-Path $PSScriptRoot 'build-workflow-cli.ps1') -ProjectRoot $upgradeSource -OutputRoot $upgradeDist | Out-Null
    $beforeCurrent = [IO.File]::ReadAllBytes((Join-Path $install 'current\workctl.cmd'))
    $beforeState = [IO.File]::ReadAllBytes($statePath)
    $stateLock = [IO.File]::Open($statePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Upgrade -Archive (Join-Path $upgradeDist 'workflow-cli-0.1.2.zip') -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | Out-Null
        Assert ($LASTEXITCODE -ne 0) 'post-swap state failure rejected upgrade'
    }
    finally { $stateLock.Dispose() }
    $afterCurrent = [IO.File]::ReadAllBytes((Join-Path $install 'current\workctl.cmd'))
    $afterState = [IO.File]::ReadAllBytes($statePath)
    Assert (($beforeCurrent.Length -eq $afterCurrent.Length) -and (@(0..($beforeCurrent.Length - 1) | Where-Object { $beforeCurrent[$_] -ne $afterCurrent[$_] }).Count -eq 0)) 'failed upgrade restored current'
    Assert (($beforeState.Length -eq $afterState.Length) -and (@(0..($beforeState.Length - 1) | Where-Object { $beforeState[$_] -ne $afterState[$_] }).Count -eq 0)) 'failed upgrade preserved install state'
    $rolledBack = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Status -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | ConvertFrom-Json
    Assert ($rolledBack.ready -eq $true -and $rolledBack.version -eq '0.1.1') 'rollback status'

    Add-Content -LiteralPath (Join-Path $install 'current\VERSION') -Value 'tamper'
    $tampered = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Status -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | ConvertFrom-Json
    Assert ($tampered.ready -eq $false) 'tamper detected'
    $pathText = [IO.File]::ReadAllText($pathFile)
    Set-Content -LiteralPath $pathFile -Value ($pathText -replace [regex]::Escape("$install\current"),'') -Encoding utf8NoBOM
    $drift = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Status -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | ConvertFrom-Json
    Assert ($drift.ready -eq $false) 'PATH drift detected'
    $removed = & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'install-workflow-cli.ps1') Uninstall -InstallRoot $install -PathBackend File -PathValueFile $pathFile -View Machine | ConvertFrom-Json
    Assert ($removed.removed -eq $true) 'uninstall'
    Assert ([IO.File]::ReadAllText($pathFile).Contains('C:\Other')) 'uninstall preserved unrelated PATH'
    '{"ok":true,"tests":"install,idempotence,tamper,path-drift,rollback,uninstall"}'
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
