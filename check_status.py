#!/usr/bin/env python3
"""Haalt de statuspagina's uit sites.json op en schrijft het resultaat naar docs/data/.

De tool probeert per site twee dingen, in deze volgorde:

1. Een machineleesbaar eindpunt (JSON). Veel statuspagina's draaien op standaard
   software (Atlassian Statuspage, Instatus, Uptime Kuma) die een JSON-versie
   aanbiedt. Dat is altijd betrouwbaarder dan tekst lezen.
2. Anders: de HTML-pagina ophalen en de tekst nalezen op signaalwoorden
   (Nederlands en Engels), bijvoorbeeld "geen storingen" of "outage".

Weet het script het niet zeker, dan wordt de status 'unknown'. Dat is bewust:
liever eerlijk "ik weet het niet" dan een vals "alles is in orde".
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "docs" / "data"
STATUS_FILE = DATA_DIR / "status.json"
HISTORY_FILE = DATA_DIR / "history.json"

# Hoeveel metingen we per site bewaren voor het tijdlijntje op het dashboard.
HISTORY_LIMIT = 240

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Dees-status-check/1.0 (+https://github.com/Samph0ny/Dees-status-check)",
    "Accept-Language": "nl,en;q=0.8",
}

# --- Statuscodes die de rest van het project gebruikt -----------------------
OK = "ok"                    # groen  - geen bekende problemen
INCIDENT = "incident"        # rood   - actieve storing
MAINTENANCE = "maintenance"  # blauw  - gepland onderhoud
UNKNOWN = "unknown"          # grijs  - pagina gelezen, status niet te bepalen
ERROR = "error"              # oranje - pagina niet te bereiken

# --- Signaalwoorden voor de tekstmethode ------------------------------------
# Let op de volgorde in classify_text(): "geen storingen" bevat het woord
# "storingen", dus de OK-zinnen worden eerst gecontroleerd.
OK_PHRASES = [
    "geen storingen", "geen actuele storingen", "geen bekende storingen",
    "geen meldingen", "geen incidenten", "geen verstoringen",
    "alles werkt naar behoren", "alle systemen operationeel",
    "alle diensten operationeel", "systemen zijn operationeel",
    "no known issues", "no incidents", "no current incidents",
    "no outages", "all systems operational", "all systems are operational",
    "all services operational", "fully operational", "operating normally",
]
INCIDENT_PHRASES = [
    "actuele storing", "actieve storing", "storingsmelding", "verstoring",
    "uitval", "niet beschikbaar", "onbereikbaar", "problemen met",
    "major outage", "partial outage", "degraded performance",
    "service disruption", "ongoing incident", "investigating",
    "identified", "monitoring an incident",
]
MAINTENANCE_PHRASES = [
    "gepland onderhoud", "onderhoudswerkzaamheden", "onderhoud gepland",
    "scheduled maintenance", "planned maintenance", "under maintenance",
    "maintenance in progress",
]

# Atlassian Statuspage vertaalt zijn eigen indicator al naar deze woorden.
STATUSPAGE_INDICATOR = {
    "none": OK,
    "minor": INCIDENT,
    "major": INCIDENT,
    "critical": INCIDENT,
    "maintenance": MAINTENANCE,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)


def try_json_endpoints(url: str) -> dict | None:
    """Zoekt naar een standaard JSON-eindpunt van bekende statuspagina-software."""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
    candidates = [
        ("statuspage", urljoin(base, "api/v2/summary.json")),
        ("instatus", urljoin(base, "summary.json")),
    ]
    for flavour, endpoint in candidates:
        try:
            resp = fetch(endpoint)
            if resp.status_code != 200:
                continue
            payload = resp.json()
        except (requests.RequestException, ValueError):
            continue

        parsed = parse_json_payload(flavour, payload)
        if parsed:
            parsed["source_url"] = endpoint
            return parsed
    return None


def parse_json_payload(flavour: str, payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None

    # Atlassian Statuspage en Instatus delen grotendeels hetzelfde formaat.
    page_status = payload.get("status")
    if isinstance(page_status, dict):
        indicator = str(page_status.get("indicator", "")).lower()
        description = page_status.get("description") or ""
        status = STATUSPAGE_INDICATOR.get(indicator, UNKNOWN)

        components = []
        for comp in payload.get("components", []) or []:
            if not isinstance(comp, dict) or comp.get("group"):
                continue
            comp_status = str(comp.get("status", "")).lower()
            components.append({
                "name": comp.get("name", "?"),
                "status": OK if comp_status == "operational" else (
                    MAINTENANCE if "maintenance" in comp_status else INCIDENT
                ),
                "raw": comp_status.replace("_", " "),
            })

        incidents = [
            i.get("name", "")
            for i in (payload.get("incidents") or [])
            if isinstance(i, dict)
        ]
        if incidents and status == OK:
            status = INCIDENT

        return {
            "status": status,
            "detail": description or (incidents[0] if incidents else ""),
            "components": components[:25],
            "open_incidents": incidents[:5],
            "method": f"json:{flavour}",
        }
    return None


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def classify_text(text: str) -> tuple[str, str]:
    """Geeft (status, gevonden zinsnede) terug op basis van signaalwoorden."""
    haystack = text.lower()

    for phrase in OK_PHRASES:
        if phrase in haystack:
            return OK, phrase
    for phrase in INCIDENT_PHRASES:
        if phrase in haystack:
            return INCIDENT, phrase
    for phrase in MAINTENANCE_PHRASES:
        if phrase in haystack:
            return MAINTENANCE, phrase
    return UNKNOWN, ""


def check_site(site: dict) -> dict:
    result = {
        "id": site["id"],
        "name": site["name"],
        "url": site["url"],
        "checked_at": now_iso(),
        "status": UNKNOWN,
        "detail": "",
        "components": [],
        "open_incidents": [],
        "method": "",
        "http_status": None,
        "excerpt": "",
    }

    structured = try_json_endpoints(site["url"])
    if structured:
        result.update(structured)
        result["http_status"] = 200
        return result

    try:
        resp = fetch(site["url"])
        result["http_status"] = resp.status_code
        resp.raise_for_status()
    except requests.RequestException as exc:
        result["status"] = ERROR
        result["method"] = "http"
        result["detail"] = f"Pagina niet bereikbaar: {exc.__class__.__name__}"
        return result

    text = page_text(resp.text)
    status, phrase = classify_text(text)
    result["status"] = status
    result["method"] = "text"
    result["detail"] = f"Gevonden op de pagina: “{phrase}”" if phrase else (
        "Geen bekende signaalwoorden gevonden — controleer de pagina zelf."
    )
    # Dit fragment helpt bij het bijstellen van de signaalwoorden.
    result["excerpt"] = text[:400]
    return result


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def main() -> int:
    config = load_json(ROOT / "sites.json", None)
    if not config or not config.get("sites"):
        print("FOUT: sites.json ontbreekt of bevat geen sites.", file=sys.stderr)
        return 1

    results = [check_site(site) for site in config["sites"]]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(
        json.dumps({"generated_at": now_iso(), "sites": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    history = load_json(HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}
    for res in results:
        entries = history.setdefault(res["id"], [])
        entries.append({"t": res["checked_at"], "s": res["status"]})
        history[res["id"]] = entries[-HISTORY_LIMIT:]
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for res in results:
        print(f"{res['status'].upper():<11} {res['name']:<22} ({res['method'] or 'n/a'}) {res['detail']}")
        if res["excerpt"]:
            print(f"            fragment: {res['excerpt'][:160]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
