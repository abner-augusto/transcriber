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
if (Test-DockerRunning) {
    Write-Host "Checking Docker containers..." -ForegroundColor Cyan

    $definedServices = @(& docker compose --project-directory "$ProjectRoot" config --services 2>$null)
    if (-not $definedServices -or $definedServices.Count -eq 0) {
        $definedServices = @("postgres", "redis")
    }

    $existingServices = @(& docker compose --project-directory "$ProjectRoot" ps -a --format "{{.Service}}" 2>$null)
    $missingServices = @($definedServices | Where-Object { $_ -and ($existingServices -notcontains $_) })

    if ($missingServices.Count -gt 0) {
        Write-Host "Container(s) not found for: $($missingServices -join ', '). Creating new instance(s)..." -ForegroundColor Yellow
        docker compose --project-directory "$ProjectRoot" up -d
    } else {
        $runningServices = @(& docker compose --project-directory "$ProjectRoot" ps --status running --format "{{.Service}}" 2>$null)
        $stoppedServices = @($definedServices | Where-Object { $_ -and ($runningServices -notcontains $_) })

        if ($stoppedServices.Count -gt 0) {
            Write-Host "Container(s) exist but are stopped ($($stoppedServices -join ', ')). Starting existing instance(s)..." -ForegroundColor Yellow
            docker compose --project-directory "$ProjectRoot" start
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Starting existing containers failed. Retrying with 'docker compose up -d'..." -ForegroundColor Yellow
                docker compose --project-directory "$ProjectRoot" up -d
            }
        } else {
            Write-Host "Docker container(s) already exist and are running." -ForegroundColor Green
        }
    }

    # Wait for database container to be ready
    Write-Host "Waiting for database to be ready..." -ForegroundColor Cyan
    $waitTimeout = 15
    $waitElapsed = 0
    while ($waitElapsed -lt $waitTimeout) {
        $pgStatus = (& docker compose --project-directory "$ProjectRoot" ps postgres --format "{{.Status}}" 2>$null)
        if ($pgStatus -match "healthy") {
            Write-Host "Database is ready." -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 1
        $waitElapsed += 1
    }
} else {
    Write-Host "Docker engine is not responding. Continuing - backend or services may fail to connect." -ForegroundColor Red
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
