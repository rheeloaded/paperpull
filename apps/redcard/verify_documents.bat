@echo off
cd /d "%~dp0"
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
if not "%~1"=="" echo Account: %~1
.venv\Scripts\python.exe redcard_docs.py --verify %CFG%
pause
