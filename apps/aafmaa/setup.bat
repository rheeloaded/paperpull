@echo off
setlocal
cd /d "%~dp0"
echo === Armed Forces Mutual Documents setup ===

set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE (
    echo Python 3 was not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

%PYEXE% -m venv .venv || goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :fail
pip install -r requirements.txt || goto :fail

rem  The shared core. In a repo checkout it lives two levels up; a standalone
rem  install ships a vendored wheel in core\ instead.
if exist "..\..\core\pyproject.toml" (
    pip install -e "..\..\core" || goto :fail
) else (
    for %%W in ("core\paperpull_core-*.whl") do pip install "%%W" || goto :fail
)
python -m playwright install chromium || goto :fail

echo.
echo Setup complete. Next: login.bat  (sign in, keep the browser open),
echo then diagnose.bat, then run_pilot.bat.
pause
exit /b 0

:fail
echo.
echo Setup FAILED - see messages above.
pause
exit /b 1
