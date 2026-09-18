#!/usr/bin/env python3
"""Desktop-app die de statuspagina's uit sites.json in de gaten houdt.

Starten:  python3 status_app.py   (of dubbelklik op start_app.bat op Windows)

De app gebruikt dezelfde controlelogica als check_status.py, maar draait op je
eigen computer. Daardoor zijn er geen GitHub Actions-minuten mee gemoeid en kun
je veel vaker verversen dan het uurlijkse schema op GitHub.

De controles draaien in een achtergrondthread, zodat het venster niet bevriest
terwijl er op de websites gewacht wordt.
"""

from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - alleen op systemen zonder tkinter
    print(
        "Kan tkinter niet laden. Dat hoort standaard bij Python op Windows en macOS.\n"
        "Op Linux installeer je het met:  sudo apt install python3-tk",
        file=sys.stderr,
    )
    raise SystemExit(1)

from check_status import load_sites, check_site

# Hoe vaak er ververst kan worden. De sleutel is wat je in het menu ziet.
INTERVALS = {
    "30 seconden": 30,
    "1 minuut": 60,
    "5 minuten": 300,
    "15 minuten": 900,
    "1 uur": 3600,
}
DEFAULT_INTERVAL = "1 minuut"

KLEUREN = {
    "ok": "#1a8a4a",
    "incident": "#c62828",
    "maintenance": "#1565c0",
    "unknown": "#6b7280",
    "error": "#b55a00",
    "bezig": "#9aa2aa",
}
LABELS = {
    "ok": "In orde",
    "incident": "Storing",
    "maintenance": "Onderhoud",
    "unknown": "Onbekend",
    "error": "Niet bereikbaar",
}


class StatusApp:
    def __init__(self, root: tk.Tk, sites: list[dict]) -> None:
        self.root = root
        self.sites = sites
        self.rows: dict[str, dict] = {}
        self.results: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.interval = INTERVALS[DEFAULT_INTERVAL]

        root.title("Status Check")
        root.minsize(560, 120 + 70 * len(sites))

        self._build_ui()
        self._start_worker()
        self.root.after(200, self._drain_results)

    # --- Venster opbouwen --------------------------------------------------
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        for site in self.sites:
            card = ttk.Frame(outer, padding=(0, 8))
            card.pack(fill="x")

            top = ttk.Frame(card)
            top.pack(fill="x")

            dot = tk.Canvas(top, width=14, height=14, highlightthickness=0)
            circle = dot.create_oval(2, 2, 12, 12, fill=KLEUREN["bezig"], outline="")
            dot.pack(side="left", padx=(0, 10))

            ttk.Label(top, text=site["name"], font=("", 11, "bold")).pack(side="left")

            badge = ttk.Label(top, text="Controleren…")
            badge.pack(side="right")

            detail = ttk.Label(card, text="", foreground="#61686f", wraplength=520,
                               justify="left")
            detail.pack(fill="x", pady=(4, 0))

            ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=4)

            self.rows[site["id"]] = {
                "canvas": dot, "circle": circle, "badge": badge, "detail": detail,
            }

        bar = ttk.Frame(outer, padding=(0, 10, 0, 0))
        bar.pack(fill="x")

        ttk.Label(bar, text="Verversen elke:").pack(side="left")

        self.interval_var = tk.StringVar(value=DEFAULT_INTERVAL)
        keuze = ttk.Combobox(bar, textvariable=self.interval_var, state="readonly",
                             values=list(INTERVALS), width=12)
        keuze.pack(side="left", padx=8)
        keuze.bind("<<ComboboxSelected>>", self._on_interval_change)

        ttk.Button(bar, text="Nu verversen", command=self.refresh_now).pack(side="left")

        self.status_label = ttk.Label(bar, text="", foreground="#61686f")
        self.status_label.pack(side="right")

    # --- Achtergrondwerk ---------------------------------------------------
    def _start_worker(self) -> None:
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _loop(self) -> None:
        """Draait in een aparte thread: controleert, wacht, herhaalt."""
        while not self.stop_event.is_set():
            for site in self.sites:
                if self.stop_event.is_set():
                    return
                try:
                    self.results.put(check_site(site))
                except Exception as exc:  # netwerk- of parsefout: nooit crashen
                    self.results.put({
                        "id": site["id"], "name": site["name"], "status": "error",
                        "detail": f"Onverwachte fout: {exc.__class__.__name__}",
                        "checked_at": datetime.now().isoformat(timespec="seconds"),
                    })
            self.results.put({"__ronde_klaar__": True})
            # Wachten tot het interval om is, of tot er op "Nu verversen" is geklikt.
            self.wake_event.wait(self.interval)
            self.wake_event.clear()

    def refresh_now(self) -> None:
        self.wake_event.set()
        self.status_label.config(text="Controleren…")

    def _on_interval_change(self, _event=None) -> None:
        self.interval = INTERVALS[self.interval_var.get()]
        self.refresh_now()

    # --- Resultaten in het venster zetten ----------------------------------
    def _drain_results(self) -> None:
        while True:
            try:
                res = self.results.get_nowait()
            except queue.Empty:
                break
            if res.get("__ronde_klaar__"):
                klok = datetime.now().strftime("%H:%M:%S")
                self.status_label.config(text=f"Laatste controle: {klok}")
                continue
            self._update_row(res)
        self.root.after(200, self._drain_results)

    def _update_row(self, res: dict) -> None:
        row = self.rows.get(res["id"])
        if not row:
            return
        status = res.get("status", "unknown")
        row["canvas"].itemconfig(row["circle"], fill=KLEUREN.get(status, KLEUREN["unknown"]))
        row["badge"].config(text=LABELS.get(status, status))
        row["detail"].config(text=res.get("detail", ""))

    def on_close(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        self.root.destroy()


def main() -> int:
    sites = load_sites()
    if not sites:
        print("FOUT: sites.json ontbreekt of bevat geen sites.", file=sys.stderr)
        return 1

    root = tk.Tk()
    app = StatusApp(root, sites)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
