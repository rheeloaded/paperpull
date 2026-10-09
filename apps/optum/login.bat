@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9285)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Optum Bank Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to Optum Bank (do all the 2FA / device approval yourself).
echo   2. Open Help & Tools, then Statements & Tax Docs.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  paperpull optum diagnose   (a survey for the maintainer)
echo.
echo READ-ONLY: this tool only downloads your HSA statement and tax-form PDFs. It NEVER
echo pays a bill, reimburses, contributes, invests, transfers, or changes any setting.
echo.
.venv\Scripts\python.exe optum_docs.py --open-browser %CFG%
echo.
pause
