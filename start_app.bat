@echo off
REM Dubbelklik dit bestand om de status-app te starten (Windows).
REM Ontbreken er pakketten, dan worden die de eerste keer vanzelf geinstalleerd.
cd /d "%~dp0"

python -c "import requests, bs4, pystray, PIL" >nul 2>&1
if errorlevel 1 (
    echo Eenmalig de benodigde pakketten installeren, even geduld...
    python -m pip install -r requirements.txt
    echo.
)

python status_app.py
if errorlevel 1 pause
