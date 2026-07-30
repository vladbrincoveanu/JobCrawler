"""Parser tests for the StepStone.at source.

These run against a committed HTML fixture rather than the live site, so a
StepStone redesign surfaces as a specific, readable failure here instead of the
source silently returning zero jobs in production.

The fixture holds the first 10 of the 25 cards on a real result page, with SVG
paths and the emotion CSS blocks dropped and the teaser text truncated (see
tests/fixtures/.fixture-license). One CSS block is kept on purpose: it contains
a `[data-at="job-item"]` selector that a naive card splitter would count as an
eleventh card.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sources import stepstone_at as s  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "stepstone_search_devops_wien.html"
# The fixture was captured on this date; relative ages ("vor 2 Tagen") only
# resolve to the expected absolute dates when anchored to it.
CAPTURED = date(2026, 7, 30)


@pytest.fixture(scope="module")
def cards():
    return s.parse_cards(FIXTURE.read_text(encoding="utf-8"), CAPTURED)


def test_fixture_is_not_empty():
    assert FIXTURE.stat().st_size > 50_000, "fixture looks truncated"


def test_parses_every_card(cards):
    # The guard that matters: a redesign makes the parser return 0 cards from a
    # perfectly valid page, which would otherwise look like "no new jobs".
    assert len(cards) == 10


def test_css_selector_is_not_mistaken_for_a_card(cards):
    # The page emits `[data-at="job-item"]{border-radius:4px}` in a style block.
    # Splitting on that attribute instead of the <article> id yields 11 cards,
    # the last of which is markup garbage.
    html = FIXTURE.read_text(encoding="utf-8")
    assert html.count('data-at="job-item"') == len(cards) + 1, "fixture lost its decoy"
    assert all(c["title"] and c["company"] for c in cards)


def test_no_card_is_partially_parsed(cards):
    for card in cards:
        assert card["title"], f"missing title: {card}"
        assert card["company"], f"missing company: {card}"
        assert card["url"].startswith("https://www.stepstone.at/stellenangebote--"), card["url"]
        assert card["location"], f"missing location: {card}"
        assert card["posted"], f"missing posted date: {card}"


def test_fields_carry_no_leaked_markup(cards):
    # Regression: the field extractor cut at the next data-at marker, which left
    # the following element's unclosed opening tag glued onto every value
    # ("Wien <span class=\"res-r5cg0x\" data-genesis-element=\"BASE\"").
    for card in cards:
        for key in ("title", "company", "location", "home_office", "snippet"):
            value = card[key]
            assert "<" not in value and 'class="' not in value, f"{key} leaked markup: {value!r}"
            assert not value.startswith(">"), f"{key} leaked a tag close: {value!r}"


def test_known_card_parsed_exactly(cards):
    card = next(c for c in cards if "--986112-inline.html" in c["url"])
    assert card["title"] == "Linux DevOps Engineer (w/m/d)"
    assert card["company"] == ("AGES - Österreichische Agentur für Gesundheit und "
                              "Ernährungssicherheit GmbH")
    assert card["location"] == "Wien"
    assert card["home_office"] == "Teilweise Home-Office"
    assert card["posted"] == "2026-07-23"  # rendered as "vor 1 Woche"


def test_multi_location_and_postal_code_locations_survive(cards):
    locations = {c["location"] for c in cards}
    assert "Graz, Wien" in locations   # multi-location ad, comma-joined
    assert "1090 Wien" in locations    # postal code prefix kept verbatim


def test_home_office_flag_is_read_not_assumed(cards):
    flagged = [c for c in cards if c["home_office"]]
    # Some ads carry the marker, most don't. Both extremes mean a broken parser.
    assert 0 < len(flagged) < len(cards)


@pytest.mark.parametrize("text,expected", [
    ("vor 22 Stunden", "2026-07-30"),   # hours old -> today
    ("vor 1 Tag", "2026-07-29"),
    ("vor 3 Tagen", "2026-07-27"),
    ("vor 1 Woche", "2026-07-23"),
    ("vor 2 Wochen", "2026-07-16"),
    ("vor 1 Monat", "2026-06-30"),
    ("Heute", "2026-07-30"),
    ("Gestern", "2026-07-29"),
    ("", None),
    ("irgendwann", None),
])
def test_relative_ages_resolve(text, expected):
    assert s.parse_posted(text, CAPTURED) == expected


def test_search_url_forms():
    assert s.search_url("devops engineer", "wien") == \
        "https://www.stepstone.at/jobs/devops-engineer/in-wien"
    # Empty location = Austria-wide, the arm that reaches remote ads.
    assert s.search_url("devops engineer", "") == \
        "https://www.stepstone.at/jobs/devops-engineer"
    # Page 1 is the bare URL; StepStone only needs ?page= from 2 on.
    assert s.search_url("devops", "wien", 1) == "https://www.stepstone.at/jobs/devops/in-wien"
    assert s.search_url("devops", "wien", 3) == \
        "https://www.stepstone.at/jobs/devops/in-wien?page=3"


def test_slugify_drops_dots_unlike_karriere():
    # /jobs/.net 404s on StepStone; /jobs/net is the working form.
    assert s.slugify(".NET Entwickler") == "net-entwickler"
    # '#' percent-encoded: raw, requests would read it as a fragment start and
    # fetch /jobs/c instead of the C# search.
    assert s.slugify("C# developer") == "c%23-developer"
    assert s.slugify("  Site  Reliability Engineer ") == "site-reliability-engineer"
    assert s.slugify("!!!") == ""


@pytest.mark.parametrize("location,remote,expected", [
    ("Wien", "false", True),
    ("1090 Wien", "false", True),
    ("Graz, Wien", "false", True),      # Wien among several
    ("Graz", "true", True),             # Austria-wide REMOTE
    ("Graz", "false", False),           # onsite elsewhere
])
def test_scope_filter_keeps_wien_and_remote_only(location, remote, expected):
    assert s.in_scope({"location": location, "is_remote": remote}, ["wien", ""]) is expected


def test_inline_style_block_is_not_read_as_text():
    """Regression from a live run: StepStone inlines an emotion <style> block
    inside some title anchors. Stripping tags alone leaves the CSS behind, and a
    job landed on the dashboard titled ".res-xrpel9{box-sizing:border-box…}"."""
    chunk = ('<article id="job-item-1"><a href="/stellenangebote--x--1-inline.html" '
             'data-at="job-item-title"><style data-emotion="res x">'
             '.res-xrpel9{box-sizing:border-box;margin:0}</style>'
             '<div>Cloud Engineer (m/w/d)</div></a>'
             '<span data-at="job-item-company-name">ACME GmbH</span></article>')
    card = s.parse_cards(chunk, CAPTURED)[0]
    assert card["title"] == "Cloud Engineer (m/w/d)"
    assert "box-sizing" not in card["title"]
