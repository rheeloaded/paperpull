@echo off
cd /d "%~dp0"
rem  status.bat  -> how current is every archive, and what is worth running
rem
rem  Put this next to your install folders (the folder that CONTAINS
rem  "Target Receipts", "M&T Bank Mortgage" and so on) along with status.py,
rem  and run it. It reads only local state files, downloads nothing, and
rem  changes nothing.

set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
    echo Could not find Python on PATH.
    echo Run this from any app folder instead, for example:
    echo     "Target Receipts\.venv\Scripts\python.exe" status.py --html
    pause
    exit /b 1
)

%PYEXE% status.py --html %*
echo.
pause
