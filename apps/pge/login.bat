@echo off
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

set CFG=
if not "%~1"=="" set CFG=--config config.%~1.json

if not exist "%PY%" (
    echo This app is not set up yet - run setup.bat first.
    pause & exit /b 1
)

echo ============================================================
echo PG^&E Documents - sign in
echo ============================================================
echo A normal Chromium window will open. Then:
echo 1. Sign in to PG^&E (do all 2FA / device approval yourself)
echo 2. Go to Billing and payments (your statement history)
echo 3. LEAVE THAT BROWSER WINDOW OPEN - do not close it
echo.

"%PY%" pge_docs.py --open-browser %CFG%
pause
