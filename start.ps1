# Transcriber start script for Windows
# Starts all services in separate windows.
# Usage: powershell -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host ""
Write-Host "Starting Transcriber services..." -ForegroundColor Cyan
Write-Host ""

# Make sure Docker Desktop is running before we try to compose anything.
# Native stderr can trip $ErrorActionPreference='Stop', so isolate the call.
function Test-DockerRunning {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & docker info *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

if (-not (Test-DockerRunning)) {
    Write-Host "Docker engine not responding. Starting Docker Desktop..." -ForegroundColor Yellow
    $dockerDesktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Start-Process $dockerDesktop
        $timeout = 90
        $elapsed = 0
        while (-not (Test-DockerRunning) -and $elapsed -lt $timeout) {
            Start-Sleep -Seconds 2
            $elapsed += 2
            Write-Host "." -NoNewline
        }
        Write-Host ""
        if (Test-DockerRunning) {
            Write-Host "Docker Desktop is ready." -ForegroundColor Green
        } else {
            Write-Host "Docker Desktop did not become ready in ${timeout}s. Continuing - compose may fail." -ForegroundColor Red
        }
    } else {
        Write-Host "Docker Desktop not found at '$dockerDesktop'. Skipping auto-start." -ForegroundColor Red
    }
}

# Bring up Postgres + Redis
try {
    docker compose --project-directory "$ProjectRoot" up -d 2>$null
} catch {
    Write-Host "Docker compose already running or provided status output." -ForegroundColor Yellow
}

# Backend
Start-Process powershell -ArgumentList "-NoExit", "-File", "$ProjectRoot\_start_backend.ps1" -WindowStyle Normal
Write-Host "[1/3] Backend started (port 8000)" -ForegroundColor Green

# Celery
Start-Process powershell -ArgumentList "-NoExit", "-File", "$ProjectRoot\_start_celery.ps1" -WindowStyle Normal
Write-Host "[2/3] Celery worker started" -ForegroundColor Green

# Frontend
Start-Process powershell -ArgumentList "-NoExit", "-File", "$ProjectRoot\_start_frontend.ps1" -WindowStyle Normal
Write-Host "[3/3] Frontend started (port 5174)" -ForegroundColor Green

Write-Host ""
Write-Host "All services running!" -ForegroundColor Green
Write-Host "  App: http://localhost:5174"
Write-Host ""
Write-Host "Each service runs in its own window. Close the windows to stop."
Write-Host ""

# Open browser after a short delay
Start-Sleep -Seconds 4
Start-Process "http://localhost:5174"
