[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [ValidateSet("Model", "Machine")]
    [string]$View = "Model",
    [ValidateRange(10, 600)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$startedAt = [DateTimeOffset]::UtcNow

function Get-AgentBaseTestDiagnostic {
    param(
        [AllowEmptyString()]
        [string]$Text,
        [int]$MaximumLength = 1200
    )

    $value = $Text.Trim()
    if ($value.Length -le $MaximumLength) {
        return $value
    }
    $half = [Math]::Floor(($MaximumLength - 32) / 2)
    return $value.Substring(0, $half) + "`n... output omitted ...`n" + $value.Substring($value.Length - $half)
}

$scriptFiles = @(
    @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File)
    Get-Item -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'common\codex_cli_runtime.ps1')
) | Sort-Object FullName -Unique
$parseFailures = New-Object 'System.Collections.Generic.List[string]'
foreach ($scriptFile in $scriptFiles) {
    $tokens = $null
    $parseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($scriptFile.FullName, [ref]$tokens, [ref]$parseErrors)
    foreach ($parseError in @($parseErrors)) {
        $parseFailures.Add("$($scriptFile.Name): $($parseError.Message)")
    }
}
if ($parseFailures.Count -gt 0) {
    throw "Routing infrastructure syntax validation failed: $($parseFailures -join '; ')"
}

& (Join-Path $PSScriptRoot 'validate_contract.ps1') -ProjectRoot $ProjectRoot | Out-Null

$suiteNames = @(
    'test_routing_fingerprint.ps1'
    'test_routing_capsule.ps1'
    'test_routing_evaluation_plan.ps1'
    'test_routing_evaluator_runtime.ps1'
    'test_routing_attempt_history.ps1'
    'test_routing_refresh_recovery.ps1'
)
$pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
$runners = New-Object 'System.Collections.Generic.List[object]'
$failures = New-Object 'System.Collections.Generic.List[string]'
try {
    foreach ($suiteName in $suiteNames) {
        $suitePath = Join-Path $PSScriptRoot $suiteName
        if (-not (Test-Path -LiteralPath $suitePath -PathType Leaf)) {
            throw "Routing infrastructure suite is missing: $suitePath"
        }
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $pwshPath
        foreach ($argument in @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $suitePath)) {
            $startInfo.ArgumentList.Add([string]$argument)
        }
        $startInfo.WorkingDirectory = $ProjectRoot
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
        $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
        $startInfo.Environment['AGENTBASE_ROUTING_EVALUATOR_DISABLED'] = '1'
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            $process.Dispose()
            throw "Routing infrastructure suite did not start: $suiteName"
        }
        $runners.Add([pscustomobject]@{
            name = $suiteName
            process = $process
            stdout_task = $process.StandardOutput.ReadToEndAsync()
            stderr_task = $process.StandardError.ReadToEndAsync()
            deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
        })
    }

    foreach ($runner in $runners) {
        $remaining = [int][Math]::Max(0, [Math]::Ceiling(($runner.deadline - [DateTimeOffset]::UtcNow).TotalMilliseconds))
        $timedOut = $remaining -eq 0 -or -not $runner.process.WaitForExit($remaining)
        if ($timedOut) {
            try { $runner.process.Kill($true) } catch { }
            try { $runner.process.WaitForExit() } catch { }
        }
        $stdout = $runner.stdout_task.GetAwaiter().GetResult()
        $stderr = $runner.stderr_task.GetAwaiter().GetResult()
        if ($timedOut) {
            $failures.Add("$($runner.name): timed out after $TimeoutSeconds seconds")
        }
        elseif ($stdout.Length -gt 1048576 -or $stderr.Length -gt 1048576) {
            $failures.Add("$($runner.name): output exceeded the 1 MiB bound")
        }
        elseif ($runner.process.ExitCode -ne 0) {
            $diagnostic = Get-AgentBaseTestDiagnostic -Text (($stderr + [Environment]::NewLine + $stdout).Trim())
            $failures.Add("$($runner.name): exit $($runner.process.ExitCode): $diagnostic")
        }
    }
}
finally {
    foreach ($runner in $runners) {
        if (-not $runner.process.HasExited) {
            try { $runner.process.Kill($true) } catch { }
        }
        $runner.process.Dispose()
    }
}

if ($failures.Count -gt 0) {
    throw "Routing evaluation infrastructure failed $($failures.Count) suite(s):$([Environment]::NewLine)$($failures -join [Environment]::NewLine)"
}

$result = [pscustomobject][ordered]@{
    ready = $true
    suite_count = $suiteNames.Count
    syntax_file_count = $scriptFiles.Count
    elapsed_ms = [long]([DateTimeOffset]::UtcNow - $startedAt).TotalMilliseconds
    model_evaluator_runs = 0
}
if ($View -eq 'Machine') {
    $result | ConvertTo-Json -Depth 5 -Compress
}
else {
    Write-Output "ready=true suites=$($result.suite_count) syntax_files=$($result.syntax_file_count) model_evaluator_runs=0 elapsed_ms=$($result.elapsed_ms)"
}
