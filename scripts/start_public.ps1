param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$localUrl = "http://127.0.0.1:$Port"
$startedServer = $null

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment was not found: $pythonPath"
}

function Find-Cloudflared {
    $repositoryTool = Join-Path $projectRoot ".tools\cloudflared.exe"
    if (Test-Path -LiteralPath $repositoryTool) {
        return $repositoryTool
    }

    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $wingetLink = Join-Path `
        $env:LOCALAPPDATA `
        "Microsoft\WinGet\Links\cloudflared.exe"
    if (Test-Path -LiteralPath $wingetLink) {
        return $wingetLink
    }

    return $null
}

function Test-RirimeroServer {
    try {
        $health = Invoke-RestMethod `
            -Uri "$localUrl/api/health" `
            -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

$cloudflaredPath = Find-Cloudflared
if (-not $cloudflaredPath) {
    throw "cloudflared was not found. Run .\scripts\setup_public_access.ps1 first."
}

if (-not (Test-RirimeroServer)) {
    $logDirectory = Join-Path $projectRoot ".data"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutPath = Join-Path $logDirectory "public-server-$timestamp.out.log"
    $stderrPath = Join-Path $logDirectory "public-server-$timestamp.err.log"

    Write-Host "Starting Ririmero locally at $localUrl ..."
    $startedServer = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @(
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1",
            "--port", $Port
        ) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $serverReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($startedServer.HasExited) {
            break
        }
        if (Test-RirimeroServer) {
            $serverReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $serverReady) {
        if (-not $startedServer.HasExited) {
            Stop-Process -Id $startedServer.Id
        }
        if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Tail 30
        }
        throw "Ririmero did not start. Check $stderrPath"
    }
} else {
    Write-Host "Using the Ririmero server already running at $localUrl"
}

Write-Host ""
Write-Host "A temporary public URL ending in trycloudflare.com will appear below."
Write-Host "Share only that HTTPS URL. Press Ctrl+C to close public access."
Write-Warning "Anyone who knows the URL can access the experiment. Do not share the admin code."
Write-Host ""

try {
    & $cloudflaredPath tunnel --url $localUrl
} finally {
    if ($startedServer -and -not $startedServer.HasExited) {
        Write-Host "Stopping the local Ririmero server started by this script..."
        Stop-Process -Id $startedServer.Id
    }
}
