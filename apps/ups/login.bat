@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9277)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  UPS Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to ups.com yourself, including any code it sends.
echo   2. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   3. Then run:  paperpull ups pilot   (the five newest documents)
echo.
echo READ-ONLY: this tool only downloads your UPS invoice PDFs. It NEVER
echo pays, sets up automatic payments, disputes, or changes any setting.
echo.
.venv\Scripts\python.exe ups_docs.py --open-browser %CFG%
echo.
pause
