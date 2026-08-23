@echo off
cd /d "%~dp0"
rem  run_all.bat          -> your account
rem  run_all.bat spouse   -> spouse's account (separate folders + progress)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo FULL download of M^&T Bank statements, tax forms, and insurance documents.
if not "%~1"=="" echo Account: %~1
echo Run the pilot first if you have not: run_pilot.bat %~1
echo Make sure that account's signed-in browser is still OPEN.
.venv\Scripts\python.exe mtb_docs.py --all %CFG%
pause
