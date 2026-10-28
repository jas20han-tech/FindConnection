# Graph RAG Intelligence Platform - Stop Script
# Stops backend (FastAPI/uvicorn) and frontend (Next.js/node)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Graph RAG Intelligence Platform" -ForegroundColor Cyan
Write-Host "  Stopping Backend & Frontend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$Stopped = 0

# Stop processes by port
function Stop-ProcessOnPort {
    param(
        [int]$Port,
        [string]$Name
    )
    
    Write-Host "[STOP] Checking $Name on port $Port..." -ForegroundColor Yellow
    
    $Connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    
    if ($Connections) {
        $Pids = $Connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($ProcessId in $Pids) {
            $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
            if ($Process) {
                Write-Host "[STOP] Stopping $Name (PID: $ProcessId, Name: $($Process.ProcessName))" -ForegroundColor Gray
                Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
                $script:Stopped++
            }
        }
        Write-Host "[OK] Stopped $Name on port $Port" -ForegroundColor Green
    }
    else {
        Write-Host "[SKIP] $Name not running on port $Port" -ForegroundColor Gray
    }
}

# Stop backend on port 8000
Stop-ProcessOnPort -Port 8000 -Name "Backend (FastAPI)"

Write-Host ""

# Stop frontend on port 3000
Stop-ProcessOnPort -Port 3000 -Name "Frontend (Next.js)"

Write-Host ""

# Also stop any remaining node/python/uvicorn processes related to this project
Write-Host "[CLEAN] Looking for related processes..." -ForegroundColor Yellow

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Kill uvicorn processes
$UvicornProcs = Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue
if ($UvicornProcs) {
    foreach ($Proc in $UvicornProcs) {
        Write-Host "[STOP] Stopping uvicorn (PID: $($Proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
        $Stopped++
    }
}

# Kill node processes running next dev in this directory (be careful not to kill other node processes)
$NodeProcs = Get-Process -Name "node" -ErrorAction SilentlyContinue
if ($NodeProcs) {
    foreach ($Proc in $NodeProcs) {
        try {
            $CmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $($Proc.Id)").CommandLine
            if ($CmdLine -like "*$RootDir*" -or $CmdLine -like "*next*") {
                Write-Host "[STOP] Stopping node process (PID: $($Proc.Id))" -ForegroundColor Gray
                Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
                $Stopped++
            }
        }
        catch {
            # Skip if can't get command line
        }
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($Stopped -eq 0) {
    Write-Host "  No processes were found running" -ForegroundColor Yellow
}
else {
    Write-Host "  Stopped $Stopped process(es)" -ForegroundColor Green
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
