@echo off
REM Bouwt "Status Check.exe" op je eigen Windows-computer.
REM Dubbelklik dit bestand. Het resultaat komt in de map dist\.
cd /d "%~dp0"

echo Pakketten installeren...
python -m pip install -r requirements.txt pyinstaller || goto :fout

echo Bouwen...
python -m PyInstaller --onefile --windowed --name "Status Check" --icon icon.ico --add-data "icon.png;." status_app.py || goto :fout

copy sites.json dist\sites.json >nul

echo.
echo Klaar. Je vindt "Status Check.exe" in de map dist.
echo Houd sites.json ernaast staan, daar staan de diensten in.
pause
exit /b 0

:fout
echo.
echo Er ging iets mis. Staat Python geinstalleerd en in je PATH?
pause
exit /b 1
