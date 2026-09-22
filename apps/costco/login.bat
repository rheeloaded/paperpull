@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9268)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Costco Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A browser window will open. Then:
echo   1. Sign in to your Costco account (handle any code or passkey yourself).
echo   2. Open Orders ^& Purchases and confirm you can see your purchases.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Run:  paperpull costco record   and click your way to one receipt.
echo.
.venv\Scripts\python.exe costco_receipts.py --open-browser %CFG%
echo.
pause
