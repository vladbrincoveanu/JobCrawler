from crawler.storage.dedup import normalize, content_hash


def test_normalize_lowercase():
    assert normalize("HELLO World") == "hello world"


def test_normalize_collapses_whitespace():
    assert normalize("foo  bar\t\nbaz") == "foo bar baz"


def test_normalize_strips_punctuation():
    assert normalize("ACME, Inc.!") == "acme inc"


def test_normalize_strips_legal_suffixes():
    assert normalize("ACME GmbH") == "acme"
    assert normalize("Foo AG") == "foo"
    assert normalize("Bar eG OG KG mbH") == "bar"
    assert normalize("X & Y. OG") == "x y"  # also strips & and .


def test_normalize_vienna_districts():
    assert normalize("1. Bezirk") == "wien 1"
    assert normalize("I. Bezirk, Wien") == "wien 1"
    assert normalize("erster Bezirk") == "wien 1"
    assert normalize("Wien") == "wien"


def test_content_hash_stable():
    h1 = content_hash("Software Engineer", "ACME GmbH", "Wien")
    h2 = content_hash("software engineer", "acme", "wien")
    assert h1 == h2  # normalization makes them equal


def test_content_hash_different_inputs():
    h1 = content_hash("Software Engineer", "ACME", "Wien")
    h2 = content_hash("Data Scientist", "ACME", "Wien")
    assert h1 != h2


def test_content_hash_is_hex_64():
    h = content_hash("X", "Y", "Z")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)