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

REM Update KOE shortcut on the SSD
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SCRIPT_DIR%KOE.lnk'); $s.TargetPath = '%SCRIPT_DIR%launch_gui.bat'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.IconLocation = '%SCRIPT_DIR%assets\icon.ico,0'; $s.Description = 'KOE - Speaker Diarization and Audio Leveler'; $s.Save()" >nul 2>&1

REM Create KOE shortcut on the User Desktop
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $desk = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut($desk + '\KOE.lnk'); $s.TargetPath = '%SCRIPT_DIR%launch_gui.bat'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.IconLocation = '%SCRIPT_DIR%assets\icon.ico,0'; $s.Description = 'KOE - Speaker Diarization and Audio Leveler'; $s.Save()" >nul 2>&1

echo [SUCCESS] KOE is now registered on this computer!
echo.
echo  * Desktop Icon: 'KOE' shortcut created on your Desktop.
echo  * Folder Launcher: Double-click 'KOE' in this folder.
echo  * Terminal Command: Run 'koe' from any terminal.
echo.
echo ========================================================
pause
