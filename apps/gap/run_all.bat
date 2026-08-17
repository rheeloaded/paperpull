@echo off
cd /d "%~dp0"
rem  run_all.bat          -> your account (config.json)
rem  run_all.bat spouse   -> spouse's account (config.spouse.json)
rem  Downloads the full order history. To limit it, set default_start_date
rem  in that account's config.
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo FULL Gap download (your entire order history).
if not "%~1"=="" echo Account: %~1
echo Make sure that account's signed-in browser is still OPEN.
.venv\Scripts\python.exe gap_receipts.py --all %CFG%
pause
