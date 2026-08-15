$ErrorActionPreference = "Stop"

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = [Security.Principal.WindowsPrincipal]::new($currentIdentity)
$isAdministrator = $currentPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdministrator) {
    Write-Host "Opening the Windows administrator confirmation dialog."
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath)
    )
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
    exit
}

$activeProfiles = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -ne $null } |
    ForEach-Object {
        Get-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex
    }

if (-not $activeProfiles) {
    throw "No active network connection was found."
}

$publicProfiles = $activeProfiles |
    Where-Object { $_.NetworkCategory -eq "Public" }

if ($publicProfiles) {
    Write-Warning "This allows devices on the same Wi-Fi to connect to this PC."
    Write-Warning "Continue only on a trusted network, such as your home Wi-Fi."
    $confirmation = Read-Host "Change the current Wi-Fi profile to Private? [y/N]"
    if ($confirmation -notmatch "^[yY]$") {
        Write-Host "No changes were made."
        Read-Host "Press Enter to close"
        exit
    }
    foreach ($profile in $publicProfiles) {
        Set-NetConnectionProfile `
            -InterfaceIndex $profile.InterfaceIndex `
            -NetworkCategory Private
    }
}

$ruleName = "Ririmero Mobile - TCP 8000 LocalSubnet"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Set-NetFirewallRule `
        -DisplayName $ruleName `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Private
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8000 `
        -RemoteAddress LocalSubnet `
        -Profile Private | Out-Null
}

Write-Host "Mobile access setup is complete."
Write-Host "Next, run scripts\start_mobile.ps1."
Read-Host "Press Enter to close"
