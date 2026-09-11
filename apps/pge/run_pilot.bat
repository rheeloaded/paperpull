@echo off
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

set CFG=
if not "%~1"=="" set CFG=--config config.%~1.json

if not exist "%PY%" (
    echo This app is not set up yet - run setup.bat first.
    pause & exit /b 1
)

"%PY%" pge_docs.py --pilot %CFG%
pause
