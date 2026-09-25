# Start the local app (API, Job runner, and built UI share this process).
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path "frontend\dist\index.html")) {
    throw "Built frontend is missing. Run .\install.ps1 first."
}

$url = "http://127.0.0.1:8000"
$alreadyRunning = $false
try {
    Invoke-RestMethod "$url/api/health" -TimeoutSec 2 | Out-Null
    $alreadyRunning = $true
} catch { }

if (-not $alreadyRunning) {
    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $server = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Normal
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($server.HasExited) { throw "Transcriber exited before the server became ready." }
        try {
            Invoke-RestMethod "$url/api/health" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw "Transcriber did not become ready within 90 seconds." }
}

Start-Process $url
Write-Host "Transcriber is running at $url. Close its Python window to stop it."
