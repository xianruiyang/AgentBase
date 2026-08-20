[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
$entryPoint = Join-Path $resolvedProjectRoot 'development\codex-deployment\manage_agentbase.ps1'
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$passed = $false
$validation = $null
$diagnostic = $null
try {
    $records = @(
        & $entryPoint `
            -Action Validate `
            -ProjectRoot $resolvedProjectRoot `
            -SkillDeliveryMode Plugin `
            3>$null 4>$null 6>$null
    )
    if ($records.Count -ne 1 -or [string]$records[0].action -ne 'Validate') {
        throw 'Native validation owner did not return exactly one Validate result'
    }
    $validation = $records[0]
    $passed = $true
}
catch {
    $diagnostic = [regex]::Replace([string]$_.Exception.Message, '\s+', ' ').Trim()
    if ($diagnostic.Length -gt 600) {
        $diagnostic = $diagnostic.Substring(0, 297) + ' ... ' + $diagnostic.Substring($diagnostic.Length - 298)
    }
}
finally {
    $stopwatch.Stop()
}
$result = [pscustomobject][ordered]@{
    schema = 'agentbase.native-validation/v2'
    status = if ($passed) { 'passed' } else { 'failed' }
    passed = $passed
    duration_seconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
    validation = $validation
    diagnostic = $diagnostic
    installation_status = 'not-assessed'
    external_actions = [pscustomobject][ordered]@{
        model_invoked = $false
        software_installed = $false
        published = $false
    }
}
$result | ConvertTo-Json -Depth 20
