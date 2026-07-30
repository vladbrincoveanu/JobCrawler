"""Tests for the per-CV dashboards.

The two orderings these enforce are deliberately different and easy to conflate:
the LIST is newest-posted-first, the SCORE is rank by match quality within the
CV bucket. A change that sorts the list by score would pass a naive "is it
sorted" test, so both are asserted explicitly.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout  # noqa: E402


def job(title, score, posted, **extra):
    base = {"title": title, "score": score, "posted": posted, "company": "ACME",
            "location": "Wien", "url": f"https://x/{title}", "apply_url": f"https://x/{title}",
            "ats_type": "stepstone_at", "is_remote": "false", "salary_min": None,
            "salary_max": None, "salary_currency": None, "salary_period": None}
    base.update(extra)
    return base


def test_list_is_newest_first_not_best_first():
    ranked = scout.rank_jobs([
        job("old-but-best", 90, "2026-07-01"),
        job("new-but-worst", 10, "2026-07-30"),
        job("middle", 50, "2026-07-15"),
    ])
    assert [j["title"] for j in ranked] == ["new-but-worst", "middle", "old-but-best"]


def test_score_is_rank_within_the_set_not_the_raw_score():
    ranked = scout.rank_jobs([
        job("best", 90, "2026-07-01"),
        job("worst", 10, "2026-07-30"),
        job("middle", 50, "2026-07-15"),
    ])
    by_title = {j["title"]: j for j in ranked}
    assert by_title["best"]["rank"] == 1
    assert by_title["middle"]["rank"] == 2
    assert by_title["worst"]["rank"] == 3
    # Top of the set is always 100 regardless of its raw score …
    assert by_title["best"]["rank_score"] == 100
    # … and the bottom is never 0: last of three still beats being unmatched.
    assert by_title["worst"]["rank_score"] > 0


def test_score_scale_is_comparable_across_differently_sized_buckets():
    small = scout.rank_jobs([job(f"s{i}", 100 - i, "2026-07-01") for i in range(3)])
    large = scout.rank_jobs([job(f"l{i}", 100 - i, "2026-07-01") for i in range(300)])
    assert small[0]["rank_score"] == large[0]["rank_score"] == 100


def test_jobs_without_a_posting_date_sort_last():
    ranked = scout.rank_jobs([
        job("undated", 99, None),
        job("dated", 1, "2026-07-01"),
    ])
    assert [j["title"] for j in ranked] == ["dated", "undated"]


def test_rank_jobs_handles_an_empty_set():
    assert scout.rank_jobs([]) == []


class FakeBucket:
    def __init__(self, id, label, cv):
        self.id, self.label, self.cv = id, label, cv


@pytest.fixture
def rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "dashboards")
    bucketed = [
        job("DevOps Engineer", 80, "2026-07-30", bucket="C"),
        job("Backend Engineer", 70, "2026-07-29", bucket="A"),
        job("Unbucketed Job", 99, "2026-07-30", bucket=None),
    ]
    args = type("Args", (), {"days": 14})()
    scout.generate_cv_dashboards(bucketed, [
        FakeBucket("A", "Backend / Distributed", "CV_Backend.pdf"),
        FakeBucket("C", "DevOps / SRE", "CV_DevOps.pdf"),
    ], args)
    return tmp_path / "dashboards"


def test_one_page_per_cv_plus_an_index(rendered):
    assert sorted(p.name for p in rendered.glob("*.html")) == \
        ["cv-A.html", "cv-C.html", "index.html"]


def test_each_cv_page_shows_only_its_own_jobs(rendered):
    page_c = (rendered / "cv-C.html").read_text(encoding="utf-8")
    assert "DevOps Engineer" in page_c
    assert "Backend Engineer" not in page_c
    assert "CV_DevOps.pdf" in page_c  # the page names the CV to actually send


def test_unbucketed_jobs_appear_on_no_page(rendered):
    # A job no CV matches is not "available" for any CV — silently filing it
    # under one would mean applying with the wrong CV.
    for page in rendered.glob("*.html"):
        assert "Unbucketed Job" not in page.read_text(encoding="utf-8")


def test_index_aggregates_every_bucketed_job(rendered):
    index = (rendered / "index.html").read_text(encoding="utf-8")
    assert "DevOps Engineer" in index and "Backend Engineer" in index


def test_titles_are_html_escaped(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "d")
    args = type("Args", (), {"days": 14})()
    scout.generate_cv_dashboards(
        [job("<script>alert(1)</script> Engineer", 10, "2026-07-30", bucket="A")],
        [FakeBucket("A", "Backend", "CV.pdf")], args)
    page = (tmp_path / "d" / "cv-A.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_empty_bucket_renders_a_page_saying_so(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "d")
    args = type("Args", (), {"days": 14})()
    scout.generate_cv_dashboards([], [FakeBucket("A", "Backend", "CV.pdf")], args)
    page = (tmp_path / "d" / "cv-A.html").read_text(encoding="utf-8")
    assert "no jobs matched" in page
