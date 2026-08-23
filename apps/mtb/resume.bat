@echo off
cd /d "%~dp0"
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo Resuming M^&T Bank document download.
if not "%~1"=="" echo Account: %~1
echo Make sure that account's signed-in browser is still OPEN.
.venv\Scripts\python.exe mtb_docs.py --resume %CFG%
pause
