[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Routing", "Policy", "References")]
    [string]$Phase,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$ProjectRoot,
    [string]$RoutingResultsPath,
    [string]$AttemptHistoryPath,
    [string]$CodexExecutablePath,
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("low", "medium", "high", "xhigh")]
    [string]$ReasoningEffort = "medium",
    [ValidateRange(1, 60)]
    [int]$TimeoutMinutes = 20,
    [string]$RetryJustification
)

$ErrorActionPreference = "Stop"

if ([string]$env:AGENTBASE_ROUTING_EVALUATOR_DISABLED -eq '1') {
    throw 'Independent evaluator execution is disabled inside the deterministic routing-test boundary'
}

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")
. (Join-Path $PSScriptRoot "routing_evaluator_runtime.ps1")

function Remove-AgentBaseEvaluationTempRoot {
    param(
        [string]$Path,
        [string]$TempBase
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    $resolvedBase = [IO.Path]::GetFullPath($TempBase).TrimEnd('\') + '\'
    $leaf = Split-Path -Leaf $resolved
    if (-not $resolved.StartsWith($resolvedBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not $leaf.StartsWith('AgentBase-routing-eval-', [StringComparison]::Ordinal)) {
        throw "Refusing evaluation cleanup outside the approved temporary root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ($Phase -eq "References") {
    if ([string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
        throw "RoutingResultsPath is required for the References phase"
    }
    $RoutingResultsPath = (Resolve-Path -LiteralPath $RoutingResultsPath).Path
}
elseif (-not [string]::IsNullOrWhiteSpace($RoutingResultsPath)) {
    throw "RoutingResultsPath is not accepted for the $Phase phase"
}
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot "evidence\attempts.json"
}
$AttemptHistoryPath = [IO.Path]::GetFullPath($AttemptHistoryPath)
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory) -or -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Output directory must already exist: $outputDirectory"
}

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$routingResults = if ($Phase -eq "References") {
    Get-Content -LiteralPath $RoutingResultsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
else {
    $null
}
if ($null -ne $routingResults) {
    Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults | Out-Null
}
$capsule = switch ($Phase) {
    "Policy" { Get-AgentBasePolicyEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract }
    "References" { Get-AgentBaseReferenceEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routingResults }
    default { Get-AgentBaseRoutingEvaluationCapsule -ProjectRoot $ProjectRoot -Contract $contract }
}
$outputSchema = Get-AgentBaseRoutingOutputJsonSchema -Phase $Phase -Capsule $capsule
$codexExecutable = Resolve-AgentBaseCodexExecutable -ExplicitPath $CodexExecutablePath
$codexVersion = Get-AgentBaseCodexVersion -ExecutablePath $codexExecutable
$evaluatorId = "agentbase-$($Phase.ToLowerInvariant())-$([guid]::NewGuid().ToString('N'))"
$beginParameters = @{
    Action = 'Begin'
    Phase = $Phase
    ProjectRoot = $ProjectRoot
    AttemptHistoryPath = $AttemptHistoryPath
    EvaluatorId = $evaluatorId
    EvaluatorModel = $Model
}
if ($Phase -eq "References") {
    $beginParameters.RoutingResultsPath = $RoutingResultsPath
}
if (-not [string]::IsNullOrWhiteSpace($RetryJustification)) {
    $beginParameters.RetryJustification = $RetryJustification
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempRoot = Join-Path $tempBase ("AgentBase-routing-eval-{0}" -f [guid]::NewGuid().ToString('N'))
$tempHome = Join-Path $tempRoot "home"
$tempWork = Join-Path $tempRoot "work"
$tempRuntime = Join-Path $tempRoot "runtime"
$schemaPath = Join-Path $tempRoot "output-schema.json"
$lastMessagePath = Join-Path $tempRoot "last-message.json"
$modelCatalogPath = Join-Path $tempRoot "model-catalog.json"
$authLinkPath = Join-Path $tempHome "auth.json"
$authSourcePath = Join-Path $env:USERPROFILE ".codex\auth.json"
$modelCatalogSourcePath = Join-Path $env:USERPROFILE ".codex\models_cache.json"
$temporaryOutputPath = Join-Path $outputDirectory (".{0}.{1}.tmp" -f ([IO.Path]::GetFileName($OutputPath)), [guid]::NewGuid().ToString('N'))
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$finishCalled = $false
$authLock = $null
$authHashBefore = $null
$attemptId = $null
$evaluatorRuntime = $null
$modelCatalog = $null
$processStarted = $false
$process = $null
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
try {
    if ($tempRoot.StartsWith($ProjectRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Detached evaluator work root must be outside the repository"
    }
    if (-not (Test-Path -LiteralPath $authSourcePath -PathType Leaf)) {
        throw "Codex login state is missing; run the user-level Codex CLI login before independent evaluation"
    }
    [IO.Directory]::CreateDirectory($tempHome) | Out-Null
    [IO.Directory]::CreateDirectory($tempWork) | Out-Null
    [IO.Directory]::CreateDirectory($tempRuntime) | Out-Null
    $modelCatalog = New-AgentBaseCodexModelCatalogProjection -SourcePath $modelCatalogSourcePath -DestinationPath $modelCatalogPath -Model $Model
    $authHashBefore = (Get-FileHash -LiteralPath $authSourcePath -Algorithm SHA256).Hash
    New-Item -ItemType HardLink -Path $authLinkPath -Target $authSourcePath -ErrorAction Stop | Out-Null
    $authLock = [IO.File]::Open($authSourcePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    [IO.File]::WriteAllText($schemaPath, ($outputSchema | ConvertTo-Json -Depth 30) + [Environment]::NewLine, $utf8NoBom)

    $evaluatorRuntime = "$codexVersion/windows/read-only/ephemeral/cases-only-v4/catalog-$(([string]$modelCatalog.sha256).Substring(0, 16))"
    $beginParameters.EvaluatorRuntime = $evaluatorRuntime
    $begin = & (Join-Path $PSScriptRoot "record_routing_attempt.ps1") @beginParameters
    $attemptId = [string]$begin.attempt_id

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $codexExecutable
    foreach ($argument in @(Get-AgentBaseCodexEvaluatorArguments -Model $Model -ReasoningEffort $ReasoningEffort -ModelCatalogPath $modelCatalog.path -SchemaPath $schemaPath -LastMessagePath $lastMessagePath -WorkPath $tempWork)) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    $startInfo.WorkingDirectory = $tempWork
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardInputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    Set-AgentBaseCodexEvaluatorEnvironment -StartInfo $startInfo -CodexHome $tempHome -RuntimeTemp $tempRuntime

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Codex evaluator process did not start"
    }
    $processStarted = $true
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $capsuleJson = $capsule.payload | ConvertTo-Json -Depth 20
    $process.StandardInput.Write($capsuleJson)
    $process.StandardInput.Close()
    if (-not $process.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        try { $process.Kill($true) } catch { }
        try { [void]$process.WaitForExit(5000) } catch { }
        throw "Codex evaluator exceeded the $TimeoutMinutes minute phase timeout"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    if ($stdout.Length -gt 5242880 -or $stderr.Length -gt 1048576) {
        throw "Codex evaluator exceeded the bounded diagnostic output contract"
    }
    if ($exitCode -ne 0) {
        $diagnostic = Get-AgentBaseCodexFailureDiagnostic -StandardOutput $stdout -StandardError $stderr
        throw "Codex evaluator exited with code ${exitCode}: $diagnostic"
    }
    if (-not (Test-Path -LiteralPath $lastMessagePath -PathType Leaf)) {
        throw "Codex evaluator did not produce its schema-constrained final result"
    }

    $toolEvents = New-Object 'System.Collections.Generic.List[string]'
    $usage = [ordered]@{ input_tokens = $null; cached_input_tokens = $null; output_tokens = $null }
    foreach ($line in @($stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        try {
            $event = $line | ConvertFrom-Json -Depth 50 -DateKind String
        }
        catch {
            throw "Codex evaluator emitted non-JSON data on its JSONL channel"
        }
        $itemType = [string]$event.item.type
        if ($itemType -in @("command_execution", "mcp_tool_call", "web_search", "file_change", "tool_call", "function_call", "image_generation")) {
            $toolEvents.Add($itemType)
        }
        if ([string]$event.type -eq "turn.completed" -and $null -ne $event.usage) {
            foreach ($field in @("input_tokens", "cached_input_tokens", "output_tokens")) {
                if ($null -ne $event.usage.$field) { $usage[$field] = [long]$event.usage.$field }
            }
        }
    }
    if ($toolEvents.Count -gt 0) {
        throw "Detached evaluator attempted forbidden tool activity: $(@($toolEvents | Sort-Object -Unique) -join ', ')"
    }
    if ($stdout.Contains($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $stderr.Contains($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $stdout.Contains((Join-Path $env:USERPROFILE ".codex\skills"), [StringComparison]::OrdinalIgnoreCase) -or
        $stderr.Contains((Join-Path $env:USERPROFILE ".codex\skills"), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Detached evaluator diagnostics reveal access to a real repository or user skill root"
    }
    $modelOutput = Get-Content -LiteralPath $lastMessagePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    if (@($modelOutput.PSObject.Properties.Name).Count -ne 1 -or -not ($modelOutput.PSObject.Properties.Name -contains "cases")) {
        throw "Codex evaluator result must contain only the cases projection"
    }
    $evaluator = [pscustomobject][ordered]@{
        id = $evaluatorId
        model = $Model
        runtime = $evaluatorRuntime
        evaluated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        isolation_mode = "detached-capsule"
        repository_accessed = $false
        hidden_expectations_accessed = $false
        auth_mode = "read-only-hardlink"
        model_catalog_sha256 = [string]$modelCatalog.sha256
        disabled_features = @(Get-AgentBaseRoutingEvaluatorDisabledFeatures)
    }
    $result = New-AgentBaseRoutingResultEnvelope -Phase $Phase -Capsule $capsule -Evaluator $evaluator -Cases @($modelOutput.cases)
    $authHashAfterEvaluation = (Get-FileHash -LiteralPath $authSourcePath -Algorithm SHA256).Hash
    if ($authHashAfterEvaluation -ne $authHashBefore) {
        throw "Detached evaluator changed the real Codex authentication state"
    }
    [IO.File]::WriteAllText($temporaryOutputPath, ($result | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $utf8NoBom)
    [IO.File]::Move($temporaryOutputPath, $OutputPath, $true)
    $stopwatch.Stop()

    $finishParameters = @{
        Action = 'Finish'
        Phase = $Phase
        ProjectRoot = $ProjectRoot
        AttemptHistoryPath = $AttemptHistoryPath
        AttemptId = $attemptId
        ResultsPath = $OutputPath
        DurationMilliseconds = [long]$stopwatch.ElapsedMilliseconds
    }
    if ($Phase -eq "References") { $finishParameters.RoutingResultsPath = $RoutingResultsPath }
    if ($null -ne $usage.input_tokens) { $finishParameters.InputTokens = [long]$usage.input_tokens }
    if ($null -ne $usage.cached_input_tokens) { $finishParameters.CachedInputTokens = [long]$usage.cached_input_tokens }
    if ($null -ne $usage.output_tokens) { $finishParameters.OutputTokens = [long]$usage.output_tokens }
    $finishCalled = $true
    $finish = & (Join-Path $PSScriptRoot "record_routing_attempt.ps1") @finishParameters

    [pscustomobject][ordered]@{
        phase = $Phase
        action = "evaluated"
        attempt_id = [string]$finish.attempt_id
        result_path = $OutputPath
        evaluator_id = $evaluatorId
        model = $Model
        runtime = $evaluatorRuntime
        duration_ms = [long]$stopwatch.ElapsedMilliseconds
        input_tokens = $usage.input_tokens
        cached_input_tokens = $usage.cached_input_tokens
        output_tokens = $usage.output_tokens
        case_count = @($modelOutput.cases).Count
    } | ConvertTo-Json -Compress
}
catch {
    $originalError = $_
    $stopwatch.Stop()
    if (-not $finishCalled -and -not [string]::IsNullOrWhiteSpace($attemptId)) {
        $failure = Get-AgentBaseBoundedMessage $originalError.Exception.Message
        $finishFailureParameters = @{
            Action = 'Finish'
            Phase = $Phase
            ProjectRoot = $ProjectRoot
            AttemptHistoryPath = $AttemptHistoryPath
            AttemptId = $attemptId
            DurationMilliseconds = [long]$stopwatch.ElapsedMilliseconds
        }
        $failureClass = if ($processStarted) { 'execution_failed' } else { 'orchestration_failed' }
        if ($processStarted) {
            $finishFailureParameters.ExecutionFailureSummary = $failure
        }
        else {
            $finishFailureParameters.OrchestrationFailureSummary = $failure
        }
        if ($Phase -eq "References") { $finishFailureParameters.RoutingResultsPath = $RoutingResultsPath }
        $finishCalled = $true
        try {
            & (Join-Path $PSScriptRoot "record_routing_attempt.ps1") @finishFailureParameters | Out-Null
        }
        catch {
            $expectedPrefix = "Recorded failed $Phase attempt $attemptId ($failureClass):"
            if (-not $_.Exception.Message.StartsWith($expectedPrefix, [StringComparison]::Ordinal)) {
                throw "Evaluator failed and its attempt could not be finalized: $failure; recorder: $($_.Exception.Message)"
            }
        }
    }
    throw $originalError
}
finally {
    if ($null -ne $process) {
        if ($processStarted -and -not $process.HasExited) {
            try { $process.Kill($true) } catch { }
            try { [void]$process.WaitForExit(5000) } catch { }
        }
        $process.Dispose()
    }
    if ($null -ne $authLock) {
        $authLock.Dispose()
    }
    $authChanged = $false
    if ((Test-Path -LiteralPath $authSourcePath -PathType Leaf) -and $null -ne $authHashBefore) {
        $authHashAfter = (Get-FileHash -LiteralPath $authSourcePath -Algorithm SHA256).Hash
        if ($authHashAfter -ne $authHashBefore) {
            $authChanged = $true
        }
    }
    if (Test-Path -LiteralPath $temporaryOutputPath) {
        [IO.File]::Delete($temporaryOutputPath)
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-AgentBaseEvaluationTempRoot -Path $tempRoot -TempBase $tempBase
    }
    if ($authChanged) {
        throw "Detached evaluator changed the real Codex authentication state"
    }
}
