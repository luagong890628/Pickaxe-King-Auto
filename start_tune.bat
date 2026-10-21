@echo off
setlocal
cd /d "%~dp0"

rem Tuning copy. The stable launcher is D:\project\Pickaxe-King-Auto\start_auto.bat
rem Both folders share one git repo (git worktree); this one borrows the venv.
set "PY=D:\project\Pickaxe-King-Auto\.venv\Scripts\python.exe"

if not exist "%PY%" goto no_python

"%PY%" -c "import cv2" >nul 2>&1
if errorlevel 1 goto no_deps

echo Pickaxe King Auto - TUNE
echo.
echo Route: village north 950px, then start north 600px + rest, wait 30s, repeat.
echo Stable build lives in D:\project\Pickaxe-King-Auto
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
echo Missing %PY%
echo The stable folder's .venv is required.
echo Press Enter to close
set /p "_="
exit /b 1

:no_deps
echo Missing opencv in the stable folder's .venv
echo Run: D:\project\Pickaxe-King-Auto\.venv\Scripts\pip install -r requirements.txt
echo Press Enter to close
set /p "_="
exit /b 1
