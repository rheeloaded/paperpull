@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9261)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  State Farm Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to State Farm (do all the 2FA / device approval yourself).
echo   2. Open your documents or statements page if you know where it is.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  paperpull statefarm diagnose   (a survey for the maintainer)
echo.
echo READ-ONLY: this tool only downloads your statement PDFs. It NEVER
echo transfers, pays, sends money, opens or closes anything, or changes any
echo setting.
echo.
.venv\Scripts\python.exe statefarm_docs.py --open-browser %CFG%
echo.
pause
