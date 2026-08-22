param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$sandboxRoot = Join-Path $ProjectRoot "development\codex-deployment\sandbox"
$testRoot = Join-Path $sandboxRoot ("portable-agent-contract-test-" + [guid]::NewGuid().ToString("N"))
$sourceRoot = Join-Path $ProjectRoot "global\agents"
$contractPath = Join-Path $PSScriptRoot "portable_agents.ps1"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

. $contractPath

function Write-FixtureText {
    param(
        [string]$Path,
        [string]$Text
    )

    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function New-AgentFixture {
    param(
        [string]$Name
    )

    $fixtureRoot = Join-Path $testRoot $Name
    New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
    foreach ($agentFile in @(Get-ChildItem -LiteralPath $sourceRoot -File -Filter "*.toml")) {
        Copy-Item -LiteralPath $agentFile.FullName -Destination (Join-Path $fixtureRoot $agentFile.Name)
    }
    return $fixtureRoot
}

function Assert-Rejected {
    param(
        [string]$Label,
        [string]$FixtureRoot,
        [string]$ExpectedMessage
    )

    $rejected = $false
    try {
        $null = @(Get-ValidatedPortableAgentSources -Path $FixtureRoot)
    }
    catch {
        $rejected = $_.Exception.Message -like $ExpectedMessage
    }
    if (-not $rejected) {
        throw "Portable agent contract did not reject ${Label}"
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    $baselineRoot = New-AgentFixture -Name "baseline"
    if (@(Get-ValidatedPortableAgentSources -Path $baselineRoot).Count -ne 2) {
        throw "Portable agent contract did not accept the current two semantic roles"
    }

    $independentTextRoot = New-AgentFixture -Name "independent-text"
    Write-FixtureText -Path (Join-Path $independentTextRoot "evidence.toml") -Text ((@(
        'name = "evidence"'
        'description = "用于只读整理有界事实并向主代理返回证据。"'
        'model = "gpt-5.6-luna"'
        'model_reasoning_effort = "medium"'
        'developer_instructions = """'
        '只处理给出权威范围的事实问题；范围不足时返回未知，不修改项目。'
        '"""'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    if (@(Get-ValidatedPortableAgentSources -Path $independentTextRoot).Count -ne 2) {
        throw "Portable agent contract still depends on the current evidence prose"
    }

    $futureModelRoot = New-AgentFixture -Name "future-model"
    $futureModel = (Get-Content -LiteralPath (Join-Path $futureModelRoot "evidence.toml") -Raw -Encoding UTF8).Replace('model = "gpt-5.6-luna"', 'model = "gpt-6.0-fast"')
    $futureModel = $futureModel.Replace('model_reasoning_effort = "medium"', 'model_reasoning_effort = "high"')
    Write-FixtureText -Path (Join-Path $futureModelRoot "evidence.toml") -Text $futureModel
    if (@(Get-ValidatedPortableAgentSources -Path $futureModelRoot).Count -ne 2) {
        throw "Portable agent contract incorrectly couples a semantic role to the current model or effort"
    }

    $englishRoot = New-AgentFixture -Name "english-prose"
    Write-FixtureText -Path (Join-Path $englishRoot "evidence.toml") -Text ((@(
        'name = "evidence"'
        'description = "Read-only evidence mapper."'
        'model = "gpt-5.6-luna"'
        'model_reasoning_effort = "medium"'
        'developer_instructions = """'
        'Return bounded evidence and do not edit files.'
        '"""'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Assert-Rejected -Label "English model-facing prose" -FixtureRoot $englishRoot -ExpectedMessage "*must use Chinese semantics*"

    $wrongIdentityRoot = New-AgentFixture -Name "wrong-identity"
    $wrongIdentity = (Get-Content -LiteralPath (Join-Path $wrongIdentityRoot "experiment.toml") -Raw -Encoding UTF8).Replace('name = "experiment"', 'name = "probe"')
    Write-FixtureText -Path (Join-Path $wrongIdentityRoot "experiment.toml") -Text $wrongIdentity
    Assert-Rejected -Label "filename/name identity mismatch" -FixtureRoot $wrongIdentityRoot -ExpectedMessage "*name does not match its file identity*"

    $wrongModelRoot = New-AgentFixture -Name "wrong-model"
    $wrongModel = (Get-Content -LiteralPath (Join-Path $wrongModelRoot "experiment.toml") -Raw -Encoding UTF8).Replace('model = "gpt-5.6-sol"', 'model = "invalid model"')
    Write-FixtureText -Path (Join-Path $wrongModelRoot "experiment.toml") -Text $wrongModel
    Assert-Rejected -Label "unsafe model identifier" -FixtureRoot $wrongModelRoot -ExpectedMessage "*explicit safe model identifier*"

    $duplicateRoot = New-AgentFixture -Name "duplicate-role"
    $evidenceText = Get-Content -LiteralPath (Join-Path $duplicateRoot "evidence.toml") -Raw -Encoding UTF8
    $duplicateExperiment = $evidenceText.Replace('name = "evidence"', 'name = "experiment"').Replace('model = "gpt-5.6-luna"', 'model = "gpt-5.6-sol"').Replace('model_reasoning_effort = "medium"', 'model_reasoning_effort = "low"')
    Write-FixtureText -Path (Join-Path $duplicateRoot "experiment.toml") -Text $duplicateExperiment
    Assert-Rejected -Label "duplicate role semantics" -FixtureRoot $duplicateRoot -ExpectedMessage "*must have distinct descriptions*"

    $wrongEffortRoot = New-AgentFixture -Name "wrong-effort"
    $wrongEffort = (Get-Content -LiteralPath (Join-Path $wrongEffortRoot "experiment.toml") -Raw -Encoding UTF8).Replace('model_reasoning_effort = "low"', 'model_reasoning_effort = "impossible"')
    Write-FixtureText -Path (Join-Path $wrongEffortRoot "experiment.toml") -Text $wrongEffort
    Assert-Rejected -Label "unsupported reasoning effort" -FixtureRoot $wrongEffortRoot -ExpectedMessage "*reasoning effort is not supported*"

    $extraFieldRoot = New-AgentFixture -Name "extra-field"
    $extraFieldText = (Get-Content -LiteralPath (Join-Path $extraFieldRoot "experiment.toml") -Raw -Encoding UTF8) + "extra = true" + [Environment]::NewLine
    Write-FixtureText -Path (Join-Path $extraFieldRoot "experiment.toml") -Text $extraFieldText
    Assert-Rejected -Label "unreviewed extra field" -FixtureRoot $extraFieldRoot -ExpectedMessage "*must contain only name, description, model, model_reasoning_effort*"

    $sensitiveRoot = New-AgentFixture -Name "sensitive-field"
    $sensitiveText = (Get-Content -LiteralPath (Join-Path $sensitiveRoot "experiment.toml") -Raw -Encoding UTF8).Replace('实现路径', 'password 配置路径')
    Write-FixtureText -Path (Join-Path $sensitiveRoot "experiment.toml") -Text $sensitiveText
    Assert-Rejected -Label "sensitive assignment vocabulary" -FixtureRoot $sensitiveRoot -ExpectedMessage "*contains a machine path, external dependency, or sensitive setting*"

    Write-Output "tests : pass"
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        $approvedRoot = [IO.Path]::GetFullPath($sandboxRoot).TrimEnd('\') + '\'
        $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
        if (-not $resolvedTestRoot.StartsWith($approvedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $resolvedTestRoot).StartsWith("portable-agent-contract-test-", [StringComparison]::Ordinal)) {
            throw "Refusing portable-agent test cleanup outside the approved sandbox: $resolvedTestRoot"
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
