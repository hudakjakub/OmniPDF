@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Python environment not found. Run these commands in this folder:
    echo py -3.14 -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" /d "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
