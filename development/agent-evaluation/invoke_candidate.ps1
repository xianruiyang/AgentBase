[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Resolve', 'Preflight', 'Run')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [string]$ResultPath,
    [string]$Workspace,
    [string]$StateRoot,
    [string]$CodexHome,
    [string]$InstalledCodexRoot,
    [string]$PromptPath,
    [string]$CanaryPath,
    [string]$DeniedAuthPath,
    [string]$SkillRootPath,
    [string]$SkillProbeManifestPath,
    [string]$ExpectedSkillProbeManifestSha256,
    [string]$ToolProbeManifestPath,
    [string]$ExpectedToolProbeManifestSha256,
    [string]$PreflightOutputPath,
    [string]$Model,
    [string]$ReasoningEffort,
    [string]$PermissionProfile,
    [string]$CodexExecutablePath,
    [ValidateRange(60, 14400)]
    [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedResult = [IO.Path]::GetFullPath($ResultPath)
$commonRuntime = Join-Path $resolvedProject 'development\common\codex_cli_runtime.ps1'
. $commonRuntime
$utf8NoBom = [Text.UTF8Encoding]::new($false)

function Write-AgentBaseJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    [IO.Directory]::CreateDirectory((Split-Path -Parent $resolved)) | Out-Null
    [IO.File]::WriteAllText(
        $resolved,
        ($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
        $utf8NoBom
    )
}

function Test-AgentBaseExactPropertySet {
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

function Test-AgentBasePathWithinOrEqual {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $relative = [IO.Path]::GetRelativePath($Root, $Candidate)
    return (
        -not [IO.Path]::IsPathRooted($relative) -and
        $relative -ne '..' -and
        -not $relative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
    )
}

function Assert-AgentBaseDisjointPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LeftName,
        [Parameter(Mandatory = $true)]
        [string]$LeftPath,
        [Parameter(Mandatory = $true)]
        [string]$RightName,
        [Parameter(Mandatory = $true)]
        [string]$RightPath
    )

    if (
        (Test-AgentBasePathWithinOrEqual -Candidate $LeftPath -Root $RightPath) -or
        (Test-AgentBasePathWithinOrEqual -Candidate $RightPath -Root $LeftPath)
    ) {
        throw "$LeftName must be disjoint from $RightName"
    }
}

function Read-AgentBaseSkillProbeManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedWorkspace,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedSkillRoot
    )

    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Expected skill probe manifest SHA-256 must be lowercase hexadecimal'
    }
    $expectedSkillRoot = [IO.Path]::GetFullPath(
        (Join-Path $ResolvedWorkspace '.agents\skills')
    )
    if (-not $ResolvedSkillRoot.Equals($expectedSkillRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Skill projection root must be the candidate workspace .agents/skills directory'
    }
    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $manifestRelative = [IO.Path]::GetRelativePath($ResolvedWorkspace, $resolvedPath)
    if (
        [IO.Path]::IsPathRooted($manifestRelative) -or
        $manifestRelative -eq '..' -or
        $manifestRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal) -or
        -not $manifestRelative.StartsWith('.agentbase' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw 'Skill probe manifest must be inside the candidate workspace .agentbase subtree'
    }
    $actualSha256 = (
        Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256 -ErrorAction Stop
    ).Hash.ToLowerInvariant()
    if ($actualSha256 -cne $ExpectedSha256) {
        throw 'Skill probe manifest changed before sandbox launch'
    }
    $manifest = [IO.File]::ReadAllText($resolvedPath, [Text.Encoding]::UTF8) |
        ConvertFrom-Json -Depth 20 -DateKind String
    if (
        -not (Test-AgentBaseExactPropertySet `
            -Value $manifest `
            -Expected @('schema', 'projection_root', 'projection_identity_sha256', 'files')) -or
        [string]$manifest.schema -cne 'agentbase.windows-swe-skill-probes/v1' -or
        [string]$manifest.projection_root -cne '.agents/skills' -or
        [string]$manifest.projection_identity_sha256 -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw 'Skill probe manifest envelope is invalid'
    }
    $files = @($manifest.files)
    if ($files.Count -eq 0) {
        throw 'Skill probe manifest is empty'
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($file in $files) {
        if (-not (Test-AgentBaseExactPropertySet -Value $file -Expected @('path', 'sha256', 'bytes'))) {
            throw 'Skill probe manifest entry fields are invalid'
        }
        $relativePath = [string]$file.path
        $segments = @($relativePath -split '/')
        if (
            [string]::IsNullOrWhiteSpace($relativePath) -or
            [IO.Path]::IsPathFullyQualified($relativePath) -or
            $segments -contains '' -or
            $segments -contains '.' -or
            $segments -contains '..' -or
            -not $seen.Add($relativePath)
        ) {
            throw 'Skill probe paths must be safe, nonempty, and unique'
        }
        if ([string]$file.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Skill probe SHA-256 is invalid: $relativePath"
        }
        if (-not (Test-AgentBaseJsonInteger -Value $file.bytes) -or [int64]$file.bytes -lt 0) {
            throw "Skill probe byte count is invalid: $relativePath"
        }
        $nativeRelative = $relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $fullPath = [IO.Path]::GetFullPath((Join-Path $ResolvedSkillRoot $nativeRelative))
        $relativeCheck = [IO.Path]::GetRelativePath($ResolvedSkillRoot, $fullPath)
        if (
            [IO.Path]::IsPathRooted($relativeCheck) -or
            $relativeCheck -eq '..' -or
            $relativeCheck.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
        ) {
            throw "Skill probe path escapes its root: $relativePath"
        }
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        $observedHash = (
            Get-FileHash -LiteralPath $fullPath -Algorithm SHA256 -ErrorAction Stop
        ).Hash.ToLowerInvariant()
        if ($observedHash -cne [string]$file.sha256 -or [int64]$item.Length -ne [int64]$file.bytes) {
            throw "Skill projection changed before sandbox launch: $relativePath"
        }
    }
    return [pscustomobject][ordered]@{
        path = $resolvedPath
        sha256 = $actualSha256
        file_count = $files.Count
    }
}

function Read-AgentBaseToolProbeManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedWorkspace
    )

    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Expected tool probe manifest SHA-256 must be lowercase hexadecimal'
    }
    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $manifestRelative = [IO.Path]::GetRelativePath($ResolvedWorkspace, $resolvedPath)
    if (
        [IO.Path]::IsPathRooted($manifestRelative) -or
        $manifestRelative -eq '..' -or
        $manifestRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal) -or
        -not $manifestRelative.StartsWith('.agentbase' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw 'Tool probe manifest must be inside the candidate workspace .agentbase subtree'
    }
    $actualSha256 = (
        Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256 -ErrorAction Stop
    ).Hash.ToLowerInvariant()
    if ($actualSha256 -cne $ExpectedSha256) {
        throw 'Tool probe manifest changed before sandbox launch'
    }
    $manifest = [IO.File]::ReadAllText($resolvedPath, [Text.Encoding]::UTF8) |
        ConvertFrom-Json -Depth 20 -DateKind String
    if (
        -not (Test-AgentBaseExactPropertySet -Value $manifest -Expected @('schema', 'probes')) -or
        [string]$manifest.schema -cne 'agentbase.windows-swe-tool-probes/v1'
    ) {
        throw 'Tool probe manifest envelope is invalid'
    }
    $rawProbes = @($manifest.probes)
    if ($rawProbes.Count -eq 0) {
        throw 'Tool probe manifest is empty'
    }
    $expectedTools = [ordered]@{}
    foreach ($probe in $rawProbes) {
        if (-not (Test-AgentBaseExactPropertySet -Value $probe -Expected @('id', 'path', 'sha256', 'argv'))) {
            throw 'Tool probe manifest entry fields are invalid'
        }
        $probeId = [string]$probe.id
        $probePath = [string]$probe.path
        $probeSha256 = [string]$probe.sha256
        $probeArguments = @($probe.argv)
        if ([string]::IsNullOrWhiteSpace($probeId) -or $expectedTools.Contains($probeId)) {
            throw 'Tool probe manifest ids must be nonempty and unique'
        }
        if (-not [IO.Path]::IsPathFullyQualified($probePath)) {
            throw "Tool probe path is not absolute: $probeId"
        }
        $resolvedProbePath = (Resolve-Path -LiteralPath $probePath).Path
        if (-not (Test-Path -LiteralPath $resolvedProbePath -PathType Leaf)) {
            throw "Tool probe path is not a file: $probeId"
        }
        if ($probeSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Tool probe SHA-256 is invalid: $probeId"
        }
        $observedProbeSha256 = (
            Get-FileHash -LiteralPath $resolvedProbePath -Algorithm SHA256 -ErrorAction Stop
        ).Hash.ToLowerInvariant()
        if ($observedProbeSha256 -cne $probeSha256) {
            throw "Tool probe executable changed before sandbox launch: $probeId"
        }
        if ($probeArguments.Count -eq 0) {
            throw "Tool probe arguments are empty: $probeId"
        }
        foreach ($argument in $probeArguments) {
            if ($argument -isnot [string]) {
                throw "Tool probe argument is not a string: $probeId"
            }
        }
        $expectedTools[$probeId] = $probeSha256
    }
    return [pscustomobject][ordered]@{
        path = $resolvedPath
        sha256 = $actualSha256
        expected_tools = $expectedTools
    }
}

