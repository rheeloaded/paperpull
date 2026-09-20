@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9256)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Citi Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to Citi (do all the 2FA / device approval yourself).
echo   2. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   3. Then run:  paperpull citi pilot   (the five newest statements)
echo.
echo READ-ONLY: this tool only downloads your statement PDFs. It NEVER
echo pays, transfers, redeems, requests anything, or changes any setting.
echo.
.venv\Scripts\python.exe citi_docs.py --open-browser %CFG%
echo.
pause
