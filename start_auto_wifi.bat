@echo off
setlocal
cd /d "%~dp0"

set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"
set "PHONE=192.168.18.21"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" goto no_python

echo Pickaxe King Auto (Wi-Fi)
echo.
echo Phone IP: %PHONE%
echo Edit PHONE in this BAT if the phone IP changes.
echo Turn on Wireless debugging on the phone, then type its port.
echo.

:ask_port
set "PORT="
set /p "PORT=Port: "
if "%PORT%"=="" goto ask_port
set "SERIAL=%PHONE%:%PORT%"

echo.
"%ADB%" connect %SERIAL%

set "ONLINE=0"
set "ONLINE_SERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices') do (
  if "%%b"=="device" (
    set /a ONLINE+=1
    set "ONLINE_SERIAL=%%a"
  )
)
if %ONLINE%==0 goto connect_failed
if %ONLINE% GTR 1 goto too_many

echo Connected: %ONLINE_SERIAL%
echo.
echo Open the game on the phone now.
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

:connect_failed
echo.
echo Connect failed: %SERIAL%
echo Check that Wireless debugging is on and the port is correct.
echo Press Enter to close
set /p "_="
exit /b 1

:too_many
echo.
echo More than one device is connected.
echo Unplug USB or disconnect the other device, then run again.
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
