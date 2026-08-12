$ErrorActionPreference = "Stop"

function Get-AgentBaseBehaviorFingerprintSchema {
    return "text-lf-v1"
}

function Get-AgentBaseBehaviorSha256 {
    param(
        [string]$Text
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $algorithm.Dispose()
    }
}

function ConvertTo-AgentBaseCanonicalText {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    return $Text.Replace("`r`n", "`n").Replace("`r", "`n")
}

function Get-AgentBaseBehaviorCandidateFingerprint {
    param(
        [string]$ProjectRoot,
        [object[]]$CandidateFiles
    )

    $rootFull = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $records = @($CandidateFiles | ForEach-Object {
        $item = Get-Item -LiteralPath ([string]$_) -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Behavior candidate must be a real file: $($item.FullName)"
        }
        $relativePath = $item.FullName.Substring($rootFull.Length + 1).Replace('\', '/')
        $canonicalText = ConvertTo-AgentBaseCanonicalText ([IO.File]::ReadAllText($item.FullName, [Text.Encoding]::UTF8))
        $canonicalBytes = [Text.UTF8Encoding]::new($false).GetBytes($canonicalText)
        $contentHash = Get-AgentBaseBehaviorSha256 $canonicalText
        "$relativePath|$($canonicalBytes.Length)|$contentHash"
    })
    [Array]::Sort([string[]]$records, [StringComparer]::Ordinal)
    return Get-AgentBaseBehaviorSha256 ($records -join "`n")
}

function Get-AgentBaseBehaviorInputFingerprint {
    param(
        [object[]]$Cases,
        [object[]]$AllowedBehaviorTags
    )

    $records = @($Cases | ForEach-Object {
        $request = ConvertTo-AgentBaseCanonicalText ([string]$_.request)
        "$([string]$_.id)|$request"
    })
    $records += @($AllowedBehaviorTags | ForEach-Object { "behavior|$([string]$_)" })
    return Get-AgentBaseBehaviorSha256 ($records -join "`n")
}
