@echo off
setlocal
cd /d "%~dp0"

set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"
set "PHONE=192.168.18.21"
set "PORT=5555"
set "PY=%~dp0.venv\Scripts\python.exe"
set "SERIAL="
set "RECOVERED="

if not exist "%PY%" goto no_python

echo Pickaxe King Auto
echo.
echo   1) Wi-Fi  (fixed port %PORT%, wireless debugging not needed)
echo   2) USB    (cable connected)
echo.
echo Wi-Fi phone IP: %PHONE%
echo Edit PHONE in this BAT if it changes.
echo.

:ask_mode
set "MODE="
set /p "MODE=Choose 1=Wi-Fi, 2=USB: "
if "%MODE%"=="1" goto wifi
if "%MODE%"=="2" goto ensure_adb
goto ask_mode

:wifi
set "SERIAL=%PHONE%:%PORT%"
echo.
goto ensure_adb

:ensure_adb
"%ADB%" server-status >nul 2>&1
if not errorlevel 1 (
  if defined SERIAL "%ADB%" connect %SERIAL%
  goto check_devices
)
:restart_adb_server
echo ADB server is not responding; restarting it.
"%ADB%" kill-server >nul 2>&1
"%ADB%" start-server >nul 2>&1
if errorlevel 1 goto adb_unavailable
"%ADB%" server-status >nul 2>&1
if errorlevel 1 goto adb_unavailable
if defined SERIAL "%ADB%" connect %SERIAL%
goto check_devices

:adb_unavailable
echo ADB server could not be started or is not responding.
echo Check the ADB installation and any other process using port 5037.
echo Press Enter to close
set /p "_="
exit /b 1

:check_devices
set "ONLINE=0"
set "TARGET="
set "SERIAL_ONLINE=0"
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices') do (
  if "%%b"=="device" (
    set /a ONLINE+=1
    if not defined TARGET set "TARGET=%%a"
    if /i "%%a"=="%SERIAL%" set "TARGET=%%a"
    if /i "%%a"=="%SERIAL%" set "SERIAL_ONLINE=1"
  )
)
if %ONLINE%==0 goto no_device
if defined SERIAL if "%SERIAL_ONLINE%"=="0" goto wifi_recovery
if %ONLINE% GTR 1 echo Note: %ONLINE% adb entries for this phone, using %TARGET%

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

:wifi_recovery
if defined RECOVERED goto wifi_failed
set "RECOVERED=1"
echo Wi-Fi %SERIAL% is not online.
set "USBSERIAL="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices') do (
  if "%%b"=="device" (
    echo %%a | findstr /c:":" >nul
    if errorlevel 1 if not defined USBSERIAL set "USBSERIAL=%%a"
  )
)
if not defined USBSERIAL goto wifi_needs_usb
echo Re-enabling fixed port %PORT% over USB (%USBSERIAL%)...
"%ADB%" -s %USBSERIAL% tcpip %PORT%
ping -n 5 127.0.0.1 >nul
"%ADB%" connect %SERIAL%
goto check_devices

:wifi_needs_usb
echo.
echo The phone is not listening on port %PORT% (this happens after a phone reboot).
echo Plug in the USB cable, allow USB debugging, then run this BAT again.
echo Press Enter to close
set /p "_="
exit /b 1

:wifi_failed
echo.
echo Could not bring up Wi-Fi %SERIAL% even after re-enabling port %PORT% over USB.
echo Check the cable, USB debugging, and that PHONE matches the phone IP.
echo Press Enter to close
set /p "_="
exit /b 1

:no_device
echo.
echo No device found.
echo Wi-Fi: plug in USB once so this BAT can enable port %PORT%.
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