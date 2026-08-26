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
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $processIds = @($listeners.OwningProcess | Select-Object -Unique)
        foreach ($processId in $processIds) {
            Write-Host "Port 8000 is in use by PID $processId. Stopping process..." -ForegroundColor Yellow
            try {
                Stop-Process -Id $processId -Force -ErrorAction Stop
            } catch {
                Write-Host "Could not stop PID $processId`: $($_.Exception.Message)" -ForegroundColor Red
                return $false
            }
        }

        $deadline = (Get-Date).AddSeconds(5)
        do {
            Start-Sleep -Milliseconds 250
            $remainingListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        } while ($remainingListener -and (Get-Date) -lt $deadline)

        if ($remainingListener) {
            Write-Host "Port 8000 is still occupied. Server startup cancelled." -ForegroundColor Red
            return $false
        }

        Write-Host "Port 8000 is now free." -ForegroundColor Green
    } else {
        Write-Host "Port 8000 is clean." -ForegroundColor Green
    }

    return $true
}

function Run-Diagnostics {
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host " Checking PyTorch & CUDA status..." -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    & $pythonExe -c "
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

# Always launch through the project virtual environment when available.
$venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonExe = $venvPython
    Write-Host "Using project virtual environment (.venv)." -ForegroundColor Cyan
} else {
    $pythonExe = "python"
    Write-Host "WARNING: .venv was not found. Falling back to system Python." -ForegroundColor Yellow
}

# Main loop
do {
    Show-Menu
    $choice = Read-Host "Enter choice (1-5)"
    switch ($choice) {
        "1" {
            $portReady = Stop-ServerOnPort8000
            if ($portReady) {
                Write-Host "Starting server in Production Mode..." -ForegroundColor Cyan
                & $pythonExe app.py
            }
            Read-Host "Press Enter to continue"
        }
        "2" {
            $portReady = Stop-ServerOnPort8000
            if ($portReady) {
                Write-Host "Starting server in Development Mode..." -ForegroundColor Cyan
                & $pythonExe -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload --reload-exclude downloads --reload-exclude static --reload-exclude tasks_db.json
            }
            Read-Host "Press Enter to continue"
        }
        "3" {
            $null = Stop-ServerOnPort8000
            Read-Host "Press Enter to continue"
        }
        "4" {
            Run-Diagnostics
            Read-Host "Press Enter to continue"
        }
        "5" {
            Write-Host "Goodbye!" -ForegroundColor Cyan
            return
        }
    }
} while ($true)
