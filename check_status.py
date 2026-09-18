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
    "alles werkt naar behoren", "werken naar behoren", "werkt naar behoren",
    "alle systemen operationeel",
    "alle diensten operationeel", "systemen zijn operationeel",
    "no current disturbances", "no ongoing disturbances", "no disturbances",
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

# --- Ruis die we weggooien voor we de tekst lezen ------------------------------
# Menu's, footers en cookiebalken bevatten vaak woorden als "storingen" (bv. een
# menu-item "Actuele storingen"). Die zeggen niets over de huidige status, dus
# ze worden verwijderd voordat we gaan zoeken.
NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "nav", "header",
              "footer", "aside", "form"]
NOISE_ATTR = re.compile(
    r"(nav|menu|breadcrumb|cookie|consent|sidebar|skip-link|site-footer|site-header)",
    re.IGNORECASE,
)

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

    # Instatus heeft een eigen formaat met activeIncidents / activeMaintenances.
    if "activeIncidents" in payload or "activeMaintenances" in payload:
        incidents = [i.get("name", "") for i in (payload.get("activeIncidents") or [])
                     if isinstance(i, dict)]
        maintenances = [m.get("name", "") for m in (payload.get("activeMaintenances") or [])
                        if isinstance(m, dict)]
        if incidents:
            status, detail = INCIDENT, incidents[0]
        elif maintenances:
            status, detail = MAINTENANCE, maintenances[0]
        else:
            status, detail = OK, "Geen actieve incidenten gemeld"
        return {
            "status": status,
            "detail": detail,
            "components": [],
            "open_incidents": incidents[:5],
            "method": "json:instatus",
        }

    # Atlassian Statuspage: de status zit in een object met een indicator.
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


# Hoeveel tekst we minimaal willen overhouden. Blijft er minder over, dan heeft
# het filteren te veel weggesneden en proberen we een mildere variant.
MIN_TEXT_LENGTH = 120


