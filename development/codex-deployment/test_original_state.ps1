param([string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$ErrorActionPreference = 'Stop'
$sandbox = Join-Path $ProjectRoot 'development\codex-deployment\sandbox'
$test = Join-Path $sandbox ('original-state-test-' + [guid]::NewGuid().ToString('N'))
$manage = Join-Path $PSScriptRoot 'manage_agentbase.ps1'
function Assert-Test([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function New-TestRoot([string]$Name) { $path = Join-Path $test $Name; New-Item -ItemType Directory -Path $path -Force | Out-Null; $path }
function Write-TestText([string]$Path, [string]$Text) { New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null; [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false))) }
try {
    # A later settings deployment extends the first recovery point without replacing it.
    $root = New-TestRoot 'continuous'
    Write-TestText (Join-Path $root 'AGENTS.md') "original rules`n"
    $config = Join-Path $root 'config.toml'
    Write-TestText $config "approval_policy = `"on-request`"`n[mcp_servers.original]`ncommand = `"keep`"`n"
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root
    $originalManifest = Join-Path $root 'backups\AgentBase-original\manifest.json'
    $manifestBefore = [IO.File]::ReadAllText($originalManifest)
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root -InstallPortableSettings
    Assert-Test ([IO.File]::ReadAllText((Join-Path $root 'backups\AgentBase-original\payload\AGENTS.md')) -ceq "original rules`n") 'Later deploy replaced the earliest original file'
    Assert-Test ([IO.File]::ReadAllText($originalManifest) -cne $manifestBefore) 'Portable settings did not extend the recovery point'
    [IO.File]::AppendAllText($config, "`n[mcp_servers.later]`ncommand = `"also-keep`"`n")
    $preview = & $manage -Action PreviewRestore -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test ($preview.ready -and -not $preview.restored) 'Preview was not ready or mutated state'
    Assert-Test ($preview.changes.Count -gt 8) 'Preview machine output did not retain the complete change list'
    foreach ($field in @('action', 'changes', 'conflicts', 'external_actions')) {
        Assert-Test ($preview.PSObject.Properties.Name -contains $field) "Preview machine output omitted $field"
    }
    $display = $preview | Out-String
    Assert-Test ($display -match '(?i)more') 'Default preview display omitted the additional-change hint'
    Assert-Test (-not $display.Contains('also-keep') -and -not $display.Contains('on-request')) 'Default preview display leaked config values'
    $bundle = Join-Path $test 'recovery-bundle'
    $built = & (Join-Path $PSScriptRoot 'build_recovery_bundle.ps1') -OutputDirectory $bundle
    Assert-Test ($built.built -and $built.file_count -eq 10) 'Independent recovery bundle was not built'
    $bundlePreview = & pwsh.exe -NoProfile -File (Join-Path $bundle 'restore.ps1') -Action PreviewRestore -CodexRoot $root 2>&1 | Out-String
    $bundlePreviewExit = $LASTEXITCODE
    Assert-Test ($bundlePreviewExit -eq 0 -and $bundlePreview -match 'PreviewRestore') 'Fresh PowerShell recovery-bundle preview failed'
    $restored = & (Join-Path $bundle 'restore.ps1') -Action RestoreOriginal -CodexRoot $root
    Assert-Test $restored.restored 'Restore failed'
    $text = [IO.File]::ReadAllText($config)
    Assert-Test ($text.Contains('approval_policy = "on-request"') -and $text.Contains('[mcp_servers.later]')) 'Restore lost original or later MCP content'
    $again = & $manage -Action PreviewRestore -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test ($again.ready -and $again.changes.Count -eq 0) 'Restore was not idempotent'

    # File and key conflicts together block every write.
    $root = New-TestRoot 'conflicts'
    Write-TestText (Join-Path $root 'AGENTS.md') "personal original`n"
    Write-TestText (Join-Path $root 'config.toml') "approval_policy = `"on-request`"`n"
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root -InstallPortableSettings
    $agentsPath = Join-Path $root 'AGENTS.md'; $conflictConfig = Join-Path $root 'config.toml'
    Write-TestText $agentsPath "personal post-deploy edit`n"
    $installedConfig = [IO.File]::ReadAllText($conflictConfig).Replace('approval_policy = "never"', 'approval_policy = "always"')
    Write-TestText $conflictConfig $installedConfig
    $otherPath = Join-Path $root 'agents\evidence.toml'; $otherBefore = [IO.File]::ReadAllText($otherPath)
    $blocked = & $manage -Action PreviewRestore -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test (-not $blocked.ready -and $blocked.conflicts -contains 'AGENTS.md' -and $blocked.conflicts -contains 'config.toml:approval_policy') 'Expected conflicts were not reported'
    $threw = $false; try { $null = & $manage -Action RestoreOriginal -ProjectRoot $ProjectRoot -CodexRoot $root } catch { $threw = $true }
    Assert-Test $threw 'Conflicted restore was not rejected'
    Assert-Test ([IO.File]::ReadAllText($agentsPath) -ceq "personal post-deploy edit`n") 'Blocked restore changed personal file'
    Assert-Test ([IO.File]::ReadAllText($conflictConfig) -ceq $installedConfig) 'Blocked restore changed config'
    Assert-Test ([IO.File]::ReadAllText($otherPath) -ceq $otherBefore) 'Blocked restore partially wrote another file'

    # Config originally absent is removed if no user-owned content remains.
    $root = New-TestRoot 'missing-config'
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root -InstallPortableSettings
    $missingRestored = & $manage -Action RestoreOriginal -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test ($missingRestored.restored -and -not (Test-Path -LiteralPath (Join-Path $root 'config.toml'))) 'New config was not removed'
    $missingPreview = & $manage -Action PreviewRestore -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test ($missingPreview.ready -and $missingPreview.changes.Count -eq 0) 'Missing-config restore was not idempotent'
    $originalStateRoot = Join-Path $root 'backups\AgentBase-original'
    $restoreDirectoryCount = @(Get-ChildItem -LiteralPath $originalStateRoot -Directory -Filter 'restore-*').Count
    $null = & $manage -Action RestoreOriginal -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test (@(Get-ChildItem -LiteralPath $originalStateRoot -Directory -Filter 'restore-*').Count -eq $restoreDirectoryCount) 'Repeated missing-config restore created a transaction directory'

    # Skip and any older deployment receipt prevent a later manufactured baseline.
    $root = New-TestRoot 'skip'
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root -OriginalStatePolicy Skip
    Assert-Test (-not (Test-Path -LiteralPath (Join-Path $root 'backups\AgentBase-original\manifest.json'))) 'Skip created a recovery point'
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test (-not (Test-Path -LiteralPath (Join-Path $root 'backups\AgentBase-original\manifest.json'))) 'Auto created a recovery point after Skip'
    $root = New-TestRoot 'legacy-history'
    Write-TestText (Join-Path $root 'backups\AgentBase-legacy\manifest.json') "{`"schema`":`"agentbase.deployment/v6`"}`n"
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test (-not (Test-Path -LiteralPath (Join-Path $root 'backups\AgentBase-original\manifest.json'))) 'Auto created a recovery point after legacy history'

    # Plugin recovery requires an external disable action and explicit declaration.
    $root = New-TestRoot 'plugin'
    Write-TestText (Join-Path $root 'AGENTS.md') "plugin original`n"
    $null = & $manage -Action Deploy -ProjectRoot $ProjectRoot -CodexRoot $root -SkillDeliveryMode Plugin -InstallPortableSettings
    $pluginPreview = & $manage -Action PreviewRestore -ProjectRoot $ProjectRoot -CodexRoot $root
    Assert-Test (-not $pluginPreview.ready -and $pluginPreview.external_actions.Count -eq 1) 'Plugin preview omitted external action'
    $pluginThrew = $false; try { $null = & $manage -Action RestoreOriginal -ProjectRoot $ProjectRoot -CodexRoot $root } catch { $pluginThrew = $true }
    Assert-Test $pluginThrew 'Plugin restore proceeded without PluginDisabled'
    Assert-Test ((& $manage -Action RestoreOriginal -ProjectRoot $ProjectRoot -CodexRoot $root -PluginDisabled).restored) 'Plugin restore failed with PluginDisabled'

    # Inject a second-file write failure into the helper and verify transaction rollback.
    & {
        function Assert-ChildPath([string]$Root, [string]$Path, [string]$Label) { $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'; if (-not [IO.Path]::GetFullPath($Path).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "$Label outside root" } }
        function Get-TextSha256([string]$Text) { $h = [Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-', '') } finally { $h.Dispose() } }
        function Get-TextFileFingerprint([string]$Text) { "FILE|$([Text.Encoding]::UTF8.GetByteCount($Text))|$(Get-TextSha256 $Text)" }
        function Get-PathFingerprint([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { return 'MISSING' }; $item = Get-Item -LiteralPath $Path -Force; "FILE|$($item.Length)|$((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash)" }
        function Write-Utf8NoBomFile([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false))) }
        function Write-JsonFile([string]$Path, [object]$Value) { Write-Utf8NoBomFile $Path (($Value | ConvertTo-Json -Depth 10) + [Environment]::NewLine) }
        function Get-ReversedArray([object]$Values) { [object[]]$items = @($Values); [Array]::Reverse($items); $items }
        . (Join-Path $PSScriptRoot 'portable_config.ps1'); . (Join-Path $PSScriptRoot 'original_config.ps1'); . (Join-Path $PSScriptRoot 'original_state.ps1')
        $failureRoot = New-TestRoot 'injected-failure'; $base = Get-OriginalStateRoot $failureRoot
        Write-TestText (Join-Path $base 'payload\AGENTS.md') "before agents`n"; Write-TestText (Join-Path $base 'payload\config.toml') "before config`n"
        Write-TestText (Join-Path $failureRoot 'AGENTS.md') "deployed agents`n"; Write-TestText (Join-Path $failureRoot 'config.toml') "deployed config`n"
        $state = [pscustomobject]@{ schema = 'agentbase.original-state/v1'; codex_root = $failureRoot; created_at_utc = [DateTime]::UtcNow.ToString('o'); state = 'active'; plugin_used = $false; config_keys = @(); files = @(
            [pscustomobject]@{ path = 'AGENTS.md'; before = Get-PathFingerprint (Join-Path $base 'payload\AGENTS.md'); expected = @((Get-PathFingerprint (Join-Path $failureRoot 'AGENTS.md'))) },
            [pscustomobject]@{ path = 'config.toml'; before = Get-PathFingerprint (Join-Path $base 'payload\config.toml'); expected = @((Get-PathFingerprint (Join-Path $failureRoot 'config.toml'))) }) }
        Save-OriginalState -Root $failureRoot -State $state
        $manifestHash = (Get-FileHash -LiteralPath (Join-Path $base 'manifest.json') -Algorithm SHA256).Hash
        $payloadHash = (Get-FileHash -LiteralPath (Join-Path $base 'payload\AGENTS.md') -Algorithm SHA256).Hash
        $script:restoreCopies = 0
        function Copy-Item {
            param([string]$LiteralPath, [string]$Destination, [switch]$Force)
            $script:restoreCopies++
            if ($script:restoreCopies -eq 2) { throw 'Injected restore write failure' }
            Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
        }
        $injected = $false; try { $null = Invoke-OriginalRestore -Root $failureRoot } catch { $injected = $_.Exception.Message -like '*Injected restore write failure*' }
        Assert-Test $injected 'Controlled failure was not injected'
        Assert-Test ([IO.File]::ReadAllText((Join-Path $failureRoot 'AGENTS.md')) -ceq "deployed agents`n") 'First file was not rolled back'
        Assert-Test ([IO.File]::ReadAllText((Join-Path $failureRoot 'config.toml')) -ceq "deployed config`n") 'Failing file was not rolled back'
        Assert-Test ((Get-FileHash -LiteralPath (Join-Path $base 'manifest.json') -Algorithm SHA256).Hash -ceq $manifestHash) 'Permanent manifest changed'
        Assert-Test ((Get-FileHash -LiteralPath (Join-Path $base 'payload\AGENTS.md') -Algorithm SHA256).Hash -ceq $payloadHash) 'Permanent payload changed'
    }
    [pscustomobject]@{ tests = 'pass'; cases = 7 }
} finally {
    $resolved = [IO.Path]::GetFullPath($test)
    if (-not $resolved.StartsWith([IO.Path]::GetFullPath($sandbox).TrimEnd('\') + '\')) { throw 'Unsafe test cleanup' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