function Resolve-AgentBaseEvaluationCodex {
    $npmPrefix = Get-AgentBaseUserNpmPrefix
    $sandboxFallback = if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $null
    }
    else {
        Join-Path $env:USERPROFILE '.codex\.sandbox-bin\codex.exe'
    }
    $executable = Resolve-AgentBaseCodexNativeExecutable `
        -ExplicitPath $CodexExecutablePath `
        -NpmPrefix $npmPrefix `
        -SandboxFallbackPath $sandboxFallback
    return [pscustomobject][ordered]@{
        schema = 'agentbase.codex-cli-identity/v1'
        path = $executable
        sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        version = Get-AgentBaseCodexVersion -ExecutablePath $executable
    }
}

function Set-AgentBaseEvaluationEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory = $true)]
        [string]$CodexHomePath,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeTemp
    )

    foreach ($name in @($StartInfo.Environment.Keys | Where-Object { [string]$_ -like 'CODEX_*' })) {
        [void]$StartInfo.Environment.Remove([string]$name)
    }
    foreach ($name in @(
        'OPENAI_API_KEY',
        'OPENAI_API_BASE',
        'OPENAI_BASE_URL',
        'OPENAI_ORG_ID',
        'OPENAI_PROJECT_ID',
        'AZURE_OPENAI_API_KEY',
        'GIT_DIR',
        'GIT_WORK_TREE',
        'PWD',
        'OLDPWD'
    )) {
        [void]$StartInfo.Environment.Remove($name)
    }
    $StartInfo.Environment['CODEX_HOME'] = [IO.Path]::GetFullPath($CodexHomePath)
    $StartInfo.Environment['TEMP'] = [IO.Path]::GetFullPath($RuntimeTemp)
    $StartInfo.Environment['TMP'] = [IO.Path]::GetFullPath($RuntimeTemp)
    $StartInfo.Environment['TMPDIR'] = [IO.Path]::GetFullPath($RuntimeTemp)
    $StartInfo.Environment['APPDATA'] = [IO.Path]::GetFullPath(
        (Join-Path $RuntimeTemp 'appdata')
    )
    $StartInfo.Environment['LOCALAPPDATA'] = [IO.Path]::GetFullPath(
        (Join-Path $RuntimeTemp 'localappdata')
    )
    $StartInfo.Environment['NO_COLOR'] = '1'
}

function Invoke-AgentBaseBoundedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$CodexHomePath,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeTemp,
        [string]$StandardInput,
        [Parameter(Mandatory = $true)]
        [int]$Timeout
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    $startInfo.WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardInputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    Set-AgentBaseEvaluationEnvironment -StartInfo $startInfo -CodexHomePath $CodexHomePath -RuntimeTemp $RuntimeTemp

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $started = [DateTimeOffset]::UtcNow
    try {
        if (-not $process.Start()) {
            throw 'process did not start'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if ($null -ne $StandardInput) {
            $process.StandardInput.Write($StandardInput)
        }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($Timeout * 1000)) {
            try { $process.Kill($true) } catch {}
            $process.WaitForExit()
            throw "process timed out after $Timeout seconds"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject][ordered]@{
            exit_code = $process.ExitCode
            stdout = $stdout
            stderr = $stderr
            duration_seconds = [Math]::Round(([DateTimeOffset]::UtcNow - $started).TotalSeconds, 3)
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-AgentBaseCandidatePreflight {
    param(
        [Parameter(Mandatory = $true)]
        [object]$CodexIdentity,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedWorkspace,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedHome,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedCanary,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedDeniedAuth,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedInstalledAuth,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectCanary,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedSkillRoot,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedSkillProbeManifest,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSkillProbeManifestSha256,
        [Parameter(Mandatory = $true)]
        [int]$ExpectedSkillFileCount,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedToolProbeManifest,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedToolProbeManifestSha256,
        [Parameter(Mandatory = $true)]
        [object]$ExpectedToolProbes,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedOutput,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeTemp,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeAppData,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeLocalAppData,
        [string]$FailureResultPath,
        [switch]$AllowFailedReceipt
    )

    $preflightScript = Join-Path $ResolvedWorkspace '.agentbase\preflight.ps1'
    $preflightArguments = @(
        'sandbox',
        '-P', $Profile,
        '-C', $ResolvedWorkspace,
        '--',
        'pwsh.exe', '-NoProfile', '-NonInteractive', '-File', $preflightScript,
        '-CanaryPath', $ResolvedCanary,
        '-DeniedAuthPath', $ResolvedDeniedAuth,
        '-InstalledAuthPath', $ResolvedInstalledAuth,
        '-ProjectCanaryPath', $ResolvedProjectCanary,
        '-SkillRootPath', $ResolvedSkillRoot,
        '-SkillProbeManifestPath', $ResolvedSkillProbeManifest,
        '-ExpectedSkillProbeManifestSha256', $ExpectedSkillProbeManifestSha256,
        '-ToolProbeManifestPath', $ResolvedToolProbeManifest,
        '-ExpectedToolProbeManifestSha256', $ExpectedToolProbeManifestSha256,
        '-WriteProbePath', ($ResolvedOutput + '.write-probe'),
        '-RuntimeTempPath', $RuntimeTemp,
        '-RuntimeAppDataPath', $RuntimeAppData,
        '-RuntimeLocalAppDataPath', $RuntimeLocalAppData
    )
    $preflightProcess = Invoke-AgentBaseBoundedProcess `
        -Executable $CodexIdentity.path `
        -Arguments $preflightArguments `
        -WorkingDirectory $ResolvedWorkspace `
        -CodexHomePath $ResolvedHome `
        -RuntimeTemp $RuntimeTemp `
        -Timeout 300
    $preflightDiagnostic = [regex]::Replace(
        ([string]$preflightProcess.stderr).Trim(),
        '\s+',
        ' '
    )
    if ($preflightDiagnostic.Length -gt 600) {
        $preflightDiagnostic = $preflightDiagnostic.Substring(0, 297) + ' ... ' + $preflightDiagnostic.Substring($preflightDiagnostic.Length - 298)
    }
    if ([string]::IsNullOrWhiteSpace([string]$preflightProcess.stdout)) {
        throw "candidate preflight produced no receipt; exit=$($preflightProcess.exit_code); diagnostic=$preflightDiagnostic"
    }
    try {
        $preflight = [string]$preflightProcess.stdout | ConvertFrom-Json -Depth 20 -DateKind String
    }
    catch {
        throw "candidate preflight produced an invalid receipt; exit=$($preflightProcess.exit_code); diagnostic=$preflightDiagnostic"
    }
    $expectedTools = @($ExpectedToolProbes.Keys | Sort-Object)
    $actualTools = if ($null -eq $preflight.tool_probes) {
        @()
    }
    else {
        @($preflight.tool_probes.PSObject.Properties.Name | Sort-Object -Unique)
    }
    $manifestReady = (
        $preflight.tool_probe_manifest_readable -is [bool] -and
        [bool]$preflight.tool_probe_manifest_readable -and
        [string]$preflight.tool_probe_manifest_sha256 -ceq $ExpectedToolProbeManifestSha256 -and
        $null -eq $preflight.tool_probe_manifest_error_type
    )
    $toolShapeValid = if ($manifestReady) {
        $expectedTools.Count -eq $actualTools.Count
    }
    else {
        $actualTools.Count -eq 0
    }
    if ($toolShapeValid -and $manifestReady) {
        for ($index = 0; $index -lt $expectedTools.Count; $index++) {
            if ([string]$expectedTools[$index] -cne [string]$actualTools[$index]) {
                $toolShapeValid = $false
                break
            }
            $probe = $preflight.tool_probes.([string]$expectedTools[$index])
            if (
                $null -eq $probe -or
                $probe.PSObject.Properties.Name -notcontains 'expected_sha256' -or
                $probe.PSObject.Properties.Name -notcontains 'observed_sha256' -or
                $probe.PSObject.Properties.Name -notcontains 'exit_code' -or
                $probe.PSObject.Properties.Name -notcontains 'summary' -or
                [string]$probe.expected_sha256 -cne [string]$ExpectedToolProbes[[string]$expectedTools[$index]] -or
                (
                    $null -ne $probe.observed_sha256 -and
                    [string]$probe.observed_sha256 -cnotmatch '^[0-9a-f]{64}$'
                ) -or
                -not (Test-AgentBaseJsonInteger -Value $probe.exit_code) -or
                $probe.summary -isnot [string]
            ) {
                $toolShapeValid = $false
                break
            }
        }
    }
    $skillManifestHashShapeValid = if ([bool]$preflight.skill_probe_manifest_readable) {
        [string]$preflight.skill_probe_manifest_sha256 -cmatch '^[0-9a-f]{64}$'
    }
    else {
        [string]::IsNullOrEmpty([string]$preflight.skill_probe_manifest_sha256)
    }
    $expectedSmokeNames = @('artifact', 'ast-cache', 'fd-tree', 'rg-pagination', 'scc-machine')
    $actualSmokeNames = if ($null -eq $preflight.srcq_smoke) {
        @()
    }
    else {
        @($preflight.srcq_smoke.PSObject.Properties.Name | Sort-Object -Unique)
    }
    $srcqSmokeShapeValid = $actualSmokeNames.Count -eq $expectedSmokeNames.Count
    if ($srcqSmokeShapeValid) {
        for ($index = 0; $index -lt $expectedSmokeNames.Count; $index++) {
            $name = [string]$expectedSmokeNames[$index]
            if ($name -cne [string]$actualSmokeNames[$index]) {
                $srcqSmokeShapeValid = $false
                break
            }
            $smoke = $preflight.srcq_smoke.($name)
            if (
                -not (Test-AgentBaseExactPropertySet -Value $smoke -Expected @('passed', 'summary')) -or
                $smoke.passed -isnot [bool] -or
                $smoke.summary -isnot [string]
            ) {
                $srcqSmokeShapeValid = $false
                break
            }
        }
    }
    $receiptPropertiesValid = Test-AgentBaseExactPropertySet -Value $preflight -Expected @(
        'schema', 'passed',
        'canary_readable', 'canary_error_type',
        'auth_readable', 'auth_error_type',
        'installed_auth_readable', 'installed_auth_error_type',
        'project_canary_readable', 'project_canary_error_type',
        'skill_probe_manifest_readable', 'skill_probe_manifest_sha256',
        'skill_probe_manifest_error_type', 'skill_projection_readable',
        'skill_projection_error_type', 'skill_projection_write_denied',
        'skill_projection_write_error_type', 'skill_files_expected',
        'skill_files_verified', 'workspace_write_probe_passed',
        'workspace_write_probe_error_type', 'runtime_temp_attempt_scoped',
        'runtime_appdata_attempt_scoped', 'runtime_localappdata_attempt_scoped',
        'runtime_state_error_type', 'tool_probe_manifest_readable',
        'tool_probe_manifest_sha256', 'tool_probe_manifest_error_type',
        'tool_probes', 'srcq_doctor_exit_code', 'srcq_scc_doctor_exit_code',
        'srcq_smoke', 'srcq_doctor_summary', 'srcq_scc_doctor_summary'
    )
    $receiptShapeValid = (
        $receiptPropertiesValid -and
        [string]$preflight.schema -eq 'agentbase.windows-swe-preflight/v9' -and
        $preflight.passed -is [bool] -and
        $preflight.canary_readable -is [bool] -and
        $preflight.auth_readable -is [bool] -and
        $preflight.installed_auth_readable -is [bool] -and
        $preflight.project_canary_readable -is [bool] -and
        $preflight.skill_probe_manifest_readable -is [bool] -and
        $preflight.skill_projection_readable -is [bool] -and
        $preflight.skill_projection_write_denied -is [bool] -and
        (Test-AgentBaseJsonInteger -Value $preflight.skill_files_expected) -and
        [int64]$preflight.skill_files_expected -ge 0 -and
        (Test-AgentBaseJsonInteger -Value $preflight.skill_files_verified) -and
        [int64]$preflight.skill_files_verified -ge 0 -and
        [int64]$preflight.skill_files_verified -le [int64]$preflight.skill_files_expected -and
        $preflight.workspace_write_probe_passed -is [bool] -and
        $preflight.runtime_temp_attempt_scoped -is [bool] -and
        $preflight.runtime_appdata_attempt_scoped -is [bool] -and
        $preflight.runtime_localappdata_attempt_scoped -is [bool] -and
        $preflight.tool_probe_manifest_readable -is [bool] -and
        (
            $null -eq $preflight.tool_probe_manifest_sha256 -or
            [string]$preflight.tool_probe_manifest_sha256 -cmatch '^[0-9a-f]{64}$'
        ) -and
        (
            $null -eq $preflight.tool_probe_manifest_error_type -or
            $preflight.tool_probe_manifest_error_type -is [string]
        ) -and
        (Test-AgentBaseJsonInteger -Value $preflight.srcq_doctor_exit_code) -and
        (Test-AgentBaseJsonInteger -Value $preflight.srcq_scc_doctor_exit_code) -and
        $toolShapeValid -and
        $skillManifestHashShapeValid -and
        $srcqSmokeShapeValid
    )
    if (-not $receiptShapeValid) {
        throw "candidate preflight returned an invalid receipt; exit=$($preflightProcess.exit_code); diagnostic=$preflightDiagnostic"
    }
    $allToolProbesPassed = $manifestReady
    if ($allToolProbesPassed) {
        foreach ($tool in $expectedTools) {
            $probe = $preflight.tool_probes.([string]$tool)
            $expectedProbeSha256 = [string]$ExpectedToolProbes[[string]$tool]
            if (
                [string]$probe.expected_sha256 -cne $expectedProbeSha256 -or
                [string]$probe.observed_sha256 -cne $expectedProbeSha256 -or
                [int]$probe.exit_code -ne 0 -or
                [string]::IsNullOrWhiteSpace([string]$probe.summary)
            ) {
                $allToolProbesPassed = $false
                break
            }
        }
    }
    $preflightPassed = (
        $preflightProcess.exit_code -eq 0 -and
        [bool]$preflight.passed -and
        -not [bool]$preflight.canary_readable -and
        -not [bool]$preflight.auth_readable -and
        -not [bool]$preflight.installed_auth_readable -and
        -not [bool]$preflight.project_canary_readable -and
        [bool]$preflight.skill_probe_manifest_readable -and
        [string]$preflight.skill_probe_manifest_sha256 -ceq $ExpectedSkillProbeManifestSha256 -and
        $null -eq $preflight.skill_probe_manifest_error_type -and
        [bool]$preflight.skill_projection_readable -and
        [bool]$preflight.skill_projection_write_denied -and
        [int]$preflight.skill_files_expected -eq $ExpectedSkillFileCount -and
        [int]$preflight.skill_files_verified -eq $ExpectedSkillFileCount -and
        [bool]$preflight.workspace_write_probe_passed -and
        [bool]$preflight.runtime_temp_attempt_scoped -and
        [bool]$preflight.runtime_appdata_attempt_scoped -and
        [bool]$preflight.runtime_localappdata_attempt_scoped -and
        $allToolProbesPassed -and
        [int]$preflight.srcq_doctor_exit_code -eq 0 -and
        [int]$preflight.srcq_scc_doctor_exit_code -eq 0 -and
        @($expectedSmokeNames | Where-Object { -not [bool]$preflight.srcq_smoke.($_).passed }).Count -eq 0
    )
    Write-AgentBaseJson -Path $ResolvedOutput -Value $preflight
    $exitMatchesReceipt = (
        ($preflightPassed -and $preflightProcess.exit_code -eq 0) -or
        (-not $preflightPassed -and -not [bool]$preflight.passed -and $preflightProcess.exit_code -eq 1)
    )
    if (-not $exitMatchesReceipt) {
        throw "candidate preflight exit and receipt disagree; exit=$($preflightProcess.exit_code); diagnostic=$preflightDiagnostic"
    }
    if (-not $preflightPassed -and -not $AllowFailedReceipt) {
        if (-not [string]::IsNullOrWhiteSpace($FailureResultPath)) {
            Write-AgentBaseJson -Path $FailureResultPath -Value ([ordered]@{
                schema = 'agentbase.windows-swe-codex-run/v3'
                status = 'blocked-precondition'
                model_invoked = $false
                exit_code = $null
                duration_seconds = $preflightProcess.duration_seconds
                diagnostic = $preflightDiagnostic
                codex = $CodexIdentity
                permission_profile = $Profile
                preflight = $preflight
            })
        }
        throw "candidate preflight failed; exit=$($preflightProcess.exit_code); diagnostic=$preflightDiagnostic"
    }
    return [pscustomobject][ordered]@{
        process = $preflightProcess
        receipt = $preflight
        passed = $preflightPassed
        diagnostic = $preflightDiagnostic
    }
}

$identity = Resolve-AgentBaseEvaluationCodex
if ($Action -eq 'Resolve') {
    Write-AgentBaseJson -Path $resolvedResult -Value $identity
    exit 0
}

foreach ($required in @{
    Workspace = $Workspace
    StateRoot = $StateRoot
    CodexHome = $CodexHome
    InstalledCodexRoot = $InstalledCodexRoot
    CanaryPath = $CanaryPath
    DeniedAuthPath = $DeniedAuthPath
    SkillRootPath = $SkillRootPath
    SkillProbeManifestPath = $SkillProbeManifestPath
    ExpectedSkillProbeManifestSha256 = $ExpectedSkillProbeManifestSha256
    ToolProbeManifestPath = $ToolProbeManifestPath
    ExpectedToolProbeManifestSha256 = $ExpectedToolProbeManifestSha256
    PreflightOutputPath = $PreflightOutputPath
    PermissionProfile = $PermissionProfile
}.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace([string]$required.Value)) {
        throw "$Action action requires -$($required.Key)"
    }
}
if ($Action -eq 'Run') {
    foreach ($required in @{
        PromptPath = $PromptPath
        Model = $Model
        ReasoningEffort = $ReasoningEffort
    }.GetEnumerator()) {
        if ([string]::IsNullOrWhiteSpace([string]$required.Value)) {
            throw "Run action requires -$($required.Key)"
        }
    }
}

$resolvedWorkspace = (Resolve-Path -LiteralPath $Workspace).Path
$resolvedState = (Resolve-Path -LiteralPath $StateRoot).Path
$resolvedHome = (Resolve-Path -LiteralPath $CodexHome).Path
$resolvedInstalledCodexRoot = (Resolve-Path -LiteralPath $InstalledCodexRoot).Path
$resolvedInstalledAuth = (Resolve-Path -LiteralPath (Join-Path $resolvedInstalledCodexRoot 'auth.json')).Path
$resolvedProjectCanary = (Resolve-Path -LiteralPath (Join-Path $resolvedProject 'README.md')).Path
$resolvedPrompt = if ($Action -eq 'Run') { (Resolve-Path -LiteralPath $PromptPath).Path } else { $null }
$resolvedCanary = (Resolve-Path -LiteralPath $CanaryPath).Path
$resolvedDeniedAuth = [IO.Path]::GetFullPath($DeniedAuthPath)
if ($Action -eq 'Preflight' -and -not (Test-Path -LiteralPath $resolvedDeniedAuth -PathType Leaf)) {
    throw 'Preflight action requires an existing fake staged auth canary'
}
$resolvedSkillRoot = (Resolve-Path -LiteralPath $SkillRootPath).Path
$resolvedPreflight = [IO.Path]::GetFullPath($PreflightOutputPath)
$homeRelative = [IO.Path]::GetRelativePath($resolvedState, $resolvedHome)
$canaryRelative = [IO.Path]::GetRelativePath($resolvedState, $resolvedCanary)
foreach ($boundary in @{
    'Codex home' = $homeRelative
    'Canary' = $canaryRelative
}.GetEnumerator()) {
    $relative = [string]$boundary.Value
    if (
        [IO.Path]::IsPathRooted($relative) -or
        $relative -eq '..' -or
        $relative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
    ) {
        throw "$($boundary.Key) must be inside the denied state root"
    }
}
$resultRelative = [IO.Path]::GetRelativePath($resolvedState, $resolvedResult)
if (
    [IO.Path]::IsPathRooted($resultRelative) -or
    $resultRelative -eq '..' -or
    $resultRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
) {
    throw 'Result path must be inside the denied state root'
}
if ($Action -eq 'Run') {
    $promptRelative = [IO.Path]::GetRelativePath($resolvedState, $resolvedPrompt)
    if (
        [IO.Path]::IsPathRooted($promptRelative) -or
        $promptRelative -eq '..' -or
        $promptRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
    ) {
        throw 'Candidate prompt must be inside the denied state root'
    }
}
$expectedDeniedAuth = [IO.Path]::GetFullPath((Join-Path $resolvedHome 'auth.json'))
if (-not $resolvedDeniedAuth.Equals($expectedDeniedAuth, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Denied auth preflight path must be the staged Codex home auth.json'
}
Assert-AgentBaseDisjointPaths -LeftName 'Candidate workspace' -LeftPath $resolvedWorkspace -RightName 'denied state root' -RightPath $resolvedState
Assert-AgentBaseDisjointPaths -LeftName 'Candidate workspace' -LeftPath $resolvedWorkspace -RightName 'project root' -RightPath $resolvedProject
Assert-AgentBaseDisjointPaths -LeftName 'Denied state root' -LeftPath $resolvedState -RightName 'project root' -RightPath $resolvedProject
Assert-AgentBaseDisjointPaths -LeftName 'Installed Codex root' -LeftPath $resolvedInstalledCodexRoot -RightName 'candidate workspace' -RightPath $resolvedWorkspace
Assert-AgentBaseDisjointPaths -LeftName 'Installed Codex root' -LeftPath $resolvedInstalledCodexRoot -RightName 'denied state root' -RightPath $resolvedState
Assert-AgentBaseDisjointPaths -LeftName 'Installed Codex root' -LeftPath $resolvedInstalledCodexRoot -RightName 'project root' -RightPath $resolvedProject
$preflightRelative = [IO.Path]::GetRelativePath($resolvedWorkspace, $resolvedPreflight)
if (
    [IO.Path]::IsPathRooted($preflightRelative) -or
    $preflightRelative -eq '..' -or
    $preflightRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal) -or
    -not $preflightRelative.StartsWith('.agentbase' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
) {
    throw 'Preflight output must be inside the candidate workspace .agentbase subtree'
}
$skillProbeManifest = Read-AgentBaseSkillProbeManifest `
    -Path $SkillProbeManifestPath `
    -ExpectedSha256 $ExpectedSkillProbeManifestSha256 `
    -ResolvedWorkspace $resolvedWorkspace `
    -ResolvedSkillRoot $resolvedSkillRoot
$toolProbeManifest = Read-AgentBaseToolProbeManifest `
    -Path $ToolProbeManifestPath `
    -ExpectedSha256 $ExpectedToolProbeManifestSha256 `
    -ResolvedWorkspace $resolvedWorkspace
