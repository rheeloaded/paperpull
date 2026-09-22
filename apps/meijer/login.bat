@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9266)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Meijer Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A browser window will open. Then:
echo   1. Sign in to your Meijer account (handle any OTP / puzzle yourself).
echo   2. Open your Purchase History and confirm you see your orders.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Tell Claude you're signed in (or run run_pilot.bat %~1)
echo.
.venv\Scripts\python.exe meijer_receipts.py --open-browser %CFG%
echo.
pause
