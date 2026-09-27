@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9280)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Apple Receipts - sign in
echo ============================================================
if not "%~1"=="" echo Account %~1
echo.
echo A browser window will open on Report a Problem.
echo   1. Sign in there, and answer any code Apple sends yourself.
echo   2. For Apple Store orders, open apple.com/shop/order/list in a second
echo      tab and sign in there too. It is a separate sign-in.
echo   3. LEAVE THAT BROWSER WINDOW OPEN, do not close it.
echo   4. Then run the pilot, paperpull apple pilot
echo.
.venv\Scripts\python.exe apple_receipts.py --open-browser %CFG%
echo.
pause
