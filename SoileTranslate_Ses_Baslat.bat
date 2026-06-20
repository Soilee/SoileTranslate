@echo off
title SoileTranslate Ses
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -m venv .venv
    ) else (
        py -3.13 -m venv .venv
    )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Kurulum hatasi.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "main.py"
