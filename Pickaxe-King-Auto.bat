@echo off
setlocal
cd /d "%~dp0"

set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" goto no_python

echo Pickaxe King Auto
echo.

:ensure_adb
"%ADB%" server-status >nul 2>&1
if not errorlevel 1 goto detect
echo ADB server is not responding; restarting it.
"%ADB%" kill-server >nul 2>&1
"%ADB%" start-server >nul 2>&1
if errorlevel 1 goto adb_unavailable
"%ADB%" server-status >nul 2>&1
if errorlevel 1 goto adb_unavailable

:detect
echo Detecting phone (wireless debugging preferred, USB as fallback)...
set "TARGET="
for /f "delims=" %%t in ('"%PY%" -m pkauto.adb') do set "TARGET=%%t"
if not defined TARGET goto no_device

echo Connected: %TARGET%
set "ANDROID_SERIAL=%TARGET%"
echo.
echo Before you start:
echo   - open the game on the phone
echo   - turn the screen brightness down
echo.
echo Press Enter to start Pickaxe-King-Auto...
set /p "_="

"%PY%" cycle_fixed.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Finished.
if not "%RC%"=="0" echo Finished with exit code %RC%.
echo Press Enter to close
set /p "_="
exit /b %RC%

:adb_unavailable
echo ADB server could not be started or is not responding.
echo Check the ADB installation and any other process using port 5037.
echo Press Enter to close
set /p "_="
exit /b 1

:no_device
echo.
echo No device found.
echo Wireless: turn on Wireless debugging on the phone (no port input needed).
echo USB: check the cable and allow USB debugging on the phone.
echo Press Enter to close
set /p "_="
exit /b 1

:no_python
echo Missing .venv\Scripts\python.exe
echo Run:
echo   python -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
echo Press Enter to close
set /p "_="
exit /b 1
