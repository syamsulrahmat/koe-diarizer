@echo off
setlocal
echo ========================================================
echo       Unregistering KOE from this Computer
echo ========================================================
echo.

if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\koe.cmd" (
    del "%LOCALAPPDATA%\Microsoft\WindowsApps\koe.cmd"
    echo [SUCCESS] KOE global shortcut removed from this computer.
) else (
    echo KOE was not registered in user WindowsApps folder.
)

echo.
pause
