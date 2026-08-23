[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$CurrentEvidencePath,
    [string]$AttemptHistoryPath,
    [string]$CodexExecutablePath,
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("low", "medium", "high", "xhigh")]
    [string]$ReasoningEffort = "medium",
    [ValidateRange(1, 60)]
    [int]$TimeoutMinutes = 20,
    [string]$RoutingRetryJustification,
    [string]$PolicyRetryJustification,
    [string]$ReferencesRetryJustification
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "routing_evaluation_common.ps1")
. (Join-Path $PSScriptRoot "routing_evaluator_runtime.ps1")
. (Join-Path $PSScriptRoot "routing_attempt_history.ps1")

function Write-AgentBaseStageFile {
    param(
        [string]$Path,
        [object]$Value
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    $directory = Split-Path -Parent $resolved
    if ([string]::IsNullOrWhiteSpace($directory) -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Stage evidence directory must already exist: $directory"
    }
    $temporaryPath = Join-Path $directory ('.{0}.{1}.tmp' -f ([IO.Path]::GetFileName($resolved)), [guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::WriteAllText($temporaryPath, ($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporaryPath, $resolved, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) { [IO.File]::Delete($temporaryPath) }
    }
}

function Copy-AgentBaseStageFile {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    $resolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
    $resolvedTarget = [IO.Path]::GetFullPath($TargetPath)
    $directory = Split-Path -Parent $resolvedTarget
    if ([string]::IsNullOrWhiteSpace($directory) -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Stage evidence directory must already exist: $directory"
    }
    $temporaryPath = Join-Path $directory ('.{0}.{1}.tmp' -f ([IO.Path]::GetFileName($resolvedTarget)), [guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::Copy($resolvedSource, $temporaryPath, $true)
        [IO.File]::Move($temporaryPath, $resolvedTarget, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) { [IO.File]::Delete($temporaryPath) }
    }
}

function Start-AgentBasePhaseRunner {
    param(
        [string]$PhaseName,
        [string]$ResultPath,
        [string]$RoutingPath,
        [string]$RetryJustification
    )

    $pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pwshPath
    foreach ($argument in @(
        "-NoLogo", "-NoProfile", "-NonInteractive",
        "-File", (Join-Path $PSScriptRoot "invoke_routing_evaluation.ps1"),
        "-Phase", $PhaseName,
        "-OutputPath", $ResultPath,
        "-ProjectRoot", $ProjectRoot,
        "-AttemptHistoryPath", $AttemptHistoryPath,
        "-Model", $Model,
        "-ReasoningEffort", $ReasoningEffort,
        "-TimeoutMinutes", [string]$TimeoutMinutes
    )) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    if (-not [string]::IsNullOrWhiteSpace($RoutingPath)) {
        $startInfo.ArgumentList.Add("-RoutingResultsPath")
        $startInfo.ArgumentList.Add($RoutingPath)
    }
    if (-not [string]::IsNullOrWhiteSpace($CodexExecutablePath)) {
        $startInfo.ArgumentList.Add("-CodexExecutablePath")
        $startInfo.ArgumentList.Add([IO.Path]::GetFullPath($CodexExecutablePath))
    }
    if (-not [string]::IsNullOrWhiteSpace($RetryJustification)) {
        $startInfo.ArgumentList.Add("-RetryJustification")
        $startInfo.ArgumentList.Add($RetryJustification)
    }
    $startInfo.WorkingDirectory = $ProjectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "$PhaseName evaluator wrapper did not start"
    }
    return [pscustomobject]@{
        phase = $PhaseName
        process = $process
        stdout_task = $process.StandardOutput.ReadToEndAsync()
        stderr_task = $process.StandardError.ReadToEndAsync()
    }
}

function Complete-AgentBasePhaseRunner {
    param(
        [object]$Runner
    )

    $maximumWait = ($TimeoutMinutes + 2) * 60 * 1000
    if (-not $Runner.process.WaitForExit($maximumWait)) {
        try { $Runner.process.Kill($true) } catch { }
        throw "$($Runner.phase) evaluator wrapper exceeded its bounded wait"
    }
    $stdout = $Runner.stdout_task.GetAwaiter().GetResult()
    $stderr = $Runner.stderr_task.GetAwaiter().GetResult()
    $exitCode = $Runner.process.ExitCode
    $Runner.process.Dispose()
    if ($stdout.Length -gt 1048576 -or $stderr.Length -gt 1048576) {
        throw "$($Runner.phase) evaluator wrapper exceeded its bounded output"
    }
    if ($exitCode -ne 0) {
        $message = Get-AgentBaseBoundedMessage -Text $stderr -MaximumLength 700
        throw "$($Runner.phase) evaluator wrapper failed with exit code ${exitCode}: $message"
    }
    $lines = @($stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -ne 1) {
        throw "$($Runner.phase) evaluator wrapper did not return exactly one machine receipt"
    }
    return $lines[0] | ConvertFrom-Json -Depth 30 -DateKind String
}

function Invoke-AgentBaseReuseReceipt {
    param(
        [string]$PhaseName,
        [string]$RoutingPath
    )

    $parameters = @{
        Action = 'Reuse'
        Phase = $PhaseName
        ProjectRoot = $ProjectRoot
        SourceEvidencePath = $CurrentEvidencePath
        AttemptHistoryPath = $AttemptHistoryPath
    }
    if ($PhaseName -eq "References") {
        $parameters.RoutingResultsPath = $RoutingPath
    }
    return & (Join-Path $PSScriptRoot "record_routing_attempt.ps1") @parameters
}

function Resolve-AgentBasePendingReceipt {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$PhaseName,
        [string]$ResultPath,
        [string]$RoutingPath
    )

    if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
        return $null
    }
    if ($PhaseName -eq "References" -and -not (Test-Path -LiteralPath $RoutingPath -PathType Leaf)) {
        return $null
    }
    try {
        $results = Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        $routing = if ($PhaseName -eq "References") {
            Get-Content -LiteralPath $RoutingPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        }
        else {
            $null
        }
        switch ($PhaseName) {
            "Policy" { Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -PolicyResults $results | Out-Null }
            "References" { Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing -ReferenceResults $results | Out-Null }
            default { Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $results | Out-Null }
        }
    }
    catch {
        return $null
    }

    $history = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
    if ($null -eq $history -or [string]$history.active_cycle_id -ne [string]$initialPlan.evaluation_generation_sha256) {
        return $null
    }
    $semanticHash = Get-AgentBaseStageSemanticResultFingerprint -Phase $PhaseName -Results $results
    $fileHash = (Get-FileHash -LiteralPath $ResultPath -Algorithm SHA256).Hash
    $matching = @($history.attempts | Where-Object {
        [string]$_.phase -eq $PhaseName -and
        [string]$_.outcome -eq 'passed' -and
        [string]$_.stage_result_sha256 -eq $semanticHash -and
        [string]$_.evaluator_id -eq [string]$results.evaluator.id -and
        [string]$_.candidate_bundle_sha256 -eq [string]$results.candidate_bundle_sha256 -and
        [string]$_.evaluation_input_sha256 -eq [string]$results.evaluation_input_sha256 -and
        [string]$_.evaluation_capsule_sha256 -eq [string]$results.evaluation_capsule_sha256 -and
        (([string]$_.origin -eq 'evidence_reuse') -or [string]$_.result_sha256 -eq $fileHash)
    })
    if ($matching.Count -gt 1) {
        throw "$PhaseName pending result matches more than one passed receipt"
    }
    if ($matching.Count -eq 0) {
        $failedMatching = @($history.attempts | Where-Object {
            [string]$_.phase -eq $PhaseName -and
            [string]$_.outcome -eq 'failed' -and
            [string]$_.failure_class -eq 'oracle_violation' -and
            [string]$_.result_sha256 -eq $fileHash -and
            [string]$_.evaluator_id -eq [string]$results.evaluator.id -and
            [string]$_.candidate_bundle_sha256 -eq [string]$results.candidate_bundle_sha256 -and
            [string]$_.evaluation_input_sha256 -eq [string]$results.evaluation_input_sha256 -and
            [string]$_.evaluation_capsule_sha256 -eq [string]$results.evaluation_capsule_sha256
        })
        if ($failedMatching.Count -gt 1) {
            throw "$PhaseName pending result matches more than one oracle-violation receipt"
        }
        if ($failedMatching.Count -eq 0) {
            return $null
        }
        $parameters = @{
            Action = 'Revalidate'
            Phase = $PhaseName
            ResultsPath = $ResultPath
            ProjectRoot = $ProjectRoot
            AttemptHistoryPath = $AttemptHistoryPath
        }
        if ($PhaseName -eq 'References') {
            $parameters.RoutingResultsPath = $RoutingPath
        }
        $receipt = & (Join-Path $PSScriptRoot 'record_routing_attempt.ps1') @parameters
        $receipt | Add-Member -NotePropertyName action -NotePropertyValue 'oracle-revalidated' -Force
        $receipt | Add-Member -NotePropertyName result_path -NotePropertyValue ([IO.Path]::GetFullPath($ResultPath)) -Force
        $receipt | Add-Member -NotePropertyName evaluator_id -NotePropertyValue ([string]$results.evaluator.id) -Force
        $receipt | Add-Member -NotePropertyName model -NotePropertyValue ([string]$results.evaluator.model) -Force
        $receipt | Add-Member -NotePropertyName runtime -NotePropertyValue ([string]$results.evaluator.runtime) -Force
        $receipt | Add-Member -NotePropertyName duration_ms -NotePropertyValue 0 -Force
        $receipt | Add-Member -NotePropertyName input_tokens -NotePropertyValue 0 -Force
        $receipt | Add-Member -NotePropertyName cached_input_tokens -NotePropertyValue 0 -Force
        $receipt | Add-Member -NotePropertyName output_tokens -NotePropertyValue 0 -Force
        $receipt | Add-Member -NotePropertyName case_count -NotePropertyValue @($results.cases).Count -Force
        return $receipt
    }
    $receipt = $matching[0]
    return [pscustomobject][ordered]@{
        phase = $PhaseName
        action = "recovered"
        attempt_id = [string]$receipt.attempt_id
        result_path = [IO.Path]::GetFullPath($ResultPath)
        evaluator_id = [string]$receipt.evaluator_id
        model = [string]$receipt.evaluator_model
        runtime = [string]$receipt.evaluator_runtime
        duration_ms = [long]$receipt.duration_ms
        input_tokens = [long]$receipt.input_tokens
        cached_input_tokens = [long]$receipt.cached_input_tokens
        output_tokens = [long]$receipt.output_tokens
        case_count = @($results.cases).Count
    }
}

function Invoke-AgentBaseCarryForwardReceipt {
    param(
        [ValidateSet("Routing", "Policy", "References")]
        [string]$PhaseName,
        [string]$SourcePath,
        [string]$TargetPath,
        [string]$SourceHistoryPath,
        [string]$RoutingPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $SourceHistoryPath -PathType Leaf) -or
        ($PhaseName -eq "References" -and -not (Test-Path -LiteralPath $RoutingPath -PathType Leaf))) {
        return $null
    }
    try {
        $source = Get-Content -LiteralPath $SourcePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        $routing = if ($PhaseName -eq "References") {
            Get-Content -LiteralPath $RoutingPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
        }
        else {
            $null
        }
        switch ($PhaseName) {
            "Policy" { Assert-AgentBasePolicyEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -PolicyResults $source | Out-Null }
            "References" { Assert-AgentBaseReferenceEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $routing -ReferenceResults $source | Out-Null }
            default { Assert-AgentBaseRoutingEvaluationResults -ProjectRoot $ProjectRoot -Contract $contract -RoutingResults $source | Out-Null }
        }
    }
    catch {
        return $null
    }
    Copy-AgentBaseStageFile -SourcePath $SourcePath -TargetPath $TargetPath
    $parameters = @{
        Action = "CarryForward"
        ProjectRoot = $ProjectRoot
        Phase = $PhaseName
        SourceStagePath = $TargetPath
        SourceAttemptHistoryPath = $SourceHistoryPath
        AttemptHistoryPath = $AttemptHistoryPath
    }
    if ($PhaseName -eq "References") { $parameters.RoutingResultsPath = $RoutingPath }
    $receipt = & (Join-Path $PSScriptRoot "record_routing_attempt.ps1") @parameters
    $action = if ([string]$receipt.origin -eq 'oracle_revalidation') { 'oracle-revalidated' } else { 'carried-forward' }
    $receipt | Add-Member -NotePropertyName action -NotePropertyValue $action -Force
    $receipt | Add-Member -NotePropertyName result_path -NotePropertyValue ([IO.Path]::GetFullPath($TargetPath)) -Force
    return $receipt
}

