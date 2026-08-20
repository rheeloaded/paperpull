@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9225)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Armed Forces Mutual Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open. Then:
echo   1. Sign in to Armed Forces Mutual (do all the 2FA / verification yourself).
echo   2. Go to your Documents / Statements area and open it.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements, policy documents
echo and tax forms. It NEVER pays a premium, requests or repays a loan,
echo surrenders or withdraws value, changes a beneficiary, or changes
echo any setting.
echo.
.venv\Scripts\python.exe aafmaa_docs.py --open-browser %CFG%
echo.
pause
