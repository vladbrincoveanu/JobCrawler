"""Canonical normalization + content hash for cross-source dedup.

Spec § Dedup. Excludes salary/description/employment_type (too noisy).
"""
import hashlib
import re

LEGAL_SUFFIXES = (
    " mbh", " ag", " eg", " og", " kg",
    " gmbh",  # lowercase variant covered by re.IGNORECASE
)

# Vienna district normalization: "1. Bezirk" / "I. Bezirk" / "erster Bezirk" → "wien 1"
_DISTRICT_ROMAN = {
    "erster": 1, "i": 1, "1": 1, "1.": 1,
    "zweiter": 2, "ii": 2, "2": 2, "2.": 2,
    "dritter": 3, "iii": 3, "3": 3, "3.": 3,
    "vierter": 4, "iv": 4, "4": 4, "4.": 4,
    "fuenfter": 5, "fünfter": 5, "v": 5, "5": 5, "5.": 5,
    "sechster": 6, "vi": 6, "6": 6, "6.": 6,
    "siebenter": 7, "vii": 7, "7": 7, "7.": 7,
    "achter": 8, "viii": 8, "8": 8, "8.": 8,
    "neunter": 9, "ix": 9, "9": 9, "9.": 9,
    "zehnter": 10, "x": 10, "10": 10, "10.": 10,
    "elfter": 11, "xi": 11, "11": 11, "11.": 11,
    "zwoelfter": 12, "zwölfter": 12, "xii": 12, "12": 12, "12.": 12,
}


def normalize(s: str | None) -> str:
    """Aggressive normalize: lowercase, collapse ws, strip punct, strip suffixes."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    # Strip punctuation except alphanumerics + spaces
    s = re.sub(r"[^\w\s]", "", s)  # strip everything but alphanumerics + whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Vienna district: "1. bezirk" / "erster bezirk" / "wien 1" → "wien 1"
    s = _normalize_vienna(s)
    # Strip legal suffixes (loop: "Bar eG OG KG mbH" → strip " mbh" → "bar eg og kg" → strip " kg" → ...)
    while True:
        stripped = False
        for suffix in LEGAL_SUFFIXES:
            if s.endswith(suffix):
                s = s[: -len(suffix)].strip()
                stripped = True
                break
        if not stripped:
            break
    return s


def _normalize_vienna(s: str) -> str:
    """Convert '1. bezirk' / 'erster bezirk' / 'i. bezirk, wien' / 'wien' → 'wien 1' / 'wien'."""
    # Pattern: "<district> bezirk" optionally followed by ", wien" (e.g. "I. Bezirk, Wien")
    m = re.match(
        r"^(erster|zweiter|dritter|vierter|fuenfter|fünfter|sechster|siebenter|achter|neunter|zehnter|elfter|zwoelfter|zwölfter|[ivxIVX]+|\d{1,2})\.?\s*bezirk(?:\s*,?\s*wien)?$",
        s,
    )
    if m:
        district_raw = m.group(1).lower()
        district = _DISTRICT_ROMAN.get(district_raw)
        if district is not None:
            return f"wien {district}"
    return s


def content_hash(title: str, company: str, location: str) -> str:
    """SHA256 hex of canonical(title | company | location)."""
    canonical = f"{normalize(title)}|{normalize(company)}|{normalize(location)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()