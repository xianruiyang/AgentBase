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
    if (@(Get-ValidatedPortableAgentSources -Path $baselineRoot).Count -ne 3) {
        throw "Portable agent contract did not accept the current three source roles"
    }

    $independentTextRoot = New-AgentFixture -Name "independent-text"
    Write-FixtureText -Path (Join-Path $independentTextRoot "luna.toml") -Text ((@(
        'name = "luna"'
        'description = "用于输入明确且可以快速核对结果的独立窄任务。"'
        'model = "gpt-5.6-luna"'
        'developer_instructions = """'
        '只处理已经给出完整边界的工作；出现影响范围不明或需要共同职责裁决时，把未知项返回给调用方。'
        '"""'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    if (@(Get-ValidatedPortableAgentSources -Path $independentTextRoot).Count -ne 3) {
        throw "Portable agent contract still depends on the current Luna prose"
    }

    $englishRoot = New-AgentFixture -Name "english-prose"
    Write-FixtureText -Path (Join-Path $englishRoot "luna.toml") -Text ((@(
        'name = "luna"'
        'description = "Use Luna for narrow tasks."'
        'model = "gpt-5.6-luna"'
        'developer_instructions = """'
        'Complete narrow tasks and return evidence.'
        '"""'
    ) -join [Environment]::NewLine) + [Environment]::NewLine)
    Assert-Rejected -Label "English model-facing prose" -FixtureRoot $englishRoot -ExpectedMessage "*must use Chinese semantics*"

    $wrongIdentityRoot = New-AgentFixture -Name "wrong-identity"
    $wrongIdentity = (Get-Content -LiteralPath (Join-Path $wrongIdentityRoot "terra.toml") -Raw -Encoding UTF8).Replace('model = "gpt-5.6-terra"', 'model = "gpt-5.6-sol"')
    Write-FixtureText -Path (Join-Path $wrongIdentityRoot "terra.toml") -Text $wrongIdentity
    Assert-Rejected -Label "filename/model identity mismatch" -FixtureRoot $wrongIdentityRoot -ExpectedMessage "*does not match its file identity*"

    $duplicateRoot = New-AgentFixture -Name "duplicate-role"
    $lunaText = Get-Content -LiteralPath (Join-Path $duplicateRoot "luna.toml") -Raw -Encoding UTF8
    $duplicateTerra = $lunaText.Replace('name = "luna"', 'name = "terra"').Replace('model = "gpt-5.6-luna"', 'model = "gpt-5.6-terra"')
    Write-FixtureText -Path (Join-Path $duplicateRoot "terra.toml") -Text $duplicateTerra
    Assert-Rejected -Label "duplicate role semantics" -FixtureRoot $duplicateRoot -ExpectedMessage "*must have distinct descriptions*"

    $extraFieldRoot = New-AgentFixture -Name "extra-field"
    $extraFieldText = (Get-Content -LiteralPath (Join-Path $extraFieldRoot "sol.toml") -Raw -Encoding UTF8) + "extra = true" + [Environment]::NewLine
    Write-FixtureText -Path (Join-Path $extraFieldRoot "sol.toml") -Text $extraFieldText
    Assert-Rejected -Label "unreviewed extra field" -FixtureRoot $extraFieldRoot -ExpectedMessage "*must contain only name, description, model*"

    $sensitiveRoot = New-AgentFixture -Name "sensitive-field"
    $sensitiveText = (Get-Content -LiteralPath (Join-Path $sensitiveRoot "sol.toml") -Raw -Encoding UTF8).Replace('复杂问题', 'password 配置问题')
    Write-FixtureText -Path (Join-Path $sensitiveRoot "sol.toml") -Text $sensitiveText
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
