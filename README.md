# Dees Status Check

Een kleine monitoringtool die elk uur drie statuspagina's controleert en het
resultaat toont op een simpel dashboard. Geen server nodig: GitHub doet het werk.

Gecontroleerde diensten:

| Dienst | Statuspagina |
| --- | --- |
| Aurora Innovation | https://aurorainnovation.com/en/service-status/ |
| ZorgDomein | https://zorgdomein.com/actuele-storingen/ |
| Lantel Cloud | https://status.lantelcloud.nl/ |

## Hoe het werkt (in het kort)

1. **GitHub Actions** start elk uur automatisch een kleine computer in de cloud.
2. Die draait `check_status.py`, dat de drie pagina's ophaalt en per dienst
   bepaalt: is het in orde, is er een storing, of is er onderhoud?
3. Het resultaat wordt opgeslagen in `docs/data/status.json`.
4. Het dashboard `docs/index.html` leest dat bestand en toont het.

Er komt dus geen server of database aan te pas. De resultaten staan gewoon als
bestand in deze repository, en GitHub Pages serveert de pagina.

## De bestanden

| Bestand | Wat het doet |
| --- | --- |
| `sites.json` | **Dit pas je aan** om diensten toe te voegen of te wijzigen. |
| `check_status.py` | Haalt de pagina's op en bepaalt de status. |
| `test_check_status.py` | Tests voor de herkenningslogica (werkt zonder internet). |
| `docs/index.html` | Het dashboard dat je in je browser ziet. |
| `docs/data/status.json` | De laatste meting. Wordt automatisch geschreven. |
| `docs/data/history.json` | De laatste 240 metingen per dienst (voor het balkje). |
| `.github/workflows/check-status.yml` | De uurlijkse automatische controle. |

## Hoe de status bepaald wordt

Het script probeert twee methodes, in deze volgorde:

1. **JSON-eindpunt** (het betrouwbaarst). Veel statuspagina's draaien op standaard
   software zoals Atlassian Statuspage of Instatus. Die bieden hun status ook
   machineleesbaar aan, bijvoorbeeld op `/api/v2/summary.json`. Vindt het script
   dat, dan gebruikt het dat.
2. **Tekst lezen** (de terugvaloptie). Anders wordt de HTML-pagina opgehaald en de
   tekst nagelezen op signaalwoorden zoals "geen storingen", "actuele storing",
   "gepland onderhoud", "major outage".

   Menu's, headers, footers en cookiebalken worden eerst weggegooid. Dat is nodig:
   het menu van ZorgDomein bevat het item "Actuele storingen", en zonder filtering
   werd dat gelezen als een echte storing.

   Dat filteren gebeurt op drie niveaus (`strict`, `mild`, `raw`). Het script kiest
   het strengste niveau dat nog minstens 200 tekens oplevert. Zo wordt voorkomen dat
   een site waarbij het filter te veel wegsnijdt helemaal zonder tekst komt te
   zitten. Welk niveau gebruikt is, staat in het veld `method`, bijvoorbeeld
   `text:strict`.

Mogelijke uitkomsten:

| Status | Betekenis |
| --- | --- |
| `ok` | Geen bekende problemen. |
| `incident` | Er is een storing gemeld. |
| `maintenance` | Gepland onderhoud. |
| `unknown` | Pagina gelezen, maar geen signaalwoorden herkend. |
| `error` | Pagina was niet bereikbaar. |

`unknown` is bewust een aparte status. Liever eerlijk "ik weet het niet" dan een
vals "alles is in orde".

## Eenmalige instelling: GitHub Pages aanzetten

Het dashboard is pas zichtbaar als je Pages aanzet:

1. Ga in deze repository naar **Settings** → **Pages**.
2. Bij **Source** kies je **Deploy from a branch**.
3. Kies branch `main` en map `/docs`. Klik op **Save**.

Na een minuut staat je dashboard op
`https://samph0ny.github.io/Dees-status-check/`.

## Zelf draaien op je eigen computer

```bash
pip install -r requirements.txt
python3 check_status.py      # controleert de sites, schrijft docs/data/
python3 test_check_status.py # draait de tests
```

Het dashboard bekijken (het leest bestanden, dus het heeft een kleine webserver
nodig — rechtstreeks openen met `file://` werkt niet):

```bash
python3 -m http.server 8000 --directory docs
# open daarna http://localhost:8000
```

## Een dienst toevoegen

Zet er een blokje bij in `sites.json`:

```json
{
  "id": "korte-naam-zonder-spaties",
  "name": "Naam zoals die op het dashboard komt",
  "url": "https://voorbeeld.nl/status",
  "language": "nl"
}
```

Commit en push — de volgende controle neemt hem mee.

## Als een dienst `unknown` blijft

Dan herkent het script de woorden op die pagina nog niet. In
`docs/data/status.json` staan per dienst twee hulpvelden: `excerpt` (de eerste
1500 tekens zoals het script de pagina leest, dus na het weggooien van menu's) en
`match_context` (de tekst rondom de gevonden zinsnede, zodat je kunt zien of het
om een echte melding gaat).

Daarnaast staat er `text_lengths`: hoeveel tekst elk filterniveau opleverde. Staat
`raw` daar ook op bijna nul, dan bevat de HTML zelf geen status en wordt die pas
door JavaScript ingeladen. Filteren helpt dan niet — zo'n site heeft een andere
aanpak nodig. Daar zie je welke bewoording de site
gebruikt. Voeg die zinsnede toe aan `OK_PHRASES`, `INCIDENT_PHRASES` of
`MAINTENANCE_PHRASES` bovenin `check_status.py`.

Let op de volgorde: de OK-zinnen worden eerst gecontroleerd, omdat "geen
storingen" nu eenmaal het woord "storingen" bevat.
