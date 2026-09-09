[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
$evaluationRoot = Join-Path $resolvedProjectRoot 'development\agent-evaluation'
$entryPoint = Join-Path $evaluationRoot 'agent_eval.py'
$testRoot = Join-Path $evaluationRoot 'tests'
$fixtureCorpus = Join-Path $testRoot 'fixtures\synthetic-corpus.json'
$python = (Get-Command python.exe -ErrorAction Stop).Source
$syntaxErrors = @()
foreach ($scriptName in @(
    'invoke_candidate.ps1'
    'evo\manage_skill_cache.ps1'
    '..\common\get_payload_manifest.ps1'
)) {
    $tokens = $null
    $errors = $null
    $scriptPath = Join-Path $evaluationRoot $scriptName
    [void][Management.Automation.Language.Parser]::ParseFile(
        $scriptPath,
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($parseError in @($errors)) {
        $syntaxErrors += '{0}:{1}: {2}' -f @(
            $scriptName,
            $parseError.Extent.StartLineNumber,
            $parseError.Message
        )
    }
}
if ($syntaxErrors.Count -gt 0) {
    throw "Agent evaluation PowerShell syntax validation failed:`n$($syntaxErrors -join [Environment]::NewLine)"
}

$agentFlagName = 'AGENTBASE_AGENT_EVALUATOR_DISABLED'
$routingFlagName = 'AGENTBASE_ROUTING_EVALUATOR_DISABLED'
$agentFlagPath = "Env:\$agentFlagName"
$routingFlagPath = "Env:\$routingFlagName"
$hadAgentFlag = Test-Path -LiteralPath $agentFlagPath
$hadRoutingFlag = Test-Path -LiteralPath $routingFlagPath
$previousAgentFlag = if ($hadAgentFlag) { (Get-Item -LiteralPath $agentFlagPath).Value } else { $null }
$previousRoutingFlag = if ($hadRoutingFlag) { (Get-Item -LiteralPath $routingFlagPath).Value } else { $null }

try {
    Set-Item -LiteralPath $agentFlagPath -Value '1'
    Set-Item -LiteralPath $routingFlagPath -Value '1'

    & $python -X utf8 $entryPoint validate --project-root $resolvedProjectRoot --corpus $fixtureCorpus --view machine | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Agent evaluation corpus validation failed with exit code $LASTEXITCODE."
    }

    & $python -X utf8 -m unittest discover -s $testRoot -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) {
        throw "Agent evaluation infrastructure tests failed with exit code $LASTEXITCODE."
    }
}
finally {
    if ($hadAgentFlag) {
        Set-Item -LiteralPath $agentFlagPath -Value $previousAgentFlag
    }
    else {
        Remove-Item -LiteralPath $agentFlagPath -ErrorAction SilentlyContinue
    }
    if ($hadRoutingFlag) {
        Set-Item -LiteralPath $routingFlagPath -Value $previousRoutingFlag
    }
    else {
        Remove-Item -LiteralPath $routingFlagPath -ErrorAction SilentlyContinue
    }
}

Write-Host 'AgentBase Windows SWE infrastructure checks passed (model evaluator disabled).'
