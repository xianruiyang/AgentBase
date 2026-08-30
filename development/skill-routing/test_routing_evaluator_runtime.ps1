$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_fingerprint.ps1")
. (Join-Path $PSScriptRoot "routing_evaluator_runtime.ps1")

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("AgentBase-routing-runtime-test-{0}" -f [guid]::NewGuid().ToString('N'))
$utf8NoBom = [Text.UTF8Encoding]::new($false)

try {
    [IO.Directory]::CreateDirectory($testRoot) | Out-Null
    $sourcePath = Join-Path $testRoot "models_cache.json"
    $projectionPath = Join-Path $testRoot "model-catalog.json"
    $schemaPath = Join-Path $testRoot "schema.json"
    $messagePath = Join-Path $testRoot "message.json"
    $workPath = Join-Path $testRoot "work"
    [IO.Directory]::CreateDirectory($workPath) | Out-Null
    $source = [pscustomobject][ordered]@{
        fetched_at = "not-part-of-the-projection"
        etag = "not-part-of-the-projection"
        models = @(
            [pscustomobject][ordered]@{ slug = "gpt-5.6-sol"; display_name = "Sol"; model_messages = [pscustomobject]@{ instructions = "target" } }
            [pscustomobject][ordered]@{ slug = "gpt-5.6-luna"; display_name = "Luna"; model_messages = [pscustomobject]@{ instructions = "other" } }
        )
    }
    [IO.File]::WriteAllText($sourcePath, ($source | ConvertTo-Json -Depth 20), $utf8NoBom)
    [IO.File]::WriteAllText($schemaPath, "{}", $utf8NoBom)

    $projection = New-AgentBaseCodexModelCatalogProjection -SourcePath $sourcePath -DestinationPath $projectionPath -Model "gpt-5.6-sol"
    $projectionDocument = Get-Content -LiteralPath $projection.path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
    if (@($projectionDocument.PSObject.Properties.Name).Count -ne 1 -or @($projectionDocument.models).Count -ne 1 -or
        [string]$projectionDocument.models[0].slug -ne "gpt-5.6-sol" -or
        [string]$projection.sha256 -notmatch '^[0-9A-F]{64}$') {
        throw "Sanitized model catalog did not retain exactly the requested model"
    }
    if (($projectionDocument | ConvertTo-Json -Depth 20).Contains("not-part-of-the-projection")) {
        throw "Sanitized model catalog retained cache metadata or an unselected model"
    }

    $layoutPrefix = Join-Path $testRoot 'npm-prefix'
    $nativeCandidates = @(Get-AgentBaseCodexNativeCandidatePaths -NpmPrefix $layoutPrefix)
    if ($nativeCandidates.Count -ne 3 -or @($nativeCandidates | Where-Object { $_ -match '(?i)\\WindowsApps\\' }).Count -ne 0) {
        throw "Shared Codex runtime owner did not return the nested, hoisted, and package-vendor candidates"
    }
    $vendorCandidate = [string]$nativeCandidates[2]
    [IO.Directory]::CreateDirectory((Split-Path -Parent $vendorCandidate)) | Out-Null
    [IO.File]::WriteAllBytes($vendorCandidate, [byte[]]@(0))
    $resolvedVendor = Resolve-AgentBaseCodexNativeExecutable -NpmPrefix $layoutPrefix
    if (-not $resolvedVendor.Equals($vendorCandidate, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Shared Codex runtime owner did not resolve the package-vendor fallback layout"
    }

    $hoistedCandidate = [string]$nativeCandidates[1]
    [IO.Directory]::CreateDirectory((Split-Path -Parent $hoistedCandidate)) | Out-Null
    [IO.File]::WriteAllBytes($hoistedCandidate, [byte[]]@(0))
    $resolvedHoisted = Resolve-AgentBaseCodexNativeExecutable -NpmPrefix $layoutPrefix
    if (-not $resolvedHoisted.Equals($hoistedCandidate, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Shared Codex runtime owner did not prefer the hoisted npm layout over package-vendor fallback"
    }

    $nestedCandidate = [string]$nativeCandidates[0]
    [IO.Directory]::CreateDirectory((Split-Path -Parent $nestedCandidate)) | Out-Null
    [IO.File]::WriteAllBytes($nestedCandidate, [byte[]]@(0))
    $resolvedNested = Resolve-AgentBaseCodexNativeExecutable -NpmPrefix $layoutPrefix
    if (-not $resolvedNested.Equals($nestedCandidate, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Shared Codex runtime owner did not prefer the nested npm layout"
    }

    $shellPolicy = Get-AgentBaseCodexShellEnvironmentPolicy
    if ([string]$shellPolicy.descriptor.sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$shellPolicy.policy.filters.'GIT_*' -ne 'exclude' -or
        $shellPolicy.policy.ignore_default_excludes -ne $false) {
        throw 'Shared Codex shell environment policy identity or filters are invalid'
    }
    $arguments = @(Get-AgentBaseCodexEvaluatorArguments -Model "gpt-5.6-sol" -ReasoningEffort "medium" -ModelCatalogPath $projection.path -SchemaPath $schemaPath -LastMessagePath $messagePath -WorkPath $workPath -ShellPolicySha256 $shellPolicy.descriptor.sha256)
    $disabled = New-Object 'System.Collections.Generic.List[string]'
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        if ($arguments[$index] -eq "--disable") {
            if ($index + 1 -ge $arguments.Count) { throw "Evaluator arguments end with an incomplete feature disable" }
            $disabled.Add($arguments[$index + 1])
        }
    }
    $expectedDisabled = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    if ($disabled.Count -ne $expectedDisabled.Count -or @($disabled | Where-Object { $expectedDisabled -notcontains $_ }).Count -ne 0) {
        throw "Evaluator arguments do not disable the canonical non-evaluation capabilities"
    }
    foreach ($required in @("--strict-config", "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--output-schema", "--json")) {
        if ($arguments -notcontains $required) { throw "Evaluator arguments are missing isolation flag: $required" }
    }
    if ($arguments -notcontains 'analytics.enabled=false') {
        throw "Evaluator arguments do not disable unrelated analytics delivery"
    }
    foreach ($requiredPolicy in @(
        'shell_environment_policy.ignore_default_excludes=false'
        'shell_environment_policy.filters."ALL_PROXY"="exclude"'
        'shell_environment_policy.filters."GIT_*"="exclude"'
        'shell_environment_policy.filters."SSH_*"="exclude"'
    )) {
        if ($arguments -notcontains $requiredPolicy) {
            throw "Evaluator arguments omit shared model-shell isolation: $requiredPolicy"
        }
    }
    $catalogArgument = @($arguments | Where-Object { $_ -like 'model_catalog_json=*' })
    if ($catalogArgument.Count -ne 1 -or $catalogArgument[0].Contains('\')) {
        throw "Evaluator arguments do not carry one TOML-safe sanitized model catalog path"
    }

    $environmentStartInfo = [Diagnostics.ProcessStartInfo]::new()
    $environmentStartInfo.Environment['CODEX_EXISTING_TEST'] = 'remove-me'
    $environmentStartInfo.Environment['OPENAI_API_KEY'] = 'remove-me'
    $environmentOutput = @(Set-AgentBaseCodexEvaluatorEnvironment -StartInfo $environmentStartInfo -CodexHome $testRoot -RuntimeTemp $testRoot)
    if ($environmentOutput.Count -ne 0 -or $environmentStartInfo.Environment.ContainsKey('CODEX_EXISTING_TEST') -or
        $environmentStartInfo.Environment.ContainsKey('OPENAI_API_KEY') -or
        [string]$environmentStartInfo.Environment['CODEX_HOME'] -ne [IO.Path]::GetFullPath($testRoot)) {
        throw "Evaluator environment sanitization leaked output, inherited Codex/OpenAI state, or the wrong home"
    }

    $bounded = Get-AgentBaseBoundedMessage -Text (("A" * 90) + ("Z" * 90)) -MaximumLength 80
    if ($bounded.Length -ne 80 -or -not $bounded.StartsWith("A") -or -not $bounded.EndsWith("Z") -or -not $bounded.Contains(" ... ")) {
        throw "Bounded diagnostics do not preserve both the head and tail"
    }
    $structuredDiagnostic = Get-AgentBaseCodexFailureDiagnostic -StandardOutput '{"type":"error","message":"structured failure"}' -StandardError "" -MaximumLength 120
    if ($structuredDiagnostic -ne "structured failure") {
        throw "Evaluator diagnostics did not recover a JSONL error from stdout"
    }

    $jsonlLines = @(
        ([pscustomobject]@{ type = 'item.completed'; item = [pscustomobject]@{ type = 'command_execution' } } | ConvertTo-Json -Compress)
        ([pscustomobject]@{ type = 'item.completed'; item = [pscustomobject]@{ type = 'mcp_tool_call' } } | ConvertTo-Json -Compress)
        ([pscustomobject]@{
            type = 'turn.completed'
            usage = [pscustomobject]@{
                input_tokens = 120
                cached_input_tokens = 20
                cache_write_input_tokens = 0
                output_tokens = 30
                reasoning_output_tokens = 0
            }
        } | ConvertTo-Json -Compress)
    )
    $jsonlSummary = Get-AgentBaseCodexJsonlSummary -Text ($jsonlLines -join "`n")
    if ($jsonlSummary.event_count -ne 3 -or $jsonlSummary.turn_completed_count -ne 1 -or
        -not $jsonlSummary.usage_complete -or $jsonlSummary.usage.input_tokens -ne 120 -or
        $jsonlSummary.usage.cached_input_tokens -ne 20 -or $jsonlSummary.usage.output_tokens -ne 30 -or
        @($jsonlSummary.tool_event_types).Count -ne 2 -or
        @($jsonlSummary.tool_event_types) -notcontains 'command_execution' -or
        @($jsonlSummary.tool_event_types) -notcontains 'mcp_tool_call') {
        throw 'Shared Codex JSONL parser did not preserve event, tool, or usage evidence'
    }
    $invalidJsonRejected = $false
    try {
        Get-AgentBaseCodexJsonlSummary -Text "not-json" | Out-Null
    }
    catch {
        $invalidJsonRejected = $_.Exception.Message.Contains('non-JSON')
    }
    if (-not $invalidJsonRejected) {
        throw 'Shared Codex JSONL parser accepted non-JSON channel output'
    }
    $negativeUsageRejected = $false
    try {
        Get-AgentBaseCodexJsonlSummary -Text '{"type":"turn.completed","usage":{"input_tokens":-1}}' | Out-Null
    }
    catch {
        $negativeUsageRejected = $_.Exception.Message.Contains('negative input_tokens')
    }
    if (-not $negativeUsageRejected) {
        throw 'Shared Codex JSONL parser accepted negative usage'
    }

    $missingModelRejected = $false
    try {
        New-AgentBaseCodexModelCatalogProjection -SourcePath $sourcePath -DestinationPath (Join-Path $testRoot "missing.json") -Model "missing-model" | Out-Null
    }
    catch {
        $missingModelRejected = $_.Exception.Message.Contains("exactly one entry")
    }
    if (-not $missingModelRejected) {
        throw "Model catalog projection accepted a missing requested model"
    }

    $guardOutputPath = Join-Path $testRoot 'guard-output.json'
    $guardHistoryPath = Join-Path $testRoot 'guard-attempts.json'
    $previousGuard = $env:AGENTBASE_ROUTING_EVALUATOR_DISABLED
    $guardRejected = $false
    try {
        $env:AGENTBASE_ROUTING_EVALUATOR_DISABLED = '1'
        & (Join-Path $PSScriptRoot 'invoke_routing_evaluation.ps1') -Phase Routing -OutputPath $guardOutputPath -ProjectRoot $projectRoot -AttemptHistoryPath $guardHistoryPath | Out-Null
    }
    catch {
        $guardRejected = $_.Exception.Message.Contains('disabled inside the deterministic routing-test boundary')
    }
    finally {
        $env:AGENTBASE_ROUTING_EVALUATOR_DISABLED = $previousGuard
    }
    if (-not $guardRejected -or (Test-Path -LiteralPath $guardOutputPath) -or (Test-Path -LiteralPath $guardHistoryPath)) {
        throw "Deterministic test boundary did not reject evaluator execution before output or Begin"
    }

    Write-Output "Routing evaluator runtime tests passed: native npm layouts, one-model catalog projection, shared model-shell policy, disabled capabilities, strict isolation flags, JSONL evidence parsing, no-model test guard, and head-tail diagnostics are valid."
}
finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $approvedBase = $tempBase.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($approvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $resolved).StartsWith('AgentBase-routing-runtime-test-', [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temporary root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
