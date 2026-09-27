@echo off
rem One command for every app. See paperpull.py for the details.
rem The packaged app carries its own Python, a checkout uses the one on PATH.
rem
rem Double-clicked in the packaged app, with nothing after it, this opens the
rem control panel. The panel's own launcher used to be a batch file named
rem PaperPull.bat, which Windows cannot tell apart from this one, so older
rem shortcuts land here and still open the panel.
rem
rem Each branch ends outside any parentheses, because an exit code taken
rem inside a parenthesized block is read before the block runs, and every
rem run reported success whatever happened.
if not "%~1"=="" goto terminal
if not exist "%~dp0PaperPull.exe" goto terminal
"%~dp0PaperPull.exe"
exit /b %errorlevel%

:terminal
if not exist "%~dp0python\python.exe" goto systempython
"%~dp0python\python.exe" "%~dp0paperpull.py" %*
exit /b %errorlevel%

:systempython
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  exit /b 1
)
%PYEXE% "%~dp0paperpull.py" %*
exit /b %errorlevel%