$attemptRuntimeRoot = Split-Path -Parent $resolvedHome
$runtimeTemp = [IO.Path]::GetFullPath((Join-Path $attemptRuntimeRoot 'runtime-temp'))
$runtimeRelative = [IO.Path]::GetRelativePath($resolvedState, $runtimeTemp)
if (
    [IO.Path]::IsPathRooted($runtimeRelative) -or
    $runtimeRelative -eq '..' -or
    $runtimeRelative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
) {
    throw 'Runtime tmpdir must be inside the denied state root'
}
Assert-AgentBaseDisjointPaths -LeftName 'Runtime tmpdir' -LeftPath $runtimeTemp -RightName 'candidate workspace' -RightPath $resolvedWorkspace
Assert-AgentBaseDisjointPaths -LeftName 'Runtime tmpdir' -LeftPath $runtimeTemp -RightName 'project root' -RightPath $resolvedProject
Assert-AgentBaseDisjointPaths -LeftName 'Runtime tmpdir' -LeftPath $runtimeTemp -RightName 'installed Codex root' -RightPath $resolvedInstalledCodexRoot
[IO.Directory]::CreateDirectory($runtimeTemp) | Out-Null
$runtimeAppData = Join-Path $runtimeTemp 'appdata'
$runtimeLocalAppData = Join-Path $runtimeTemp 'localappdata'
[IO.Directory]::CreateDirectory($runtimeAppData) | Out-Null
[IO.Directory]::CreateDirectory($runtimeLocalAppData) | Out-Null

