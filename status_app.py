#!/usr/bin/env python3
"""Desktop-app die de statuspagina's uit sites.json in de gaten houdt.

Starten:  python3 status_app.py   (of dubbelklik start_app.bat op Windows)

De app gebruikt dezelfde controlelogica als check_status.py, maar draait op je
eigen computer. Daardoor zijn er geen GitHub Actions-minuten mee gemoeid.

Het venster ververst zichzelf elke 70 seconden. De voortgang daarvan loopt als
een dun lijntje rond de Refresh-knop, in de kleur van de zwaarste status die op
dat moment te zien is.
"""

from __future__ import annotations

import math
import queue
import sys
import threading
import time
from pathlib import Path
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:  # pragma: no cover - alleen op systemen zonder tkinter
    print(
        "Kan tkinter niet laden. Dat hoort standaard bij Python op Windows en macOS.\n"
        "Op Linux installeer je het met:  sudo apt install python3-tk",
        file=sys.stderr,
    )
    raise SystemExit(1)

try:
    import pystray
    from PIL import Image
    TRAY_BESCHIKBAAR = True
except ImportError:  # zonder deze pakketten draait de app gewoon zonder systeemvak
    TRAY_BESCHIKBAAR = False

from check_status import load_sites, check_site


def bestandspad(naam: str) -> Path:
    """Vindt een meegeleverd bestand, ook als PyInstaller er een .exe van maakte.

    PyInstaller pakt meegeleverde bestanden uit in een tijdelijke map; het pad
    daarvan staat in sys._MEIPASS. Daarbuiten ligt het gewoon naast dit script.
    """
    tijdelijk = getattr(sys, "_MEIPASS", None)
    if tijdelijk:
        kandidaat = Path(tijdelijk) / naam
        if kandidaat.exists():
            return kandidaat
    return Path(__file__).parent / naam

# --- Vaste instellingen -------------------------------------------------------
INTERVAL = 70           # seconden tussen twee automatische controles
TICK_MS = 100           # hoe vaak het ringetje opnieuw getekend wordt
VENSTER_B, VENSTER_H = 420, 380

# --- Palet --------------------------------------------------------------------
BG        = "#0D0A0C"   # bijna zwart, warme ondertoon
BONE      = "#E9E1DD"   # botwit
MUTED     = "#9A8B92"
FAINT     = "#6E626A"
RULE      = "#241C22"   # scheidingslijn onder de voettekst
ROW_LINE  = "#1F191E"
ACCENT    = "#791F65"   # rusttoestand: koplijn en ring
WINE      = "#B3384F"   # storing
PLUM      = "#8A6E9B"   # onderhoud
AMBER     = "#C08A4A"   # onbereikbaar
GREY      = "#8B8188"   # onbekend
CHECKING  = "#6E656B"
BTN_BG    = "#1E1620"
TRACK     = "#2A2129"   # onbelichte helft van de ring

# Kleur van het stipje per status. "In orde" krijgt bewust de accentkleur en een
# botwit label: de betekenis zit in het woord, de kleur is versiering.
STIP = {"ok": ACCENT, "incident": WINE, "maintenance": PLUM,
        "error": AMBER, "unknown": GREY, "checking": CHECKING}
LABELKLEUR = {"ok": BONE, "incident": WINE, "maintenance": PLUM,
              "error": AMBER, "unknown": GREY, "checking": CHECKING}
# Een probleemstatus krijgt een nauwelijks zichtbare tint achter de rij.
TINT = {"incident": "#191014", "maintenance": "#16111A", "error": "#1A1610"}
LABEL = {"ok": "In orde", "incident": "Storing", "maintenance": "Onderhoud",
         "unknown": "Onbekend", "error": "Onbereikbaar", "checking": "Controleren"}

# Bij een dienst zonder problemen tonen we een vaste zin. Welk woord de scraper
# precies vond is nuttig voor het bijstellen van de herkenning (dat staat in
# docs/data/status.json), maar in het venster is het alleen ruis.
TEKST_IN_ORDE = "Geen actuele storingen"

# Van zwaar naar licht. De ring neemt de kleur van de zwaarste status die
# voorkomt; alles vanaf 'maintenance' valt terug op de accentkleur.
ERNST = ["incident", "error"]


