@echo off
cd /d "%~dp0"
rem  Control panel for the downloader apps.
rem  Optional: point it at your existing working copies instead of ..\apps:
rem     set APPS_ROOT=C:\path\to\Receipt and Statement Downloader
rem     run_gui.bat
if not exist ".venv\Scripts\python.exe" (
  echo Setting up the GUI virtual environment...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
echo.
echo Opening http://127.0.0.1:8765
start "" http://127.0.0.1:8765
python -m uvicorn app:app --port 8765
pause
