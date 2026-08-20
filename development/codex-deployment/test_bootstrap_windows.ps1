[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bootstrap = Join-Path $scriptRoot "bootstrap_windows.ps1"
$powershellExe = (Get-Process -Id $PID).Path

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-BootstrapProcess {
    param(
        [string[]]$Arguments,
        [switch]$EmptyPath
    )

    $previousPath = $env:PATH
    try {
        if ($EmptyPath) {
            $env:PATH = ""
        }
        $output = @(& $powershellExe -NoLogo -NoProfile -NonInteractive -File $bootstrap @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:PATH = $previousPath
    }
    return [pscustomobject]@{
        exit_code = $exitCode
        text = ($output -join [Environment]::NewLine).Trim()
    }
}

$modelReady = Invoke-BootstrapProcess -Arguments @("-Action", "Check")
Assert-True ($modelReady.exit_code -eq 0) "model readiness check failed on the prepared host"
Assert-True ($modelReady.text -eq "{ready:true}") "default readiness output is not the compact model receipt"

$machineReady = Invoke-BootstrapProcess -Arguments @("-Action", "Check", "-View", "Machine")
Assert-True ($machineReady.exit_code -eq 0) "machine readiness check failed on the prepared host"
$machineReadyResult = $machineReady.text | ConvertFrom-Json
Assert-True ([bool]$machineReadyResult.ready) "machine readiness result is not ready"
Assert-True (@($machineReadyResult.tools).Count -eq 8) "machine readiness result omitted prerequisite states"
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$machineReadyResult.tools[0].package_id)) "machine readiness result omitted package identity"
$packageIds = @($machineReadyResult.tools | ForEach-Object { [string]$_.package_id })
Assert-True ($packageIds -contains "BenBoyter.scc") "machine readiness result omitted the scc package identity"
Assert-True ($packageIds -contains "sharkdp.hyperfine") "machine readiness result omitted the hyperfine package identity"
Assert-True ($packageIds -contains "@openai/codex@0.148.0") "machine readiness result omitted the isolated Codex CLI package identity"
$codexState = @($machineReadyResult.tools | Where-Object { [string]$_.name -eq "Codex CLI" })[0]
Assert-True ([bool]$codexState.isolation_options_supported) "Codex CLI does not expose the isolated exec options required by routing evaluation"
Assert-True ([bool]$codexState.path_precedes_windowsapps) "Codex CLI user npm prefix does not precede WindowsApps in the persisted user PATH"
Assert-True (-not ([string]$codexState.path).Contains("\WindowsApps\", [StringComparison]::OrdinalIgnoreCase)) "Codex CLI readiness selected the package-identity-protected WindowsApps binary"

$modelMissing = Invoke-BootstrapProcess -Arguments @("-Action", "Check") -EmptyPath
Assert-True ($modelMissing.exit_code -eq 1) "missing prerequisites did not retain the check failure exit code"
Assert-True ($modelMissing.text.StartsWith("{ready:false tools:[")) "missing prerequisites did not produce the compact model diagnosis"
Assert-True ($modelMissing.text.Contains('next:"rerun with -Action Install"')) "model diagnosis omitted the recovery action"
Assert-True ($modelMissing.text.Contains("{name:fd next:install}")) "model diagnosis did not distinguish a missing tool from an outdated tool"
Assert-True ($modelMissing.text.Contains("{name:scc next:install}")) "model diagnosis omitted the missing scc recovery"
Assert-True ($modelMissing.text.Contains("{name:hyperfine next:install}")) "model diagnosis omitted the missing hyperfine recovery"
Assert-True (-not $modelMissing.text.Contains("package_id") -and -not $modelMissing.text.Contains("path:")) "model diagnosis exposed machine-only prerequisite fields"

$machineMissing = Invoke-BootstrapProcess -Arguments @("-Action", "Check", "-View", "Machine") -EmptyPath
Assert-True ($machineMissing.exit_code -eq 1) "machine missing-prerequisite check lost the failure exit code"
$machineMissingResult = $machineMissing.text | ConvertFrom-Json
Assert-True (-not [bool]$machineMissingResult.ready) "machine missing-prerequisite result incorrectly reported readiness"
$unsupportedTools = @($machineMissingResult.tools | Where-Object { -not [bool]$_.supported })
Assert-True ($unsupportedTools.Count -ge 1) "machine missing-prerequisite result omitted unsupported tools"

$modelInstallError = Invoke-BootstrapProcess -Arguments @("-Action", "Install") -EmptyPath
Assert-True ($modelInstallError.exit_code -eq 2) "bootstrap operation failure lost its error exit code"
Assert-True ($modelInstallError.text.StartsWith("{ready:false error:")) "bootstrap operation failure was not compacted"
Assert-True (-not $modelInstallError.text.Contains("ScriptStackTrace")) "bootstrap model failure exposed a PowerShell stack"

$machineInstallError = Invoke-BootstrapProcess -Arguments @("-Action", "Install", "-View", "Machine") -EmptyPath
Assert-True ($machineInstallError.exit_code -eq 2) "bootstrap machine failure lost its error exit code"
$machineInstallErrorResult = $machineInstallError.text | ConvertFrom-Json
Assert-True (-not [bool]$machineInstallErrorResult.ready -and $machineInstallErrorResult.action -eq "Install") "bootstrap machine failure lost the structured error contract"

"tests : pass"
exit 0
