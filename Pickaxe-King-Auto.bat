@echo off
setlocal
cd /d "%~dp0"

set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"
set "PHONE=192.168.18.21"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" goto no_python

echo Pickaxe King Auto
echo.
echo   1) Wi-Fi  (type the wireless-debugging port)
echo   2) USB    (cable connected)
echo.
echo Wi-Fi phone IP: %PHONE%
echo Edit PHONE in this BAT if it changes.
echo.

:ask_mode
set "MODE="
set /p "MODE=Choose 1 or 2: "
if "%MODE%"=="1" goto wifi
if "%MODE%"=="2" goto check
goto ask_mode

:wifi
echo.
echo Turn on Wireless debugging on the phone, then type its port.
:ask_port
set "PORT="
set /p "PORT=Port: "
if "%PORT%"=="" goto ask_port
echo.
"%ADB%" connect %PHONE%:%PORT%
goto check

:check
set "ONLINE=0"
set "ONLINE_SERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices') do (
  if "%%b"=="device" (
    set /a ONLINE+=1
    set "ONLINE_SERIAL=%%a"
  )
)
if %ONLINE%==0 goto no_device
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

:no_device
echo.
echo No device found.
echo Wi-Fi: check Wireless debugging and the port.
echo USB: check the cable and allow USB debugging on the phone.
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
