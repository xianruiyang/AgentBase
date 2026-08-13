$ErrorActionPreference = "Stop"

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$testRoot = Join-Path $tempBase ("AgentBase-routing-capsule-" + [guid]::NewGuid().ToString("N"))
$outputPath = Join-Path $testRoot "capsule.json"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $receipt = & (Join-Path $PSScriptRoot "build_routing_evaluation.ps1") -ProjectRoot $projectRoot -OutputPath $outputPath
    $raw = Get-Content -LiteralPath $outputPath -Raw -Encoding UTF8
    $capsule = $raw | ConvertFrom-Json -Depth 100

    if ([int]$capsule.schema_version -ne 2 -or [string]$capsule.evaluation_kind -ne "routing-policy") {
        throw "Detached capsule has the wrong schema or evaluation kind"
    }
    if ([string]$capsule.evaluation_capsule_sha256 -ne [string]$receipt.evaluation_capsule_sha256) {
        throw "Detached capsule receipt does not match its embedded identity"
    }
    if ([string]::IsNullOrWhiteSpace([string]$capsule.candidate.global.content) -or @($capsule.candidate.skills).Count -eq 0) {
        throw "Detached capsule does not embed the routing candidate"
    }
    if ($raw.Contains($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Detached capsule leaks the source repository path"
    }
    foreach ($case in @($capsule.cases)) {
        $unexpectedProperties = @($case.PSObject.Properties.Name | Where-Object { @("id", "request", "available_peer_skills") -notcontains $_ })
        if ($unexpectedProperties.Count -gt 0) {
            throw "Detached capsule leaks hidden case fields for $($case.id): $($unexpectedProperties -join ', ')"
        }
    }
    foreach ($hiddenField in @("expected_skills", "forbidden_skills", "expected_behavior_tags", "forbidden_behavior_tags", "strict_routing_case_ids")) {
        if ($capsule.PSObject.Properties.Name -contains $hiddenField) {
            throw "Detached capsule exposes hidden top-level field: $hiddenField"
        }
    }
    if ([string]$capsule.output_schema.evaluator.isolation_mode -ne "detached-capsule") {
        throw "Detached capsule output schema does not require isolation metadata"
    }
    if ([bool]$capsule.output_schema.evaluator.repository_accessed -or [bool]$capsule.output_schema.evaluator.hidden_expectations_accessed) {
        throw "Detached capsule output schema does not require a clean input attestation"
    }

    Write-Output "Routing capsule tests passed: candidate content is embedded, repository paths and hidden expectations are absent, and the receipt is bound to the capsule identity."
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if (-not $resolvedTestRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $resolvedTestRoot).StartsWith("AgentBase-routing-capsule-", [StringComparison]::Ordinal)) {
        throw "Refusing test cleanup outside the approved temp root: $resolvedTestRoot"
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
