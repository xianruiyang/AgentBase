param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

Update-FormatData -PrependPath (Join-Path $PSScriptRoot 'manage_agentbase.format.ps1xml') -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
. (Join-Path $PSScriptRoot "portable_config.ps1")

$portablePath = Join-Path $ProjectRoot "global\config.toml"
$testRoot = Join-Path $env:TEMP ("AgentBase-portable-config-" + [guid]::NewGuid().ToString("N"))
$resolvedTempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Portable-config test root escaped the host temp directory: $resolvedTestRoot"
}
New-Item -ItemType Directory -Path $resolvedTestRoot | Out-Null

$installedPath = Join-Path $resolvedTestRoot "config.toml"
$mergedPath = Join-Path $resolvedTestRoot "merged.toml"
$duplicatePath = Join-Path $resolvedTestRoot "duplicate.toml"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
try {
    $fixture = (@(
        'model = "old"'
        'model_reasoning_effort = "high"'
        'model_reasoning_summary = "detailed"'
        'model_verbosity = "high"'
        'approval_policy = "on-request"'
        'sandbox_mode = "workspace-write"'
        'web_search = "cached"'
        'service_tier = "fast"'
        'notify = ["host"]'
        '[agents]'
        'default_subagent_model = "gpt-5.6-terra"'
        'default_subagent_reasoning_effort = "low"'
        'keep-host-agent-setting = true'
        '[mcp_servers.keep]'
        'command = "keep"'
        '[features]'
        'path = "host-feature"'
        '[desktop]'
        'ambient-suggestions-enabled = true'
        'theme = "system"'
        '[projects.''D:\workspace'']'
        'trust_level = "trusted"'
    ) -join [Environment]::NewLine) + [Environment]::NewLine
    [IO.File]::WriteAllText($installedPath, $fixture, $utf8NoBom)

    $merged = Get-MergedPortableConfigText -PortableSourcePath $portablePath -InstalledPath $installedPath
    [IO.File]::WriteAllText($mergedPath, $merged, $utf8NoBom)
    foreach ($required in @(
        'model = "old"'
        'model_reasoning_effort = "high"'
        'model_reasoning_summary = "none"'
        'model_verbosity = "low"'
        'approval_policy = "never"'
        'sandbox_mode = "danger-full-access"'
        'web_search = "live"'
        'service_tier = "default"'
        'default_subagent_model = "gpt-5.6-luna"'
        'default_subagent_reasoning_effort = "max"'
        'keep-host-agent-setting = true'
        '[mcp_servers.keep]'
        'command = "keep"'
        'path = "host-feature"'
        'theme = "system"'
        'trust_level = "trusted"'
        '[desktop]'
        'ambient-suggestions-enabled = false'
    )) {
        if (-not $merged.Contains($required)) {
            throw "Portable config merge lost required content: $required"
        }
    }
    foreach ($retired in @(
        'model_reasoning_summary = "detailed"'
        'model_verbosity = "high"'
        'approval_policy = "on-request"'
        'sandbox_mode = "workspace-write"'
        'web_search = "cached"'
        'service_tier = "fast"'
        'default_subagent_model = "gpt-5.6-terra"'
        'default_subagent_reasoning_effort = "low"'
        'ambient-suggestions-enabled = true'
    )) {
        if ($merged.Contains($retired)) {
            throw "Portable config merge retained a replaced managed setting: $retired"
        }
    }

    $portableText = Get-Content -LiteralPath $portablePath -Raw -Encoding UTF8
    $sourceContract = Get-PortableConfigContractText -Text $portableText -PortableText $portableText
    $mergedContract = Get-PortableConfigContractText -Text $merged -PortableText $portableText
    if ($sourceContract -ne $mergedContract) {
        throw "Merged managed projection does not match the portable source"
    }
    $sourceFingerprint = Get-PortableConfigContractFingerprint -Path $portablePath -PortableSourcePath $portablePath
    $mergedFingerprint = Get-PortableConfigContractFingerprint -Path $mergedPath -PortableSourcePath $portablePath
    if ($sourceFingerprint -ne $mergedFingerprint) {
        throw "Merged managed fingerprint does not match the portable source"
    }
    $mergedAgain = Get-MergedPortableConfigText -PortableSourcePath $portablePath -InstalledPath $mergedPath
    if ($mergedAgain -cne $merged) {
        throw "Portable config merge rewrote unchanged host formatting"
    }
    $hostChangedContract = Get-PortableConfigContractText -Text ($merged.Replace('command = "keep"', 'command = "keep-updated"')) -PortableText $portableText
    if ($hostChangedContract -ne $sourceContract) {
        throw "Host-only MCP changes altered the managed projection"
    }

    $duplicateFixture = $fixture + "[features]" + [Environment]::NewLine + "hooks = false" + [Environment]::NewLine
    [IO.File]::WriteAllText($duplicatePath, $duplicateFixture, $utf8NoBom)
    $duplicateRejected = $false
    try {
        Get-MergedPortableConfigText -PortableSourcePath $portablePath -InstalledPath $duplicatePath | Out-Null
    }
    catch {
        $duplicateRejected = $_.Exception.Message -like "Codex config contains duplicate managed table*"
    }
    if (-not $duplicateRejected) {
        throw "Portable config merge did not reject an ambiguous managed table"
    }

    $result = [pscustomobject]@{
        managed_projection_matches = $true
        mcp_preserved = $true
        project_trust_preserved = $true
        same_table_host_key_preserved = $true
        unchanged_merge_is_byte_stable = $true
        host_only_change_ignored_by_contract = $true
        ambiguous_managed_table_rejected = $true
    }
    $result.PSObject.TypeNames.Insert(0, 'AgentBase.Deployment.TestResult')
    $result
}
finally {
    if (Test-Path -LiteralPath $resolvedTestRoot -PathType Container) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
