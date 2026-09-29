@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9281)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Uber Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account %~1
echo.
echo A browser window will open on your Uber trips.
echo   1. Sign in there, and answer any code Uber sends yourself.
echo   2. For Uber Eats orders, open ubereats.com/orders in a second tab
echo      and sign in there too. It is a separate sign-in.
echo   3. LEAVE THAT BROWSER WINDOW OPEN, do not close it.
echo   4. Then run the pilot, paperpull uber pilot
echo.
.venv\Scripts\python.exe uber_receipts.py --open-browser %CFG%
echo.
pause
