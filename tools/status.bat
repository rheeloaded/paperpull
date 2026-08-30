@echo off
rem  status.bat  -> how current is every archive, and what is worth running
rem
rem  Put this next to your install folders (the folder that CONTAINS your
rem  provider folders) along with status.py, and run it. It reads only local
rem  state files, downloads nothing, and changes nothing.
rem
rem  Two deliberate hardening steps below, because this script is meant to
rem  live in a DATA folder rather than a program folder, and a data folder is
rem  a plausible place for something else to drop a file:
rem    NoDefaultCurrentDirectoryInExePath stops cmd resolving `py` from the
rem      current folder, so a planted py.bat cannot run instead of Python.
rem    python -P stops Python putting the script's own folder on sys.path,
rem      so a planted statistics.py or json.py cannot be imported instead of
rem      the real module.
setlocal
set "NoDefaultCurrentDirectoryInExePath=1"
cd /d "%~dp0"

set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
    echo Could not find Python on PATH.
    echo Run it from any app folder instead, for example:
    echo     "<a provider folder>\.venv\Scripts\python.exe" -P status.py --html
    pause
    exit /b 1
)

%PYEXE% -P status.py --html %*
echo.
pause
