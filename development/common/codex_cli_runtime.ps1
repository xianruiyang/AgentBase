$ErrorActionPreference = 'Stop'
$script:AgentBaseCodexShellEnvironmentPolicyPath = Join-Path $PSScriptRoot 'codex_shell_environment_policy.json'

function Get-AgentBaseCodexShellEnvironmentPolicy {
    param(
        [string]$PolicyPath = $script:AgentBaseCodexShellEnvironmentPolicyPath
    )

    $resolved = (Resolve-Path -LiteralPath $PolicyPath).Path
    $item = Get-Item -LiteralPath $resolved -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -le 0 -or $item.Length -gt 65536) {
        throw "Codex shell environment policy must be a bounded regular file: $resolved"
    }
    try {
        $policy = [IO.File]::ReadAllText($resolved, [Text.Encoding]::UTF8) | ConvertFrom-Json -Depth 20 -DateKind String
    }
    catch {
        throw "Codex shell environment policy is not valid JSON: $($_.Exception.Message)"
    }
    $expectedProperties = @('schema', 'inherit', 'ignore_default_excludes', 'experimental_use_profile', 'filters')
    $actualProperties = @($policy.PSObject.Properties.Name)
    if ($actualProperties.Count -ne $expectedProperties.Count -or
        @($actualProperties | Where-Object { $expectedProperties -notcontains $_ }).Count -ne 0 -or
        [string]$policy.schema -ne 'agentbase.codex-shell-environment-policy/v1' -or
        [string]$policy.inherit -notin @('all', 'core', 'none') -or
        $policy.ignore_default_excludes -isnot [bool] -or
        $policy.experimental_use_profile -isnot [bool]) {
        throw 'Codex shell environment policy has an invalid shape'
    }
    $filters = @($policy.filters.PSObject.Properties)
    if ($filters.Count -eq 0 -or @($filters | Where-Object {
        [string]::IsNullOrWhiteSpace([string]$_.Name) -or
        ([string]$_.Name).Length -gt 128 -or
        [string]$_.Value -ne 'exclude'
    }).Count -ne 0) {
        throw 'Codex shell environment policy filters are invalid'
    }
    return [pscustomobject][ordered]@{
        descriptor = [pscustomobject][ordered]@{
            schema = 'agentbase.codex-shell-environment-policy/v1'
            logical_path = 'development/common/codex_shell_environment_policy.json'
            sha256 = ((Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash).ToLowerInvariant()
        }
        policy = $policy
    }
}

function ConvertTo-AgentBaseCodexTomlString {
    param(
        [AllowEmptyString()]
        [string]$Value
    )

    return [string](ConvertTo-Json -InputObject $Value -Compress)
}

function Get-AgentBaseCodexShellEnvironmentArguments {
    param(
        [string]$ExpectedSha256
    )

    $resolved = Get-AgentBaseCodexShellEnvironmentPolicy
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
        -not ([string]$resolved.descriptor.sha256).Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Codex shell environment policy changed after identity capture'
    }
    $policy = $resolved.policy
    $arguments = New-Object 'System.Collections.Generic.List[string]'
    foreach ($override in @(
        "shell_environment_policy.inherit=$(ConvertTo-AgentBaseCodexTomlString ([string]$policy.inherit))"
        "shell_environment_policy.ignore_default_excludes=$(([string]$policy.ignore_default_excludes).ToLowerInvariant())"
        "shell_environment_policy.experimental_use_profile=$(([string]$policy.experimental_use_profile).ToLowerInvariant())"
    )) {
        $arguments.Add('-c')
        $arguments.Add([string]$override)
    }
    [string[]]$filterNames = @($policy.filters.PSObject.Properties.Name)
    [Array]::Sort($filterNames, [StringComparer]::Ordinal)
    foreach ($filterName in $filterNames) {
        $filterValue = $policy.filters.PSObject.Properties[$filterName].Value
        $key = ConvertTo-AgentBaseCodexTomlString $filterName
        $value = ConvertTo-AgentBaseCodexTomlString ([string]$filterValue)
        $arguments.Add('-c')
        $arguments.Add("shell_environment_policy.filters.${key}=${value}")
    }
    return [string[]]$arguments.ToArray()
}

