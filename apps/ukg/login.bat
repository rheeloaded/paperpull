@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9234)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  UKG Pay Statements - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal browser window opens at your employer's UKG site. Then:
echo   1. Sign in the way your company does - a UKG username and password,
echo      or your company's single sign-on. Either is fine: this tool never
echo      sees your credentials and never touches the sign-in itself.
echo   2. Complete any MFA / verification prompt yourself.
echo   3. Open your Pay / Pay Statements area and confirm you can see them.
echo   4. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo.
echo If the window opens somewhere unexpected, set "base_url" in config.json
echo to the address you see in your browser once signed in.
echo.
.venv\Scripts\python.exe ukg_docs.py --open-browser %CFG%
echo.
pause
