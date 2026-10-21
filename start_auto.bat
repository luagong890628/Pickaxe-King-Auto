@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" goto no_python

"%PY%" -c "import cv2" >nul 2>&1
if errorlevel 1 goto no_deps

echo Pickaxe King Auto
echo.
echo Route: village, then start area, then rest, then wait 30s, repeat.
echo Phone must be connected and the game must be open.
echo Press Ctrl+C to stop.
echo.
"%PY%" cycle_fixed.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Finished.
if not "%RC%"=="0" echo Finished with exit code %RC%.
echo Press Enter to close
set /p "_="
exit /b %RC%

:no_python
echo Missing .venv\Scripts\python.exe
echo Run:
echo   python -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
echo Press Enter to close
set /p "_="
exit /b 1

:no_deps
echo Missing opencv in .venv
echo Run: .venv\Scripts\pip install -r requirements.txt
echo Press Enter to close
set /p "_="
exit /b 1
