@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9269)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Target Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A browser window will open. Then:
echo   1. Sign in to Target (handle any code or puzzle yourself).
echo   2. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   3. Then run run_pilot.bat %~1
echo.
.venv\Scripts\python.exe target_receipts.py --open-browser %CFG%
echo.
pause
