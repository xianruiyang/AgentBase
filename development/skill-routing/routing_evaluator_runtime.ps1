$ErrorActionPreference = "Stop"

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'common\codex_cli_runtime.ps1')

function Resolve-AgentBaseCodexExecutable {
    param(
        [string]$ExplicitPath
    )

    $npmPrefix = Get-AgentBaseUserNpmPrefix
    $sandboxFallback = if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $null
    }
    else {
        Join-Path $env:USERPROFILE '.codex\.sandbox-bin\codex.exe'
    }
    return Resolve-AgentBaseCodexNativeExecutable -ExplicitPath $ExplicitPath -NpmPrefix $npmPrefix -SandboxFallbackPath $sandboxFallback
}

function Get-AgentBaseCodexVersion {
    param(
        [string]$ExecutablePath
    )

    $output = & $ExecutablePath --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Codex CLI version readback failed with exit code $LASTEXITCODE"
    }
    $text = ([string]($output -join " ")).Trim()
    if ([string]::IsNullOrWhiteSpace($text) -or $text.Length -gt 100) {
        throw "Codex CLI returned an invalid version identity"
    }
    return $text
}

function Get-AgentBaseBoundedMessage {
    param(
        [string]$Text,
        [ValidateRange(40, 5000)]
        [int]$MaximumLength = 450
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return "No diagnostic text was returned."
    }
    $singleLine = [regex]::Replace($Text.Trim(), '\s+', ' ')
    if ($singleLine.Length -le $MaximumLength) {
        return $singleLine
    }
    $marker = " ... "
    $available = $MaximumLength - $marker.Length
    $headLength = [int][Math]::Ceiling($available / 2)
    $tailLength = $available - $headLength
    return $singleLine.Substring(0, $headLength) + $marker + $singleLine.Substring($singleLine.Length - $tailLength)
}

function Get-AgentBaseCodexFailureDiagnostic {
    param(
        [string]$StandardOutput,
        [string]$StandardError,
        [ValidateRange(80, 5000)]
        [int]$MaximumLength = 450
    )

    $messages = New-Object 'System.Collections.Generic.List[string]'
    if (-not [string]::IsNullOrWhiteSpace($StandardError)) {
        $messages.Add("stderr: $StandardError")
    }
    foreach ($line in @($StandardOutput -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        try {
            $event = $line | ConvertFrom-Json -Depth 30 -DateKind String
        }
        catch {
            continue
        }
        foreach ($candidate in @($event.message, $event.error.message, $event.error)) {
            $text = [string]$candidate
            if (-not [string]::IsNullOrWhiteSpace($text) -and -not $messages.Contains($text)) {
                $messages.Add($text)
            }
        }
    }
    if ($messages.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($StandardOutput)) {
        $messages.Add("stdout: $StandardOutput")
    }
    return Get-AgentBaseBoundedMessage -Text ($messages -join " | ") -MaximumLength $MaximumLength
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
        throw "Codex model catalog projection must not overwrite its source"
    }

    try {
        $catalog = [IO.File]::ReadAllText($resolvedSource, [Text.Encoding]::UTF8) | ConvertFrom-Json -Depth 100 -DateKind String
    }
    catch {
        throw "Codex model catalog source is not valid JSON: $($_.Exception.Message)"
    }
    $models = @($catalog.models)
    if ($models.Count -eq 0) {
        throw "Codex model catalog source contains no models"
    }
    $selected = @($models | Where-Object { [string]$_.slug -eq $Model })
    if ($selected.Count -ne 1) {
        throw "Codex model catalog must contain exactly one entry for requested model: $Model"
    }
    $projection = [pscustomobject][ordered]@{
        models = @($selected[0])
    }
    $json = $projection | ConvertTo-Json -Depth 100
    [IO.File]::WriteAllText($resolvedDestination, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    $projectionItem = Get-Item -LiteralPath $resolvedDestination -Force
    if (($projectionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $projectionItem.Length -le 0 -or $projectionItem.Length -gt 1048576) {
        throw "Codex model catalog projection is not a bounded regular file"
    }
    return [pscustomobject][ordered]@{
        path = $projectionItem.FullName
        sha256 = (Get-FileHash -LiteralPath $projectionItem.FullName -Algorithm SHA256).Hash
        model = $Model
        model_count = 1
    }
}

function Get-AgentBaseCodexEvaluatorArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Model,
        [Parameter(Mandatory = $true)]
        [string]$ReasoningEffort,
        [Parameter(Mandatory = $true)]
        [string]$ModelCatalogPath,
        [Parameter(Mandatory = $true)]
        [string]$SchemaPath,
        [Parameter(Mandatory = $true)]
        [string]$LastMessagePath,
        [Parameter(Mandatory = $true)]
        [string]$WorkPath
    )

    $catalogTomlPath = [IO.Path]::GetFullPath($ModelCatalogPath).Replace('\', '/')
    $arguments = New-Object 'System.Collections.Generic.List[string]'
    foreach ($argument in @(
        "exec",
        "--model", $Model,
        "-c", "model_reasoning_effort=`"$ReasoningEffort`"",
        "-c", "model_catalog_json=`"$catalogTomlPath`"",
        "-c", "analytics.enabled=false",
        "--strict-config"
    )) {
        $arguments.Add([string]$argument)
    }
    foreach ($feature in @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)) {
        $arguments.Add("--disable")
        $arguments.Add([string]$feature)
    }
    foreach ($argument in @(
        "--sandbox", "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema", [IO.Path]::GetFullPath($SchemaPath),
        "--output-last-message", [IO.Path]::GetFullPath($LastMessagePath),
        "--json",
        "--color", "never",
        "--cd", [IO.Path]::GetFullPath($WorkPath),
        "-"
    )) {
        $arguments.Add([string]$argument)
    }
    return [string[]]$arguments.ToArray()
}

function Set-AgentBaseCodexEvaluatorEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory = $true)]
        [string]$CodexHome,
        [Parameter(Mandatory = $true)]
        [string]$RuntimeTemp
    )

    foreach ($name in @($StartInfo.Environment.Keys | Where-Object { [string]$_ -like 'CODEX_*' })) {
        [void]$StartInfo.Environment.Remove([string]$name)
    }
    foreach ($name in @(
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "AZURE_OPENAI_API_KEY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "PWD",
        "OLDPWD"
    )) {
        [void]$StartInfo.Environment.Remove($name)
    }
    $StartInfo.Environment["CODEX_HOME"] = [IO.Path]::GetFullPath($CodexHome)
    $StartInfo.Environment["TEMP"] = [IO.Path]::GetFullPath($RuntimeTemp)
    $StartInfo.Environment["TMP"] = [IO.Path]::GetFullPath($RuntimeTemp)
    $StartInfo.Environment["NO_COLOR"] = "1"
}
