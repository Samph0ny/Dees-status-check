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


def test_perimeter_matches_the_maths():
    """Vangt een pad dat een verkeerde kant op loopt.

    Een eerdere versie sprong na de rechteronderhoek naar het verkeerde punt,
    waardoor er een diagonaal door de knop liep. Het pad liep nog wel rond en
    groeide nog netjes, dus die tests merkten er niets van. De omtrek was
    echter tien pixels te lang, en dat is hier wel te zien.
    """
    x0, y0, x1, y1, r = 1, 1, 111, 35, 5
    pad = app.afgeronde_rechthoek(x0, y0, x1, y1, r)
    gemeten = sum(math.dist(pad[i], pad[i + 1]) for i in range(len(pad) - 1))
    exact = 2 * (x1 - x0 - 2 * r) + 2 * (y1 - y0 - 2 * r) + 2 * math.pi * r
    # De bogen bestaan uit rechte stukjes, dus iets korter dan de echte cirkel.
    assert abs(gemeten - exact) < 0.5, f"omtrek {gemeten:.2f} hoort {exact:.2f} te zijn"


def test_every_point_lies_on_the_outline():
    """Elk punt hoort op de rand te liggen, niet ergens binnenin."""
    x0, y0, x1, y1, r = 1, 1, 111, 35, 5
    middelpunten = [(x0 + r, y0 + r), (x1 - r, y0 + r),
                    (x0 + r, y1 - r), (x1 - r, y1 - r)]
    for x, y in app.afgeronde_rechthoek(x0, y0, x1, y1, r):
        assert x0 - 0.01 <= x <= x1 + 0.01 and y0 - 0.01 <= y <= y1 + 0.01, \
            f"punt ({x:.1f}, {y:.1f}) ligt buiten de knop"
        op_rechte = (abs(x - x0) < 0.01 or abs(x - x1) < 0.01
                     or abs(y - y0) < 0.01 or abs(y - y1) < 0.01)
        op_boog = any(abs(math.dist((x, y), m) - r) < 0.01 for m in middelpunten)
        assert op_rechte or op_boog, f"punt ({x:.1f}, {y:.1f}) ligt niet op de rand"


def test_no_segment_cuts_across_the_button():
    """Geen enkel segment mag langer zijn dan de langste rechte zijde."""
    x0, y0, x1, y1, r = 1, 1, 111, 35, 5
    pad = app.afgeronde_rechthoek(x0, y0, x1, y1, r)
    langste = max(math.dist(pad[i], pad[i + 1]) for i in range(len(pad) - 1))
    assert langste <= (x1 - x0 - 2 * r) + 0.01, f"segment van {langste:.1f} is een diagonaal"


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


# --- Knipperen van het taakbalkicoon -----------------------------------------
def test_no_flashing_when_everything_is_fine():
    vorige = {"a": "ok", "b": "ok"}
    nieuwe = {"a": "ok", "b": "ok"}
    assert not app.moet_knipperen(vorige, nieuwe)
    assert app.alles_in_orde(nieuwe.values())


def test_flashing_when_a_problem_appears():
    for probleem in ("incident", "error", "maintenance", "unknown"):
        vorige = {"a": "ok", "b": "ok"}
        nieuwe = {"a": "ok", "b": probleem}
        assert app.moet_knipperen(vorige, nieuwe), f"{probleem} hoort te knipperen"
        assert not app.alles_in_orde(nieuwe.values())


def test_no_repeat_flashing_for_a_known_problem():
    # Een storing die al bestond, hoort niet elke ronde opnieuw te knipperen.
    vorige = {"a": "ok", "b": "incident"}
    nieuwe = {"a": "ok", "b": "incident"}
    assert not app.moet_knipperen(vorige, nieuwe)


def test_flashing_when_a_problem_changes_kind():
    vorige = {"a": "maintenance"}
    nieuwe = {"a": "incident"}
    assert app.moet_knipperen(vorige, nieuwe)


def test_flashing_on_the_very_first_round():
    # Bij de eerste ronde is er nog geen vorige stand; een probleem moet dan
    # wel degelijk opvallen.
    assert app.moet_knipperen({}, {"a": "incident"})
    assert not app.moet_knipperen({}, {"a": "ok"})


def test_recovery_stops_the_flashing():
    vorige = {"a": "incident"}
    nieuwe = {"a": "ok"}
    assert not app.moet_knipperen(vorige, nieuwe)
    assert app.alles_in_orde(nieuwe.values())


def test_flashing_is_a_no_op_off_windows():
    # Buiten Windows mag de aanroep niets doen en zeker niet klappen.
    app_object = object.__new__(app.StatusApp)
    if sys.platform != "win32":
        app_object._knipper(True)   # mag geen fout geven
        app_object._knipper(False)


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


def test_ok_rows_show_a_fixed_sentence():
    # Bij "in orde" hoort in het venster geen scraper-uitleg te staan, maar
    # altijd dezelfde zin. De gevonden zinsnede blijft wel in status.json staan.
    assert app.TEKST_IN_ORDE == "Geen actuele storingen"
    assert "Gevonden op de pagina" not in app.TEKST_IN_ORDE


def test_icon_files_are_present():
    from pathlib import Path as _P
    hier = _P(app.__file__).parent
    for naam in ("icon.png", "icon.ico"):
        bestand = hier / naam
        assert bestand.exists(), f"{naam} ontbreekt"
        assert bestand.stat().st_size > 0, f"{naam} is leeg"


def test_resource_path_finds_bundled_files():
    # Zonder PyInstaller moet het bestand naast het script gevonden worden.
    assert app.bestandspad("icon.png").exists()


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
