@echo off
set "PROJECT_ROOT=%~dp0.."
if not exist "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" (
    echo Python environment not found. Run these commands in this folder:
    echo py -3.14 -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -r requirements\runtime.txt
    pause
    exit /b 1
)
start "" /d "%PROJECT_ROOT%" "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" -m omnipdf %*
