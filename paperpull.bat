@echo off
rem One command for every app. See paperpull.py for the details.
rem The packaged app carries its own Python; a checkout uses the one on PATH.
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" "%~dp0paperpull.py" %*
  exit /b %errorlevel%
)
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  exit /b 1
)
%PYEXE% "%~dp0paperpull.py" %*
