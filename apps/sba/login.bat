@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9254)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  SBA Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to SBA (do all the 2FA / device approval yourself).
echo   2. Open your loan's Statements page in the MySBA Loan Portal.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  paperpull sba diagnose   (a survey for the maintainer)
echo.
echo READ-ONLY: this tool only downloads your statement PDFs. It NEVER
echo makes or schedules a payment, applies or asks for anything, or changes
echo any setting.
echo.
.venv\Scripts\python.exe sba_docs.py --open-browser %CFG%
echo.
pause
