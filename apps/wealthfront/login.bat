@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9224)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Wealthfront Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to Wealthfront (do the 2FA yourself).
echo   2. Open your Documents / Statements page.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run run_pilot.bat %~1
echo.
echo READ-ONLY: this tool only downloads statements and tax forms.
echo It never transfers money, trades, or changes any setting.
echo.
.venv\Scripts\python.exe wealthfront_docs.py --open-browser %CFG%
echo.
pause
