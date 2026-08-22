[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CanaryPath,
    [Parameter(Mandatory = $true)]
    [string]$DeniedAuthPath,
    [Parameter(Mandatory = $true)]
    [string]$InstalledAuthPath,
    [Parameter(Mandatory = $true)]
    [string]$ProjectCanaryPath,
    [Parameter(Mandatory = $true)]
    [string]$SkillRootPath,
    [Parameter(Mandatory = $true)]
    [string]$SkillProbeManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedSkillProbeManifestSha256,
    [Parameter(Mandatory = $true)]
    [string]$ToolProbeManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedToolProbeManifestSha256,
    [Parameter(Mandatory = $true)]
    [string]$WriteProbePath,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeTempPath,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeAppDataPath,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeLocalAppDataPath
)

$ErrorActionPreference = 'Stop'

function Get-AgentBaseBoundedSummary {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [object[]]$Value,
        [ValidateRange(16, 4096)]
        [int]$Maximum = 240
    )

    $summary = ''
    foreach ($item in @($Value)) {
        $candidate = ([string]$item).Trim()
        if ($candidate.Length -gt 0) {
            $summary = [regex]::Replace($candidate, '\s+', ' ')
            break
        }
    }
    if ($summary.Length -gt $Maximum) {
        return $summary.Substring(0, $Maximum - 3) + '...'
    }
    return $summary
}

function Test-AgentBaseExactPropertySet {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,
        [Parameter(Mandatory = $true)]
        [string[]]$Expected
    )

    $actualNames = @($Value.PSObject.Properties.Name | Sort-Object)
    $expectedNames = @($Expected | Sort-Object)
    if ($actualNames.Count -ne $expectedNames.Count) {
        return $false
    }
    for ($index = 0; $index -lt $expectedNames.Count; $index++) {
        if ([string]$actualNames[$index] -cne [string]$expectedNames[$index]) {
            return $false
        }
    }
    return $true
}

function Test-AgentBaseJsonInteger {
    [CmdletBinding()]
    param([object]$Value)

    return (
        $Value -is [sbyte] -or
        $Value -is [byte] -or
        $Value -is [int16] -or
        $Value -is [uint16] -or
        $Value -is [int32] -or
        $Value -is [uint32] -or
        $Value -is [int64] -or
        $Value -is [uint64]
    )
}

$skillProbeManifestReadable = $false
$skillProbeManifestHash = $null
$skillProbeManifestError = $null
$validatedSkillFiles = @()
try {
    $skillProbeManifestHash = (
        Get-FileHash -LiteralPath $SkillProbeManifestPath -Algorithm SHA256 -ErrorAction Stop
    ).Hash.ToLowerInvariant()
    $skillProbeManifestReadable = $true
    if ($skillProbeManifestHash -cne $ExpectedSkillProbeManifestSha256) {
        throw [IO.InvalidDataException]::new('skill probe manifest SHA-256 mismatch')
    }
    $skillManifestText = [IO.File]::ReadAllText(
        [IO.Path]::GetFullPath($SkillProbeManifestPath),
        [Text.Encoding]::UTF8
    )
    $skillManifest = $skillManifestText | ConvertFrom-Json -Depth 20 -DateKind String
    if (
        -not (Test-AgentBaseExactPropertySet `
            -Value $skillManifest `
            -Expected @('schema', 'projection_root', 'projection_identity_sha256', 'files')) -or
        [string]$skillManifest.schema -cne 'agentbase.windows-swe-skill-probes/v1' -or
        [string]$skillManifest.projection_root -cne '.agents/skills' -or
        [string]$skillManifest.projection_identity_sha256 -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw [IO.InvalidDataException]::new('skill probe manifest envelope is invalid')
    }
    $rawSkillFiles = @($skillManifest.files)
    if ($rawSkillFiles.Count -eq 0) {
        throw [IO.InvalidDataException]::new('skill probe manifest is empty')
    }
    $seenSkillPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $normalizedSkillFiles = @()
    foreach ($file in $rawSkillFiles) {
        if (-not (Test-AgentBaseExactPropertySet -Value $file -Expected @('path', 'sha256', 'bytes'))) {
            throw [IO.InvalidDataException]::new('skill probe entry fields are invalid')
        }
        $relativePath = [string]$file.path
        $expectedHash = [string]$file.sha256
        $expectedBytes = $file.bytes
        $segments = @($relativePath -split '/')
        if (
            [string]::IsNullOrWhiteSpace($relativePath) -or
            [IO.Path]::IsPathFullyQualified($relativePath) -or
            $segments -contains '' -or
            $segments -contains '.' -or
            $segments -contains '..' -or
            -not $seenSkillPaths.Add($relativePath)
        ) {
            throw [IO.InvalidDataException]::new('skill probe paths must be safe, nonempty, and unique')
        }
        if ($expectedHash -cnotmatch '^[0-9a-f]{64}$') {
            throw [IO.InvalidDataException]::new("skill probe SHA-256 is invalid: $relativePath")
        }
        if (
            -not (Test-AgentBaseJsonInteger -Value $expectedBytes) -or
            [int64]$expectedBytes -lt 0
        ) {
            throw [IO.InvalidDataException]::new("skill probe byte count is invalid: $relativePath")
        }
        $normalizedSkillFiles += [pscustomobject][ordered]@{
            path = $relativePath
            sha256 = $expectedHash
            bytes = [int64]$expectedBytes
        }
    }
    $validatedSkillFiles = @($normalizedSkillFiles | Sort-Object -Property path)
}
catch {
    $skillProbeManifestError = $_.Exception.GetType().FullName
    $validatedSkillFiles = @()
}

