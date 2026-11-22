@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9320)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Sonic Bills - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A browser window with a profile of its own will open. Then:
echo   1. Sign in to Sonic (do all the 2FA / verification yourself).
echo   2. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo   3. Then run:  paperpull sonic diagnose   (a safe look, downloads nothing)
if not "%~1"=="" echo      For this account, add  --account %~1
echo.
echo READ-ONLY: this tool downloads internet bill PDFs.
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
"%PY%" sonic_docs.py --open-browser %CFG%
echo.
pause
