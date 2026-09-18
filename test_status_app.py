#!/usr/bin/env python3
"""Tests voor de desktop-app. Draai met: python3 test_status_app.py

Het venster zelf kan hier niet geopend worden, dus tkinter wordt nagebootst.
Wat wel getest wordt: de kleurrangorde van de ring, de wiskunde achter het
voortgangslijntje, de lettertypekeuze, en dat elke status een kleur en label heeft.
"""

import math
import sys
import types
from unittest.mock import MagicMock

# tkinter nabootsen, zodat status_app importeerbaar is zonder beeldscherm.
for naam in ("tkinter", "tkinter.font"):
    module = types.ModuleType(naam)
    module.__getattr__ = lambda _n: MagicMock()  # type: ignore[attr-defined]
    sys.modules.setdefault(naam, module)
sys.modules["tkinter"].font = sys.modules["tkinter.font"]
sys.modules["tkinter"].Canvas = object  # RefreshKnop erft hiervan

import check_status
import status_app as app


# --- De ring krijgt de kleur van de zwaarste status --------------------------
def test_ring_is_accent_when_nothing_is_wrong():
    assert app.ring_kleur(["ok", "ok", "ok"]) == app.ACCENT


def test_ring_is_accent_for_maintenance_and_unknown():
    # Zoals afgesproken: alles behalve storing en onbereikbaar valt terug
    # op de accentkleur.
    assert app.ring_kleur(["ok", "maintenance", "unknown"]) == app.ACCENT


def test_incident_outranks_everything():
    assert app.ring_kleur(["ok", "maintenance", "incident"]) == app.WINE
    assert app.ring_kleur(["error", "incident"]) == app.WINE


def test_error_outranks_the_quiet_states():
    assert app.ring_kleur(["ok", "unknown", "error"]) == app.AMBER


# --- Het voortgangslijntje ---------------------------------------------------
def test_path_is_closed():
    pad = app.afgeronde_rechthoek(1, 1, 111, 35, 5)
    assert math.dist(pad[0], pad[-1]) < 0.001, "het pad hoort rond te lopen"


def test_progress_grows_with_the_fraction():
    pad = app.afgeronde_rechthoek(1, 1, 111, 35, 5)

    def lengte(punten):
        return sum(math.dist(punten[i], punten[i + 1]) for i in range(len(punten) - 1))

    vol = lengte(pad)
    assert app.deel_van_pad(pad, 0.0) == []
    for f in (0.25, 0.5, 0.75):
        deel = lengte(app.deel_van_pad(pad, f))
        assert abs(deel - vol * f) < 1.0, f"bij {f} is de lijn {deel:.1f} ipv {vol * f:.1f}"
    assert abs(lengte(app.deel_van_pad(pad, 1.0)) - vol) < 1.0


def test_progress_is_clamped():
    # Waarden buiten 0..1 mogen niet tot een rare lijn leiden. Let op: het pad
    # loopt rond, dus het laatste punt valt samen met het eerste en wordt bij
    # een volle ring niet nog eens meegetekend.
    pad = app.afgeronde_rechthoek(1, 1, 111, 35, 5)
    assert app.deel_van_pad(pad, -5) == []
    assert app.deel_van_pad(pad, 99) == app.deel_van_pad(pad, 1.0)
    assert len(app.deel_van_pad(pad, 1.0)) >= len(pad) - 1


# --- Lettertypes -------------------------------------------------------------
def test_font_picks_the_first_available():
    assert app.kies_lettertype(["Georgia", "Times New Roman"], "val",
                               beschikbaar={"Times New Roman"}) == "Times New Roman"
    assert app.kies_lettertype(["Georgia"], "val", beschikbaar={"Georgia"}) == "Georgia"


def test_font_falls_back_when_nothing_matches():
    assert app.kies_lettertype(["Bestaat Niet"], "val", beschikbaar=set()) == "val"


# --- Volledigheid ------------------------------------------------------------
def test_every_status_has_a_dot_colour_and_label():
    statussen = {check_status.OK, check_status.INCIDENT, check_status.MAINTENANCE,
                 check_status.UNKNOWN, check_status.ERROR, "checking"}
    for status in statussen:
        assert status in app.STIP, f"geen stipkleur voor {status}"
        assert status in app.LABELKLEUR, f"geen labelkleur voor {status}"
        assert status in app.LABEL, f"geen label voor {status}"


def test_only_problem_states_are_tinted():
    assert set(app.TINT) == {"incident", "maintenance", "error"}


def test_ok_label_is_readable():
    # De accentkleur is te donker voor kleine tekst, daarom staat het label
    # in botwit en draagt alleen het stipje de kleur.
    assert app.LABELKLEUR["ok"] == app.BONE
    assert app.STIP["ok"] == app.ACCENT


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
