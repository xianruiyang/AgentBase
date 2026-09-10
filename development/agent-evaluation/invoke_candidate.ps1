[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$InstalledCodexRoot,
    [string]$RuntimeCodexRoot = '',
    [Parameter(Mandatory = $true)]
    [string]$PromptPath,
    [Parameter(Mandatory = $true)]
    [string]$ResultPath,
    [Parameter(Mandatory = $true)]
    [string]$Model,
    [Parameter(Mandatory = $true)]
    [string]$ReasoningEffort,
    [Parameter(Mandatory = $true)]
    [string]$CodexExecutablePath,
    [string]$TaskRuntimeBinPath = '',
    [string[]]$ConfigOverride = @(),
    [switch]$EnableHooks,
    [string]$ResultSchema = 'agentbase.windows-swe-codex-run/v8',
    [ValidateRange(60, 14400)]
    [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedWorkspace = (Resolve-Path -LiteralPath $Workspace).Path
$resolvedCodexRoot = (Resolve-Path -LiteralPath $InstalledCodexRoot).Path
$declaredRuntimeCodexRoot = if ([string]::IsNullOrWhiteSpace($RuntimeCodexRoot)) {
    $resolvedCodexRoot
}
else {
    [IO.Path]::GetFullPath($RuntimeCodexRoot)
}
$resolvedRuntimeCodexRoot = if ([string]::IsNullOrWhiteSpace($RuntimeCodexRoot)) {
    $resolvedCodexRoot
}
else {
    (Resolve-Path -LiteralPath $RuntimeCodexRoot).Path
}
$resolvedPrompt = (Resolve-Path -LiteralPath $PromptPath).Path
$resolvedCodex = (Resolve-Path -LiteralPath $CodexExecutablePath).Path
$resolvedTaskRuntimeBin = if ([string]::IsNullOrWhiteSpace($TaskRuntimeBinPath)) {
    ''
}
else {
    (Resolve-Path -LiteralPath $TaskRuntimeBinPath).Path
}
$resolvedResult = [IO.Path]::GetFullPath($ResultPath)
$expectedEvoRuntimeRoot = Join-Path (Split-Path -Parent $resolvedResult) 'codex-runtime-home'
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

function Invoke-AgentBaseBoundedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$CodexHome,
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$RuntimeBin,
        [Parameter(Mandatory = $true)]
        [string]$StartedMarkerPath,
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$StandardInput,
        [Parameter(Mandatory = $true)]
        [int]$Timeout
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardInputEncoding = $utf8NoBom
    $startInfo.StandardOutputEncoding = $utf8NoBom
    $startInfo.StandardErrorEncoding = $utf8NoBom
    $startInfo.Environment['CODEX_HOME'] = $CodexHome
    $startInfo.Environment['CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED'] = '1'
    if (-not [string]::IsNullOrWhiteSpace($RuntimeBin)) {
        $currentPath = [string]$startInfo.Environment['PATH']
        $startInfo.Environment['PATH'] = if ([string]::IsNullOrWhiteSpace($currentPath)) {
            $RuntimeBin
        }
        else {
            $RuntimeBin + [IO.Path]::PathSeparator + $currentPath
        }
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $stdoutTask = $null
    $stderrTask = $null
    $started = [DateTimeOffset]::UtcNow
    try {
        if (-not $process.Start()) {
            throw 'Codex candidate process did not start'
        }
        [IO.File]::WriteAllText($StartedMarkerPath, 'started' + [Environment]::NewLine, $utf8NoBom)
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write($StandardInput)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($Timeout * 1000)) {
            $process.Kill($true)
            $process.WaitForExit()
            throw "Codex candidate timed out after $Timeout seconds"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject][ordered]@{
            exit_code = $process.ExitCode
            stdout = $stdout
            stderr = $stderr
            duration_seconds = [Math]::Round(
                ([DateTimeOffset]::UtcNow - $started).TotalSeconds,
                3
            )
        }
    }
    finally {
        $process.Dispose()
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $resolvedRuntimeCodexRoot 'auth.json') -PathType Leaf)) {
    throw 'Codex runtime root has no auth.json'
}
if (-not (Test-Path -LiteralPath (Join-Path $resolvedWorkspace '.codex\config.toml') -PathType Leaf)) {
    throw 'Candidate workspace has no projected .codex/config.toml'
}
if (-not [string]::IsNullOrWhiteSpace($resolvedTaskRuntimeBin) -and
    (Get-Item -LiteralPath $resolvedTaskRuntimeBin -Force).PSIsContainer -ne $true) {
    throw 'Candidate task runtime bin is not a directory'
}

