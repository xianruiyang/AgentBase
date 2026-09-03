function Get-AgentBaseLifecycleTextSha256 {
    param(
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-', '')
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-AgentBaseLifecycleRelativePath {
    param(
        [string]$Path,
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -ne $Path.Trim()) {
        throw "$Label must be a non-empty relative path without surrounding whitespace"
    }
    $normalized = $Path.Replace('/', '\')
    if ([IO.Path]::IsPathRooted($normalized) -or $normalized -ne $normalized.Trim('\')) {
        throw "$Label must be a relative path: $Path"
    }
    $segments = @($normalized -split '\\')
    if ($segments.Count -eq 0 -or @($segments | Where-Object { [string]::IsNullOrWhiteSpace($_) -or $_ -in @('.', '..') }).Count -gt 0) {
        throw "$Label contains an unsafe path segment: $Path"
    }
    if ($normalized.Contains(':') -or $normalized.Contains('*') -or $normalized.Contains('?')) {
        throw "$Label contains unsupported path characters: $Path"
    }
    return $normalized
}

function Get-AgentBaseLifecycleModes {
    param(
        [object[]]$Modes,
        [string]$Label
    )

    $allowed = @('DirectCompatibility', 'Plugin')
    $normalized = @($Modes | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    if ($normalized.Count -eq 0 -or @($normalized | Where-Object { $allowed -notcontains $_ }).Count -gt 0) {
        throw "$Label must contain DirectCompatibility, Plugin, or both"
    }
    return $normalized
}

function Test-AgentBaseLifecycleUnitInScope {
    param(
        [object]$Unit,
        [ValidateSet('DirectCompatibility', 'Plugin')]
        [string]$DeliveryMode,
        [bool]$IncludePortableSettings
    )

    return @($Unit.delivery_modes) -contains $DeliveryMode -and
        (-not [bool]$Unit.requires_portable_settings -or $IncludePortableSettings)
}

function Assert-AgentBaseLifecycleIdentityEqual {
    param(
        [object]$Expected,
        [object]$Actual,
        [string]$Context
    )

    if ([string]$Expected.kind -ne [string]$Actual.kind) {
        throw "$Context changed kind for $($Expected.id)"
    }
    if ([string]$Expected.kind -eq 'path') {
        if (-not [string]::Equals([string]$Expected.relative_path, [string]$Actual.relative_path, [StringComparison]::OrdinalIgnoreCase) -or
            [string]$Expected.path_kind -ne [string]$Actual.path_kind) {
            throw "$Context changed path identity for $($Expected.id)"
        }
        return
    }
    if ([string]$Expected.table -cne [string]$Actual.table -or [string]$Expected.key -cne [string]$Actual.key) {
        throw "$Context changed config-key identity for $($Expected.id)"
    }
}

function Assert-AgentBaseLifecyclePresentDefinitionEqual {
    param(
        [object]$Expected,
        [object]$Actual,
        [string]$Context
    )

    Assert-AgentBaseLifecycleIdentityEqual -Expected $Expected -Actual $Actual -Context $Context
    if ([string]$Expected.kind -eq 'path' -and
        ((@($Expected.delivery_modes | Sort-Object) -join '|') -ne (@($Actual.delivery_modes | Sort-Object) -join '|') -or
        [bool]$Expected.requires_portable_settings -ne [bool]$Actual.requires_portable_settings)) {
        throw "$Context changed present delivery scope for $($Expected.id)"
    }
}

function Get-ManagedAssetLifecycleContract {
    param(
        [string]$Path,
        [object[]]$CurrentPathUnits,
        [object[]]$CurrentConfigUnits,
        [object]$PreviousManifest,
        [ValidateSet('', 'DirectCompatibility', 'Plugin')]
        [string]$DeliveryMode = '',
        [bool]$IncludePortableSettings = $true
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Managed-asset lifecycle contract is missing: $Path"
    }
    try {
        $document = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Managed-asset lifecycle contract is not valid JSON: $($_.Exception.Message)"
    }
    if ([int]$document.schema_version -ne 1) {
        throw "Unsupported managed-asset lifecycle schema: $($document.schema_version)"
    }

    $units = New-Object 'System.Collections.Generic.List[object]'
    foreach ($state in @('present', 'retired', 'transferred')) {
        foreach ($entry in @($document.paths.$state)) {
            $id = [string]$entry.id
            if ($id -notmatch '^[a-z0-9][a-z0-9:._/-]*$') {
                throw "Managed path has an invalid stable id: $id"
            }
            $pathKind = [string]$entry.kind
            if (@('file', 'directory') -notcontains $pathKind) {
                throw "Managed path has an unsupported kind: $id ($pathKind)"
            }
            if ($entry.PSObject.Properties.Name -notcontains 'requires_portable_settings') {
                throw "Managed path must declare requires_portable_settings: $id"
            }
            $since = if ($entry.PSObject.Properties.Name -contains 'since') { [string]$entry.since } else { $null }
            $reason = if ($entry.PSObject.Properties.Name -contains 'reason') { [string]$entry.reason } else { $null }
            if ($state -ne 'present' -and ([string]::IsNullOrWhiteSpace($since) -or [string]::IsNullOrWhiteSpace($reason))) {
                throw "Non-present managed path must declare since and reason: $id"
            }
            $units.Add([pscustomobject][ordered]@{
                id = $id
                kind = 'path'
                state = $state
                relative_path = Get-AgentBaseLifecycleRelativePath -Path ([string]$entry.path) -Label "Managed path $id"
                path_kind = $pathKind
                delivery_modes = @(Get-AgentBaseLifecycleModes -Modes @($entry.modes) -Label "Managed path modes for $id")
                requires_portable_settings = [bool]$entry.requires_portable_settings
                since = $since
                reason = $reason
                replaced_by = if ($entry.PSObject.Properties.Name -contains 'replaced_by') { [string]$entry.replaced_by } else { $null }
                legacy_import = $entry.PSObject.Properties.Name -contains 'legacy_import' -and [bool]$entry.legacy_import
            })
        }
    }
    foreach ($state in @('present', 'retired', 'transferred')) {
        foreach ($entry in @($document.config_keys.$state)) {
            $id = [string]$entry.id
            $table = [string]$entry.table
            $key = [string]$entry.key
            if ($id -notmatch '^config:[a-z0-9][a-z0-9:._/-]*$' -or
                ($table -ne '' -and $table -notmatch '^[A-Za-z0-9_.-]+$') -or
                $key -notmatch '^[A-Za-z0-9_-]+$') {
                throw "Managed config key has an invalid identity: $id"
            }
            $since = if ($entry.PSObject.Properties.Name -contains 'since') { [string]$entry.since } else { $null }
            $reason = if ($entry.PSObject.Properties.Name -contains 'reason') { [string]$entry.reason } else { $null }
            if ($state -ne 'present' -and ([string]::IsNullOrWhiteSpace($since) -or [string]::IsNullOrWhiteSpace($reason))) {
                throw "Non-present managed config key must declare since and reason: $id"
            }
            $units.Add([pscustomobject][ordered]@{
                id = $id
                kind = 'config_key'
                state = $state
                table = $table
                key = $key
                delivery_modes = @('DirectCompatibility', 'Plugin')
                requires_portable_settings = $true
                since = $since
                reason = $reason
                replaced_by = if ($entry.PSObject.Properties.Name -contains 'replaced_by') { [string]$entry.replaced_by } else { $null }
                legacy_import = $entry.PSObject.Properties.Name -contains 'legacy_import' -and [bool]$entry.legacy_import
            })
        }
    }

    $ids = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $pathLocators = New-Object 'System.Collections.Generic.List[object]'
    $configLocators = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($unit in $units) {
        if (-not $ids.Add([string]$unit.id)) {
            throw "Managed-asset lifecycle contains a duplicate stable id: $($unit.id)"
        }
        if ([string]$unit.kind -eq 'config_key') {
            $locator = "$($unit.table)`0$($unit.key)"
            if (-not $configLocators.Add($locator)) {
                throw "Managed-asset lifecycle contains a duplicate config locator: $($unit.table).$($unit.key)"
            }
            continue
        }
        foreach ($existing in $pathLocators) {
            $path = [string]$unit.relative_path
            $existingPath = [string]$existing.relative_path
            if ([string]::Equals($path, $existingPath, [StringComparison]::OrdinalIgnoreCase) -or
                $path.StartsWith($existingPath + '\', [StringComparison]::OrdinalIgnoreCase) -or
                $existingPath.StartsWith($path + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Managed-asset lifecycle paths overlap: $path <-> $existingPath"
            }
        }
        $pathLocators.Add($unit)
    }

    $currentUnits = @($CurrentPathUnits) + @($CurrentConfigUnits)
    $contractById = @{}
    foreach ($unit in $units) { $contractById[[string]$unit.id] = $unit }
    foreach ($unit in $units) {
        $replacementId = [string]$unit.replaced_by
        if (-not [string]::IsNullOrWhiteSpace($replacementId) -and
            ([string]::Equals([string]$unit.id, $replacementId, [StringComparison]::OrdinalIgnoreCase) -or
            -not $contractById.ContainsKey($replacementId))) {
            throw "Managed asset has an invalid replacement identity: $($unit.id) -> $replacementId"
        }
    }
    $currentById = @{}
    foreach ($unit in $currentUnits) {
        $id = [string]$unit.id
        if ($currentById.ContainsKey($id)) {
            throw "Current managed assets contain a duplicate stable id: $id"
        }
        $currentById[$id] = $unit
        if (-not $contractById.ContainsKey($id)) {
            throw "Current managed asset is missing from the lifecycle contract: $id"
        }
        $contractUnit = $contractById[$id]
        if ([string]$contractUnit.state -ne 'present') {
            throw "Current managed asset is not present in the lifecycle contract: $id ($($contractUnit.state))"
        }
        Assert-AgentBaseLifecyclePresentDefinitionEqual -Expected $contractUnit -Actual $unit -Context 'Current managed asset'
    }
    foreach ($unit in @($units | Where-Object { [string]$_.state -eq 'present' })) {
        $currentUnitRequired = [string]::IsNullOrWhiteSpace($DeliveryMode) -or
            (Test-AgentBaseLifecycleUnitInScope -Unit $unit -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)
        if ($currentUnitRequired -and -not $currentById.ContainsKey([string]$unit.id)) {
            throw "Lifecycle present unit disappeared without an explicit transition: $($unit.id)"
        }
    }

    $previousUnits = if ($null -ne $PreviousManifest -and
        $PreviousManifest.PSObject.Properties.Name -contains 'managed_asset_units' -and
        [int]$PreviousManifest.schema_version -ge 7) {
        @($PreviousManifest.managed_asset_units)
    }
    else {
        @()
    }
    if ($previousUnits.Count -gt 0) {
        $previousById = @{}
        foreach ($previous in $previousUnits) { $previousById[[string]$previous.id] = $previous }
        foreach ($previous in $previousUnits) {
            $id = [string]$previous.id
            if (-not $contractById.ContainsKey($id)) {
                throw "Previously deployed managed asset was deleted from the lifecycle contract: $id"
            }
            $current = $contractById[$id]
            Assert-AgentBaseLifecycleIdentityEqual -Expected $previous -Actual $current -Context 'Managed-asset lifecycle transition'
            $previousState = [string]$previous.state
            $currentState = [string]$current.state
            $allowed = $previousState -eq $currentState -or
                ($previousState -eq 'present' -and $currentState -in @('retired', 'transferred'))
            if (-not $allowed) {
                throw "Managed asset has an unsupported lifecycle transition: $id ($previousState -> $currentState)"
            }
        }
        foreach ($unit in $units) {
            if (-not $previousById.ContainsKey([string]$unit.id) -and [string]$unit.state -ne 'present' -and -not [bool]$unit.legacy_import) {
                throw "New non-present lifecycle unit must be declared as a legacy import: $($unit.id)"
            }
        }
    }

    $unitArray = $units.ToArray()
    $canonicalUnits = @($unitArray | Sort-Object id | ForEach-Object {
        if ([string]$_.kind -eq 'path') {
            [ordered]@{
                id = [string]$_.id
                kind = 'path'
                state = [string]$_.state
                path = [string]$_.relative_path
                path_kind = [string]$_.path_kind
                modes = @($_.delivery_modes)
                settings = [bool]$_.requires_portable_settings
                since = $_.since
                reason = $_.reason
                replaced_by = $_.replaced_by
                legacy_import = [bool]$_.legacy_import
            }
        }
        else {
            [ordered]@{
                id = [string]$_.id
                kind = 'config_key'
                state = [string]$_.state
                table = [string]$_.table
                key = [string]$_.key
                since = $_.since
                reason = $_.reason
                replaced_by = $_.replaced_by
                legacy_import = [bool]$_.legacy_import
            }
        }
    })
    $canonicalText = ConvertTo-Json -InputObject $canonicalUnits -Depth 6 -Compress
    return [pscustomobject]@{
        path = $Path
        schema_version = 1
        sha256 = (Get-AgentBaseLifecycleTextSha256 -Text ([string]$canonicalText))
        units = @($unitArray)
        path_units = @($unitArray | Where-Object { [string]$_.kind -eq 'path' })
        config_units = @($unitArray | Where-Object { [string]$_.kind -eq 'config_key' })
    }
}

function Get-ManagedAssetLifecycleReceiptUnits {
    param(
        [object]$Contract,
        [object[]]$CurrentConfigUnits,
        [object]$PreviousManifest,
        [ValidateSet('DirectCompatibility', 'Plugin')]
        [string]$DeliveryMode,
        [bool]$IncludePortableSettings
    )

    $currentConfigById = @{}
    foreach ($unit in @($CurrentConfigUnits)) { $currentConfigById[[string]$unit.id] = $unit }
    $previousById = @{}
    if ($null -ne $PreviousManifest -and $PreviousManifest.PSObject.Properties.Name -contains 'managed_asset_units') {
        foreach ($unit in @($PreviousManifest.managed_asset_units)) { $previousById[[string]$unit.id] = $unit }
    }

    return @($Contract.units | Sort-Object id | ForEach-Object {
        $unit = $_
        $inScope = Test-AgentBaseLifecycleUnitInScope -Unit $unit -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings
        $receipt = [ordered]@{
            id = [string]$unit.id
            kind = [string]$unit.kind
            state = [string]$unit.state
            delivery_modes = @($unit.delivery_modes)
            requires_portable_settings = [bool]$unit.requires_portable_settings
            deployment_in_scope = $inScope
        }
        if ([string]$unit.kind -eq 'path') {
            $receipt.relative_path = [string]$unit.relative_path
            $receipt.path_kind = [string]$unit.path_kind
        }
        else {
            $receipt.table = [string]$unit.table
            $receipt.key = [string]$unit.key
            if ([string]$unit.state -eq 'present' -and $inScope) {
                $currentConfigUnit = $currentConfigById[[string]$unit.id]
                $receipt.source_fingerprint = [string]$currentConfigUnit.source_fingerprint
            }
            elseif ($previousById.ContainsKey([string]$unit.id)) {
                $previous = $previousById[[string]$unit.id]
                $lastFingerprint = if ($previous.PSObject.Properties.Name -contains 'source_fingerprint') {
                    [string]$previous.source_fingerprint
                }
                elseif ($previous.PSObject.Properties.Name -contains 'last_managed_source_fingerprint') {
                    [string]$previous.last_managed_source_fingerprint
                }
                else {
                    $null
                }
                if (-not [string]::IsNullOrWhiteSpace($lastFingerprint)) {
                    $receipt.last_managed_source_fingerprint = $lastFingerprint
                }
            }
        }
        [pscustomobject]$receipt
    })
}

function Get-SelectedRetiredManagedPathUnits {
    param(
        [object]$Contract,
        [ValidateSet('DirectCompatibility', 'Plugin')]
        [string]$DeliveryMode,
        [bool]$IncludePortableSettings
    )

    return @($Contract.path_units | Where-Object {
        [string]$_.state -eq 'retired' -and
        (Test-AgentBaseLifecycleUnitInScope -Unit $_ -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)
    })
}

function Get-SelectedRetiredManagedConfigUnits {
    param(
        [object]$Contract,
        [ValidateSet('DirectCompatibility', 'Plugin')]
        [string]$DeliveryMode,
        [bool]$IncludePortableSettings
    )

    return @($Contract.config_units | Where-Object {
        [string]$_.state -eq 'retired' -and
        (Test-AgentBaseLifecycleUnitInScope -Unit $_ -DeliveryMode $DeliveryMode -IncludePortableSettings $IncludePortableSettings)
    })
}
