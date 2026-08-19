@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9238)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  U.S. Bank Documents - sign in
echo ============================================================
echo READ-ONLY: downloads card statements. It never pays a bill, transfers a
echo balance, redeems rewards, or changes a setting. Run diagnose any time
echo for a safe look - it reads the page and downloads nothing.
echo Your Edge or Chrome will open. Sign in to U.S. Bank yourself (all 2FA),
echo then open Statements and documents - and LEAVE THAT WINDOW OPEN.
if not "%~1"=="" echo Account: %~1
echo.
echo   3. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
.venv\Scripts\python.exe usbank_docs.py --open-browser %CFG%
echo.
pause
