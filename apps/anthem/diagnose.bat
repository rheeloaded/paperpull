@echo off
cd /d "%~dp0"
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo Read-only inspection of the Anthem documents page. Downloads NOTHING.
if not "%~1"=="" echo Account: %~1
echo Make sure you are signed in and your documents page is open.
.venv\Scripts\python.exe anthem_docs.py --diagnose %CFG%
pause