if ($Action -eq 'Preflight') {
    $preflightResult = Invoke-AgentBaseCandidatePreflight `
        -CodexIdentity $identity `
        -ResolvedWorkspace $resolvedWorkspace `
        -ResolvedHome $resolvedHome `
        -ResolvedCanary $resolvedCanary `
        -ResolvedDeniedAuth $resolvedDeniedAuth `
        -ResolvedInstalledAuth $resolvedInstalledAuth `
        -ResolvedProjectCanary $resolvedProjectCanary `
        -ResolvedSkillRoot $resolvedSkillRoot `
        -ResolvedSkillProbeManifest $skillProbeManifest.path `
        -ExpectedSkillProbeManifestSha256 $skillProbeManifest.sha256 `
        -ExpectedSkillFileCount $skillProbeManifest.file_count `
        -ResolvedToolProbeManifest $toolProbeManifest.path `
        -ExpectedToolProbeManifestSha256 $toolProbeManifest.sha256 `
        -ExpectedToolProbes $toolProbeManifest.expected_tools `
        -ResolvedOutput $resolvedPreflight `
        -Profile $PermissionProfile `
        -RuntimeTemp $runtimeTemp `
        -RuntimeAppData $runtimeAppData `
        -RuntimeLocalAppData $runtimeLocalAppData `
        -AllowFailedReceipt
    $preflightEnvelope = [ordered]@{
        schema = 'agentbase.windows-swe-sandbox-check/v3'
        status = if ($preflightResult.passed) { 'passed' } else { 'failed' }
        passed = [bool]$preflightResult.passed
        codex = $identity
        permission_profile = $PermissionProfile
        duration_seconds = $preflightResult.process.duration_seconds
        diagnostic = if ($preflightResult.passed) { $null } else { $preflightResult.diagnostic }
        preflight = $preflightResult.receipt
    }
    Write-AgentBaseJson -Path $resolvedResult -Value $preflightEnvelope
    if ([IO.Directory]::Exists($runtimeTemp)) {
        [IO.Directory]::Delete($runtimeTemp, $true)
    }
    if (-not $preflightResult.passed) {
        exit 3
    }
    exit 0
}

