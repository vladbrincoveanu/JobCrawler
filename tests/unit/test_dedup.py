from crawler.storage.dedup import normalize, content_hash


def test_normalize_lowercase():
    assert normalize("HELLO World") == "hello world"


def test_normalize_collapses_whitespace():
    assert normalize("foo  bar\t\nbaz") == "foo bar baz"


def test_normalize_strips_punctuation():
    # Non-alnum runs become spaces, then collapsed
    assert normalize("ACME, Inc.!") == "acme inc"
    assert normalize("X & Y. OG") == "x y og"  # & and . become spaces, then collapsed


def test_normalize_strips_accents():
    # NFKD + combining strip → ASCII only for combining marks
    assert normalize("Wién") == "wien"
    assert normalize("café") == "cafe"
    # ß is NOT decomposed by NFKD (no combining-mark form) — becomes stripped
    assert normalize("Größere") == "gro ere"


def test_normalize_handles_empty_and_none():
    assert normalize("") == ""
    assert normalize(None) == ""


def test_normalize_pure_punctuation_collapses():
    assert normalize("!!!") == ""
    assert normalize(".,?") == ""


def test_content_hash_stable_across_case_and_punct():
    # Normalization (lowercase + strip punct) makes these collide
    h1 = content_hash("Software Engineer", "ACME, Inc.", "Wien")
    h2 = content_hash("software engineer", "acme inc", "wien")
    assert h1 == h2


def test_content_hash_handles_none_fields():
    # None values normalize to empty string
    h1 = content_hash("SWE", None, None)
    h2 = content_hash("SWE", "", "")
    assert h1 == h2


def test_content_hash_different_inputs():
    h1 = content_hash("Software Engineer", "ACME", "Wien")
    h2 = content_hash("Data Scientist", "ACME", "Wien")
    assert h1 != h2


def test_content_hash_is_hex_64():
    h = content_hash("X", "Y", "Z")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)