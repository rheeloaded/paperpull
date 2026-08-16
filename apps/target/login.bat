@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json)
rem  login.bat spouse   -> config.spouse.json (separate folders + session)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
if not "%~1"=="" echo Account: %~1
.venv\Scripts\python.exe target_receipts.py --login %CFG%
pause
