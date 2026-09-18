#!/bin/bash
# Dubbelklik dit bestand om de status-app te starten (macOS).
# Eenmalig uitvoerbaar maken:  chmod +x start_app.command
# Ontbreken er pakketten, dan worden die de eerste keer vanzelf geinstalleerd.
cd "$(dirname "$0")"

if ! python3 -c "import requests, bs4, pystray, PIL" >/dev/null 2>&1; then
    echo "Eenmalig de benodigde pakketten installeren, even geduld..."
    python3 -m pip install -r requirements.txt
    echo
fi

python3 status_app.py