# Het icoon in het systeemvak is maar 16 bij 16 pixels en staat op de taakbalk,
# niet op onze eigen donkere achtergrond. De accentkleur is daar te donker voor
# (1,7:1 op een donkere taakbalk), dus die wordt lichter gemaakt. De andere
# kleuren zijn licht bijgesteld zodat ze op een donkere en een lichte taakbalk
# allebei minstens 3:1 halen.
TRAY_KLEUR = {
    "ok": "#C232A2",           # accent, opgelicht
    "incident": "#C95168",     # wijnrood, opgelicht
    "maintenance": "#8A6E9B",  # pruim
    "error": "#C08A4A",        # amber
    "unknown": "#8B8188",
    "checking": "#6E656B",
}

# Van zwaarst naar lichtst: het systeemvak toont de ernstigste status.
VOLGORDE = ["incident", "error", "maintenance", "unknown", "checking", "ok"]


def ergste(statussen) -> str:
    """Geeft de zwaarste status uit een verzameling."""
    aanwezig = set(statussen)
    for status in VOLGORDE:
        if status in aanwezig:
            return status
    return "ok"


def tray_tekst(per_dienst: dict) -> str:
    """Maakt de tekst die verschijnt als je over het systeemvak-icoon zweeft.

    per_dienst is {naam van de dienst: status}.
    """
    problemen = [naam for naam, status in per_dienst.items() if status not in RUSTIG]
    if not problemen:
        return "Status Check \u2014 alles in orde"
    if len(problemen) == 1:
        naam = problemen[0]
        return f"Status Check \u2014 {LABEL.get(per_dienst[naam], '?').lower()}: {naam}"
    return f"Status Check \u2014 {len(problemen)} diensten met een melding"


# Statussen die geen aandacht vragen. Alles daarbuiten (storing, onderhoud,
# onbekend, onbereikbaar) laat het taakbalkicoon knipperen.
RUSTIG = {"ok"}


def alles_in_orde(statussen) -> bool:
    return all(status in RUSTIG for status in statussen)


def moet_knipperen(vorige: dict, nieuwe: dict) -> bool:
    """Bepaalt of het taakbalkicoon moet gaan knipperen.

    Alleen bij een nieuw of veranderd probleem. Een storing die al drie rondes
    bestaat, laat het icoon dus niet elke keer opnieuw knipperen: dan zou het
    blijven ratelen terwijl je het allang weet.
    """
    for id_, status in nieuwe.items():
        if status in RUSTIG:
            continue
        if vorige.get(id_) != status:
            return True
    return False


def ring_kleur(statussen) -> str:
    """Geeft de ringkleur voor de zwaarste status in de lijst."""
    aanwezig = set(statussen)
    for status in ERNST:
        if status in aanwezig:
            return {"incident": WINE, "error": AMBER}[status]
    return ACCENT


def afgeronde_rechthoek(x0, y0, x1, y1, r, per_hoek=6):
    """Punten langs een afgeronde rechthoek, met de klok mee vanaf linksboven.

    Wordt gebruikt om de voortgangsring te tekenen: door het eerste deel van
    deze punten te verbinden ontstaat een lijn die steeds verder rondloopt.
    """
    # Alleen de vier hoeken worden beschreven; de rechte zijden ontstaan vanzelf
    # doordat het eindpunt van de ene boog en het beginpunt van de volgende op
    # dezelfde lijn liggen. Zo kan er geen zijde meer verkeerd berekend worden.
    hoeken = [
        (x1 - r, y0 + r, -math.pi / 2, 0.0),          # rechtsboven
        (x1 - r, y1 - r, 0.0, math.pi / 2),           # rechtsonder
        (x0 + r, y1 - r, math.pi / 2, math.pi),       # linksonder
        (x0 + r, y0 + r, math.pi, 1.5 * math.pi),     # linksboven
    ]

    def op_boog(cx, cy, hoek):
        return (cx + r * math.cos(hoek), cy + r * math.sin(hoek))

    punten = [(x0 + r, y0)]                # begin van de bovenrand
    for cx, cy, a0, a1 in hoeken:
        punten.append(op_boog(cx, cy, a0))  # einde van de rechte zijde ervoor
        for stap in range(1, per_hoek + 1):
            punten.append(op_boog(cx, cy, a0 + (a1 - a0) * stap / per_hoek))
    punten.append((x0 + r, y0))            # terug bij het begin
    return punten


