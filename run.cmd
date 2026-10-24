@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    echo Please follow README.md to create .venv and install requirements.
    pause
    exit /b 1
)
if errorlevel 1 pause
