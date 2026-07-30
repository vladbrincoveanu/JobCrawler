"""Parser tests for the karriere.at source.

These run against a committed HTML fixture rather than the live site, so a
karriere.at redesign surfaces as a specific, readable failure here instead of
the source silently returning zero jobs in production.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sources import karriere_at as k  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "karriere_search_devops_wien.html"
# The fixture was captured on this date; relative dates ("vor 2 Tagen") only
# resolve to the expected absolute dates when anchored to it.
CAPTURED = date(2026, 7, 30)


@pytest.fixture(scope="module")
def cards():
    return k.parse_cards(FIXTURE.read_text(encoding="utf-8"), CAPTURED)


def test_fixture_is_not_empty():
    assert FIXTURE.stat().st_size > 50_000, "fixture looks truncated"


def test_parses_every_card(cards):
    # This is the guard that matters: a redesign makes the parser return 0 cards
    # from a perfectly valid page, which would otherwise look like "no new jobs".
    assert len(cards) == 15


def test_no_card_is_partially_parsed(cards):
    for card in cards:
        assert card["title"], f"missing title: {card}"
        assert card["company"], f"missing company: {card}"
        assert card["url"].startswith("https://www.karriere.at/jobs/"), card["url"]
        assert card["location"], f"missing location: {card}"


def test_known_card_parsed_exactly(cards):
    card = next(c for c in cards if c["url"].endswith("/10026945"))
    assert card["title"] == "DevOps Cloud Engineer*"
    assert card["company"] == "karriere.at"
    # Multi-location ad: both locations kept, comma-joined, in document order.
    assert card["location"] == "Wien 2. Bezirk (Leopoldstadt), Linz"
    assert card["posted"] == "2026-07-28"  # rendered as "vor 2 Tagen"


def test_locations_are_real_places_not_the_fallback(cards):
    # Regression: the location regex silently missed the data-location attribute
    # and every card fell back to "Österreich".
    fallbacks = [c for c in cards if c["location"] == "Österreich"]
    assert len(fallbacks) < len(cards) / 2


def test_relative_dates_resolve():
    assert k.parse_posted("heute veröffentlicht", CAPTURED) == "2026-07-30"
    assert k.parse_posted("gestern veröffentlicht", CAPTURED) == "2026-07-29"
    assert k.parse_posted("vor 5 Tagen veröffentlicht", CAPTURED) == "2026-07-25"
    assert k.parse_posted("12.07.2026", CAPTURED) == "2026-07-12"
    assert k.parse_posted("", CAPTURED) is None
    assert k.parse_posted("irgendwann", CAPTURED) is None
    assert k.parse_posted("31.02.2026", CAPTURED) is None  # invalid date, not a crash


@pytest.mark.parametrize("text,expected", [
    # Amount-before-currency is karriere.at's own format.
    ("ab 56.000 € jährlich", 56_000),
    ("ab 49.784,42 € jährlich", 49_784),          # German decimal comma
    ("ab 4.500 € monatlich", 4_500 * 14),         # AT: 14 salaries a year
    ("3.954 € – 5.000 € monatlich", 5_000 * 14),  # range -> top of range
    # Currency-before-amount shows up in free job text.
    ("mind. EUR 65.000 brutto/Jahr", 65_000),
    # No period stated: too small to be annual, so it must be monthly.
    ("4.200 €", 4_200 * 14),
    ("", None),
    ("Vollzeit", None),
    ("ab 500 € monatlich", None),                 # implausible; refuse to guess
])
def test_salary_parsing(text, expected):
    assert k.parse_salary(text)[0] == expected


def test_search_urls_cross_terms_and_locations():
    urls = k.search_urls(["devops engineer", ".net"], ["wien", ""])
    assert urls == [
        "https://www.karriere.at/jobs/devops-engineer/wien",
        "https://www.karriere.at/jobs/devops-engineer",
        "https://www.karriere.at/jobs/.net/wien",
        "https://www.karriere.at/jobs/.net",
    ]


def test_search_urls_deduplicate():
    assert len(k.search_urls(["kubernetes", "kubernetes"], ["wien"])) == 1


def test_slugify_keeps_dots_and_hyphenates_spaces():
    assert k.slugify("  .NET Entwickler ") == ".net-entwickler"
    assert k.slugify("C#") == "c#"


@pytest.mark.parametrize("location,remote,expected", [
    ("Wien", "false", True),
    ("Wien 2. Bezirk (Leopoldstadt), Linz", "false", True),   # Wien among several
    ("Vienna", "false", True),                                # English spelling
    ("Linz", "true", True),                                   # Austria-wide REMOTE
    ("Linz", "false", False),                                 # onsite elsewhere
    ("Graz, Salzburg", "false", False),
])
def test_scope_filter_keeps_wien_and_remote_only(location, remote, expected):
    """The Austria-wide search arm exists to reach remote ads. It must not
    smuggle in onsite jobs in other Austrian cities."""
    job = {"location": location, "is_remote": remote}
    assert k.in_scope(job, ["wien", ""]) is expected


def test_scope_filter_is_a_noop_without_named_locations():
    assert k.in_scope({"location": "Graz", "is_remote": "false"}, [""]) is True


def test_clean_decodes_german_entities():
    assert k.clean("<b>&Uuml;berblick</b>&nbsp;&amp; mehr") == "Überblick & mehr"
