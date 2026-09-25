@echo off
setlocal
echo ========================================================
echo       Registering KOE on this Computer
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "TARGET_DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"

if not exist "%TARGET_DIR%" (
    mkdir "%TARGET_DIR%"
)

echo @echo off > "%TARGET_DIR%\koe.cmd"
echo "%SCRIPT_DIR%runtime\python.exe" "%SCRIPT_DIR%transcribe.py" %%* >> "%TARGET_DIR%\koe.cmd"

echo [SUCCESS] KOE is now registered on this computer!
echo You can open ANY terminal anywhere and run:
echo.
echo     koe "path\to\audio.mp3" "path\to\captions.srt"
echo.
echo ========================================================
pause
