@echo off
if "%~1"=="" (
    if exist "%~dp0runtime\pythonw.exe" (
        start "" "%~dp0runtime\pythonw.exe" "%~dp0gui.pyw"
    ) else (
        start "" pythonw "%~dp0gui.pyw"
    )
) else (
    if exist "%~dp0runtime\python.exe" (
        "%~dp0runtime\python.exe" "%~dp0transcribe.py" %*
    ) else (
        python "%~dp0transcribe.py" %*
    )
)