$skillManifestReady = (
    $skillProbeManifestReadable -and
    $skillProbeManifestHash -ceq $ExpectedSkillProbeManifestSha256 -and
    $null -eq $skillProbeManifestError
)
$skillFilesExpected = $validatedSkillFiles.Count
$skillFilesVerified = 0
$skillProjectionReadable = $false
$skillProjectionError = $null
try {
    if (-not $skillManifestReady) {
        throw [IO.InvalidDataException]::new('skill probe manifest is not ready')
    }
    $resolvedSkillRoot = [IO.Path]::GetFullPath($SkillRootPath)
    if (-not [IO.Directory]::Exists($resolvedSkillRoot)) {
        throw [IO.DirectoryNotFoundException]::new('skill projection root is missing')
    }
    $actualItems = @(Get-ChildItem -LiteralPath $resolvedSkillRoot -Force -Recurse -ErrorAction Stop)
    if (@($actualItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -ne 0) {
        throw [IO.InvalidDataException]::new('skill projection contains a reparse point')
    }
    $actualFiles = @(
        $actualItems |
            Where-Object { -not $_.PSIsContainer } |
            ForEach-Object {
                ([IO.Path]::GetRelativePath($resolvedSkillRoot, $_.FullName)).Replace('\', '/')
            } |
            Sort-Object
    )
    $expectedFiles = @($validatedSkillFiles | ForEach-Object { $_.path } | Sort-Object)
    if ($actualFiles.Count -ne $expectedFiles.Count) {
        throw [IO.InvalidDataException]::new('skill projection file count mismatch')
    }
    for ($index = 0; $index -lt $expectedFiles.Count; $index++) {
        if ([string]$actualFiles[$index] -cne [string]$expectedFiles[$index]) {
            throw [IO.InvalidDataException]::new('skill projection file set mismatch')
        }
    }
    foreach ($file in $validatedSkillFiles) {
        $nativeRelative = ([string]$file.path).Replace('/', [IO.Path]::DirectorySeparatorChar)
        $fullPath = [IO.Path]::GetFullPath((Join-Path $resolvedSkillRoot $nativeRelative))
        $relativeCheck = [IO.Path]::GetRelativePath($resolvedSkillRoot, $fullPath)
        if (
            [IO.Path]::IsPathRooted($relativeCheck) -or
            $relativeCheck -eq '..' -or
            $relativeCheck.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
        ) {
            throw [IO.InvalidDataException]::new("skill probe path escapes its root: $($file.path)")
        }
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        $actualHash = (
            Get-FileHash -LiteralPath $fullPath -Algorithm SHA256 -ErrorAction Stop
        ).Hash.ToLowerInvariant()
        if ($actualHash -cne [string]$file.sha256 -or [int64]$item.Length -ne [int64]$file.bytes) {
            throw [IO.InvalidDataException]::new("skill projection content mismatch: $($file.path)")
        }
        $skillFilesVerified++
    }
    $skillProjectionReadable = $skillFilesVerified -eq $skillFilesExpected
}
catch {
    $skillProjectionError = $_.Exception.GetType().FullName
}

$skillProjectionWriteDenied = $false
$skillProjectionWriteError = $null
$skillWriteProbe = [IO.Path]::GetFullPath((Join-Path $SkillRootPath '.agentbase-write-probe'))
try {
    [IO.File]::WriteAllText(
        $skillWriteProbe,
        'agentbase-skill-write-probe',
        [Text.UTF8Encoding]::new($false)
    )
}
catch {
    $skillProjectionWriteDenied = $true
    $skillProjectionWriteError = $_.Exception.GetType().FullName
}
finally {
    if ([IO.File]::Exists($skillWriteProbe)) {
        [IO.File]::Delete($skillWriteProbe)
    }
}

$toolProbeManifestReadable = $false
$toolProbeManifestHash = $null
$toolProbeManifestError = $null
$validatedProbes = @()
try {
    $toolProbeManifestHash = (
        Get-FileHash -LiteralPath $ToolProbeManifestPath -Algorithm SHA256 -ErrorAction Stop
    ).Hash.ToLowerInvariant()
    $toolProbeManifestReadable = $true
    if ($toolProbeManifestHash -cne $ExpectedToolProbeManifestSha256) {
        throw [IO.InvalidDataException]::new('tool probe manifest SHA-256 mismatch')
    }
    $manifestText = [IO.File]::ReadAllText(
        [IO.Path]::GetFullPath($ToolProbeManifestPath),
        [Text.Encoding]::UTF8
    )
    $manifest = $manifestText | ConvertFrom-Json -Depth 20 -DateKind String
    if (
        -not (Test-AgentBaseExactPropertySet -Value $manifest -Expected @('schema', 'probes')) -or
        [string]$manifest.schema -cne 'agentbase.windows-swe-tool-probes/v1'
    ) {
        throw [IO.InvalidDataException]::new('tool probe manifest envelope is invalid')
    }
    $rawProbes = @($manifest.probes)
    if ($rawProbes.Count -eq 0) {
        throw [IO.InvalidDataException]::new('tool probe manifest is empty')
    }
    $seenIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $normalizedProbes = @()
    foreach ($probe in $rawProbes) {
        if (-not (Test-AgentBaseExactPropertySet -Value $probe -Expected @('id', 'path', 'sha256', 'argv'))) {
            throw [IO.InvalidDataException]::new('tool probe entry fields are invalid')
        }
        $probeId = [string]$probe.id
        $probePath = [string]$probe.path
        $expectedProbeHash = [string]$probe.sha256
        $probeArguments = @($probe.argv)
        if ([string]::IsNullOrWhiteSpace($probeId) -or -not $seenIds.Add($probeId)) {
            throw [IO.InvalidDataException]::new('tool probe ids must be nonempty and unique')
        }
        if (-not [IO.Path]::IsPathFullyQualified($probePath)) {
            throw [IO.InvalidDataException]::new("tool probe path is not absolute: $probeId")
        }
        if ($expectedProbeHash -cnotmatch '^[0-9a-f]{64}$') {
            throw [IO.InvalidDataException]::new("tool probe SHA-256 is invalid: $probeId")
        }
        if ($probeArguments.Count -eq 0) {
            throw [IO.InvalidDataException]::new("tool probe arguments are empty: $probeId")
        }
        foreach ($argument in $probeArguments) {
            if ($argument -isnot [string]) {
                throw [IO.InvalidDataException]::new("tool probe argument is not a string: $probeId")
            }
        }
        $normalizedProbes += [pscustomobject][ordered]@{
            id = $probeId
            path = [IO.Path]::GetFullPath($probePath)
            sha256 = $expectedProbeHash
            argv = [string[]]$probeArguments
        }
    }
    $validatedProbes = @($normalizedProbes | Sort-Object -Property id)
}
catch {
    $toolProbeManifestError = $_.Exception.GetType().FullName
    $validatedProbes = @()
}

$manifestReady = (
    $toolProbeManifestReadable -and
    $toolProbeManifestHash -ceq $ExpectedToolProbeManifestSha256 -and
    $null -eq $toolProbeManifestError
)
$toolProbes = [ordered]@{}
$allToolProbesPassed = $manifestReady
foreach ($probe in $validatedProbes) {
    $probeOutput = @()
    $probeExit = -1
    $observedProbeHash = $null
    try {
        $observedProbeHash = (
            Get-FileHash -LiteralPath $probe.path -Algorithm SHA256 -ErrorAction Stop
        ).Hash.ToLowerInvariant()
        if ($observedProbeHash -cne $probe.sha256) {
            $probeOutput = @('executable SHA-256 mismatch')
        }
        else {
            $probeOutput = @(& $probe.path @($probe.argv) 2>&1)
            $probeExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        }
    }
    catch {
        $probeOutput = @($_.Exception.Message)
    }
    if ($observedProbeHash -cne $probe.sha256 -or $probeExit -ne 0) {
        $allToolProbesPassed = $false
    }
    $toolProbes[[string]$probe.id] = [ordered]@{
        expected_sha256 = [string]$probe.sha256
        observed_sha256 = $observedProbeHash
        exit_code = $probeExit
        summary = Get-AgentBaseBoundedSummary -Value $probeOutput -Maximum 160
    }
}

$canaryReadable = $false
$canaryError = $null
try {
    Get-Content -LiteralPath $CanaryPath -Raw -ErrorAction Stop | Out-Null
    $canaryReadable = $true
}
catch {
    $canaryError = $_.Exception.GetType().FullName
}

$authReadable = $false
$authError = $null
try {
    Get-Content -LiteralPath $DeniedAuthPath -Raw -ErrorAction Stop | Out-Null
    $authReadable = $true
}
catch {
    $authError = $_.Exception.GetType().FullName
}

$installedAuthReadable = $false
$installedAuthError = $null
try {
    Get-Content -LiteralPath $InstalledAuthPath -Raw -ErrorAction Stop | Out-Null
    $installedAuthReadable = $true
}
catch {
    $installedAuthError = $_.Exception.GetType().FullName
}

$projectCanaryReadable = $false
$projectCanaryError = $null
try {
    Get-Content -LiteralPath $ProjectCanaryPath -Raw -ErrorAction Stop | Out-Null
    $projectCanaryReadable = $true
}
catch {
    $projectCanaryError = $_.Exception.GetType().FullName
}

$workspaceWriteProbePassed = $false
$workspaceWriteProbeError = $null
$writeProbeFullPath = $null
try {
    $writeProbeFullPath = [IO.Path]::GetFullPath($WriteProbePath)
    [IO.Directory]::CreateDirectory((Split-Path -Parent $writeProbeFullPath)) | Out-Null
    $writeProbeValue = 'agentbase-workspace-write-probe'
    [IO.File]::WriteAllText($writeProbeFullPath, $writeProbeValue, [Text.UTF8Encoding]::new($false))
    $workspaceWriteProbePassed = (
        [IO.File]::ReadAllText($writeProbeFullPath, [Text.Encoding]::UTF8) -ceq $writeProbeValue
    )
}
catch {
    $workspaceWriteProbeError = $_.Exception.GetType().FullName
}
finally {
    if ($null -ne $writeProbeFullPath -and [IO.File]::Exists($writeProbeFullPath)) {
        [IO.File]::Delete($writeProbeFullPath)
    }
}

$runtimeTempAttemptScoped = $false
$runtimeAppDataAttemptScoped = $false
$runtimeLocalAppDataAttemptScoped = $false
$runtimeStateError = $null
try {
    $expectedRuntimeTemp = [IO.Path]::GetFullPath($RuntimeTempPath)
    $expectedRuntimeAppData = [IO.Path]::GetFullPath($RuntimeAppDataPath)
    $expectedRuntimeLocalAppData = [IO.Path]::GetFullPath($RuntimeLocalAppDataPath)
    $workspaceRoot = [IO.Path]::GetFullPath((Get-Location).Path)
    $tempRelativeToWorkspace = [IO.Path]::GetRelativePath($workspaceRoot, $expectedRuntimeTemp)
    $runtimeTempAttemptScoped = (
        [IO.Path]::IsPathRooted($tempRelativeToWorkspace) -or
        $tempRelativeToWorkspace -eq '..' -or
        $tempRelativeToWorkspace.StartsWith(
            '..' + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::Ordinal
        )
    )
    foreach ($name in @('TEMP', 'TMP', 'TMPDIR')) {
        $actualRuntimeTemp = [Environment]::GetEnvironmentVariable($name)
        if (
            [string]::IsNullOrWhiteSpace($actualRuntimeTemp) -or
            -not ([IO.Path]::GetFullPath($actualRuntimeTemp)).Equals(
                $expectedRuntimeTemp,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            $runtimeTempAttemptScoped = $false
            $runtimeStateError = 'AgentBase.RuntimeTempPathMismatch'
            break
        }
    }
    $runtimeAppDataAttemptScoped = (
        ([IO.Path]::GetFullPath([Environment]::GetEnvironmentVariable('APPDATA'))).Equals(
            $expectedRuntimeAppData,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        ([IO.Path]::GetRelativePath($expectedRuntimeTemp, $expectedRuntimeAppData)) -notmatch '^\.\.'
    )
    $runtimeLocalAppDataAttemptScoped = (
        ([IO.Path]::GetFullPath([Environment]::GetEnvironmentVariable('LOCALAPPDATA'))).Equals(
            $expectedRuntimeLocalAppData,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        ([IO.Path]::GetRelativePath($expectedRuntimeTemp, $expectedRuntimeLocalAppData)) -notmatch '^\.\.'
    )
    if (-not $runtimeAppDataAttemptScoped -or -not $runtimeLocalAppDataAttemptScoped) {
        $runtimeStateError = 'AgentBase.RuntimeAppDataPathMismatch'
    }
}
catch {
    $runtimeTempAttemptScoped = $false
    $runtimeAppDataAttemptScoped = $false
    $runtimeLocalAppDataAttemptScoped = $false
    $runtimeStateError = $_.Exception.GetType().FullName
}

$probeById = @{}
foreach ($probe in $validatedProbes) {
    $probeById[[string]$probe.id] = $probe
}
$srcqProbe = $probeById['srcq']
$srcqDoctor = @()
$srcqDoctorExit = -1
$sccDoctor = @()
$sccDoctorExit = -1
$srcqSmoke = [ordered]@{
    'ast-cache' = [ordered]@{ passed = $false; summary = 'not run' }
    'rg-pagination' = [ordered]@{ passed = $false; summary = 'not run' }
    'fd-tree' = [ordered]@{ passed = $false; summary = 'not run' }
    'scc-machine' = [ordered]@{ passed = $false; summary = 'not run' }
    artifact = [ordered]@{ passed = $false; summary = 'not run' }
}
if (
    $null -ne $srcqProbe -and
    $toolProbes.Contains('srcq') -and
    [string]$toolProbes['srcq'].observed_sha256 -ceq [string]$srcqProbe.sha256
) {
    try {
        $srcqDoctor = @(& $srcqProbe.path doctor --engine $probeById['ast-grep'].path 2>&1)
        $srcqDoctorExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    catch {
        $srcqDoctor = @($_.Exception.Message)
    }
    try {
        $sccDoctor = @(& $srcqProbe.path query scc doctor --engine $probeById['scc'].path 2>&1)
        $sccDoctorExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    catch {
        $sccDoctor = @($_.Exception.Message)
    }

    $smokeRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $WriteProbePath) 'runtime-probe\srcq-smoke'))
    try {
        [IO.Directory]::CreateDirectory($smokeRoot) | Out-Null
        $typescriptPath = Join-Path $smokeRoot 'probe.ts'
        $paginationPath = Join-Path $smokeRoot 'pagination.txt'
        $treeRoot = Join-Path $smokeRoot 'tree'
        $treeNested = Join-Path $treeRoot 'nested'
        [IO.Directory]::CreateDirectory($treeNested) | Out-Null
        [IO.File]::WriteAllText(
            $typescriptPath,
            "export function probe(value: string): string {`n  console.log(value);`n  return 'agentbase-artifact';`n}`n",
            [Text.UTF8Encoding]::new($false)
        )
        [IO.File]::WriteAllText(
            $paginationPath,
            "agentbase-pagination one`nagentbase-pagination two`nagentbase-pagination three`n",
            [Text.UTF8Encoding]::new($false)
        )
        [IO.File]::WriteAllText(
            (Join-Path $treeRoot 'a.ts'),
            "export const alpha = 1;`n",
            [Text.UTF8Encoding]::new($false)
        )
        [IO.File]::WriteAllText(
            (Join-Path $treeNested 'b.ts'),
            "export const beta = 2;`n",
            [Text.UTF8Encoding]::new($false)
        )

        try {
            $astOutput = @(
                & $srcqProbe.path exec `
                    --engine $probeById['ast-grep'].path `
                    --cwd $workspaceRoot `
                    --output machine `
                    --profile locations `
                    --cache on `
                    -- run -p 'console.log($A)' -l ts $typescriptPath 2>&1
            )
            $astExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $astDocument = ($astOutput -join [Environment]::NewLine) |
                ConvertFrom-Json -Depth 20 -DateKind String
            $cacheId = [string]$astDocument._sgy.cache
            $cacheInfo = @(& $srcqProbe.path cache info $cacheId 2>&1)
            $cacheInfoExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $cacheRemove = @(& $srcqProbe.path cache remove $cacheId 2>&1)
            $cacheRemoveExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $astPassed = (
                $astExit -eq 0 -and
                [int64]$astDocument._sgy.total -eq 1 -and
                [bool]$astDocument._sgy.complete -and
                @($astDocument.results).Count -eq 1 -and
                $cacheId -cmatch '^[0-9A-HJKMNP-TV-Z]{26}$' -and
                $cacheInfoExit -eq 0 -and
                $cacheRemoveExit -eq 0
            )
            $srcqSmoke['ast-cache'] = [ordered]@{
                passed = $astPassed
                summary = if ($astPassed) { 'one AST match; cache info/remove round trip passed' } else {
                    Get-AgentBaseBoundedSummary -Value @($astOutput + $cacheInfo + $cacheRemove)
                }
            }
        }
        catch {
            $srcqSmoke['ast-cache'] = [ordered]@{
                passed = $false
                summary = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
            }
        }

        try {
            $paginationResults = @()
            $paginationPageCount = 0
            $continuationHandle = $null
            $paginationComplete = $false
            while ($paginationPageCount -lt 8 -and -not $paginationComplete) {
                $pageOutput = if ($null -eq $continuationHandle) {
                    @(
                        & $srcqProbe.path query rg exec `
                            --engine $probeById['rg'].path `
                            --cwd $workspaceRoot `
                            --limit 1 `
                            -- -n -F 'agentbase-pagination' $paginationPath 2>&1
                    )
                }
                else {
                    @(
                        & $srcqProbe.path more $continuationHandle 2>&1
                    )
                }
                $pageExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
                if ($pageExit -ne 0) {
                    throw [InvalidOperationException]::new(
                        "srcq pagination page failed: $(Get-AgentBaseBoundedSummary -Value $pageOutput)"
                    )
                }
                $paginationPageCount++
                $pageLines = @($pageOutput | ForEach-Object { [string]$_ })
                $paginationResults += @(
                    $pageLines | Where-Object {
                        -not [string]::IsNullOrWhiteSpace($_) -and -not $_.StartsWith('@')
                    }
                )
                $moreLines = @($pageLines | Where-Object { $_.StartsWith('@more ') })
                $nextLines = @($pageLines | Where-Object { $_.StartsWith('@next ') })
                if ($moreLines.Count -eq 0) {
                    if ($nextLines.Count -ne 0) {
                        throw [IO.InvalidDataException]::new('final srcq page returned @next without @more')
                    }
                    $paginationComplete = $true
                    continue
                }
                if ($moreLines.Count -ne 1 -or $nextLines.Count -ne 1) {
                    throw [IO.InvalidDataException]::new('srcq pagination controls are ambiguous')
                }
                $nextCommand = $nextLines[0].Substring(6)
                $parseTokens = $null
                $parseErrors = $null
                [void][Management.Automation.Language.Parser]::ParseInput(
                    $nextCommand,
                    [ref]$parseTokens,
                    [ref]$parseErrors
                )
                if (@($parseErrors).Count -ne 0 -or $nextCommand -cnotmatch '^srcq more (q[1-9][0-9]*)$') {
                    throw [IO.InvalidDataException]::new('srcq @next is not a valid bounded PowerShell command')
                }
                $continuationHandle = $Matches[1]
            }
            $paginationPassed = (
                $paginationComplete -and
                $paginationPageCount -eq 3 -and
                $paginationResults.Count -eq 3 -and
                @($paginationResults | Sort-Object -Unique).Count -eq 3
            )
            $srcqSmoke['rg-pagination'] = [ordered]@{
                passed = $paginationPassed
                summary = if ($paginationPassed) { 'three one-result model pages resumed through validated short @next handles' } else {
                    "pages=$paginationPageCount results=$($paginationResults.Count) complete=$paginationComplete"
                }
            }
        }
        catch {
            $srcqSmoke['rg-pagination'] = [ordered]@{
                passed = $false
                summary = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
            }
        }

        try {
            $fdOutput = @(
                & $srcqProbe.path query fd exec `
                    --engine $probeById['fd'].path `
                    --cwd $workspaceRoot `
                    --output machine `
                    --view tree `
                    -- --type f . $treeRoot 2>&1
            )
            $fdExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $fdDocument = ($fdOutput -join [Environment]::NewLine) |
                ConvertFrom-Json -Depth 20 -DateKind String
            $fdTreePassed = (
                $fdExit -eq 0 -and
                [int64]$fdDocument._sgy.result_total -eq 2 -and
                [bool]$fdDocument._sgy.complete.result -and
                $fdDocument.trees.PSObject.Properties.Count -eq 1
            )
            $srcqSmoke['fd-tree'] = [ordered]@{
                passed = $fdTreePassed
                summary = if ($fdTreePassed) { 'two files preserved in one machine tree' } else {
                    Get-AgentBaseBoundedSummary -Value $fdOutput
                }
            }
        }
        catch {
            $srcqSmoke['fd-tree'] = [ordered]@{
                passed = $false
                summary = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
            }
        }

        try {
            $sccOutput = @(
                & $srcqProbe.path query scc exec `
                    --engine $probeById['scc'].path `
                    --cwd $workspaceRoot `
                    --output machine `
                    --view languages `
                    -- $treeRoot 2>&1
            )
            $sccExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $sccDocument = ($sccOutput -join [Environment]::NewLine) |
                ConvertFrom-Json -Depth 20 -DateKind String
            $sccMachinePassed = (
                $sccExit -eq 0 -and
                [int64]$sccDocument.summary.files -eq 2 -and
                [int64]$sccDocument.summary.languages -eq 1 -and
                [string]$sccDocument.languages[0].name -ceq 'TypeScript' -and
                [bool]$sccDocument._sgy.complete.result
            )
            $srcqSmoke['scc-machine'] = [ordered]@{
                passed = $sccMachinePassed
                summary = if ($sccMachinePassed) { 'two TypeScript files projected through machine view' } else {
                    Get-AgentBaseBoundedSummary -Value $sccOutput
                }
            }
        }
        catch {
            $srcqSmoke['scc-machine'] = [ordered]@{
                passed = $false
                summary = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
            }
        }

        try {
            $artifactPath = Join-Path $smokeRoot 'rg-artifact.bin'
            $artifactOutput = @(
                & $srcqProbe.path query rg exec `
                    --engine $probeById['rg'].path `
                    --cwd $workspaceRoot `
                    --output machine `
                    --artifact-out $artifactPath `
                    -- -n -F 'agentbase-artifact' $typescriptPath 2>&1
            )
            $artifactExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
            $artifactText = if ([IO.File]::Exists($artifactPath)) {
                [IO.File]::ReadAllText($artifactPath, [Text.Encoding]::UTF8)
            }
            else {
                ''
            }
            $artifactEnvelope = $artifactOutput -join [Environment]::NewLine
            $artifactPassed = (
                $artifactExit -eq 0 -and
                $artifactText -match 'agentbase-artifact' -and
                $artifactEnvelope -match 'sgy\.query\.artifact/v1'
            )
            $srcqSmoke.artifact = [ordered]@{
                passed = $artifactPassed
                summary = if ($artifactPassed) { 'native rg bytes and machine artifact envelope agree' } else {
                    Get-AgentBaseBoundedSummary -Value $artifactOutput
                }
            }
        }
        catch {
            $srcqSmoke.artifact = [ordered]@{
                passed = $false
                summary = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
            }
        }
    }
    catch {
        $setupFailure = Get-AgentBaseBoundedSummary -Value @($_.Exception.Message)
        foreach ($name in @($srcqSmoke.Keys)) {
            if ([string]$srcqSmoke[$name].summary -ceq 'not run') {
                $srcqSmoke[$name] = [ordered]@{ passed = $false; summary = $setupFailure }
            }
        }
    }
    finally {
        if ($null -ne $smokeRoot -and [IO.Directory]::Exists($smokeRoot)) {
            [IO.Directory]::Delete($smokeRoot, $true)
        }
    }
}
else {
    $srcqDoctor = @('hash-verified srcq executable is unavailable')
    $sccDoctor = @('hash-verified srcq executable is unavailable')
    foreach ($name in @($srcqSmoke.Keys)) {
        $srcqSmoke[$name] = [ordered]@{
            passed = $false
            summary = 'hash-verified srcq toolchain is unavailable'
        }
    }
}

$passed = (
    -not $canaryReadable -and
    -not $authReadable -and
    -not $installedAuthReadable -and
    -not $projectCanaryReadable -and
    $skillManifestReady -and
    $skillProjectionReadable -and
    $skillFilesVerified -eq $skillFilesExpected -and
    $skillProjectionWriteDenied -and
    $workspaceWriteProbePassed -and
    $runtimeTempAttemptScoped -and
    $runtimeAppDataAttemptScoped -and
    $runtimeLocalAppDataAttemptScoped -and
    $manifestReady -and
    $allToolProbesPassed -and
    $srcqDoctorExit -eq 0 -and
    $sccDoctorExit -eq 0 -and
    @($srcqSmoke.Values | Where-Object { -not [bool]$_.passed }).Count -eq 0
)
$value = [ordered]@{
    schema = 'agentbase.windows-swe-preflight/v9'
    passed = $passed
    canary_readable = $canaryReadable
    canary_error_type = $canaryError
    auth_readable = $authReadable
    auth_error_type = $authError
    installed_auth_readable = $installedAuthReadable
    installed_auth_error_type = $installedAuthError
    project_canary_readable = $projectCanaryReadable
    project_canary_error_type = $projectCanaryError
    skill_probe_manifest_readable = $skillProbeManifestReadable
    skill_probe_manifest_sha256 = $skillProbeManifestHash
    skill_probe_manifest_error_type = $skillProbeManifestError
    skill_projection_readable = $skillProjectionReadable
    skill_projection_error_type = $skillProjectionError
    skill_projection_write_denied = $skillProjectionWriteDenied
    skill_projection_write_error_type = $skillProjectionWriteError
    skill_files_expected = $skillFilesExpected
    skill_files_verified = $skillFilesVerified
    workspace_write_probe_passed = $workspaceWriteProbePassed
    workspace_write_probe_error_type = $workspaceWriteProbeError
    runtime_temp_attempt_scoped = $runtimeTempAttemptScoped
    runtime_appdata_attempt_scoped = $runtimeAppDataAttemptScoped
    runtime_localappdata_attempt_scoped = $runtimeLocalAppDataAttemptScoped
    runtime_state_error_type = $runtimeStateError
    tool_probe_manifest_readable = $toolProbeManifestReadable
    tool_probe_manifest_sha256 = $toolProbeManifestHash
    tool_probe_manifest_error_type = $toolProbeManifestError
    tool_probes = $toolProbes
    srcq_doctor_exit_code = $srcqDoctorExit
    srcq_scc_doctor_exit_code = $sccDoctorExit
    srcq_smoke = $srcqSmoke
    srcq_doctor_summary = Get-AgentBaseBoundedSummary -Value $srcqDoctor
    srcq_scc_doctor_summary = Get-AgentBaseBoundedSummary -Value $sccDoctor
}

$value | ConvertTo-Json -Depth 10
if (-not $passed) {
    exit 1
}
