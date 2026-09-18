# Dees Status Check

Een kleine monitoringtool die elk uur drie statuspagina's controleert en het
resultaat toont op een simpel dashboard. Geen server nodig: GitHub doet het werk.

Gecontroleerde diensten:

| Dienst | Statuspagina |
| --- | --- |
| Aurora Innovation | https://aurorainnovation.com/en/service-status/ |
| ZorgDomein | https://zorgdomein.com/actuele-storingen/ |
| Lantel Cloud | https://status.lantelcloud.nl/ |

Er zijn twee manieren om het te gebruiken:

- **De desktop-app** (`status_app.py`) — draait op je eigen computer en ververst zo
  vaak als je wilt, tot elke 30 seconden. Kost niets.
- **De automatische controle op GitHub** — draait elk uur vanzelf door en bouwt een
  geschiedenis op, ook als je computer uit staat.

## De desktop-app

Op Windows dubbelklik je `start_app.bat`, op macOS `start_app.command`. Die
controleren of alle pakketten aanwezig zijn en installeren ze de eerste keer
vanzelf. Liever met de hand:

```bash
pip install -r requirements.txt
python3 status_app.py
```

In de **.exe** zit dit allemaal al ingebouwd: Python zelf en alle pakketten zitten
in dat ene bestand. Daar hoef je niets voor te installeren.

De app ververst zichzelf elke 70 seconden. De voortgang daarvan loopt als een dun
lijntje rond de Refresh-knop; dat lijntje is meteen de enige aanduiding van het
interval. Met die knop forceer je direct een controle. De
controles draaien op de achtergrond, dus het venster blijft bruikbaar terwijl er
gewacht wordt.

Naast de klok, in het systeemvak, staat een vleermuisicoon in de kleur van de
zwaarste status: alles in orde, onderhoud, onbereikbaar of storing. Zweef er met
je muis overheen voor een korte samenvatting. Rechtsklikken geeft een menu met
**Tonen**, **Nu verversen** en **Afsluiten**; dubbelklikken opent het venster.

Die kleuren zijn iets lichter dan in het venster. Het icoon is maar 16 bij 16
pixels en staat op de taakbalk in plaats van op onze eigen donkere achtergrond;
de accentkleur haalt daar maar 1,7:1 contrast en zou wegvallen.

**Het kruisje sluit de app niet af** maar verbergt het venster — het blijft in het
systeemvak doordraaien. Afsluiten doe je via het menu daar. Ontbreken `pystray` of
`pillow`, dan is er geen systeemvak-icoon en sluit het kruisje de app gewoon af.

Is er iets anders dan "in orde", dan gaat het taakbalkicoon knipperen tot je het
venster naar voren haalt. Dat gebeurt alleen bij een nieuw of veranderd probleem:
een storing die al drie rondes bestaat laat het icoon niet elke keer opnieuw
ratelen. Windows heeft hier een eigen aanroep voor (`FlashWindowEx`); op macOS en
Linux bestaat geen vergelijkbare mogelijkheid vanuit tkinter, dus daar gebeurt er
niets.

Dat lijntje krijgt de kleur van de zwaarste status die op dat moment te zien is:
wijnrood bij een storing, amber als een pagina onbereikbaar is, en anders de
accentkleur. Zo zie je aan de onderrand al of er iets aan de hand is.

Wil je een ander interval? Pas `INTERVAL` bovenin `status_app.py` aan.

**Als de app niet start met "No module named tkinter":** tkinter hoort standaard bij
Python op Windows en macOS. Op Linux installeer je het los met
`sudo apt install python3-tk`.

## Een .exe maken voor Windows

Zo hoef je Python niet te installeren om de app te gebruiken.

**Via GitHub (aanbevolen — geen Python en geen .bat nodig):** ga naar het tabblad
**Actions**, kies **Windows .exe bouwen** en klik op **Run workflow**. GitHub bouwt
het programma op een Windows-machine. Na een paar minuten staat onderaan die run
een bestand `Status-Check-Windows` klaar om te downloaden, met `Status Check.exe`
en `sites.json` erin.

Zet je bij het starten **Ook een release aanmaken** aan, dan komt het resultaat er
bovendien als release bij te staan. Dat geeft een vaste downloadlink onder
**Releases**, handig als je het later nog eens nodig hebt of naar een collega wilt
sturen. Zonder die optie verdwijnt de download na 90 dagen.

**Op je eigen Windows-computer:** dubbelklik `build_exe.bat`. Het resultaat komt in
de map `dist`.

Het icoon zit in de .exe verwerkt: `icon.ico` wordt het icoon van het bestand zelf,
`icon.png` wordt meegeleverd voor het venster.

Houd `sites.json` altijd náást de .exe staan. Het programma leest dat bestand van
schijf, dus je kunt diensten toevoegen of wijzigen zonder opnieuw te bouwen.

Een .exe kan alleen op Windows gebouwd worden — vandaar dat de workflow op een
Windows-machine draait.

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
| `status_app.py` | De desktop-app. Gebruikt dezelfde logica als hierboven. |
| `start_app.bat` / `start_app.command` | Dubbelklik-starters voor Windows en macOS. |
| `build_exe.bat` | Bouwt de .exe op je eigen Windows-computer. |
| `icon.png` / `icon.ico` | Het vleermuisicoon: voor het venster en voor de .exe. |
| `test_check_status.py` | Tests voor de herkenningslogica (werkt zonder internet). |
| `test_status_app.py` | Tests voor de desktop-app (werkt zonder beeldscherm). |
| `docs/index.html` | Het dashboard dat je in je browser ziet. |
| `docs/data/status.json` | De laatste meting. Wordt automatisch geschreven. |
| `docs/data/history.json` | De laatste 240 metingen per dienst (voor het balkje). |
| `.github/workflows/check-status.yml` | De uurlijkse automatische controle. |
| `.github/workflows/build-exe.yml` | Bouwt de Windows-.exe, handmatig te starten. |

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

In het venster staat bij een dienst zonder problemen altijd dezelfde zin: "Geen
actuele storingen". Welke zinsnede de herkenning precies vond is nuttig bij het
bijstellen, maar dat is diagnostiek — dat blijft in `docs/data/status.json` staan
en hoort niet in beeld.

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

Zet er een blokje bij in `sites.json`. Zowel de app als de automatische controle
lezen datzelfde bestand, dus je hoeft het maar op één plek te doen:

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

## Een pagina met meerdere kopjes

ZorgDomein zet op één pagina een kopje "Actuele storingen" en daaronder een kopje
"Gepland onderhoud". Zonder onderscheid telt aangekondigd onderhoud mee als
actuele storing. Daarvoor is het veld `section` in `sites.json`:

```json
"section": "Actuele storingen"
```

Het script leest dan alleen de tekst die onder dat kopje staat, tot aan het
volgende kopje.
