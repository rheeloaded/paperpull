@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9252)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  AT&T Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to AT&T (do all the 2FA / device approval yourself).
echo   2. Open your billing page (myAT&T, Billing, bill history).
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  paperpull att diagnose   (a survey for the maintainer)
echo.
echo READ-ONLY: this tool only downloads your bill PDFs. It NEVER pays a
echo bill, changes your plan, enrolls in autopay/paperless, or changes any
echo setting.
echo.
.venv\Scripts\python.exe att_docs.py --open-browser %CFG%
echo.
pause
