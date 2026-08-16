@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9227)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  American Express Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to American Express (do all the 2FA / device approval yourself).
echo   2. Go to Statements ^& Activity (statements, year-end summary, tax docs).
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements, year-end summaries, and
echo tax documents. It NEVER pays a bill, transfers a balance, moves money,
echo redeems rewards, or changes any setting.
echo.
.venv\Scripts\python.exe amex_docs.py --open-browser %CFG%
echo.
pause
