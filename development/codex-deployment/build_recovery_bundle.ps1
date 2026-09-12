param([Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'Recovery bundle output must be a new directory' }
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$files = @(
    'development/codex-deployment/manage_agentbase.ps1',
    'development/codex-deployment/manage_agentbase.format.ps1xml',
    'development/codex-deployment/portable_config.ps1',
    'development/codex-deployment/portable_agents.ps1',
    'development/codex-deployment/managed_asset_lifecycle.ps1',
    'development/codex-deployment/original_config.ps1',
    'development/codex-deployment/original_state.ps1',
    'development/common/payload_contract.ps1'
)
foreach ($relative in $files) {
    $source = Join-Path $project $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Recovery source missing: $relative" }
}
foreach ($relative in $files) {
    $target = Join-Path $output $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $project $relative) -Destination $target
}
$launcher = @'
param(
    [ValidateSet('PreviewRestore', 'RestoreOriginal', 'Rollback')]
    [string]$Action = 'PreviewRestore',
    [Parameter(Mandatory)][string]$CodexRoot,
    [string]$BackupPath,
    [switch]$PluginDisabled
)
$arguments = @{ Action = $Action; ProjectRoot = $PSScriptRoot; CodexRoot = $CodexRoot }
if ($BackupPath) { $arguments.BackupPath = $BackupPath }
if ($PluginDisabled) { $arguments.PluginDisabled = $true }
& (Join-Path $PSScriptRoot 'development/codex-deployment/manage_agentbase.ps1') @arguments
'@
[IO.File]::WriteAllText((Join-Path $output 'restore.ps1'), $launcher, [Text.UTF8Encoding]::new($false))
$readme = @'
# AgentBase recovery (Windows / PowerShell 7)

This directory contains recovery code only. Original user data stays under the
chosen Codex root's backups/AgentBase-original directory. Keep both available.
No Codex login, model, Python, source checkout, or installed CLI is required.

Preview is read-only and may run inside Codex:

    pwsh -File .\restore.ps1 -CodexRoot '<your-codex-root>'

After reviewing the preview, open PowerShell 7 independently from Windows Start
or Windows Terminal, outside Codex's integrated terminal and command tools. Keep
that window open, exit Codex normally, and run the restore command there from
this recovery directory:

    pwsh -File .\restore.ps1 -Action RestoreOriginal -CodexRoot '<your-codex-root>'

The same independent-window requirement applies to -Action Rollback. This tool
does not close Codex or detach its PowerShell process from a host. If Codex helps,
it should only preview and prepare the exact command and paths for you; it must
not terminate its own host and then attempt to continue restoring. Starting
another pwsh through Codex does not by itself establish an independent lifetime.

If the preview reports plugin use, first disable/uninstall agentbase-core through
the official Codex plugin entry, then pass -PluginDisabled to acknowledge that
completed step. This switch does not disable the plugin for you.
Conflicts block all restoration; preserve/reconcile those personal changes first.
Legacy installations without an original recovery point can use -Action Rollback
with -BackupPath '<exact-deployment-backup>'. Do not force away personal drift.
This tool does not revert host prerequisite installations, PATH, or plugin state.
'@
[IO.File]::WriteAllText((Join-Path $output 'README.md'), $readme, [Text.UTF8Encoding]::new($false))
[pscustomobject]@{ built = $true; directory = $output; file_count = $files.Count + 2 }
