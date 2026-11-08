@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9303)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  DKB Documents - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A browser window will open on banking.dkb.de. Then:
echo   1. Sign in to DKB yourself, including the two-factor prompt.
echo   2. Open your statements or messages area if you know where it is.
echo   3. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   4. Then run:  paperpull dkb diagnose   (a safe look, downloads nothing)
echo.
echo READ-ONLY: this tool only downloads statements and tax forms. It NEVER
echo moves money between funds, changes contributions, withdraws, takes a
echo loan, changes beneficiaries, or changes any setting.
echo.
rem This app's own Python when setup.bat made one. Otherwise, in a
rem checkout, the one setup-all.bat made for every app in gui\.venv, once
rem it holds what an app needs.
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto run
set "PY=..\..\gui\.venv\Scripts\python.exe"
if not exist "%PY%" goto notsetup
"%PY%" -c "import importlib.util as u, sys; sys.exit(not all(map(u.find_spec, ['paperpull_core', 'playwright', 'pypdf'])))" >nul 2>&1
if not errorlevel 1 goto run
:notsetup
if exist "..\..\setup-all.bat" (
  echo This app is not set up yet. Run setup-all.bat in the PaperPull folder first.
) else (
  echo This app is not set up yet - run setup.bat first.
)
echo.
pause
exit /b 1

:run
"%PY%" dkb_docs.py --open-browser %CFG%
echo.
pause
