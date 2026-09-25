@echo off
if exist "%~dp0runtime\python.exe" (
    "%~dp0runtime\python.exe" "%~dp0transcribe.py" %*
) else (
    python "%~dp0transcribe.py" %*
)