def deel_van_pad(punten, fractie):
    """Geeft het eerste deel van een pad terug, als fractie van de totale lengte."""
    fractie = max(0.0, min(1.0, fractie))
    lengtes = [math.dist(punten[i], punten[i + 1]) for i in range(len(punten) - 1)]
    totaal = sum(lengtes)
    if totaal == 0 or fractie == 0:
        return []
    doel = totaal * fractie
    pad, afgelegd = [punten[0]], 0.0
    for i, lengte in enumerate(lengtes):
        if afgelegd + lengte >= doel:
            rest = (doel - afgelegd) / lengte if lengte else 0
            x0, y0 = punten[i]
            x1, y1 = punten[i + 1]
            pad.append((x0 + (x1 - x0) * rest, y0 + (y1 - y0) * rest))
            break
        pad.append(punten[i + 1])
        afgelegd += lengte
    return pad


def kies_lettertype(voorkeuren, standaard, beschikbaar=None):
    """Kiest het eerste lettertype dat op dit systeem aanwezig is."""
    families = set(beschikbaar if beschikbaar is not None else tkfont.families())
    for naam in voorkeuren:
        if naam in families:
            return naam
    return standaard


class RefreshKnop(tk.Canvas):
    """Knop met een voortgangsring eromheen, getekend op een canvas."""

    B, H, R = 112, 36, 5

    def __init__(self, ouder, bij_klik):
        super().__init__(ouder, width=self.B, height=self.H, bg=BG,
                         highlightthickness=0, cursor="hand2")
        self.bij_klik = bij_klik
        self.pad = afgeronde_rechthoek(1, 1, self.B - 1, self.H - 1, self.R)
        self.kleur = ACCENT
        self.lettertype = ("TkDefaultFont", 9, "bold")
        self.bind("<Button-1>", lambda _e: self.bij_klik())
        self.teken(0.0)

    def teken(self, fractie: float) -> None:
        self.delete("all")
        self.create_rectangle(1, 1, self.B - 1, self.H - 1, fill=BTN_BG, outline="")
        # De hele omtrek in gedempte kleur, daaroverheen het afgelegde deel.
        self.create_line([c for p in self.pad for c in p],
                         fill=TRACK, width=2, joinstyle="round")
        deel = deel_van_pad(self.pad, fractie)
        if len(deel) > 1:
            self.create_line([c for p in deel for c in p],
                             fill=self.kleur, width=2, capstyle="round",
                             joinstyle="round")
        self.create_text(self.B / 2, self.H / 2, text="Refresh",
                         fill=BONE, font=self.lettertype)