$logRoot = Join-Path (Split-Path -Parent $resolvedResult) 'codex-logs'
[IO.Directory]::CreateDirectory($logRoot) | Out-Null

$authSource = $resolvedInstalledAuth
$modelCatalogSource = (Resolve-Path -LiteralPath (Join-Path $resolvedInstalledCodexRoot 'models_cache.json')).Path

$authLink = $resolvedDeniedAuth
$catalogPath = Join-Path $resolvedHome 'models-evaluation.json'
$lastMessagePath = Join-Path $logRoot 'last-message.txt'
$stdoutPath = Join-Path $logRoot 'events.jsonl'
$stderrPath = Join-Path $logRoot 'stderr.txt'
$authLock = $null
$result = $null
try {
    $authHashBefore = (Get-FileHash -LiteralPath $authSource -Algorithm SHA256).Hash
    New-Item -ItemType HardLink -Path $authLink -Target $authSource -ErrorAction Stop | Out-Null
    $authLock = [IO.File]::Open($authSource, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $catalog = New-AgentBaseCodexModelCatalogProjection `
        -SourcePath $modelCatalogSource `
        -DestinationPath $catalogPath `
        -Model $Model

    $preflightResult = Invoke-AgentBaseCandidatePreflight `
        -CodexIdentity $identity `
        -ResolvedWorkspace $resolvedWorkspace `
        -ResolvedHome $resolvedHome `
        -ResolvedCanary $resolvedCanary `
        -ResolvedDeniedAuth $resolvedDeniedAuth `
        -ResolvedInstalledAuth $resolvedInstalledAuth `
        -ResolvedProjectCanary $resolvedProjectCanary `
        -ResolvedSkillRoot $resolvedSkillRoot `
        -ResolvedSkillProbeManifest $skillProbeManifest.path `
        -ExpectedSkillProbeManifestSha256 $skillProbeManifest.sha256 `
        -ExpectedSkillFileCount $skillProbeManifest.file_count `
        -ResolvedToolProbeManifest $toolProbeManifest.path `
        -ExpectedToolProbeManifestSha256 $toolProbeManifest.sha256 `
        -ExpectedToolProbes $toolProbeManifest.expected_tools `
        -ResolvedOutput $resolvedPreflight `
        -Profile $PermissionProfile `
        -RuntimeTemp $runtimeTemp `
        -RuntimeAppData $runtimeAppData `
        -RuntimeLocalAppData $runtimeLocalAppData `
        -FailureResultPath $resolvedResult
    $preflight = $preflightResult.receipt

    $catalogTomlPath = [IO.Path]::GetFullPath([string]$catalog.path).Replace('\', '/')
    $arguments = @(
        'exec',
        '--model', $Model,
        '-c', "model_reasoning_effort=`"$ReasoningEffort`"",
        '-c', "model_catalog_json=`"$catalogTomlPath`"",
        '-c', 'analytics.enabled=false',
        '--strict-config',
        '--ephemeral',
        '--skip-git-repo-check',
        '--output-last-message', $lastMessagePath,
        '--json',
        '--color', 'never',
        '--cd', $resolvedWorkspace,
        '-'
    )
    $prompt = [IO.File]::ReadAllText($resolvedPrompt, [Text.Encoding]::UTF8)
    $codexProcess = Invoke-AgentBaseBoundedProcess `
        -Executable $identity.path `
        -Arguments $arguments `
        -WorkingDirectory $resolvedWorkspace `
        -CodexHomePath $resolvedHome `
        -RuntimeTemp $runtimeTemp `
        -StandardInput $prompt `
        -Timeout $TimeoutSeconds
    if (([string]$codexProcess.stdout).Length -gt 16777216 -or ([string]$codexProcess.stderr).Length -gt 2097152) {
        throw 'Codex candidate exceeded the bounded diagnostic output contract'
    }
    [IO.File]::WriteAllText($stdoutPath, [string]$codexProcess.stdout, $utf8NoBom)
    [IO.File]::WriteAllText($stderrPath, [string]$codexProcess.stderr, $utf8NoBom)
    $jsonlSummary = Get-AgentBaseCodexJsonlSummary -Text ([string]$codexProcess.stdout)
    $authHashAfter = (Get-FileHash -LiteralPath $authSource -Algorithm SHA256).Hash
    if ($authHashBefore -ne $authHashAfter) {
        throw 'Codex auth.json changed while the evaluation lock was held'
    }
    $diagnosticText = (([string]$codexProcess.stderr + "`n" + [string]$codexProcess.stdout).Trim())
    if ($diagnosticText.Length -gt 800) {
        $diagnosticText = $diagnosticText.Substring(0, 400) + ' ... ' + $diagnosticText.Substring($diagnosticText.Length - 395)
    }
    $result = [ordered]@{
        schema = 'agentbase.windows-swe-codex-run/v3'
        status = 'completed'
        model_invoked = $true
        exit_code = $codexProcess.exit_code
        duration_seconds = $codexProcess.duration_seconds
        diagnostic = $diagnosticText
        codex = $identity
        model_catalog_sha256 = ([string]$catalog.sha256).ToLowerInvariant()
        permission_profile = $PermissionProfile
        preflight = $preflight
        event_count = $jsonlSummary.event_count
        turn_completed_count = $jsonlSummary.turn_completed_count
        usage_complete = $jsonlSummary.usage_complete
        usage = $jsonlSummary.usage
        tool_event_types = @($jsonlSummary.tool_event_types)
        stdout = [ordered]@{
            path = $stdoutPath
            sha256 = (Get-FileHash -LiteralPath $stdoutPath -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = (Get-Item -LiteralPath $stdoutPath).Length
        }
        stderr = [ordered]@{
            path = $stderrPath
            sha256 = (Get-FileHash -LiteralPath $stderrPath -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = (Get-Item -LiteralPath $stderrPath).Length
        }
    }
}
finally {
    if ($null -ne $authLock) {
        $authLock.Dispose()
    }
    if (Test-Path -LiteralPath $authLink -PathType Leaf) {
        Remove-Item -LiteralPath $authLink -Force
    }
    if ([IO.Directory]::Exists($runtimeTemp)) {
        [IO.Directory]::Delete($runtimeTemp, $true)
    }
}

Write-AgentBaseJson -Path $resolvedResult -Value $result
