@echo off
if exist "%~dp0runtime\pythonw.exe" (
    start "" "%~dp0runtime\pythonw.exe" "%~dp0gui.pyw"
) else (
    start "" pythonw "%~dp0gui.pyw"
)
