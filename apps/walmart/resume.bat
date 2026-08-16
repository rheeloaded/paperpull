@echo off
cd /d "%~dp0"
rem  resume.bat        -> your account
rem  resume.bat jane   -> jane's account
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
if not "%~1"=="" echo Account: %~1
.venv\Scripts\python.exe walmart_receipts.py --resume %CFG%
pause
