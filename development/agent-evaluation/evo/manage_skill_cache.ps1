param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Protect', 'Inspect', 'Restore', 'CreateJunction', 'RemoveJunction')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$Target = '',
    [string]$Sddl = ''
)

$ErrorActionPreference = 'Stop'

if ($Action -in @('Protect', 'Inspect')) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Skill cache payload must be a real directory'
    }
    $acl = Get-Acl -LiteralPath $item.FullName
    if ($Action -eq 'Inspect') {
        [ordered]@{ sddl = $acl.Sddl } | ConvertTo-Json -Compress
        exit 0
    }
    $before = $acl.Sddl
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rights = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        $rights,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Deny
    )
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $item.FullName -AclObject $acl
    [ordered]@{ before_sddl = $before; protected_sddl = (Get-Acl -LiteralPath $item.FullName).Sddl } |
        ConvertTo-Json -Compress
    exit 0
}

if ($Action -eq 'Restore') {
    if ([string]::IsNullOrWhiteSpace($Sddl)) { throw 'Restore requires Sddl' }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $acl = Get-Acl -LiteralPath $item.FullName
    $acl.SetSecurityDescriptorSddlForm($Sddl)
    Set-Acl -LiteralPath $item.FullName -AclObject $acl
    [ordered]@{ restored_sddl = (Get-Acl -LiteralPath $item.FullName).Sddl } | ConvertTo-Json -Compress
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Target)) { throw "$Action requires Target" }
$targetFull = [IO.Path]::GetFullPath($Target).TrimEnd('\')

if ($Action -eq 'CreateJunction') {
    $targetItem = Get-Item -LiteralPath $targetFull -Force -ErrorAction Stop
    if (-not $targetItem.PSIsContainer -or ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Skill cache junction target must be a real directory'
    }
    if (Test-Path -LiteralPath $Path) { throw "Skill reference already exists: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $link = New-Item -ItemType Junction -Path $Path -Target $targetFull -ErrorAction Stop
    [ordered]@{ path = $link.FullName; target = $targetFull } | ConvertTo-Json -Compress
    exit 0
}

$linkItem = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
if (-not $linkItem.PSIsContainer -or ($linkItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
    throw 'Managed skill reference is not a directory reparse point'
}
$actualTarget = [IO.Path]::GetFullPath([string]$linkItem.Target).TrimEnd('\')
if (-not $actualTarget.Equals($targetFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Managed skill reference target changed'
}
[IO.Directory]::Delete($linkItem.FullName, $false)
[ordered]@{ removed = $linkItem.FullName; target = $targetFull } | ConvertTo-Json -Compress