def page_text(html: str, level: str = "strict") -> str:
    """Haalt de leesbare inhoud uit de pagina.

    Drie niveaus, van streng naar mild:

    - "strict": menu's, footers en elementen met een menu-achtige class weg, en
      alleen het main/article-gebied als dat er is. Het nauwkeurigst, maar bij
      sommige sites blijft er te weinig over.
    - "mild": alleen de duidelijke ruis-tags weg (nav, header, footer).
    - "raw": alles behalve scripts en opmaak.
    """
    soup = BeautifulSoup(html, "html.parser")

    always_drop = ["script", "style", "noscript", "svg", "iframe"]
    if level == "raw":
        drop = always_drop
    else:
        drop = NOISE_TAGS

    for tag in soup(drop):
        tag.decompose()

    if level == "strict":
        # Ook elementen weggooien die aan hun class of id te herkennen zijn als menu.
        for tag in soup.find_all(attrs={"class": True}):
            if getattr(tag, "decomposed", False):
                continue
            if NOISE_ATTR.search(" ".join(tag.get("class") or [])):
                tag.decompose()
        for tag in soup.find_all(attrs={"id": True}):
            if getattr(tag, "decomposed", False):
                continue
            if NOISE_ATTR.search(tag.get("id") or ""):
                tag.decompose()

        # Staat er een duidelijk inhoudsgebied? Gebruik dan alleen dat.
        region = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
        if region is None or len(region.get_text(strip=True)) < 80:
            region = soup
    else:
        region = soup

    text = region.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def section_text(html: str, heading: str) -> str:
    """Geeft alleen de tekst die onder een bepaald kopje staat.

    ZorgDomein zet op één pagina een kopje "Actuele storingen" en daaronder een
    kopje "Gepland onderhoud". Zonder dit onderscheid telt aangekondigd onderhoud
    mee als actuele storing, of andersom.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    needle = heading.strip().lower()
    target = None
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if needle in tag.get_text(strip=True).lower():
            target = tag
            break
    if target is None:
        return ""

    level = int(target.name[1])
    parts = []
    for sib in target.find_next_siblings():
        name = getattr(sib, "name", "") or ""
        # Stoppen bij het volgende kopje van hetzelfde of een hoger niveau.
        if re.match(r"^h[1-6]$", name) and int(name[1]) <= level:
            break
        parts.append(sib.get_text(separator=" "))

    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def best_text(html: str) -> tuple[str, str, dict]:
    """Kiest het strengste niveau dat nog genoeg tekst oplevert.

    Geeft (tekst, gebruikt niveau, lengtes per niveau) terug. Die lengtes zijn
    puur diagnostisch: staat 'raw' ook op bijna nul, dan bevat de HTML zelf geen
    status en wordt die waarschijnlijk pas door JavaScript ingeladen.
    """
    lengths = {}
    chosen_text, chosen_level = "", "raw"
    for level in ("strict", "mild", "raw"):
        text = page_text(html, level)
        lengths[level] = len(text)
        if not chosen_text and len(text) >= MIN_TEXT_LENGTH:
            chosen_text, chosen_level = text, level
    if not chosen_text:
        # Alles bleef onder de drempel: neem dan wat er nog het meest was.
        chosen_level = max(lengths, key=lambda k: lengths[k])
        chosen_text = page_text(html, chosen_level)
    return chosen_text, chosen_level, lengths


def context_around(text: str, phrase: str, width: int = 120) -> str:
    """Geeft de tekst rondom een gevonden zinsnede, om te kunnen controleren of
    het echt om een statusmelding gaat en niet om bijvoorbeeld een menu-item."""
    pos = text.lower().find(phrase)
    if pos < 0:
        return ""
    start = max(0, pos - width)
    end = min(len(text), pos + len(phrase) + width)
    return ("\u2026" if start else "") + text[start:end] + ("\u2026" if end < len(text) else "")


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
        "text_lengths": {},
        "match_context": "",
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

    text, level, lengths = best_text(resp.text)

    # Staat er een sectie in sites.json? Dan is die specifieker dan de hele pagina.
    wanted = site.get("section")
    if wanted:
        section = section_text(resp.text, wanted)
        if len(section) >= 20:
            text, level = section, f"section:{wanted}"
            lengths = dict(lengths, section=len(section))

    status, phrase = classify_text(text)
    result["status"] = status
    result["method"] = f"text:{level}"
    # Diagnostisch: hoeveel tekst elk filterniveau opleverde. Staat 'raw' ook laag,
    # dan zit de status niet in de HTML maar wordt die door JavaScript geladen.
    result["text_lengths"] = lengths
    result["detail"] = f"Gevonden op de pagina: “{phrase}”" if phrase else (
        "Geen bekende signaalwoorden gevonden — controleer de pagina zelf."
    )
    # De omliggende tekst laat zien of het om een echte melding gaat of om,
    # bijvoorbeeld, een menu-item dat toevallig hetzelfde woord bevat.
    result["match_context"] = context_around(text, phrase) if phrase else ""
    # Dit fragment helpt bij het bijstellen van de signaalwoorden.
    result["excerpt"] = text[:1500]
    return result


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def load_sites() -> list[dict]:
    """Leest sites.json en geeft de lijst met diensten terug."""
    config = load_json(ROOT / "sites.json", None)
    if not config or not config.get("sites"):
        return []
    return config["sites"]


def run_checks(write: bool = True) -> list[dict]:
    """Controleert alle diensten uit sites.json.

    Met write=True worden de resultaten ook naar docs/data/ geschreven (zoals de
    GitHub Actions-workflow doet). De desktop-app gebruikt write=False, want die
    hoeft niets op te slaan.
    """
    results = [check_site(site) for site in load_sites()]
    if write:
        save_results(results)
    return results


def save_results(results: list[dict]) -> None:
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


def main() -> int:
    if not load_sites():
        print("FOUT: sites.json ontbreekt of bevat geen sites.", file=sys.stderr)
        return 1

    results = run_checks(write=True)

    for res in results:
        print(f"{res['status'].upper():<11} {res['name']:<22} ({res['method'] or 'n/a'}) {res['detail']}")
        if res.get("text_lengths"):
            lens = " ".join(f"{k}={v}" for k, v in res["text_lengths"].items())
            print(f"            tekstlengte: {lens}")
        if res.get("match_context"):
            print(f"            context:  {res['match_context']}")
        elif res["excerpt"]:
            print(f"            fragment: {res['excerpt'][:200]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
