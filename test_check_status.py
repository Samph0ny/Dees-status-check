#!/usr/bin/env python3
"""Tests voor de herkenningslogica. Draai met: python3 test_check_status.py

Deze tests gebruiken nagebootste pagina's, dus ze werken zonder internet.
"""

from check_status import (
    page_text, best_text, classify_text, context_around, parse_json_payload,
)

# Nabootsing van een echt probleem: het menu van ZorgDomein bevat het item
# "Actuele storingen", terwijl de pagina zelf meldt dat er niets aan de hand is.
# Zonder filtering werd dat menu-item als storing gelezen.
NAV_NOISE_PAGE = """<html><body>
<nav><ul><li>Home</li><li>Voor wie</li><li>Actuele storingen</li></ul></nav>
<header><a href="/actuele-storingen/">Actuele storingen</a></header>
<main><h1>Storingen &amp; Onderhoud</h1>
<p>Er zijn op dit moment geen meldingen.</p></main>
<footer>Actuele storingen | Contact</footer>
</body></html>"""

TEXT_CASES = [
    ("geen storingen (NL)",
     "<p>Actuele storingen</p><p>Er zijn op dit moment geen storingen bekend.</p>", "ok"),
    ("actieve storing (NL)",
     "<p>Actuele storing: Verwijzen is tijdelijk niet beschikbaar.</p>", "incident"),
    ("all systems operational (EN)",
     "<p>All systems operational</p><script>var x='outage';</script>", "ok"),
    ("gepland onderhoud (NL)",
     "<p>Gepland onderhoud op zaterdag 21:00.</p>", "maintenance"),
    ("niets herkenbaars",
     "<p>Welkom op onze website.</p>", "unknown"),
    ("major outage (EN)",
     "<p>We are investigating a major outage.</p>", "incident"),
]


def test_text_classification():
    for label, body, expected in TEXT_CASES:
        got, _ = classify_text(page_text(f"<html><body>{body}</body></html>"))
        assert got == expected, f"{label}: verwacht {expected}, kreeg {got}"


def test_script_tags_are_ignored():
    # Woorden in <script> mogen de status niet beinvloeden.
    text = page_text("<html><body><p>All systems operational</p>"
                     "<script>alert('major outage')</script></body></html>")
    assert "major outage" not in text.lower()


def test_menu_items_are_not_read_as_incident():
    # Via best_text, want dat is het pad dat in productie gebruikt wordt.
    text, _, _ = best_text(NAV_NOISE_PAGE)
    assert classify_text(text)[0] == "ok", "menu-item wordt nog als storing gelezen"
    assert "Voor wie" not in page_text(NAV_NOISE_PAGE, "strict")


def test_real_incident_in_content_is_still_found():
    page = NAV_NOISE_PAGE.replace(
        "Er zijn op dit moment geen meldingen.",
        "Actuele storing: Verwijzen is niet beschikbaar.")
    status, phrase = classify_text(page_text(page))
    assert status == "incident"
    assert "Verwijzen" in context_around(page_text(page), phrase)


def test_instatus_json():
    clear = parse_json_payload("instatus", {
        "page": {"name": "LanTel"}, "activeIncidents": [], "activeMaintenances": []})
    assert clear["status"] == "ok"

    broken = parse_json_payload("instatus", {
        "page": {}, "activeIncidents": [{"name": "Storing e-mail"}],
        "activeMaintenances": []})
    assert broken["status"] == "incident"
    assert broken["open_incidents"] == ["Storing e-mail"]

    planned = parse_json_payload("instatus", {
        "page": {}, "activeIncidents": [],
        "activeMaintenances": [{"name": "Nachtelijk onderhoud"}]})
    assert planned["status"] == "maintenance"


def test_aurora_wording_is_recognised():
    # Letterlijk de bewoording die Aurora Innovation gebruikt.
    page = ("<html><body><main><h1>Service Status</h1>"
            "<p>Current service information</p>"
            "<p>Press the \u201c+\u201d to expand and view the ongoing disturbances.</p>"
            "<p>No current disturbances</p></main></body></html>")
    text, _, _ = best_text(page)
    assert classify_text(text)[0] == "ok"


def test_falls_back_when_strict_filter_removes_everything():
    # Een pagina waarvan de inhoud in een element met een menu-achtige class zit.
    # Het strenge niveau gooit alles weg; het vangnet hoort de tekst terug te halen.
    page = ("<html><body><div class=\"sidebar-content\">"
            "<p>Er zijn op dit moment geen storingen bekend bij onze dienstverlening. "
            "Mocht u toch iets ondervinden, neem dan gerust contact met ons op via de "
            "gebruikelijke kanalen. Wij houden deze pagina actueel.</p>"
            "</div></body></html>")
    strict = page_text(page, "strict")
    text, level, lengths = best_text(page)
    assert len(strict) < 200, "voorwaarde van de test klopt niet meer"
    assert level != "strict", "het vangnet is niet aangesproken"
    assert classify_text(text)[0] == "ok"
    assert lengths["raw"] > lengths["strict"]


def test_text_lengths_reveal_javascript_only_pages():
    # Een pagina zonder inhoud in de HTML: alle niveaus leveren vrijwel niets op.
    page = "<html><head><title>Status</title></head><body><div id=\"app\"></div></body></html>"
    _, _, lengths = best_text(page)
    assert max(lengths.values()) < 200


def test_statuspage_json():
    payload = {
        "status": {"indicator": "minor", "description": "Partially Degraded Service"},
        "components": [
            {"name": "API", "status": "operational"},
            {"name": "Portaal", "status": "degraded_performance"},
            {"name": "Groep", "status": "operational", "group": True},
        ],
        "incidents": [{"name": "Vertraging bij inloggen"}],
    }
    res = parse_json_payload("statuspage", payload)
    assert res["status"] == "incident"
    assert len(res["components"]) == 2, "componentgroepen horen overgeslagen te worden"
    assert res["open_incidents"] == ["Vertraging bij inloggen"]


def test_statuspage_json_all_clear():
    payload = {"status": {"indicator": "none", "description": "All Systems Operational"},
               "components": [], "incidents": []}
    assert parse_json_payload("statuspage", payload)["status"] == "ok"


def test_unknown_payload_is_rejected():
    assert parse_json_payload("statuspage", {"hello": "world"}) is None
    assert parse_json_payload("statuspage", []) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests geslaagd")
    raise SystemExit(1 if failed else 0)