class StatusApp:
    def __init__(self, root: tk.Tk, sites: list[dict]) -> None:
        self.root = root
        self.sites = sites
        self.rijen: dict[str, dict] = {}
        self.statussen: dict[str, str] = {s["id"]: "checking" for s in sites}
        self.vorige_statussen: dict[str, str] = {}
        self.resultaten: queue.Queue = queue.Queue()
        self.bezig = False
        self.cyclus_start = time.monotonic()

        root.title("Status Check")
        root.configure(bg=BG)
        root.geometry(f"{VENSTER_B}x{VENSTER_H}")
        root.resizable(False, False)
        self._zet_icoon()

        self.serif = kies_lettertype(["Georgia", "Times New Roman"], "TkDefaultFont")
        self.sans = kies_lettertype(
            ["Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans"], "TkDefaultFont")

        self.tray = None
        self._tray_basis = None

        self._bouw_venster()
        self._bouw_tray()
        # Het kruisje verbergt het venster; afsluiten gaat via het systeemvak.
        root.protocol("WM_DELETE_WINDOW", self._verberg)
        self._ververs_nu()
        self.root.after(TICK_MS, self._tik)

    # --- Systeemvak -------------------------------------------------------
    def _bouw_tray(self) -> None:
        """Zet het icoon in het systeemvak, naast de klok."""
        if not TRAY_BESCHIKBAAR:
            return
        pad = bestandspad("icon.png")
        if not pad.exists():
            return
        try:
            self._tray_basis = Image.open(pad).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem("Tonen", self._tray_tonen, default=True),
                pystray.MenuItem("Nu verversen", self._tray_verversen),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Afsluiten", self._tray_afsluiten),
            )
            self.tray = pystray.Icon(
                "status_check", self._tray_beeld("checking"),
                "Status Check", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            self.tray = None  # zonder systeemvak werkt de app nog prima

    def _tray_beeld(self, status: str):
        """Kleurt de vleermuis in de kleur die bij een status hoort."""
        kleur = TRAY_KLEUR.get(status, TRAY_KLEUR["unknown"])
        gekleurd = Image.new("RGBA", self._tray_basis.size, kleur)
        gekleurd.putalpha(self._tray_basis.getchannel("A"))
        return gekleurd

    def _werk_tray_bij(self) -> None:
        if not self.tray:
            return
        per_dienst = {s["name"]: self.statussen.get(s["id"], "unknown")
                      for s in self.sites}
        try:
            self.tray.icon = self._tray_beeld(ergste(per_dienst.values()))
            self.tray.title = tray_tekst(per_dienst)
        except Exception:
            pass

    # De menu-items draaien in de thread van pystray, dus het werk wordt
    # teruggegeven aan tkinter met after().
    def _tray_tonen(self, *_):
        self.root.after(0, self._toon_venster)

    def _tray_verversen(self, *_):
        self.root.after(0, self._ververs_nu)

    def _tray_afsluiten(self, *_):
        self.root.after(0, self._afsluiten)

    def _toon_venster(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _verberg(self) -> None:
        """Het kruisje verbergt het venster als er een systeemvak-icoon is."""
        if self.tray:
            self.root.withdraw()
        else:
            self._afsluiten()

    def _afsluiten(self) -> None:
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _knipper(self, aan: bool) -> None:
        """Laat het taakbalkicoon knipperen (alleen Windows).

        Windows heeft hier FlashWindowEx voor: hetzelfde mechanisme dat een
        mailprogramma gebruikt bij een nieuw bericht. Met FLASHW_TIMERNOFG
        knippert het door tot je het venster naar voren haalt, en niet langer.

        macOS en Linux hebben geen vergelijkbare aanroep die vanuit tkinter
        bereikbaar is; daar gebeurt er niets.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT),
                            ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD),
                            ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            FLASHW_STOP = 0
            FLASHW_ALL = 3          # zowel de titelbalk als de taakbalkknop
            FLASHW_TIMERNOFG = 12   # blijf knipperen tot het venster vooraan staat

            # winfo_id() geeft het binnenste venster; de taakbalkknop hoort bij
            # het venster daarboven.
            binnenste = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetParent(binnenste) or binnenste

            info = FLASHWINFO(
                ctypes.sizeof(FLASHWINFO), hwnd,
                (FLASHW_ALL | FLASHW_TIMERNOFG) if aan else FLASHW_STOP, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass  # knipperen is een extraatje, nooit een reden om te stoppen

    def _zet_icoon(self) -> None:
        """Zet het venstericoon. Mislukt dat, dan draait de app gewoon door."""
        pad = bestandspad("icon.png")
        if not pad.exists():
            return
        try:
            self._icoon = tk.PhotoImage(file=str(pad))
            self.root.iconphoto(True, self._icoon)
        except tk.TclError:
            pass  # geen icoon is vervelend, maar geen reden om te stoppen

    # --- Venster ----------------------------------------------------------
    def _bouw_venster(self) -> None:
        kop = tk.Frame(self.root, bg=BG)
        kop.pack(fill="x", padx=22, pady=(20, 0))
        tk.Label(kop, text="Status Check", bg=BG, fg=BONE,
                 font=(self.serif, 16, "bold")).pack(side="left")
        self.klok = tk.Label(kop, text="", bg=BG, fg=FAINT, font=(self.sans, 8))
        self.klok.pack(side="right", pady=(6, 0))

        tk.Frame(self.root, bg=ACCENT, height=1).pack(fill="x", pady=(14, 0))

        for i, site in enumerate(self.sites):
            rij = tk.Frame(self.root, bg=BG)
            rij.pack(fill="x")

            binnen = tk.Frame(rij, bg=BG)
            binnen.pack(fill="x", padx=22, pady=11)

            boven = tk.Frame(binnen, bg=BG)
            boven.pack(fill="x")

            stip = tk.Canvas(boven, width=10, height=10, bg=BG, highlightthickness=0)
            bol = stip.create_oval(1, 1, 9, 9, fill=CHECKING, outline="")
            stip.pack(side="left", padx=(0, 10))

            naam = tk.Label(boven, text=site["name"], bg=BG, fg=BONE,
                            font=(self.sans, 10, "bold"))
            naam.pack(side="left")

            merk = tk.Label(boven, text="", bg=BG, fg=CHECKING,
                            font=(self.sans, 7, "bold"))
            merk.pack(side="right")

            detail = tk.Label(binnen, text="", bg=BG, fg=MUTED, anchor="w",
                              font=(self.sans, 8))
            detail.pack(fill="x", padx=(20, 0), pady=(4, 0))

            if i < len(self.sites) - 1:
                tk.Frame(self.root, bg=ROW_LINE, height=1).pack(fill="x")

            self.rijen[site["id"]] = {
                "rij": rij, "binnen": binnen, "boven": boven, "stip": stip,
                "bol": bol, "naam": naam, "merk": merk, "detail": detail,
            }

        voet = tk.Frame(self.root, bg=BG)
        voet.pack(side="bottom", fill="x")
        tk.Frame(voet, bg=RULE, height=1).pack(fill="x")

        balk = tk.Frame(voet, bg=BG)
        balk.pack(fill="x", padx=22, pady=11)
        self.knop = RefreshKnop(balk, self._ververs_nu)
        self.knop.lettertype = (self.sans, 8, "bold")
        self.knop.pack(side="right")

    def _kleur_rij(self, id_: str, status: str) -> None:
        rij = self.rijen[id_]
        achtergrond = TINT.get(status, BG)
        for widget in (rij["rij"], rij["binnen"], rij["boven"], rij["stip"],
                       rij["naam"], rij["merk"], rij["detail"]):
            widget.configure(bg=achtergrond)
        rij["stip"].itemconfig(rij["bol"], fill=STIP.get(status, GREY))
        rij["merk"].configure(text=LABEL.get(status, status),
                              fg=LABELKLEUR.get(status, GREY))

    # --- Verversen --------------------------------------------------------
    def _ververs_nu(self) -> None:
        if self.bezig:
            return
        self.bezig = True
        self.cyclus_start = time.monotonic()
        for site in self.sites:
            self.statussen[site["id"]] = "checking"
            self._kleur_rij(site["id"], "checking")
            self.rijen[site["id"]]["detail"].configure(text="Bezig met ophalen…")
        self.knop.kleur = ring_kleur(self.statussen.values())
        threading.Thread(target=self._controleer, daemon=True).start()

    def _controleer(self) -> None:
        for site in self.sites:
            try:
                self.resultaten.put(check_site(site))
            except Exception as exc:  # nooit crashen op een kapotte pagina
                self.resultaten.put({
                    "id": site["id"], "name": site["name"], "status": "error",
                    "detail": f"Onverwachte fout: {exc.__class__.__name__}",
                })
        self.resultaten.put({"__klaar__": True})

    def _tik(self) -> None:
        while True:
            try:
                res = self.resultaten.get_nowait()
            except queue.Empty:
                break
            if res.get("__klaar__"):
                self.bezig = False
                self.klok.configure(text=datetime.now().strftime("%H:%M"))
                # Pas nu beoordelen: tijdens de ronde staat alles op 'checking'.
                if moet_knipperen(self.vorige_statussen, self.statussen):
                    self._knipper(True)
                elif alles_in_orde(self.statussen.values()):
                    self._knipper(False)
                self.vorige_statussen = dict(self.statussen)
                self._werk_tray_bij()
                continue
            self._toon(res)

        verstreken = time.monotonic() - self.cyclus_start
        self.knop.teken(min(1.0, verstreken / INTERVAL))
        if verstreken >= INTERVAL and not self.bezig:
            self._ververs_nu()

        self.root.after(TICK_MS, self._tik)

    def _toon(self, res: dict) -> None:
        id_ = res.get("id")
        if id_ not in self.rijen:
            return
        status = res.get("status", "unknown")
        self.statussen[id_] = status
        self._kleur_rij(id_, status)
        tekst = TEKST_IN_ORDE if status == "ok" else res.get("detail", "")
        self.rijen[id_]["detail"].configure(text=tekst)
        self.knop.kleur = ring_kleur(self.statussen.values())


def main() -> int:
    sites = load_sites()
    if not sites:
        print("FOUT: sites.json ontbreekt of bevat geen sites.", file=sys.stderr)
        return 1

    root = tk.Tk()
    StatusApp(root, sites)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
