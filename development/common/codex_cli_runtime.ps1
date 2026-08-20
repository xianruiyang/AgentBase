$ErrorActionPreference = 'Stop'

function Get-AgentBaseUserNpmPrefix {
    $npm = Get-Command -Name 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $npm) {
        $npm = Get-Command -Name 'npm.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -ne $npm) {
        $prefixOutput = @(& $npm.Source config get prefix 2>$null)
        $prefixExit = $LASTEXITCODE
        if ($prefixExit -eq 0 -and $prefixOutput.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace([string]$prefixOutput[-1])) {
            return [IO.Path]::GetFullPath(([string]$prefixOutput[-1]).Trim())
        }
    }
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        return $null
    }
    return [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'npm'))
}

function Get-AgentBaseCodexNativeCandidatePaths {
    param(
        [string]$NpmPrefix
    )

    if ([string]::IsNullOrWhiteSpace($NpmPrefix)) {
        return @()
    }
    $target = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
        ([Runtime.InteropServices.Architecture]::X64) {
            [pscustomobject]@{ package = 'codex-win32-x64'; triple = 'x86_64-pc-windows-msvc' }
        }
        ([Runtime.InteropServices.Architecture]::Arm64) {
            [pscustomobject]@{ package = 'codex-win32-arm64'; triple = 'aarch64-pc-windows-msvc' }
        }
        default { throw "Unsupported Windows architecture for Codex CLI: $([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)" }
    }
    $prefix = [IO.Path]::GetFullPath($NpmPrefix)
    return @(
        Join-Path $prefix "node_modules\@openai\codex\node_modules\@openai\$($target.package)\vendor\$($target.triple)\bin\codex.exe"
        Join-Path $prefix "node_modules\@openai\$($target.package)\vendor\$($target.triple)\bin\codex.exe"
        Join-Path $prefix "node_modules\@openai\codex\vendor\$($target.triple)\bin\codex.exe"
    )
}

function Resolve-AgentBaseCodexNativeExecutable {
    param(
        [string]$ExplicitPath,
        [string]$NpmPrefix,
        [string]$SandboxFallbackPath
    )

    $candidates = New-Object 'System.Collections.Generic.List[string]'
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $candidates.Add([IO.Path]::GetFullPath($ExplicitPath))
    }
    foreach ($candidate in @(Get-AgentBaseCodexNativeCandidatePaths -NpmPrefix $NpmPrefix)) {
        $candidates.Add([string]$candidate)
    }
    if (-not [string]::IsNullOrWhiteSpace($SandboxFallbackPath)) {
        $candidates.Add([IO.Path]::GetFullPath($SandboxFallbackPath))
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if ($candidate -match '(?i)\\WindowsApps\\') {
            continue
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                return $item.FullName
            }
        }
    }
    throw 'No directly executable Codex CLI was found outside WindowsApps. Install @openai/codex in the user npm prefix or pass CodexExecutablePath.'
}
