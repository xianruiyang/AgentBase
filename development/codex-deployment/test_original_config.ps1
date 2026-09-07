$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'portable_config.ps1')
. (Join-Path $PSScriptRoot 'original_config.ps1')

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Message)
    if (($Actual | ConvertTo-Json -Compress -Depth 10) -cne ($Expected | ConvertTo-Json -Compress -Depth 10)) {
        throw "$Message`nExpected: $($Expected | ConvertTo-Json -Compress -Depth 10)`nActual: $($Actual | ConvertTo-Json -Compress -Depth 10)"
    }
}

$keys = @(
    [pscustomobject]@{ table = ''; key = 'approval_policy' },
    [pscustomobject]@{ table = 'features'; key = 'multi_agent' }
)
$original = @'
approval_policy = "on-request"

[features]
multi_agent = false

[mcp_servers.local]
command = "host.exe"
'@ + "`n"
$expected = @'
approval_policy = "never"

[features]
multi_agent = true
new_owned = "ignored"

[mcp_servers.local]
command = "host.exe"
'@ + "`n"
$current = @'
approval_policy = "never"

[features]
multi_agent = true
new_owned = "ignored"

[mcp_servers.local]
command = "host.exe"
args = ["--user-added"]
'@ + "`n"

$plan = Get-OriginalConfigRestorePlan -OriginalText $original -ExpectedText $expected -CurrentText $current -Keys $keys
Assert-Equal $plan.conflicts @() 'Expected an unconflicted restore.'
Assert-Equal $plan.text (@'
approval_policy = "on-request"

[features]
multi_agent = false
new_owned = "ignored"

[mcp_servers.local]
command = "host.exe"
args = ["--user-added"]
'@ + "`n") 'Existing keys should be restored while unowned content is preserved.'

$deletePlan = Get-OriginalConfigRestorePlan -OriginalText "[features]`n" -ExpectedText "[features]`nprompt_suggestions = false`n" -CurrentText "[features]`nprompt_suggestions = false`nother = true`n" -Keys @([pscustomobject]@{ table = 'features'; key = 'prompt_suggestions' })
Assert-Equal $deletePlan.text "[features]`nother = true`n" 'A newly managed key should be removed.'

$conflictPlan = Get-OriginalConfigRestorePlan -OriginalText $original -ExpectedText $expected -CurrentText ($current.Replace('approval_policy = "never"', 'approval_policy = "always"')) -Keys $keys
Assert-Equal $conflictPlan.conflicts @('approval_policy') 'A user-modified key should be reported without its value.'
if (-not $conflictPlan.text.Contains('approval_policy = "always"')) { throw 'A conflicting assignment was modified.' }
if (-not $conflictPlan.text.Contains('multi_agent = false')) { throw 'An independent safe assignment was not restored.' }

$idempotentPlan = Get-OriginalConfigRestorePlan -OriginalText $original -ExpectedText $expected -CurrentText $plan.text -Keys $keys
Assert-Equal $idempotentPlan.conflicts @() 'An already restored config should not conflict.'
Assert-Equal $idempotentPlan.text $plan.text 'An already restored config should remain unchanged.'

$multilineRejected = $false
try {
    $null = Get-OriginalConfigAssignment -Text "[features]`nitems = [`n  1,`n]`n" -Table 'features' -Key 'items'
}
catch {
    $multilineRejected = $_.Exception.Message -like '*multiline managed value*'
}
if (-not $multilineRejected) { throw 'A multiline managed value was not rejected safely.' }

[pscustomobject]@{ passed = $true; cases = 6 }
