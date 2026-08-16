@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9225)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  USAA Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to USAA (do all the 2FA / verification yourself).
echo   2. Go to your Documents / Statements area and open it.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements, tax forms, and
echo insurance documents. It NEVER transfers money, pays bills, uses
echo Zelle, deposits, trades, files claims, or changes any setting.
echo.
.venv\Scripts\python.exe usaa_docs.py --open-browser %CFG%
echo.
pause
