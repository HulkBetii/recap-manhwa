# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

function Show-Menu {
    Clear-Host
    Write-Host "===================================================" -ForegroundColor Green
    Write-Host "  Manhwa Recap Tool - PowerShell Startup Manager" -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Green
    Write-Host "  1. Start Server (Production Mode)"
    Write-Host "  2. Start Server (Development Mode - Auto reload)"
    Write-Host "  3. Stop Server (Free port 8000)"
    Write-Host "  4. Run PyTorch GPU/CUDA Diagnostics"
    Write-Host "  5. Exit"
    Write-Host "===================================================" -ForegroundColor Green
}

function Stop-ServerOnPort8000 {
    Write-Host "Checking port 8000..." -ForegroundColor Cyan
    $processes = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($processes) {
        $pids = $processes.OwningProcess | Select-Object -Unique
        foreach ($pid in $pids) {
            Write-Host "Port 8000 is in use by PID $pid. Killing process..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
        Write-Host "Port 8000 is now free." -ForegroundColor Green
    } else {
        Write-Host "Port 8000 is clean." -ForegroundColor Green
    }
}

function Run-Diagnostics {
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host " Checking PyTorch & CUDA status..." -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    python -c "
import torch
print('PyTorch version :', torch.__version__)
print('CUDA available  :', torch.cuda.is_available())
if torch.cuda.is_available():
    print('GPU Device Name :', torch.cuda.get_device_name(0))
    print('VRAM Available  :', round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), 'GB')
else:
    print('WARNING: PyTorch is NOT utilizing GPU/CUDA. Running on CPU instead.')
"
    Write-Host "=========================================" -ForegroundColor Green
}

# Check if .venv exists and activate
if (Test-Path -Path ".venv") {
    Write-Host "Activating virtual environment (.venv)..." -ForegroundColor Cyan
    & .venv\Scripts\Activate.ps1
}

# Main loop
do {
    Show-Menu
    $choice = Read-Host "Enter choice (1-5)"
    switch ($choice) {
        "1" {
            Stop-ServerOnPort8000
            Write-Host "Starting server in Production Mode..." -ForegroundColor Cyan
            python app.py
            Read-Host "Press Enter to continue"
        }
        "2" {
            Stop-ServerOnPort8000
            Write-Host "Starting server in Development Mode..." -ForegroundColor Cyan
            uvicorn app:app --host 127.0.0.1 --port 8000 --reload --reload-exclude downloads --reload-exclude static --reload-exclude tasks_db.json
            Read-Host "Press Enter to continue"
        }
        "3" {
            Stop-ServerOnPort8000
            Read-Host "Press Enter to continue"
        }
        "4" {
            Run-Diagnostics
            Read-Host "Press Enter to continue"
        }
        "5" {
            Write-Host "Goodbye!" -ForegroundColor Cyan
            break
        }
    }
} while ($true)
