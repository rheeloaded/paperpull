@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9232)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Target Circle Card (RedCard) Statements - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal Chromium window will open at the "Manage my Target Circle Card"
echo sign-in (rcam.target.com). Then:
echo   1. Sign in to your Target Circle Card / RedCard credit account (do all
echo      the 2FA / verification yourself).
echo   2. Open your Statements / eStatements / Documents section.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  diagnose.bat %~1   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads your billing statements. It NEVER
echo pays a bill, makes a payment, transfers a balance, moves money, redeems
echo rewards, or changes any setting.
echo.
.venv\Scripts\python.exe redcard_docs.py --open-browser %CFG%
echo.
pause
