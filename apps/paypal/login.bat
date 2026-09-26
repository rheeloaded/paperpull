@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9276)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  PayPal Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Your own Edge or Chrome will open, with a separate profile. Then:
echo   1. Sign in to PayPal yourself, including any code it sends.
echo   2. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   3. Then run:  paperpull paypal pilot   (the five newest statements)
echo.
echo READ-ONLY: this tool only downloads your statement PDFs. It NEVER
echo sends or requests money, transfers, applies for anything, or changes any setting.
echo.
.venv\Scripts\python.exe paypal_docs.py --open-browser %CFG%
echo.
pause
