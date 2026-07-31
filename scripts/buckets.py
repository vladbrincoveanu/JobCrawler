"""CV bucket matching: which of the four CV variants should be sent for a job.

The keyword sets are NOT defined here. They live in
`career/Resume/JOB-SEARCH/keywords/*.txt`, the same files `kwcount.py` audits the
CV against, in the format documented there:

    keyword|synonym|synonym     # one entry per line, '#' starts a comment
                                # the FIRST FIVE entries are the "top 5"

Keeping one source of truth means a CV keyword change and a job-search keyword
change are the same edit. This module only decides how those keywords score a
job posting.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# A top-5 keyword is what the CV is actually built around, so it outweighs a
# 6-10 keyword; a hit in the title outweighs one buried in the description.
TOP_TITLE, TOP_DESC = 6.0, 2.0
NEXT_TITLE, NEXT_DESC = 3.0, 1.0
TOP_N = 5  # first five entries are the top five, per the keyword-file format

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "data" / "buckets.json"


def log(msg: str) -> None:
    print(f"[buckets] {msg}", file=sys.stderr)


@dataclass
class Bucket:
    id: str
    label: str
    cv: str
    search_terms: list[str]
    top: list[list[str]] = field(default_factory=list)     # [[kw, syn, ...], ...]
    rest: list[list[str]] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)

    @property
    def max_score(self) -> float:
        """Normalizer: every keyword present in the ad's body.

        Deliberately NOT "every keyword in the title" -- no real ad puts ten
        keywords in its title, so that denominator would squash every genuine
        match into the 20-30% band and make the number useless to read. Against
        this baseline the score means "how much of this CV's vocabulary the ad
        actually asks for", and title hits can push a job past 100 (clamped),
        which is the intended signal: the ad is named after the CV.
        """
        return len(self.top) * TOP_DESC + len(self.rest) * NEXT_DESC


def parse_keyword_file(path: Path) -> tuple[list[list[str]], list[list[str]]]:
    """Parse `keyword|synonym` lines into (top-5, rest). Comments and blank
    lines are ignored -- note that the '# 6-10:' header inside these files is a
    comment, so the top-5 split is positional, exactly as kwcount.py does it."""
    entries: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        synonyms = [s.strip().lower() for s in line.split("|") if s.strip()]
        if synonyms:
            entries.append(synonyms)
    return entries[:TOP_N], entries[TOP_N:]


def load_buckets(config_path: Path | None = None,
                 only: list[str] | None = None) -> list[Bucket]:
    """Load bucket definitions and attach their keyword sets.

    Fails loud: a bucket whose keyword file is missing raises rather than
    scoring 0 forever and silently never being recommended.
    """
    config_path = config_path or DEFAULT_CONFIG
    config = json.loads(config_path.read_text(encoding="utf-8"))
    keywords_dir = Path(config["keywords_dir"]).expanduser()

    buckets = []
    for entry in config["buckets"]:
        if only and entry["id"] not in only:
            continue
        kw_path = keywords_dir / entry["keyword_file"]
        if not kw_path.exists():
            raise FileNotFoundError(
                f"bucket {entry['id']} ({entry['label']}) references a missing "
                f"keyword file: {kw_path}. Buckets are scored from these files; "
                f"a missing one would silently zero the bucket.")
        top, rest = parse_keyword_file(kw_path)
        if len(top) < TOP_N:
            raise ValueError(
                f"{kw_path} has only {len(top)} keyword entries; the format "
                f"requires at least {TOP_N} (the first five are the top five).")
        buckets.append(Bucket(
            id=entry["id"], label=entry["label"], cv=entry["cv"],
            search_terms=entry.get("search_terms", []),
            top=top, rest=rest,
            exclude_terms=[t.lower() for t in entry.get("exclude_terms", [])],
        ))
    if not buckets:
        raise ValueError(f"no buckets loaded from {config_path} (filter={only})")
    log(f"loaded {len(buckets)} buckets: {', '.join(b.id for b in buckets)}")
    return buckets


def _hits(synonyms: list[str], text: str) -> bool:
    """Whole-word-ish containment. Word boundaries matter for short tokens
    ('agent' must not match 'management'), but the keywords contain regex
    metacharacters ('.net', 'c#', 'ci/cd') so each is escaped first."""
    for syn in synonyms:
        pattern = re.escape(syn)
        # \b is useless next to a non-word char like '.' or '#', so only anchor
        # the side that actually starts/ends with a word character.
        left = r"\b" if syn[:1].isalnum() else ""
        right = r"\b" if syn[-1:].isalnum() else ""
        if re.search(f"{left}{pattern}{right}", text):
            return True
    return False


def score_bucket(job: dict, bucket: Bucket) -> float:
    """0-100 fit of a job to one CV variant."""
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()[:6000]
    haystack = f"{title} {desc}"

    if bucket.exclude_terms and any(t in haystack for t in bucket.exclude_terms):
        return 0.0

    score = 0.0
    for synonyms in bucket.top:
        if _hits(synonyms, title):
            score += TOP_TITLE
        elif _hits(synonyms, desc):
            score += TOP_DESC
    for synonyms in bucket.rest:
        if _hits(synonyms, title):
            score += NEXT_TITLE
        elif _hits(synonyms, desc):
            score += NEXT_DESC
    if not bucket.max_score:
        return 0.0
    return round(min(100.0, 100.0 * score / bucket.max_score), 1)


def best_bucket(job: dict, buckets: list[Bucket]) -> tuple[Bucket | None, float]:
    """The CV variant to send for this job, and its 0-100 fit."""
    best, best_score = None, 0.0
    for bucket in buckets:
        score = score_bucket(job, bucket)
        if score > best_score:
            best, best_score = bucket, score
    return best, best_score


def annotate(jobs: list[dict], buckets: list[Bucket]) -> None:
    """Tag each job in place with the CV variant to send."""
    for job in jobs:
        bucket, score = best_bucket(job, buckets)
        job["bucket"] = bucket.id if bucket else None
        job["bucket_label"] = bucket.label if bucket else None
        job["bucket_cv"] = bucket.cv if bucket else None
        job["bucket_fit"] = score


def all_search_terms(buckets: list[Bucket]) -> list[str]:
    """Union of every bucket's search terms, order-preserved and deduped."""
    terms: list[str] = []
    for bucket in buckets:
        terms.extend(bucket.search_terms)
    return list(dict.fromkeys(terms))
