"""Tests for scripts/company_reviews.py — the employer pros/cons enrichment.

The risk this module carries is not "does it call an API". It is that a
language model asked about an obscure Austrian GmbH will happily invent a
plausible-sounding culture report, and that invention would be rendered next to
real job data as if it were sourced. So the tests that matter here are the ones
that pin the refusal paths: an unrecognised company must produce NO panel, a
hedged empty answer must produce no panel, and a failing model call must leave
the scan untouched rather than taking it down.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import company_reviews

MODEL = "test/model"


def reply(known=True, pros=("good pay",), cons=("long hours",), summary="ok"):
    return json.dumps(
        {"known": known, "pros": list(pros), "cons": list(cons), "summary": summary}
    )


def test_known_company_returns_pros_and_cons(tmp_path):
    record = company_reviews.fetch_review(
        "Contoso GmbH", lambda _p: reply(), MODEL, cache_dir=tmp_path, now=1000.0
    )
    assert record["pros"] == ["good pay"]
    assert record["cons"] == ["long hours"]
    # Provenance is not decoration: the UI keys its "model-generated, verify
    # this" caveat off it.
    assert record["source"] == f"llm:{MODEL}"


def test_unknown_company_yields_no_review(tmp_path):
    """`known: false` is the model's escape hatch; it must produce no panel."""
    record = company_reviews.fetch_review(
        "Nonexistent Kleinbetrieb e.U.",
        lambda _p: reply(known=False, pros=(), cons=(), summary=""),
        MODEL, cache_dir=tmp_path, now=1000.0,
    )
    assert record is None


def test_known_but_empty_answer_yields_no_review(tmp_path):
    """A model that claims knowledge but lists nothing is hedging, not
    reporting an unremarkable employer."""
    record = company_reviews.fetch_review(
        "Vague AG", lambda _p: reply(pros=(), cons=(), summary="fine"),
        MODEL, cache_dir=tmp_path, now=1000.0,
    )
    assert record is None


def test_non_json_reply_yields_no_review(tmp_path):
    record = company_reviews.fetch_review(
        "Chatty GmbH", lambda _p: "Sure! Here's what I know about them...",
        MODEL, cache_dir=tmp_path, now=1000.0,
    )
    assert record is None


def test_model_failure_does_not_propagate(tmp_path):
    """Enrichment is optional garnish; it must never fail the scan."""
    def boom(_prompt):
        raise RuntimeError("502 from provider")

    assert company_reviews.fetch_review(
        "Contoso GmbH", boom, MODEL, cache_dir=tmp_path, now=1000.0) is None


def test_second_lookup_is_served_from_cache(tmp_path):
    calls = []

    def chat(prompt):
        calls.append(prompt)
        return reply()

    company_reviews.fetch_review("Contoso GmbH", chat, MODEL,
                                 cache_dir=tmp_path, now=1000.0)
    company_reviews.fetch_review("contoso  gmbh", chat, MODEL,
                                 cache_dir=tmp_path, now=1000.0)
    # Same employer, different capitalisation/spacing -- one call, not two.
    assert len(calls) == 1


def test_unknown_company_is_not_re_asked(tmp_path):
    """The negative result is cached too, or every scan re-asks forever."""
    calls = []

    def chat(prompt):
        calls.append(prompt)
        return reply(known=False, pros=(), cons=(), summary="")

    for _ in range(3):
        company_reviews.fetch_review("Obscure e.U.", chat, MODEL,
                                     cache_dir=tmp_path, now=1000.0)
    assert len(calls) == 1


def test_cache_expires_after_ttl(tmp_path):
    calls = []

    def chat(prompt):
        calls.append(prompt)
        return reply()

    company_reviews.fetch_review("Contoso GmbH", chat, MODEL,
                                 cache_dir=tmp_path, now=1000.0)
    later = 1000.0 + company_reviews.CACHE_TTL_SECONDS + 1
    company_reviews.fetch_review("Contoso GmbH", chat, MODEL,
                                 cache_dir=tmp_path, now=later)
    assert len(calls) == 2


def test_pros_and_cons_are_capped(tmp_path):
    record = company_reviews.fetch_review(
        "Verbose AG",
        lambda _p: reply(pros=[f"pro {i}" for i in range(20)],
                         cons=[f"con {i}" for i in range(20)]),
        MODEL, cache_dir=tmp_path, now=1000.0,
    )
    assert len(record["pros"]) == company_reviews.MAX_ITEMS
    assert len(record["cons"]) == company_reviews.MAX_ITEMS


class TestAnnotate:
    def test_attaches_review_to_matching_jobs(self, tmp_path):
        jobs = [
            {"title": "A", "company": "Contoso GmbH"},
            {"title": "B", "company": "Contoso GmbH"},
        ]
        n = company_reviews.annotate(jobs, lambda _p: reply(), MODEL,
                                     cache_dir=tmp_path)
        assert n == 2
        assert jobs[0]["company_review"]["pros"] == ["good pay"]

    def test_limit_caps_distinct_companies_not_jobs(self, tmp_path):
        """A run with a hard limit of 1 still annotates every ad at the one
        company it looked up -- the limit exists to bound LLM calls."""
        calls = []

        def chat(prompt):
            calls.append(prompt)
            return reply()

        jobs = [
            {"company": "Alpha GmbH"},
            {"company": "Alpha GmbH"},
            {"company": "Beta GmbH"},
        ]
        n = company_reviews.annotate(jobs, chat, MODEL, limit=1, cache_dir=tmp_path)
        assert len(calls) == 1
        assert n == 2
        assert "company_review" not in jobs[2]

    def test_jobs_without_a_company_are_skipped(self, tmp_path):
        jobs = [{"company": None}, {"company": "   "}, {}]
        assert company_reviews.annotate(jobs, lambda _p: reply(), MODEL,
                                        cache_dir=tmp_path) == 0

    def test_unknown_company_leaves_job_unannotated(self, tmp_path):
        jobs = [{"company": "Obscure e.U."}]
        company_reviews.annotate(
            jobs, lambda _p: reply(known=False, pros=(), cons=(), summary=""),
            MODEL, cache_dir=tmp_path)
        assert "company_review" not in jobs[0]


def test_corrupt_cache_file_is_ignored(tmp_path):
    """A half-written cache file must trigger a re-ask, not a crash."""
    path = company_reviews.cache_path("Contoso GmbH", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    record = company_reviews.fetch_review("Contoso GmbH", lambda _p: reply(),
                                          MODEL, cache_dir=tmp_path, now=1000.0)
    assert record["pros"] == ["good pay"]


@pytest.mark.parametrize("name,expected", [
    ("Contoso GmbH", "contoso-gmbh"),
    ("  A&B  Systems, Ltd. ", "a-b-systems-ltd"),
    ("Ärzte IT", "rzte-it"),
])
def test_slug_normalises_company_names(name, expected):
    assert company_reviews._slug(name) == expected


def test_module_cache_dir_is_read_at_call_time(tmp_path, monkeypatch):
    """Regression: cache_dir used to be a default argument bound to CACHE_DIR at
    import time, so patching the module attribute did nothing and a test run
    wrote real files into the repo's data/company_reviews/."""
    monkeypatch.setattr(company_reviews, "CACHE_DIR", tmp_path / "patched")
    company_reviews.fetch_review("Contoso GmbH", lambda _p: reply(), MODEL, now=1000.0)
    assert (tmp_path / "patched" / "contoso-gmbh.json").exists()
