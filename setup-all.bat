@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo  PaperPull - one-shot setup
echo  Creates a virtual environment for every app + the GUI and
echo  installs Playwright's Chromium (downloaded once, then shared).
echo  This can take a few minutes the first time.
echo ============================================================
echo.

rem --- locate Python 3 ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  echo Be sure to check "Add Python to PATH" during install.
  pause & exit /b 1
)

set "FAILED="

rem --- each app ---
for /d %%A in (apps\*) do (
  echo === %%~nxA ===
  pushd "%%A"
  %PYEXE% -m venv .venv || set "FAILED=!FAILED! %%~nxA(venv)"
  .venv\Scripts\python.exe -m pip install -q --upgrade pip
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || set "FAILED=!FAILED! %%~nxA(deps)"
  .venv\Scripts\python.exe -m playwright install chromium || set "FAILED=!FAILED! %%~nxA(browser)"
  popd
)

rem --- the GUI ---
echo === gui ===
pushd gui
%PYEXE% -m venv .venv || set "FAILED=!FAILED! gui(venv)"
.venv\Scripts\python.exe -m pip install -q --upgrade pip
.venv\Scripts\python.exe -m pip install -q -r requirements.txt || set "FAILED=!FAILED! gui(deps)"
popd

echo.
if defined FAILED (
  echo !! Some setups had problems:!FAILED!
  echo    Re-run this, or run that app's own setup.bat to see the error.
) else (
  echo All set - 9 apps + the GUI are ready.
)
echo.
echo Next:
echo   * Launch the control panel:  gui\run_gui.bat
echo   * Or one app directly:       cd apps\amex  ^&  login.bat  (sign in)  ^&  run_pilot.bat
echo.
pause
