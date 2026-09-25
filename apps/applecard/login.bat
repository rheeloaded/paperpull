@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9270)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Apple Card Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to card.apple.com (do all the 2FA / device approval yourself).
echo   2. Stay on card.apple.com once you are in.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then press Record in the panel, or run:  paperpull applecard record
echo.
echo READ-ONLY: this tool only downloads your statement PDFs. It NEVER
echo transfers, pays, sends money, opens or closes anything, or changes any
echo setting.
echo.
.venv\Scripts\python.exe applecard_docs.py --open-browser %CFG%
echo.
pause
