@echo off
REM Dubbelklik dit bestand om de status-app te starten (Windows).
cd /d "%~dp0"
python status_app.py
if errorlevel 1 pause
