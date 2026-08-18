@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo  PaperPull - one-shot setup
echo  Creates a virtual environment for every app + the GUI,
echo  installs the shared core into each, and downloads
echo  Playwright's Chromium once (then shared by all of them).
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
set /a COUNT=0
set "BROWSER_DONE="

rem --- each app ---
for /d %%A in (apps\*) do (
  if exist "%%A\requirements.txt" (
    echo === %%~nxA ===
    pushd "%%A"
    if exist ".venv\Scripts\python.exe" (
      echo    reusing existing .venv
    ) else (
      %PYEXE% -m venv .venv || set "FAILED=!FAILED! %%~nxA(venv)"
    )
    .venv\Scripts\python.exe -m pip install -q --upgrade pip
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || set "FAILED=!FAILED! %%~nxA(deps)"

    rem  The shared core. Every app imports paperpull_core, so without this
    rem  step each one dies at startup with ModuleNotFoundError. A repo
    rem  checkout installs it from source; a standalone copy ships a wheel.
    if exist "..\..\core\pyproject.toml" (
      .venv\Scripts\python.exe -m pip install -q -e "..\..\core" || set "FAILED=!FAILED! %%~nxA(core)"
    ) else (
      for %%W in ("core\paperpull_core-*.whl") do (
        .venv\Scripts\python.exe -m pip install -q "%%W" || set "FAILED=!FAILED! %%~nxA(core)"
      )
    )

    rem  Chromium is a single shared download - fetch it once, not per app.
    if not defined BROWSER_DONE (
      .venv\Scripts\python.exe -m playwright install chromium && set "BROWSER_DONE=1"
    )
    popd
    set /a COUNT+=1
  )
)

rem --- the GUI ---
echo === gui ===
pushd gui
if exist ".venv\Scripts\python.exe" (
  echo    reusing existing .venv
) else (
  %PYEXE% -m venv .venv || set "FAILED=!FAILED! gui(venv)"
)
.venv\Scripts\python.exe -m pip install -q --upgrade pip
.venv\Scripts\python.exe -m pip install -q -r requirements.txt || set "FAILED=!FAILED! gui(deps)"
popd

if not defined BROWSER_DONE set "FAILED=!FAILED! playwright-chromium"

echo.
if defined FAILED (
  echo ** Some setups had problems:!FAILED!
  echo    Re-run this, or run that app's own setup.bat to see the error.
) else (
  echo All set - !COUNT! apps + the GUI are ready.
)
echo.
echo Next:
echo   * Launch the control panel:  gui\run_gui.bat
echo   * Or one app directly:       cd apps\amex  ^&  login.bat  (sign in)  ^&  run_pilot.bat
echo.
echo   Each app needs its own config.json first - copy config.example.json
echo   next to it and edit the paths. UKG also needs your employer's
echo   base_url set in that file.
echo.
pause
