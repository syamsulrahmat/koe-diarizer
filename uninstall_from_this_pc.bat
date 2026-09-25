@echo off
setlocal
echo ========================================================
echo       Unregistering KOE from this Computer
echo ========================================================
echo.

if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\koe.cmd" (
    del "%LOCALAPPDATA%\Microsoft\WindowsApps\koe.cmd"
    echo [SUCCESS] KOE terminal shortcut removed.
)

if exist "%USERPROFILE%\Desktop\KOE.lnk" (
    del "%USERPROFILE%\Desktop\KOE.lnk"
    echo [SUCCESS] KOE Desktop shortcut removed.
)

echo [SUCCESS] KOE successfully unregistered from this PC.

echo.
pause
