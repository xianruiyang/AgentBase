$ErrorActionPreference = 'SilentlyContinue'
$env:PYTHONUTF8 = '1'

$pythonScript = Join-Path $PSScriptRoot 'codex_event_logger.py'
$exitCode = 0

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -X utf8 $pythonScript
    $exitCode = $LASTEXITCODE
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -X utf8 $pythonScript
    $exitCode = $LASTEXITCODE
}

if ($env:CODEX_EVENT_LOGGER_STRICT -eq '1') {
    exit $exitCode
}

exit 0
