param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Manifest', 'Copy')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [string]$DestinationPath = ''
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'payload_contract.ps1')

$sourceRoot = (Get-Item -LiteralPath $SourcePath -Force -ErrorAction Stop).FullName.TrimEnd('\')
$files = @(Get-AgentBasePayloadFiles -Root $sourceRoot | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($sourceRoot.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})

if ($Action -eq 'Copy') {
    if ([string]::IsNullOrWhiteSpace($DestinationPath)) {
        throw 'Copy requires DestinationPath'
    }
    if (Test-Path -LiteralPath $DestinationPath) {
        throw "Payload destination already exists: $DestinationPath"
    }
    Copy-AgentBasePayloadDirectory -SourcePath $sourceRoot -DestinationPath $DestinationPath
}

[ordered]@{
    schema = 'agentbase-payload-manifest/v1'
    files = $files
} | ConvertTo-Json -Depth 5 -Compress
