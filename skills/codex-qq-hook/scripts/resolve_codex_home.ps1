function Resolve-AgentBaseCodexHome {
    param(
        [string]$RequestedRoot
    )

    $candidate = $RequestedRoot
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = $env:CODEX_HOME
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $userProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
        if ([string]::IsNullOrWhiteSpace($userProfile)) {
            throw "CodexRoot is required when CODEX_HOME and the user profile are unavailable"
        }
        $candidate = Join-Path $userProfile ".codex"
    }

    $fullPath = [IO.Path]::GetFullPath($candidate)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
        throw "Codex root does not exist: $fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Codex root must be a real directory: $fullPath"
    }
    return $item.FullName
}