function Remove-AgentBasePendingGeneration {
    param(
        [string]$Path,
        [string]$PendingBase
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    $resolvedBase = [IO.Path]::GetFullPath($PendingBase).TrimEnd('\') + '\'
    $leaf = Split-Path -Leaf $resolved
    if (-not $resolved.StartsWith($resolvedBase, [StringComparison]::OrdinalIgnoreCase) -or $leaf -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "Refusing pending-evidence cleanup outside the managed generation root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        [IO.Directory]::Delete($resolved, $true)
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($CurrentEvidencePath)) {
    $CurrentEvidencePath = Join-Path $PSScriptRoot "evidence\current.json"
}
$CurrentEvidencePath = [IO.Path]::GetFullPath($CurrentEvidencePath)
if ([string]::IsNullOrWhiteSpace($AttemptHistoryPath)) {
    $AttemptHistoryPath = Join-Path $PSScriptRoot "evidence\attempts.json"
}
$AttemptHistoryPath = [IO.Path]::GetFullPath($AttemptHistoryPath)

& (Join-Path $PSScriptRoot "validate_contract.ps1") -ProjectRoot $ProjectRoot | Out-Null
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot "trigger-cases.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$sourceEvidence = if (Test-Path -LiteralPath $CurrentEvidencePath -PathType Leaf) {
    Get-Content -LiteralPath $CurrentEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
}
else {
    $null
}
$initialPlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $ProjectRoot -Contract $contract -SourceEvidence $sourceEvidence
$evidenceDirectory = Split-Path -Parent $CurrentEvidencePath
if ([string]::IsNullOrWhiteSpace($evidenceDirectory) -or -not (Test-Path -LiteralPath $evidenceDirectory -PathType Container)) {
    throw "Current evidence directory must already exist: $evidenceDirectory"
}
$pendingBase = Join-Path $evidenceDirectory "pending"
$pendingRoot = Join-Path $pendingBase ([string]$initialPlan.evaluation_generation_sha256)
if ([int]$initialPlan.blocked_count -gt 0) {
    $blocked = @($initialPlan.phases.PSObject.Properties | Where-Object { [string]$_.Value.action -eq 'blocked' } | ForEach-Object { "$($_.Name):$($_.Value.reason)" })
    throw "Independent evidence refresh is blocked without a new evaluator run because visible input is unchanged but the current oracle rejects the prior result: $($blocked -join ', ')"
}
if ([int]$initialPlan.evaluation_count -eq 0 -and [int]$initialPlan.pending_count -eq 0 -and
    $null -ne $sourceEvidence -and [string]$sourceEvidence.evaluation_generation_sha256 -eq [string]$initialPlan.evaluation_generation_sha256) {
    & (Join-Path $PSScriptRoot "validate_routing_results.ps1") -ProjectRoot $ProjectRoot -ResultsPath $CurrentEvidencePath | Out-Null
    & (Join-Path $PSScriptRoot "validate_routing_attempt_history.ps1") -ProjectRoot $ProjectRoot -AttemptHistoryPath $AttemptHistoryPath -CurrentEvidencePath $CurrentEvidencePath | Out-Null
    if (Test-Path -LiteralPath $pendingRoot) {
        Remove-AgentBasePendingGeneration -Path $pendingRoot -PendingBase $pendingBase
    }
    [pscustomobject][ordered]@{
        action = "already-current"
        evaluation_generation_sha256 = [string]$initialPlan.evaluation_generation_sha256
        evaluator_run_count = 0
        reused_phase_count = 0
        current_evidence_path = $CurrentEvidencePath
    }
    return
}

$stagePaths = [ordered]@{
    Routing = Join-Path $pendingRoot "routing.json"
    Policy = Join-Path $pendingRoot "policy.json"
    References = Join-Path $pendingRoot "references.json"
}
$receipts = @{}
$runResults = New-Object 'System.Collections.Generic.List[object]'
$recoveredResults = New-Object 'System.Collections.Generic.List[object]'
$revalidatedResults = New-Object 'System.Collections.Generic.List[object]'
$carriedResults = New-Object 'System.Collections.Generic.List[object]'
$refreshSucceeded = $false
try {
    [IO.Directory]::CreateDirectory($pendingBase) | Out-Null
    [IO.Directory]::CreateDirectory($pendingRoot) | Out-Null
    $carrySourceRoot = $null
    $carrySourceHistoryPath = $null
    $carryHistorySnapshotPath = Join-Path $pendingRoot 'source-attempts.json'
    $historyBeforeRefresh = Read-AgentBaseRoutingAttemptHistory -Path $AttemptHistoryPath
    if ($null -ne $historyBeforeRefresh -and
        [string]$historyBeforeRefresh.active_cycle_id -ne [string]$initialPlan.evaluation_generation_sha256 -and
        @($historyBeforeRefresh.attempts | Where-Object { [string]$_.outcome -eq 'started' }).Count -eq 0) {
        $candidateSourceRoot = Join-Path $pendingBase ([string]$historyBeforeRefresh.active_cycle_id)
        if (Test-Path -LiteralPath $candidateSourceRoot -PathType Container) {
            $carrySourceRoot = $candidateSourceRoot
            $carrySourceHistoryPath = $carryHistorySnapshotPath
            Copy-AgentBaseStageFile -SourcePath $AttemptHistoryPath -TargetPath $carrySourceHistoryPath
        }
    }
    elseif ($null -ne $historyBeforeRefresh -and
        [string]$historyBeforeRefresh.active_cycle_id -eq [string]$initialPlan.evaluation_generation_sha256 -and
        (Test-Path -LiteralPath $carryHistorySnapshotPath -PathType Leaf)) {
        try {
            $carryHistorySnapshot = Read-AgentBaseRoutingAttemptHistory -Path $carryHistorySnapshotPath
            $carryHistorySnapshotHash = (Get-FileHash -LiteralPath $carryHistorySnapshotPath -Algorithm SHA256).Hash
            if ($null -ne $carryHistorySnapshot -and
                [int]$carryHistorySnapshot.schema_version -eq (Get-AgentBaseRoutingAttemptHistorySchema) -and
                @($carryHistorySnapshot.attempts | Where-Object { [string]$_.outcome -eq 'started' }).Count -eq 0 -and
                [string]$historyBeforeRefresh.previous_cycle_id -eq [string]$carryHistorySnapshot.active_cycle_id -and
                [string]$historyBeforeRefresh.previous_ledger_sha256 -eq $carryHistorySnapshotHash) {
                $candidateSourceRoot = Join-Path $pendingBase ([string]$carryHistorySnapshot.active_cycle_id)
                if (Test-Path -LiteralPath $candidateSourceRoot -PathType Container) {
                    $carrySourceRoot = $candidateSourceRoot
                    $carrySourceHistoryPath = $carryHistorySnapshotPath
                }
            }
        }
        catch {
            $carrySourceRoot = $null
            $carrySourceHistoryPath = $null
        }
    }

    foreach ($phase in @("Routing", "Policy")) {
        $pending = Resolve-AgentBasePendingReceipt -PhaseName $phase -ResultPath $stagePaths.$phase
        if ($null -ne $pending) {
            $receipts[$phase] = $pending
            if ([string]$pending.action -eq 'oracle-revalidated') { $revalidatedResults.Add($pending) }
            else { $recoveredResults.Add($pending) }
        }
        elseif ($null -ne $carrySourceRoot) {
            $carried = Invoke-AgentBaseCarryForwardReceipt -PhaseName $phase -SourcePath (Join-Path $carrySourceRoot ("{0}.json" -f $phase.ToLowerInvariant())) -TargetPath $stagePaths.$phase -SourceHistoryPath $carrySourceHistoryPath
            if ($null -ne $carried) {
                $receipts[$phase] = $carried
                if ([string]$carried.action -eq 'oracle-revalidated') { $revalidatedResults.Add($carried) }
                else { $carriedResults.Add($carried) }
            }
        }
        if (-not $receipts.ContainsKey($phase) -and [string]$initialPlan.phases.$phase.action -eq "reuse") {
            $receipts[$phase] = Invoke-AgentBaseReuseReceipt -PhaseName $phase
            if ($phase -eq "Routing") {
                Write-AgentBaseStageFile -Path $stagePaths.Routing -Value $sourceEvidence
            }
            else {
                Write-AgentBaseStageFile -Path $stagePaths.Policy -Value $sourceEvidence.policy_evaluation
            }
        }
    }
    if ([string]$initialPlan.phases.References.action -eq "reuse") {
        $pending = Resolve-AgentBasePendingReceipt -PhaseName References -ResultPath $stagePaths.References -RoutingPath $stagePaths.Routing
        if ($null -ne $pending) {
            $receipts.References = $pending
            if ([string]$pending.action -eq 'oracle-revalidated') { $revalidatedResults.Add($pending) }
            else { $recoveredResults.Add($pending) }
        }
        else {
            $receipts.References = Invoke-AgentBaseReuseReceipt -PhaseName References -RoutingPath $stagePaths.Routing
            Write-AgentBaseStageFile -Path $stagePaths.References -Value $sourceEvidence.reference_evaluation
        }
    }

    $runners = New-Object 'System.Collections.Generic.List[object]'
    if (-not $receipts.ContainsKey("Routing") -and [string]$initialPlan.phases.Routing.action -eq "evaluate") {
        $runners.Add((Start-AgentBasePhaseRunner -PhaseName Routing -ResultPath $stagePaths.Routing -RetryJustification $RoutingRetryJustification))
    }
    if (-not $receipts.ContainsKey("Policy") -and [string]$initialPlan.phases.Policy.action -eq "evaluate") {
        $runners.Add((Start-AgentBasePhaseRunner -PhaseName Policy -ResultPath $stagePaths.Policy -RetryJustification $PolicyRetryJustification))
    }
    $startedFirstWave = @($runners | ForEach-Object { [string]$_.phase })
    $runnerFailures = New-Object 'System.Collections.Generic.List[string]'
    foreach ($runner in $runners) {
        try {
            $completed = Complete-AgentBasePhaseRunner -Runner $runner
            $runResults.Add($completed)
            $receipts[[string]$completed.phase] = $completed
        }
        catch {
            $runnerFailures.Add($_.Exception.Message)
        }
    }
    if ($runnerFailures.Count -gt 0) {
        throw (($runnerFailures -join [Environment]::NewLine) + [Environment]::NewLine + "Passed stage results remain recoverable under $pendingRoot")
    }

    $routingForReferences = Get-Content -LiteralPath $stagePaths.Routing -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 -DateKind String
    $secondPlan = Get-AgentBaseRoutingEvaluationPlan -ProjectRoot $ProjectRoot -Contract $contract -SourceEvidence $sourceEvidence -RoutingResultsForReferences $routingForReferences
    if ([string]$secondPlan.phases.References.action -eq "blocked") {
        throw "Reference evaluation is blocked because its visible input is unchanged but the current oracle rejects the prior result"
    }
    if (-not $receipts.ContainsKey("References")) {
        $pending = Resolve-AgentBasePendingReceipt -PhaseName References -ResultPath $stagePaths.References -RoutingPath $stagePaths.Routing
        if ($null -ne $pending) {
            $receipts.References = $pending
            if ([string]$pending.action -eq 'oracle-revalidated') { $revalidatedResults.Add($pending) }
            else { $recoveredResults.Add($pending) }
        }
        elseif ($null -ne $carrySourceRoot) {
            $carried = Invoke-AgentBaseCarryForwardReceipt -PhaseName References -SourcePath (Join-Path $carrySourceRoot 'references.json') -TargetPath $stagePaths.References -SourceHistoryPath $carrySourceHistoryPath -RoutingPath $stagePaths.Routing
            if ($null -ne $carried) {
                $receipts.References = $carried
                if ([string]$carried.action -eq 'oracle-revalidated') { $revalidatedResults.Add($carried) }
                else { $carriedResults.Add($carried) }
            }
        }
        if (-not $receipts.ContainsKey("References")) {
            if ([string]$secondPlan.phases.References.action -eq "reuse") {
                $receipts.References = Invoke-AgentBaseReuseReceipt -PhaseName References -RoutingPath $stagePaths.Routing
                Write-AgentBaseStageFile -Path $stagePaths.References -Value $sourceEvidence.reference_evaluation
            }
            elseif ([string]$secondPlan.phases.References.action -eq "evaluate") {
                $referenceOutput = & (Join-Path $PSScriptRoot "invoke_routing_evaluation.ps1") -Phase References -OutputPath $stagePaths.References -ProjectRoot $ProjectRoot -RoutingResultsPath $stagePaths.Routing -AttemptHistoryPath $AttemptHistoryPath -CodexExecutablePath $CodexExecutablePath -Model $Model -ReasoningEffort $ReasoningEffort -TimeoutMinutes $TimeoutMinutes -RetryJustification $ReferencesRetryJustification
                $referenceResult = $referenceOutput | ConvertFrom-Json -Depth 30 -DateKind String
                $runResults.Add($referenceResult)
                $receipts.References = $referenceResult
            }
            else {
                throw "Reference phase remained unresolved after a valid routing result: $($secondPlan.phases.References.action)"
            }
        }
    }

    $merge = & (Join-Path $PSScriptRoot "merge_routing_evidence.ps1") -ProjectRoot $ProjectRoot -RoutingResultsPath $stagePaths.Routing -PolicyResultsPath $stagePaths.Policy -ReferenceResultsPath $stagePaths.References -RoutingAttemptId $receipts.Routing.attempt_id -PolicyAttemptId $receipts.Policy.attempt_id -ReferenceAttemptId $receipts.References.attempt_id -AttemptHistoryPath $AttemptHistoryPath -OutputPath $CurrentEvidencePath
    $totalInput = [long](@($runResults | ForEach-Object { [long]$_.input_tokens } | Measure-Object -Sum).Sum)
    $totalCached = [long](@($runResults | ForEach-Object { [long]$_.cached_input_tokens } | Measure-Object -Sum).Sum)
    $totalOutput = [long](@($runResults | ForEach-Object { [long]$_.output_tokens } | Measure-Object -Sum).Sum)
    [pscustomobject][ordered]@{
        action = "refreshed"
        evaluation_generation_sha256 = [string]$merge.evaluation_generation_sha256
        evaluator_run_count = $runResults.Count
        recovered_phase_count = $recoveredResults.Count
        oracle_revalidated_phase_count = $revalidatedResults.Count
        carried_forward_phase_count = $carriedResults.Count
        reused_phase_count = 3 - $runResults.Count - $recoveredResults.Count - $revalidatedResults.Count - $carriedResults.Count
        parallel_first_wave = @($startedFirstWave)
        input_tokens = $totalInput
        cached_input_tokens = $totalCached
        output_tokens = $totalOutput
        current_evidence_path = [string]$merge.path
    }
    $refreshSucceeded = $true
}
finally {
    if ($refreshSucceeded -and (Test-Path -LiteralPath $pendingBase -PathType Container)) {
        foreach ($directory in @(Get-ChildItem -LiteralPath $pendingBase -Directory -Force)) {
            if ($directory.Name -match '^[0-9A-Fa-f]{64}$') {
                Remove-AgentBasePendingGeneration -Path $directory.FullName -PendingBase $pendingBase
            }
        }
    }
}
