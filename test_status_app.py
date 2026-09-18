#!/usr/bin/env python3
"""Tests voor de desktop-app. Draai met: python3 test_status_app.py

Het venster zelf kan hier niet geopend worden, dus tkinter wordt nagebootst.
Wat wel getest wordt: dat elke mogelijke status een kleur en een label heeft, dat
de intervallen kloppen, en dat de achtergrondlus fouten opvangt in plaats van te
crashen.
"""

import sys
import types
from unittest.mock import MagicMock

# tkinter nabootsen, zodat status_app importeerbaar is zonder beeldscherm.
for naam in ("tkinter", "tkinter.ttk"):
    module = types.ModuleType(naam)
    module.__getattr__ = lambda _n: MagicMock()  # type: ignore[attr-defined]
    sys.modules.setdefault(naam, module)
sys.modules["tkinter"].ttk = sys.modules["tkinter.ttk"]

import check_status
import status_app


def test_every_status_has_a_colour_and_label():
    statussen = {check_status.OK, check_status.INCIDENT, check_status.MAINTENANCE,
                 check_status.UNKNOWN, check_status.ERROR}
    for status in statussen:
        assert status in status_app.KLEUREN, f"geen kleur voor {status}"
        assert status in status_app.LABELS, f"geen label voor {status}"


def test_intervals_are_sane():
    assert status_app.DEFAULT_INTERVAL in status_app.INTERVALS
    waarden = list(status_app.INTERVALS.values())
    assert waarden == sorted(waarden), "intervallen horen oplopend te staan"
    assert min(waarden) >= 30, "korter dan 30s is onnodig belastend voor die sites"


def test_worker_loop_survives_a_failing_check(monkeypatch=None):
    """Een kapotte controle mag de app niet onderuit halen."""
    app = object.__new__(status_app.StatusApp)
    app.sites = [{"id": "x", "name": "Test"}]
    app.stop_event = __import__("threading").Event()
    app.wake_event = __import__("threading").Event()
    app.interval = 0
    import queue
    app.results = queue.Queue()

    def boem(_site):
        raise RuntimeError("stuk")

    origineel = status_app.check_site
    status_app.check_site = boem
    try:
        # Eén ronde draaien en dan stoppen.
        def stop_na_ronde():
            app.stop_event.set()
            app.wake_event.set()
        __import__("threading").Timer(0.1, stop_na_ronde).start()
        app._loop()
    finally:
        status_app.check_site = origineel

    eerste = app.results.get_nowait()
    assert eerste["status"] == "error"
    assert "RuntimeError" in eerste["detail"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    mislukt = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            mislukt += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - mislukt}/{len(tests)} tests geslaagd")
    raise SystemExit(1 if mislukt else 0)
