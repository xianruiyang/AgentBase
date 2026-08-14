$ErrorActionPreference = "Stop"

function Assert-AgentBaseChildPath {
    param(
        [string]$Root,
        [string]$Path,
        [string]$Label
    )

    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside the approved root: $pathFull"
    }
}

function Test-AgentBaseProjectOnlyArtifact {
    param(
        [string]$RelativePath
    )

    $segments = @($RelativePath.Replace('\', '/').Split('/', [StringSplitOptions]::RemoveEmptyEntries))
    $projectOnlyDirectories = @(
        "__tests__",
        "bench",
        "benches",
        "benchmark",
        "benchmarks",
        "test",
        "tests"
    )
    for ($index = 0; $index -lt ($segments.Count - 1); $index++) {
        if ($projectOnlyDirectories -contains $segments[$index].ToLowerInvariant()) {
            return $true
        }
    }

    $leaf = if ($segments.Count -eq 0) { "" } else { $segments[-1] }
    return $leaf -match '(?i)^(test_.+|.+_test)\.(py|ps1|mjs|cjs|js|jsx|ts|tsx|rs)$' -or
        $leaf -match '(?i)^.+\.(test|spec)\.(mjs|cjs|js|jsx|ts|tsx)$' -or
        $leaf -match '(?i)^.+\.tests\.ps1$'
}

function Test-AgentBaseExcludedArtifact {
    param(
        [string]$RelativePath
    )

    if (Test-AgentBaseProjectOnlyArtifact -RelativePath $RelativePath) {
        return $true
    }

    $segments = @($RelativePath.Replace('\', '/').Split('/', [StringSplitOptions]::RemoveEmptyEntries))
    $excludedDirectories = @(
        ".codex",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "__pycache__",
        "codexRuntimeLogFile",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "target"
    )
    for ($index = 0; $index -lt ($segments.Count - 1); $index++) {
        if ($excludedDirectories -contains $segments[$index]) {
            return $true
        }
    }

    $leaf = if ($segments.Count -eq 0) { "" } else { $segments[-1] }
    if ($leaf -in @(".DS_Store", ".coverage", "Thumbs.db", "desktop.ini")) {
        return $true
    }
    return $leaf -match '(?i)\.(log|pyc|pyo|temp|tmp)$' -or $leaf -match '^\.coverage\.'
}

function Get-AgentBasePayloadFiles {
    param(
        [string]$Root,
        [switch]$IncludeProjectOnlyArtifacts
    )

    $rootItem = Get-Item -LiteralPath $Root -Force
    if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Payload root must be a real directory: $Root"
    }
    $rootFull = $rootItem.FullName.TrimEnd('\')
    $entries = @(Get-ChildItem -LiteralPath $rootFull -Recurse -Force)
    foreach ($entry in $entries) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to package a reparse point: $($entry.FullName)"
        }
    }

    return @($entries | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
        $relativePath = $_.FullName.Substring($rootFull.Length + 1).Replace('\', '/')
        if (-not (Test-AgentBaseExcludedArtifact -RelativePath $relativePath) -or
            ($IncludeProjectOnlyArtifacts -and (Test-AgentBaseProjectOnlyArtifact -RelativePath $relativePath))) {
            $_
        }
    } | Sort-Object FullName)
}

function Copy-AgentBasePayloadDirectory {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    $sourceRoot = (Get-Item -LiteralPath $SourcePath -Force).FullName.TrimEnd('\')
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    $destinationItem = Get-Item -LiteralPath $DestinationPath -Force
    if (-not $destinationItem.PSIsContainer -or ($destinationItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Payload destination must be a real directory: $DestinationPath"
    }
    $destinationRoot = $destinationItem.FullName.TrimEnd('\')
    foreach ($sourceFile in @(Get-AgentBasePayloadFiles -Root $sourceRoot)) {
        $relativePath = $sourceFile.FullName.Substring($sourceRoot.Length + 1)
        $destinationFile = Join-Path $destinationRoot $relativePath
        Assert-AgentBaseChildPath -Root $destinationRoot -Path $destinationFile -Label "Payload file"
        $destinationParent = Split-Path -Parent $destinationFile
        if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }
        Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationFile -Force
    }
}
