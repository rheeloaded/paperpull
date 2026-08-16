@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9228)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Dominion Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to Dominion (do all the 2FA / device approval yourself).
echo   2. Go to Account -^> Reports ^& statements (Documents / Tax center).
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements and tax documents.
echo It NEVER buys, sells, trades, transfers, withdraws, moves crypto, or
echo changes any setting.
echo.
.venv\Scripts\python.exe dominion_docs.py --open-browser %CFG%
echo.
pause
