@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ===================================================
echo   TRINH DANG NHAP CHROME PROFILES CHO GEMINI
echo ===================================================
echo.
echo Danh sach Profile hien co trong thu muc Profiles:
set COUNT=0
for /d %%D in (Profiles\Profile_*) do (
    set /a COUNT+=1
    echo   - %%~nxD
)
echo.
set /p PROF_NUM="Nhap so Profile ban muon dang nhap (Vi du: 1, 2, 3...): "
if "%PROF_NUM%"=="" set PROF_NUM=1

echo.
echo Dang khoi chay Chrome cho Profile %PROF_NUM%...
if exist ".venv" (
    call .venv\Scripts\activate.bat
)
python "%~dp0login_profile.py" --profile %PROF_NUM%

echo.
pause
