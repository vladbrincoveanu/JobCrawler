from datetime import datetime, timezone
from bs4 import BeautifulSoup
import pytest
from crawler.parser import select_text, select_attr, extract_jsonld, parse_iso_date
from crawler.exceptions import SchemaChanged, MissingField


def test_select_text_finds_element():
    soup = BeautifulSoup('<div><span class="x">hello</span></div>', "html.parser")
    assert select_text(soup, "span.x") == "hello"


def test_select_text_returns_none_when_missing():
    soup = BeautifulSoup("<div></div>", "html.parser")
    assert select_text(soup, "span.x") is None


def test_select_text_required_raises_missing_field():
    soup = BeautifulSoup("<div></div>", "html.parser")
    with pytest.raises(MissingField):
        select_text(soup, "span.x", required=True)


def test_select_attr():
    soup = BeautifulSoup('<a href="/x">link</a>', "html.parser")
    assert select_attr(soup, "a", "href") == "/x"


def test_extract_jsonld_job_posting():
    html = '''
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","title":"SWE","description":"d"}
    </script>
    </head></html>
    '''
    data = extract_jsonld(html)
    assert data["@type"] == "JobPosting"
    assert data["title"] == "SWE"


def test_extract_jsonld_missing_raises_schema_changed():
    with pytest.raises(SchemaChanged):
        extract_jsonld("<html><head></head></html>")


def test_parse_iso_date_with_z():
    dt = parse_iso_date("2026-06-22T10:00:00Z")
    assert dt == datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_date_with_offset():
    dt = parse_iso_date("2026-06-22T10:00:00+02:00")
    assert dt.year == 2026 and dt.month == 6 and dt.day == 22


def test_parse_iso_date_invalid_raises_schema_changed():
    with pytest.raises(SchemaChanged):
        parse_iso_date("not a date")