function Get-AgentBaseUserNpmPrefix {
    $npm = Get-Command -Name 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $npm) {
        $npm = Get-Command -Name 'npm.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -ne $npm) {
        $prefixOutput = @(& $npm.Source config get prefix 2>$null)
        $prefixExit = $LASTEXITCODE
        if ($prefixExit -eq 0 -and $prefixOutput.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace([string]$prefixOutput[-1])) {
            return [IO.Path]::GetFullPath(([string]$prefixOutput[-1]).Trim())
        }
    }
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        return $null
    }
    return [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'npm'))
}

function Get-AgentBaseCodexNativeCandidatePaths {
    param(
        [string]$NpmPrefix
    )

    if ([string]::IsNullOrWhiteSpace($NpmPrefix)) {
        return @()
    }
    $target = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
        ([Runtime.InteropServices.Architecture]::X64) {
            [pscustomobject]@{ package = 'codex-win32-x64'; triple = 'x86_64-pc-windows-msvc' }
        }
        ([Runtime.InteropServices.Architecture]::Arm64) {
            [pscustomobject]@{ package = 'codex-win32-arm64'; triple = 'aarch64-pc-windows-msvc' }
        }
        default { throw "Unsupported Windows architecture for Codex CLI: $([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)" }
    }
    $prefix = [IO.Path]::GetFullPath($NpmPrefix)
    return @(
        Join-Path $prefix "node_modules\@openai\codex\node_modules\@openai\$($target.package)\vendor\$($target.triple)\bin\codex.exe"
        Join-Path $prefix "node_modules\@openai\$($target.package)\vendor\$($target.triple)\bin\codex.exe"
        Join-Path $prefix "node_modules\@openai\codex\vendor\$($target.triple)\bin\codex.exe"
    )
}

function Resolve-AgentBaseCodexNativeExecutable {
    param(
        [string]$ExplicitPath,
        [string]$NpmPrefix,
        [string]$SandboxFallbackPath
    )

    $candidates = New-Object 'System.Collections.Generic.List[string]'
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $candidates.Add([IO.Path]::GetFullPath($ExplicitPath))
    }
    foreach ($candidate in @(Get-AgentBaseCodexNativeCandidatePaths -NpmPrefix $NpmPrefix)) {
        $candidates.Add([string]$candidate)
    }
    if (-not [string]::IsNullOrWhiteSpace($SandboxFallbackPath)) {
        $candidates.Add([IO.Path]::GetFullPath($SandboxFallbackPath))
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if ($candidate -match '(?i)\\WindowsApps\\') {
            continue
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                return $item.FullName
            }
        }
    }
    throw 'No directly executable Codex CLI was found outside WindowsApps. Install @openai/codex in the user npm prefix or pass CodexExecutablePath.'
}

function Get-AgentBaseCodexVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath
    )

    $output = @(& $ExecutablePath --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Codex CLI version readback failed with exit code $LASTEXITCODE"
    }
    $text = ([string]($output -join ' ')).Trim()
    if ([string]::IsNullOrWhiteSpace($text) -or $text.Length -gt 100 -or $text -notmatch '^codex-cli\s+\S+$') {
        throw 'Codex CLI returned an invalid version identity'
    }
    return $text
}

