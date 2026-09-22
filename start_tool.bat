@echo off
title Recap Manhwa Tool v2.0 - Server Launcher
color 0B
cd /d "%~dp0"

echo ===================================================================
echo               RECAP MANHWA AUTOMATION TOOL v2.0
echo ===================================================================
echo  [+] Project Directory: %CD%
echo  [+] Default Language : English (Andrew Voice Clone)
echo  [+] Hardware Engine  : NVIDIA RTX 3060 12GB (CUDA FP16)
echo ===================================================================
echo.

:: Open browser after 2 seconds in background
start /min cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

:: Start Python server
echo [*] Starting FastAPI Server on http://localhost:8000 ...
python app.py

if errorlevel 1 (
    echo.
    echo [!] Server exited with an error.
    pause
)
