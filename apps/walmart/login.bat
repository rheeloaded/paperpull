@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9222)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Walmart Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to Walmart (handle any "Robot or human?" check).
echo   2. Go to walmart.com/orders and confirm you see the orders.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run run_pilot.bat %~1
echo.
.venv\Scripts\python.exe walmart_receipts.py --open-browser %CFG%
echo.
pause
