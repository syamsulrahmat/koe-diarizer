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

copy /y "%SCRIPT_DIR%koe.cmd" "%TARGET_DIR%\koe.cmd" >nul

echo [SUCCESS] KOE is now registered on this computer!
echo.
echo  • To open the graphical app: Type 'koe' (or double-click launch_gui.bat)
echo  • To use from the command line: Type 'koe "audio.mp3" "captions.srt"'
echo You can open ANY terminal anywhere and run:
echo.
echo     koe "path\to\audio.mp3" "path\to\captions.srt"
echo.
echo ========================================================
pause
