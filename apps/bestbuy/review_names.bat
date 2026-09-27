@echo off
cd /d "%~dp0"
rem  review_names.bat          -> your account (config.json)
rem  review_names.bat spouse   -> config.spouse.json
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Best Buy Receipts - review names
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo Goes through the receipts whose names the app was unsure of, one at a
echo time. Type a better name, press Enter to keep the one it has, or type
echo q to stop. Each name you type renames its PDF, and the spreadsheets
echo follow.
echo.
rem This folder's own Python when setup.bat made one. A folder the PaperPull
rem app made has no setup.bat, and runs on the Python the installer put in
rem your user folder. Each step ends outside any parentheses, so the exit
rem code is the app's own.
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto run
if exist setup.bat goto notsetup
set "PY=%LOCALAPPDATA%\PaperPull\python\python.exe"
if exist "%PY%" goto run
echo PaperPull was not found where its installer puts it. If you unzipped it
echo somewhere else, run this in that folder instead.
echo   paperpull.bat bestbuy review-names
echo.
pause
exit /b 1

:notsetup
echo This app is not set up yet - run setup.bat first.
echo.
pause
exit /b 1

:run
"%PY%" bestbuy_receipts.py --review-names %CFG%
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
