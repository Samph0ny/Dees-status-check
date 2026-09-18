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
    punten = [(x0 + r, y0), (x1 - r, y0)]
    hoeken = [
        (x1 - r, y0 + r, -math.pi / 2, 0.0),          # rechtsboven
        (x1 - r, y1 - r, 0.0, math.pi / 2),           # rechtsonder
        (x0 + r, y1 - r, math.pi / 2, math.pi),       # linksonder
        (x0 + r, y0 + r, math.pi, 1.5 * math.pi),     # linksboven
    ]
    rechte = [(x1, y1 - r), (x0, y1 - r), (x0, y0 + r)]
    for i, (cx, cy, a0, a1) in enumerate(hoeken):
        for stap in range(1, per_hoek + 1):
            a = a0 + (a1 - a0) * stap / per_hoek
            punten.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        if i < len(rechte):
            punten.append(rechte[i])
    punten.append((x0 + r, y0))
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

        self._bouw_venster()
        self._ververs_nu()
        self.root.after(TICK_MS, self._tik)

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
