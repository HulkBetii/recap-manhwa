@echo off
title Chrome Profiles Login Helper - Recap Manhwa Tool
color 0E
cd /d "%~dp0"

:MENU
cls
echo ===================================================================
echo               CHROME PROFILES LOGIN / SETUP MANAGER
echo ===================================================================
echo  Select a Chrome profile to open and login to Google / Gemini:
echo.
echo   [1] Open Profile 1  (C:\Data\Profile 1)
echo   [2] Open Profile 2  (C:\Data\Profile 2)
echo   [3] Open Profile 3  (C:\Data\Profile 3)
echo   [4] Open Profile 4  (C:\Data\Profile 4)
echo   [5] Open Profile 5  (C:\Data\Profile 5)
echo.
echo   [A] Open ALL 5 Profiles at once
echo   [0] Exit
echo ===================================================================
set /p CHOICE="Enter your selection (1-5, A, 0): "

set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if "%CHOICE%"=="1" goto OPEN_P1
if "%CHOICE%"=="2" goto OPEN_P2
if "%CHOICE%"=="3" goto OPEN_P3
if "%CHOICE%"=="4" goto OPEN_P4
if "%CHOICE%"=="5" goto OPEN_P5
if /i "%CHOICE%"=="A" goto OPEN_ALL
if "%CHOICE%"=="0" goto EXIT
goto MENU

:OPEN_P1
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 1" "https://gemini.google.com"
goto MENU

:OPEN_P2
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 2" "https://gemini.google.com"
goto MENU

:OPEN_P3
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 3" "https://gemini.google.com"
goto MENU

:OPEN_P4
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 4" "https://gemini.google.com"
goto MENU

:OPEN_P5
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 5" "https://gemini.google.com"
goto MENU

:OPEN_ALL
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 1" "https://gemini.google.com"
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 2" "https://gemini.google.com"
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 3" "https://gemini.google.com"
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 4" "https://gemini.google.com"
start "" "%CHROME_EXE%" --user-data-dir="C:\Data\Profile 5" "https://gemini.google.com"
echo Opened all 5 Chrome Profiles.
pause
goto MENU

:EXIT
exit /b
