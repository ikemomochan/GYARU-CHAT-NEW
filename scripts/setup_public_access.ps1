$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$toolDirectory = Join-Path $projectRoot ".tools"
$cloudflaredPath = Join-Path $toolDirectory "cloudflared.exe"

function Assert-CloudflareSignature {
    param([Parameter(Mandatory = $true)][string]$Path)

    $signature = Get-AuthenticodeSignature -FilePath $Path
    $subject = $signature.SignerCertificate.Subject
    if (
        $signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid `
        -or $subject -notmatch 'O="Cloudflare, Inc\."'
    ) {
        throw "The downloaded cloudflared executable does not have a valid Cloudflare signature."
    }
}

if (Test-Path -LiteralPath $cloudflaredPath) {
    Assert-CloudflareSignature -Path $cloudflaredPath
    Write-Host "cloudflared is already available: $cloudflaredPath"
    & $cloudflaredPath --version
    exit
}

$architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
$assetName = switch ($architecture.ToString()) {
    "X64" { "cloudflared-windows-amd64.exe" }
    "Arm64" { "cloudflared-windows-arm64.exe" }
    "X86" { "cloudflared-windows-386.exe" }
    default { throw "Unsupported Windows architecture: $architecture" }
}

$downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/$assetName"
$temporaryPath = "$cloudflaredPath.download"

New-Item -ItemType Directory -Path $toolDirectory -Force | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "Downloading Cloudflare Tunnel from the official release..."
try {
    Invoke-WebRequest `
        -Uri $downloadUrl `
        -OutFile $temporaryPath `
        -UseBasicParsing
    Assert-CloudflareSignature -Path $temporaryPath
    Move-Item `
        -LiteralPath $temporaryPath `
        -Destination $cloudflaredPath `
        -Force
} finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

if (-not (Test-Path -LiteralPath $cloudflaredPath)) {
    throw "cloudflared download did not create $cloudflaredPath"
}

Write-Host "cloudflared setup is complete: $cloudflaredPath"
& $cloudflaredPath --version
Write-Host "Next: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_public.ps1"
