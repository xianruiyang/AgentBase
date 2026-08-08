param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("enable", "disable", "status", "default-on", "default-off")]
    [string]$Action,

    [string]$Id,
    [string]$ProjectRoot,
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Get-Location).Path
} else {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot ".codex\qq-hook-settings.json"
}

function New-DefaultConfig {
    $skillRoot = Split-Path -Parent $PSScriptRoot
    $templatePath = Join-Path $skillRoot "templates\qq-hook-settings.template.json"
    if (Test-Path -LiteralPath $templatePath) {
        return Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    throw "Template not found: $templatePath"
}

function Ensure-List {
    param($Object, [string]$Property)
    if ($null -eq $Object.PSObject.Properties[$Property]) {
        Add-Member -InputObject $Object -MemberType NoteProperty -Name $Property -Value @()
    }
    if ($null -eq $Object.$Property) {
        $Object.$Property = @()
    }
}

function Add-Unique {
    param($Object, [string]$Property, [string]$Value)
    Ensure-List $Object $Property
    $items = @($Object.$Property | Where-Object { $_ -ne $Value })
    $Object.$Property = @($items + $Value)
}

function Remove-Value {
    param($Object, [string]$Property, [string]$Value)
    Ensure-List $Object $Property
    $Object.$Property = @($Object.$Property | Where-Object { $_ -ne $Value })
}

$dir = Split-Path -Parent $ConfigPath
if (-not [string]::IsNullOrWhiteSpace($dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

if (Test-Path -LiteralPath $ConfigPath) {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $config = New-DefaultConfig
}

foreach ($property in @("enabled_thread_ids", "disabled_thread_ids", "enabled_thread_names", "disabled_thread_names")) {
    Ensure-List $config $property
}

switch ($Action) {
    "default-on" {
        $config.default_enabled = $true
    }
    "default-off" {
        $config.default_enabled = $false
    }
    "enable" {
        if ([string]::IsNullOrWhiteSpace($Id)) {
            throw "enable requires -Id. Title-based enable is intentionally not used."
        }
        Remove-Value $config "disabled_thread_ids" $Id
        Add-Unique $config "enabled_thread_ids" $Id
    }
    "disable" {
        if ([string]::IsNullOrWhiteSpace($Id)) {
            throw "disable requires -Id. Title-based disable is intentionally not used."
        }
        Remove-Value $config "enabled_thread_ids" $Id
        Add-Unique $config "disabled_thread_ids" $Id
    }
    "status" {}
}

$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
$config | ConvertTo-Json -Depth 20
