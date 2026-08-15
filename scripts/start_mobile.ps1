$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment was not found: $pythonPath"
}

$lanAddresses = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -ne $null } |
    ForEach-Object { $_.IPv4Address.IPAddress } |
    Where-Object { $_ -and $_ -notlike "169.254.*" } |
    Select-Object -Unique

$publicProfiles = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -ne $null } |
    ForEach-Object {
        Get-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex
    } |
    Where-Object { $_.NetworkCategory -eq "Public" }

if ($publicProfiles) {
    Write-Warning "The Wi-Fi profile is Public, so mobile access may be blocked."
    Write-Warning "Run .\scripts\setup_mobile_access.ps1 first."
}

Write-Host "Starting Ririmero on the local network. Press Ctrl+C to stop."
Write-Host "PC: http://127.0.0.1:8000"
foreach ($address in $lanAddresses) {
    Write-Host "Mobile: http://${address}:8000"
}
Write-Host "Connect the PC and phone to the same Wi-Fi."

Set-Location -LiteralPath $projectRoot
& $pythonPath -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
