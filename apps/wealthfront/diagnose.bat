@echo off
cd /d "%~dp0"
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo Read-only inspection of the Documents page. Downloads nothing.
if not "%~1"=="" echo Account: %~1
.venv\Scripts\python.exe wealthfront_docs.py --diagnose %CFG%
pause