$identity = [pscustomobject][ordered]@{
    path = $resolvedCodex
    version = Get-AgentBaseCodexVersion -ExecutablePath $resolvedCodex
    sha256 = (Get-FileHash -LiteralPath $resolvedCodex -Algorithm SHA256).Hash.ToLowerInvariant()
}
$logRoot = Join-Path (Split-Path -Parent $resolvedResult) 'codex-logs'
[IO.Directory]::CreateDirectory($logRoot) | Out-Null
$lastMessagePath = Join-Path $logRoot 'last-message.txt'
$stdoutPath = Join-Path $logRoot 'events.jsonl'
$stderrPath = Join-Path $logRoot 'stderr.txt'
$startedMarkerPath = Join-Path $logRoot 'model-process-started.txt'
$projectTrustKey = ConvertTo-AgentBaseCodexTomlString ($resolvedWorkspace.ToLowerInvariant())

$arguments = New-Object 'System.Collections.Generic.List[string]'
foreach ($argument in @(
    'exec'
    '--ignore-user-config'
    '--model'
    $Model
    '--sandbox'
    'danger-full-access'
    '-c'
    "model_reasoning_effort=$(ConvertTo-AgentBaseCodexTomlString $ReasoningEffort)"
    '-c'
    'approval_policy="never"'
    '-c'
    'analytics.enabled=false'
    '-c'
    "projects={$projectTrustKey={trust_level=`"trusted`"}}"
)) {
    $arguments.Add([string]$argument)
}
if ($EnableHooks) {
    $arguments.Add('--dangerously-bypass-hook-trust')
}
else {
    $arguments.Add('-c')
    $arguments.Add('features.hooks=false')
}
foreach ($override in $ConfigOverride) {
    if ([string]::IsNullOrWhiteSpace($override)) {
        throw 'Candidate config override must not be empty'
    }
    $arguments.Add('-c')
    $arguments.Add([string]$override)
}
foreach ($argument in @(
    '--strict-config'
    '--ignore-rules'
    '--skip-git-repo-check'
    '--output-last-message'
    $lastMessagePath
    '--json'
    '--color'
    'never'
    '--cd'
    $resolvedWorkspace
    '-'
)) {
    $arguments.Add([string]$argument)
}

$promptItem = Get-Item -LiteralPath $resolvedPrompt -Force
if ($promptItem.Length -le 0 -or $promptItem.Length -gt 2097152) {
    throw 'Candidate prompt must be a bounded non-empty file'
}
$prompt = [IO.File]::ReadAllText($resolvedPrompt, [Text.Encoding]::UTF8)
try {
    $codexProcess = Invoke-AgentBaseBoundedProcess `
        -Executable $resolvedCodex `
        -Arguments $arguments.ToArray() `
        -WorkingDirectory $resolvedWorkspace `
        -CodexHome $resolvedRuntimeCodexRoot `
        -RuntimeBin $resolvedTaskRuntimeBin `
        -StartedMarkerPath $startedMarkerPath `
        -StandardInput $prompt `
        -Timeout $TimeoutSeconds
}
catch {
    if (-not (Test-Path -LiteralPath $startedMarkerPath -PathType Leaf)) {
        Write-AgentBaseJson -Path $resolvedResult -Value ([ordered]@{
            schema = $ResultSchema
            status = 'precondition_failed'
            model_invoked = $false
            execution_environment = 'trusted-local-workspace'
            diagnostic = ([string]$_.Exception.Message)
        })
        exit 2
    }
    throw
}
finally {
    if ($resolvedRuntimeCodexRoot -ne $resolvedCodexRoot) {
        $runtimeItem = Get-Item -LiteralPath $declaredRuntimeCodexRoot -Force -ErrorAction SilentlyContinue
        $isExpectedRuntime = [string]::Equals(
            $declaredRuntimeCodexRoot,
            $expectedEvoRuntimeRoot,
            [StringComparison]::OrdinalIgnoreCase
        )
        $isReparsePoint = $null -ne $runtimeItem -and
            ($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        if ($isExpectedRuntime -and -not $isReparsePoint) {
            Remove-Item -LiteralPath (Join-Path $declaredRuntimeCodexRoot 'auth.json') -Force -ErrorAction SilentlyContinue
        }
    }
}
if (([string]$codexProcess.stdout).Length -gt 16777216 -or
    ([string]$codexProcess.stderr).Length -gt 2097152) {
    throw 'Codex candidate exceeded the bounded diagnostic output contract'
}
[IO.File]::WriteAllText($stdoutPath, [string]$codexProcess.stdout, $utf8NoBom)
[IO.File]::WriteAllText($stderrPath, [string]$codexProcess.stderr, $utf8NoBom)
$jsonlSummary = Get-AgentBaseCodexJsonlSummary -Text ([string]$codexProcess.stdout)
$diagnosticText = (([string]$codexProcess.stderr + "`n" + [string]$codexProcess.stdout).Trim())
if ($diagnosticText.Length -gt 800) {
    $diagnosticText = $diagnosticText.Substring(0, 400) +
        ' ... ' +
        $diagnosticText.Substring($diagnosticText.Length - 395)
}
$threadObserved = $jsonlSummary.thread_started_count -gt 0 -and
    -not [string]::IsNullOrWhiteSpace([string]$jsonlSummary.thread_id)
$knownConfigPrecondition = -not $threadObserved -and
    $diagnosticText -match 'agents\.max_concurrent_threads_per_session must be at least 1'
$modelInvoked = if ($threadObserved) { $true } elseif ($knownConfigPrecondition) { $false } else { $null }
$overrideBytes = [Text.Encoding]::UTF8.GetBytes(($ConfigOverride -join "`n"))
$overrideHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($overrideBytes)
).ToLowerInvariant()
$result = [ordered]@{
    schema = $ResultSchema
    status = if ($codexProcess.exit_code -eq 0) {
        'completed'
    }
    elseif ($knownConfigPrecondition) {
        'precondition_failed'
    }
    else {
        'failed'
    }
    process_started = $true
    model_invoked = $modelInvoked
    execution_environment = 'trusted-local-workspace'
    exit_code = $codexProcess.exit_code
    duration_seconds = $codexProcess.duration_seconds
    diagnostic = $diagnosticText
    codex = $identity
    config_override_sha256 = $overrideHash
    event_count = $jsonlSummary.event_count
    thread_started_count = $jsonlSummary.thread_started_count
    root_thread_id = $jsonlSummary.thread_id
    turn_completed_count = $jsonlSummary.turn_completed_count
    usage_scope = 'root-thread-only'
    root_usage_complete = $jsonlSummary.usage_complete
    root_usage = $jsonlSummary.usage
    usage_complete = $jsonlSummary.usage_complete
    usage = $jsonlSummary.usage
    agent_usage = @()
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
Write-AgentBaseJson -Path $resolvedResult -Value $result
if ($codexProcess.exit_code -ne 0) {
    exit $codexProcess.exit_code
}
