@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9235)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Discover Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your Edge or Chrome will open. Then:
echo   1. Sign in to Discover (do all the 2FA / verification yourself).
echo   2. Go to your Documents / Statements area and open it.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements.
echo It NEVER pays your bill, sets up autopay, transfers a balance,
echo takes a cash advance, redeems Cashback Bonus or Miles, freezes
echo or replaces your card, or changes any account setting.
echo.
.venv\Scripts\python.exe discovercard_docs.py --open-browser %CFG%
echo.
pause