function Get-AgentBaseCodexJsonlSummary {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    $eventCount = 0
    $threadStartedCount = 0
    $turnCompletedCount = 0
    $threadId = $null
    $toolEvents = New-Object 'System.Collections.Generic.List[string]'
    $usage = [ordered]@{
        total_tokens = $null
        input_tokens = $null
        cached_input_tokens = $null
        cache_write_input_tokens = $null
        output_tokens = $null
        reasoning_output_tokens = $null
    }
    foreach ($line in @($Text -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        try {
            $event = $line | ConvertFrom-Json -Depth 100 -DateKind String
        }
        catch {
            throw 'Codex emitted non-JSON data on its JSONL channel'
        }
        $eventCount++
        if ([string]$event.type -eq 'thread.started') {
            $threadStartedCount++
            $candidateThreadId = [string]$event.thread_id
            if ([string]::IsNullOrWhiteSpace($candidateThreadId)) {
                throw 'Codex JSONL thread.started omitted thread_id'
            }
            if ($null -ne $threadId -and $threadId -cne $candidateThreadId) {
                throw 'Codex JSONL contains multiple thread identities'
            }
            $threadId = $candidateThreadId
        }
        $itemType = [string]$event.item.type
        if ($itemType -in @(
            'command_execution',
            'mcp_tool_call',
            'web_search',
            'file_change',
            'tool_call',
            'function_call',
            'image_generation'
        )) {
            $toolEvents.Add($itemType)
        }
        if ([string]$event.type -eq 'turn.completed') {
            $turnCompletedCount++
            if ($null -eq $event.usage) {
                continue
            }
            foreach ($field in @(
                'input_tokens',
                'cached_input_tokens',
                'cache_write_input_tokens',
                'output_tokens',
                'reasoning_output_tokens'
            )) {
                if ($null -eq $event.usage.$field) {
                    continue
                }
                $tokenValue = [long]$event.usage.$field
                if ($tokenValue -lt 0) {
                    throw "Codex JSONL usage contains a negative ${field} value"
                }
                $usage[$field] = $tokenValue
            }
            if ($null -ne $usage.input_tokens -and $null -ne $usage.output_tokens) {
                $usage.total_tokens = [long]$usage.input_tokens + [long]$usage.output_tokens
            }
        }
    }
    $usageComplete = @($usage.Values | Where-Object { $null -eq $_ }).Count -eq 0
    return [pscustomobject][ordered]@{
        schema = 'agentbase.codex-jsonl-summary/v2'
        event_count = $eventCount
        thread_started_count = $threadStartedCount
        thread_id = $threadId
        turn_completed_count = $turnCompletedCount
        usage_complete = $usageComplete
        usage = [pscustomobject]$usage
        tool_event_types = @($toolEvents | Sort-Object -Unique)
    }
}

function New-AgentBaseCodexModelCatalogProjection {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,
        [Parameter(Mandatory = $true)]
        [string]$Model
    )

    $resolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
    $sourceItem = Get-Item -LiteralPath $resolvedSource -Force
    if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $sourceItem.Length -le 0 -or $sourceItem.Length -gt 5242880) {
        throw "Codex model catalog source must be a bounded regular file: $resolvedSource"
    }
    $resolvedDestination = [IO.Path]::GetFullPath($DestinationPath)
    $destinationDirectory = Split-Path -Parent $resolvedDestination
    if ([string]::IsNullOrWhiteSpace($destinationDirectory) -or -not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
        throw "Codex model catalog projection directory must already exist: $destinationDirectory"
    }
    if ($resolvedSource.Equals($resolvedDestination, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Codex model catalog projection must not overwrite its source'
    }
    try {
        $catalog = [IO.File]::ReadAllText($resolvedSource, [Text.Encoding]::UTF8) | ConvertFrom-Json -Depth 100 -DateKind String
    }
    catch {
        throw "Codex model catalog source is not valid JSON: $($_.Exception.Message)"
    }
    $models = @($catalog.models)
    $selected = @($models | Where-Object { [string]$_.slug -eq $Model })
    if ($selected.Count -ne 1) {
        throw "Codex model catalog must contain exactly one entry for requested model: $Model"
    }
    $projection = [pscustomobject][ordered]@{ models = @($selected[0]) }
    [IO.File]::WriteAllText(
        $resolvedDestination,
        ($projection | ConvertTo-Json -Depth 100) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    $projectionItem = Get-Item -LiteralPath $resolvedDestination -Force
    if (($projectionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $projectionItem.Length -le 0 -or $projectionItem.Length -gt 1048576) {
        throw 'Codex model catalog projection is not a bounded regular file'
    }
    return [pscustomobject][ordered]@{
        path = $projectionItem.FullName
        sha256 = (Get-FileHash -LiteralPath $projectionItem.FullName -Algorithm SHA256).Hash
        model = $Model
        model_count = 1
    }
}
