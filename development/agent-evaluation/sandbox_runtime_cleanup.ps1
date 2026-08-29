[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias('WorkspaceRoot')]
    [string]$OwnerRoot,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeTempPath,
    [ValidateSet('Candidate', 'Verifier')]
    [string]$Scope = 'Verifier'
)

$ErrorActionPreference = 'Stop'

$owner = [IO.Path]::GetFullPath($OwnerRoot)
$runtimeTemp = [IO.Path]::GetFullPath($RuntimeTempPath)
$relative = [IO.Path]::GetRelativePath($owner, $runtimeTemp)
$expected = if ($Scope -eq 'Candidate') {
    'runtime-temp'
}
else {
    Join-Path '.agentbase-verifier' 'runtime-temp'
}
if (
    [IO.Path]::IsPathRooted($relative) -or
    $relative -eq '..' -or
    $relative.StartsWith(
        '..' + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::Ordinal
    ) -or
    -not $relative.Equals($expected, [StringComparison]::OrdinalIgnoreCase)
) {
    throw "$Scope runtime cleanup target is outside the exact managed path"
}

if (-not [IO.Directory]::Exists($runtimeTemp)) {
    exit 0
}

function Remove-AgentBaseRuntimeChildren {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DirectoryPath,
        [Parameter(Mandatory = $true)]
        [string]$BoundaryRoot
    )

    foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($DirectoryPath)) {
        $fullEntry = [IO.Path]::GetFullPath($entry)
        $entryRelative = [IO.Path]::GetRelativePath($BoundaryRoot, $fullEntry)
        if (
            [IO.Path]::IsPathRooted($entryRelative) -or
            $entryRelative -eq '..' -or
            $entryRelative.StartsWith(
                '..' + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::Ordinal
            )
        ) {
            throw "$Scope runtime cleanup entry escaped its exact boundary"
        }

        $attributes = [IO.File]::GetAttributes($fullEntry)
        $isDirectory = ($attributes -band [IO.FileAttributes]::Directory) -ne 0
        $isReparsePoint = ($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        if ($isDirectory -and -not $isReparsePoint) {
            Remove-AgentBaseRuntimeChildren `
                -DirectoryPath $fullEntry `
                -BoundaryRoot $BoundaryRoot
            if (($attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) {
                [IO.File]::SetAttributes(
                    $fullEntry,
                    $attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
                )
            }
            [IO.Directory]::Delete($fullEntry, $false)
        }
        elseif ($isDirectory) {
            [IO.Directory]::Delete($fullEntry, $false)
        }
        else {
            if (-not $isReparsePoint) {
                [IO.File]::SetAttributes($fullEntry, [IO.FileAttributes]::Normal)
            }
            [IO.File]::Delete($fullEntry)
        }
    }
}

Remove-AgentBaseRuntimeChildren -DirectoryPath $runtimeTemp -BoundaryRoot $runtimeTemp

if (@([IO.Directory]::EnumerateFileSystemEntries($runtimeTemp)).Count -ne 0) {
    throw "$Scope runtime cleanup left child entries"
}
