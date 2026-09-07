function Get-ValidatedPortableAgentSources {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Portable Codex agents directory is missing: $Path"
    }

    $expectedAgentNames = @("advanced-experiment", "evidence", "experiment", "operator")
    $entries = @(Get-ChildItem -LiteralPath $Path -Force | Sort-Object Name)
    $expectedFileNames = @($expectedAgentNames | ForEach-Object { "{0}.toml" -f $_ })
    $actualFileNames = @($entries.Name)
    if (($actualFileNames -join '|') -ne ($expectedFileNames -join '|')) {
        throw "Portable Codex agents contain an unexpected file set: $($actualFileNames -join ', ')"
    }

    $descriptions = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $instructions = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($entry in $entries) {
        if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Portable Codex agent must be a real TOML file: $($entry.FullName)"
        }

        $raw = Get-Content -LiteralPath $entry.FullName -Raw -Encoding UTF8
        if ($raw -match '(?i)([a-z]:[\\/]|\\\\|https?://|api[_-]?key|password|secret|credential|trusted_hash|mcp_servers|skills\.config)') {
            throw "Portable Codex agent contains a machine path, external dependency, or sensitive setting: $($entry.Name)"
        }

        $document = [regex]::Match(
            $raw,
            '(?s)\A\s*name\s*=\s*"(?<name>[^"\r\n]+)"\s*\r?\n\s*description\s*=\s*"(?<description>[^"\r\n]+)"\s*\r?\n\s*model\s*=\s*"(?<model>[^"\r\n]+)"\s*\r?\n\s*model_reasoning_effort\s*=\s*"(?<effort>[^"\r\n]+)"\s*\r?\n\s*developer_instructions\s*=\s*"""\s*\r?\n(?<instructions>.*?)\r?\n\s*"""\s*\z'
        )
        if (-not $document.Success) {
            throw "Portable Codex agent must contain only name, description, model, model_reasoning_effort, and multiline developer_instructions in the reviewed order: $($entry.Name)"
        }

        $agentName = [IO.Path]::GetFileNameWithoutExtension($entry.Name)
        $name = $document.Groups['name'].Value.Trim()
        $description = $document.Groups['description'].Value.Trim()
        $model = $document.Groups['model'].Value.Trim()
        $effort = $document.Groups['effort'].Value.Trim()
        $developerInstructions = $document.Groups['instructions'].Value.Trim()
        if ($name -ne $agentName) {
            throw "Portable Codex agent name does not match its file identity: $($entry.Name)"
        }
        if ($model -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
            throw "Portable Codex agent model must be an explicit safe model identifier: $($entry.Name)"
        }
        if (@('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'ultra', 'max') -notcontains $effort) {
            throw "Portable Codex agent reasoning effort is not supported by the portable schema: $($entry.Name)"
        }
        if ([string]::IsNullOrWhiteSpace($description) -or [string]::IsNullOrWhiteSpace($developerInstructions)) {
            throw "Portable Codex agent description and developer instructions must be non-empty: $($entry.Name)"
        }
        if ($description -notmatch '[一-龥]' -or $developerInstructions -notmatch '[一-龥]') {
            throw "Portable Codex agent model-facing prose must use Chinese semantics: $($entry.Name)"
        }
        if (-not $descriptions.Add($description) -or -not $instructions.Add($developerInstructions)) {
            throw "Portable Codex agent roles must have distinct descriptions and developer instructions: $($entry.Name)"
        }
    }

    return $entries
}
