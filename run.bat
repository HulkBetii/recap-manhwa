@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

:MENU
cls
echo ===================================================
echo  Manhwa Recap Tool - Windows Startup Manager
echo ===================================================
echo  1. Start Server (Production Mode)
echo  2. Start Server (Development Mode - Auto reload)
echo  3. Stop Server (Free port 8000)
echo  4. Run PyTorch GPU/CUDA Diagnostics
echo  5. Exit
echo ===================================================
set /p CHOICE="Enter choice (1-5): "

if "%CHOICE%"=="1" goto START_PROD
if "%CHOICE%"=="2" goto START_DEV
if "%CHOICE%"=="3" goto STOP_SERVER
if "%CHOICE%"=="4" goto DIAGNOSTICS
if "%CHOICE%"=="5" goto EXIT
goto MENU

:START_PROD
echo.
echo Checking port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    echo Port 8000 is in use by PID %%a. Killing old process first...
    taskkill /f /pid %%a
)
echo Starting server in Production Mode...
if exist ".venv" (
    call .venv\Scripts\activate.bat
)
python app.py
pause
goto MENU

:START_DEV
echo.
echo Checking port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    echo Port 8000 is in use by PID %%a. Killing old process first...
    taskkill /f /pid %%a
)
echo Starting server in Development Mode (with reload)...
if exist ".venv" (
    call .venv\Scripts\activate.bat
)
uvicorn app:app --host 127.0.0.1 --port 8000 --reload --reload-exclude downloads --reload-exclude static --reload-exclude tasks_db.json
pause
goto MENU

:STOP_SERVER
echo.
set FOUND=0
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a
    set FOUND=1
)
if "!FOUND!"=="0" (
    echo No active process found listening on port 8000.
) else (
    echo Server stopped successfully.
)
pause
goto MENU

:DIAGNOSTICS
echo.
echo =========================================
echo  Checking PyTorch ^& CUDA status...
echo =========================================
if exist ".venv" (
    call .venv\Scripts\activate.bat
)
python -c "import torch; print('PyTorch version:', torch.__version__); print('CUDA available :', torch.cuda.is_available()); print('GPU Device Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None'); print('VRAM Total     :', round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), 'GB' if torch.cuda.is_available() else 'None')"
echo =========================================
pause
goto MENU

:EXIT
echo Goodbye!
exit /b
