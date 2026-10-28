# Graph RAG Intelligence Platform - Start Script
# Starts backend (FastAPI) and frontend (Next.js)

param(
    [switch]$NoBrowser,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Graph RAG Intelligence Platform" -ForegroundColor Cyan
Write-Host "  Starting Backend & Frontend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"

# Check if backend is already running
$BackendRunning = $false
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        $BackendRunning = $true
        Write-Host "[INFO] Backend already running on port $BackendPort" -ForegroundColor Yellow
    }
}
catch {
    $BackendRunning = $false
}

# Check if frontend is already running
$FrontendRunning = $false
try {
    $response = Invoke-WebRequest -Uri "http://localhost:$FrontendPort" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        $FrontendRunning = $true
        Write-Host "[INFO] Frontend already running on port $FrontendPort" -ForegroundColor Yellow
    }
}
catch {
    $FrontendRunning = $false
}

# Start Backend
if (-not $BackendRunning) {
    Write-Host "[START] Starting FastAPI backend on port $BackendPort..." -ForegroundColor Green
    
    $BackendScript = @"
Set-Location '$BackendDir'
`$env:DEMO_MODE = 'true'
`$env:USE_CELERY = 'false'
`$env:PYTHONPATH = '$BackendDir'
uv run uvicorn app.main:app --host 127.0.0.1 --port $BackendPort --reload
"@
    
    $BackendJob = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BackendScript -PassThru -WindowStyle Normal
    Write-Host "[INFO] Backend process started (PID: $($BackendJob.Id))" -ForegroundColor Gray
    
    # Wait for backend to be ready
    Write-Host "[WAIT] Waiting for backend to be ready..." -ForegroundColor Gray
    $MaxWait = 60
    $Waited = 0
    while ($Waited -lt $MaxWait) {
        Start-Sleep -Seconds 2
        $Waited += 2
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host "[OK] Backend is ready!" -ForegroundColor Green
                break
            }
        }
        catch {
            # Still waiting
        }
        if ($Waited % 10 -eq 0) {
            Write-Host "[WAIT] Still waiting... ($Waited/$MaxWait seconds)" -ForegroundColor Gray
        }
    }
    
    if ($Waited -ge $MaxWait) {
        Write-Host "[WARN] Backend may not be fully ready yet. Check the backend window." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[SKIP] Backend already running" -ForegroundColor Gray
}

Write-Host ""

# Start Frontend
if (-not $FrontendRunning) {
    Write-Host "[START] Starting Next.js frontend on port $FrontendPort..." -ForegroundColor Green
    
    $FrontendScript = @"
Set-Location '$FrontendDir'
npm run dev
"@
    
    $FrontendJob = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $FrontendScript -PassThru -WindowStyle Normal
    Write-Host "[INFO] Frontend process started (PID: $($FrontendJob.Id))" -ForegroundColor Gray
    
    # Wait for frontend to be ready
    Write-Host "[WAIT] Waiting for frontend to be ready..." -ForegroundColor Gray
    $MaxWait = 90
    $Waited = 0
    while ($Waited -lt $MaxWait) {
        Start-Sleep -Seconds 3
        $Waited += 3
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$FrontendPort" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host "[OK] Frontend is ready!" -ForegroundColor Green
                break
            }
        }
        catch {
            # Still waiting
        }
        if ($Waited % 15 -eq 0) {
            Write-Host "[WAIT] Still waiting... ($Waited/$MaxWait seconds)" -ForegroundColor Gray
        }
    }
    
    if ($Waited -ge $MaxWait) {
        Write-Host "[WARN] Frontend may not be fully ready yet. Check the frontend window." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[SKIP] Frontend already running" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Project Started!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Frontend: http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "  Backend:  http://localhost:$BackendPort" -ForegroundColor White
Write-Host "  API Docs: http://localhost:$BackendPort/docs" -ForegroundColor White
Write-Host "  Health:   http://localhost:$BackendPort/health" -ForegroundColor White
Write-Host ""
Write-Host "  Press any key to open in browser, or close this window..." -ForegroundColor Gray

if (-not $NoBrowser) {
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Start-Process "http://localhost:$FrontendPort"
}
else {
    Start-Sleep -Seconds 2
}
