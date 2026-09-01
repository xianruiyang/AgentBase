param(
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'

Update-FormatData -PrependPath (Join-Path $PSScriptRoot 'manage_agentbase.format.ps1xml') -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$lifecycleScript = Join-Path $ProjectRoot 'development\codex-deployment\managed_asset_lifecycle.ps1'
$portableConfigScript = Join-Path $ProjectRoot 'development\codex-deployment\portable_config.ps1'
. $lifecycleScript
. $portableConfigScript

$sandboxRoot = Join-Path $ProjectRoot 'development\codex-deployment\sandbox'
$testRoot = Join-Path $sandboxRoot ('managed-asset-lifecycle-test-' + [guid]::NewGuid().ToString('N'))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-TestText {
    param(
        [string]$Path,
        [string]$Text
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Write-LifecycleFixture {
    param(
        [string]$Path,
        [object]$Document
    )

    $text = ConvertTo-Json -InputObject $Document -Depth 8
    Write-TestText -Path $Path -Text ($text + [Environment]::NewLine)
}

function New-PathUnit {
    param(
        [string]$Id,
        [string]$RelativePath
    )

    return [pscustomobject]@{
        id = $Id
        kind = 'path'
        relative_path = $RelativePath
        path_kind = 'file'
        delivery_modes = @('DirectCompatibility')
        requires_portable_settings = $false
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $pathA = New-PathUnit -Id 'path:a' -RelativePath 'a.txt'
    $pathB = New-PathUnit -Id 'path:b' -RelativePath 'b.txt'
    $managedConfigText = 'managed_key = "agentbase"' + [Environment]::NewLine
    $managedConfigUnit = @(Get-PortableConfigManagedUnits -PortableText $managedConfigText)[0]

    $baseDocument = [ordered]@{
        schema_version = 1
        paths = [ordered]@{
            present = @(
                [ordered]@{ id = 'path:a'; path = 'a.txt'; kind = 'file'; modes = @('DirectCompatibility'); requires_portable_settings = $false }
                [ordered]@{ id = 'path:b'; path = 'b.txt'; kind = 'file'; modes = @('DirectCompatibility'); requires_portable_settings = $false }
            )
            retired = @()
            transferred = @()
        }
        config_keys = [ordered]@{
            present = @([ordered]@{ id = 'config:root/managed_key'; table = ''; key = 'managed_key' })
            retired = @()
            transferred = @()
        }
    }
    $basePath = Join-Path $testRoot 'base.json'
    Write-LifecycleFixture -Path $basePath -Document $baseDocument
    $baseContract = Get-ManagedAssetLifecycleContract -Path $basePath -CurrentPathUnits @($pathA, $pathB) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $null
    $baseReceipt = @(Get-ManagedAssetLifecycleReceiptUnits -Contract $baseContract -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $null -DeliveryMode DirectCompatibility -IncludePortableSettings $true)
    $baseManifest = [pscustomobject]@{ schema_version = 7; managed_asset_units = $baseReceipt }
    $outOfScopeReceipt = @(Get-ManagedAssetLifecycleReceiptUnits -Contract $baseContract -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $baseManifest -DeliveryMode DirectCompatibility -IncludePortableSettings $false)
    $carriedConfigUnit = @($outOfScopeReceipt | Where-Object { [string]$_.id -eq 'config:root/managed_key' })
    if ($carriedConfigUnit.Count -ne 1 -or
        [string]$carriedConfigUnit[0].last_managed_source_fingerprint -ne [string]$managedConfigUnit.source_fingerprint) {
        throw 'An out-of-scope deployment did not carry the last managed config provenance forward'
    }

    $missingPresentRejected = $false
    try {
        $null = Get-ManagedAssetLifecycleContract -Path $basePath -CurrentPathUnits @($pathA) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $null
    }
    catch {
        $missingPresentRejected = $_.Exception.Message -like 'Lifecycle present unit disappeared without an explicit transition*'
    }
    if (-not $missingPresentRejected) {
        throw 'Lifecycle validation did not reject a current path that disappeared without a transition'
    }

    $unregisteredCurrentRejected = $false
    try {
        $pathC = New-PathUnit -Id 'path:c' -RelativePath 'c.txt'
        $null = Get-ManagedAssetLifecycleContract -Path $basePath -CurrentPathUnits @($pathA, $pathB, $pathC) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $null
    }
    catch {
        $unregisteredCurrentRejected = $_.Exception.Message -like 'Current managed asset is missing from the lifecycle contract*'
    }
    if (-not $unregisteredCurrentRejected) {
        throw 'Lifecycle validation did not reject an unregistered current asset'
    }

    $deletedHistoryRejected = $false
    $ghostUnit = [pscustomobject]@{
        id = 'path:ghost'
        kind = 'path'
        state = 'present'
        delivery_modes = @('DirectCompatibility')
        requires_portable_settings = $false
        deployment_in_scope = $true
        relative_path = 'ghost.txt'
        path_kind = 'file'
    }
    try {
        $previousWithGhost = [pscustomobject]@{ schema_version = 7; managed_asset_units = @($baseReceipt) + @($ghostUnit) }
        $null = Get-ManagedAssetLifecycleContract -Path $basePath -CurrentPathUnits @($pathA, $pathB) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $previousWithGhost
    }
    catch {
        $deletedHistoryRejected = $_.Exception.Message -like 'Previously deployed managed asset was deleted from the lifecycle contract*'
    }
    if (-not $deletedHistoryRejected) {
        throw 'Lifecycle validation did not reject deletion of a previously deployed identity'
    }

    $transitionDocument = $baseDocument | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $transitionDocument.paths.present = @($transitionDocument.paths.present | Where-Object { [string]$_.id -ne 'path:b' })
    $transitionDocument.paths.retired = @([pscustomobject]@{
        id = 'path:b'
        path = 'b.txt'
        kind = 'file'
        modes = @('DirectCompatibility', 'Plugin')
        requires_portable_settings = $false
        since = 'test-transition'
        reason = 'explicit retirement'
    })
    $transitionPath = Join-Path $testRoot 'transition.json'
    Write-LifecycleFixture -Path $transitionPath -Document $transitionDocument
    $transitionContract = Get-ManagedAssetLifecycleContract -Path $transitionPath -CurrentPathUnits @($pathA) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $baseManifest
    if (@($transitionContract.units | Where-Object { [string]$_.id -eq 'path:b' -and [string]$_.state -eq 'retired' }).Count -ne 1) {
        throw 'Lifecycle validation did not retain the explicit path retirement'
    }
    $invalidReplacementDocument = $transitionDocument | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $invalidReplacementDocument.paths.retired[0] | Add-Member -NotePropertyName replaced_by -NotePropertyValue 'path:missing'
    $invalidReplacementPath = Join-Path $testRoot 'invalid-replacement.json'
    Write-LifecycleFixture -Path $invalidReplacementPath -Document $invalidReplacementDocument
    $invalidReplacementRejected = $false
    try {
        $null = Get-ManagedAssetLifecycleContract -Path $invalidReplacementPath -CurrentPathUnits @($pathA) -CurrentConfigUnits @($managedConfigUnit) -PreviousManifest $baseManifest
    }
    catch {
        $invalidReplacementRejected = $_.Exception.Message -like 'Managed asset has an invalid replacement identity*'
    }
    if (-not $invalidReplacementRejected) {
        throw 'Lifecycle validation did not reject a missing replacement identity'
    }

    $retiredConfigDocument = $baseDocument | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $retiredConfigDocument.config_keys.present = @()
    $retiredConfigDocument.config_keys.retired = @([pscustomobject]@{
        id = 'config:root/managed_key'
        table = ''
        key = 'managed_key'
        since = 'test-transition'
        reason = 'explicit config retirement'
    })
    $retiredConfigPath = Join-Path $testRoot 'retired-config.json'
    Write-LifecycleFixture -Path $retiredConfigPath -Document $retiredConfigDocument
    $retiredConfigContract = Get-ManagedAssetLifecycleContract -Path $retiredConfigPath -CurrentPathUnits @($pathA, $pathB) -CurrentConfigUnits @() -PreviousManifest $baseManifest
    $retiredConfigUnits = @($retiredConfigContract.config_units | Where-Object { [string]$_.state -eq 'retired' })
    $installedConfigPath = Join-Path $testRoot 'config.toml'
    Write-TestText -Path $installedConfigPath -Text ($managedConfigText + 'host_key = "keep"' + [Environment]::NewLine)
    $removable = @(Get-RetiredPortableConfigKeyDiagnostics -InstalledPath $installedConfigPath -RetiredConfigKeys $retiredConfigUnits -PreviousManifest $baseManifest)
    if ($removable.Count -ne 1 -or [string]$removable[0].status -ne 'removable') {
        throw "Unmodified retired config key was not classified as safely removable: $($removable | ConvertTo-Json -Compress)"
    }

    Write-TestText -Path $installedConfigPath -Text ('managed_key = "user-change"' + [Environment]::NewLine)
    $modified = @(Get-RetiredPortableConfigKeyDiagnostics -InstalledPath $installedConfigPath -RetiredConfigKeys $retiredConfigUnits -PreviousManifest $baseManifest)
    if ($modified.Count -ne 1 -or [string]$modified[0].status -ne 'modified') {
        throw 'User-modified retired config key was not protected from removal'
    }
    $unverifiable = @(Get-RetiredPortableConfigKeyDiagnostics -InstalledPath $installedConfigPath -RetiredConfigKeys $retiredConfigUnits -PreviousManifest $null)
    if ($unverifiable.Count -ne 1 -or [string]$unverifiable[0].status -ne 'unverifiable') {
        throw 'Retired config key without provenance was not rejected as unverifiable'
    }

    $transferredConfigDocument = $baseDocument | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $transferredConfigDocument.config_keys.present = @()
    $transferredConfigDocument.config_keys.transferred = @([pscustomobject]@{
        id = 'config:root/managed_key'
        table = ''
        key = 'managed_key'
        since = 'test-transfer'
        reason = 'ownership transferred to the host'
    })
    $transferredConfigPath = Join-Path $testRoot 'transferred-config.json'
    Write-LifecycleFixture -Path $transferredConfigPath -Document $transferredConfigDocument
    $transferredConfigContract = Get-ManagedAssetLifecycleContract -Path $transferredConfigPath -CurrentPathUnits @($pathA, $pathB) -CurrentConfigUnits @() -PreviousManifest $baseManifest
    $transferredConfigReceipt = @(Get-ManagedAssetLifecycleReceiptUnits -Contract $transferredConfigContract -CurrentConfigUnits @() -PreviousManifest $baseManifest -DeliveryMode DirectCompatibility -IncludePortableSettings $true | Where-Object { [string]$_.id -eq 'config:root/managed_key' })
    $transferredConfigRetirements = @(Get-SelectedRetiredManagedConfigUnits -Contract $transferredConfigContract -DeliveryMode DirectCompatibility -IncludePortableSettings $true)
    if ($transferredConfigReceipt.Count -ne 1 -or
        [string]$transferredConfigReceipt[0].state -ne 'transferred' -or
        [string]$transferredConfigReceipt[0].last_managed_source_fingerprint -ne [string]$managedConfigUnit.source_fingerprint -or
        $transferredConfigRetirements.Count -ne 0) {
        throw 'Transferred config ownership did not retain provenance without scheduling host-state removal'
    }

    $portablePath = Join-Path $testRoot 'portable.toml'
    Write-TestText -Path $portablePath -Text ('current_key = "current"' + [Environment]::NewLine)
    $installedWithRetired = 'current_key = "current"' + [Environment]::NewLine + $managedConfigText + 'host_key = "keep"' + [Environment]::NewLine
    $cleaned = Remove-RetiredPortableConfigKeysFromText -Text $installedWithRetired -RetiredConfigKeys $retiredConfigUnits
    if ($cleaned.Contains('managed_key') -or -not $cleaned.Contains('host_key = "keep"')) {
        throw 'Retired config removal did not preserve unrelated host state'
    }
    Write-TestText -Path $installedConfigPath -Text $cleaned
    $sourceFingerprint = Get-PortableConfigContractFingerprint -Path $portablePath -PortableSourcePath $portablePath -RetiredConfigKeys $retiredConfigUnits
    $installedFingerprint = Get-PortableConfigContractFingerprint -Path $installedConfigPath -PortableSourcePath $portablePath -RetiredConfigKeys $retiredConfigUnits
    if ($sourceFingerprint -ne $installedFingerprint) {
        throw 'Retired config key remained in the managed config projection after cleanup'
    }

    $result = [pscustomobject]@{
        current_inventory_matches_lifecycle = $true
        disappeared_present_unit_rejected = $true
        unregistered_current_unit_rejected = $true
        deployed_identity_deletion_rejected = $true
        explicit_cross_mode_retirement_accepted = $true
        missing_replacement_identity_rejected = $true
        config_provenance_carried_across_scope = $true
        matching_retired_config_removed = $true
        modified_retired_config_protected = $true
        unverifiable_retired_config_protected = $true
        transferred_config_preserved = $true
        unrelated_config_preserved = $true
    }
    $result.PSObject.TypeNames.Insert(0, 'AgentBase.Deployment.TestResult')
    $result
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        $approvedRoot = [IO.Path]::GetFullPath($sandboxRoot).TrimEnd('\') + '\'
        $resolvedRoot = [IO.Path]::GetFullPath($testRoot)
        if (-not $resolvedRoot.StartsWith($approvedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $resolvedRoot).StartsWith('managed-asset-lifecycle-test-', [StringComparison]::Ordinal)) {
            throw "Refusing lifecycle-test cleanup outside the approved sandbox: $resolvedRoot"
        }
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
