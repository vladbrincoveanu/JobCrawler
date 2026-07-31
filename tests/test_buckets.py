"""Tests for CV-bucket matching.

Intent under test: given a job ad, recommend the CV variant whose keyword set the
ad actually leans on -- and refuse to recommend a bucket whose known gaps the ad
leads with.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import buckets as b  # noqa: E402


@pytest.fixture(scope="module")
def all_buckets():
    return b.load_buckets()


def test_all_four_buckets_load(all_buckets):
    assert [x.id for x in all_buckets] == ["A", "B", "C", "D"]
    for bucket in all_buckets:
        assert len(bucket.top) == 5, f"{bucket.id} must have exactly 5 top keywords"
        assert bucket.rest, f"{bucket.id} has no 6-10 keywords"
        assert bucket.search_terms, f"{bucket.id} has no search terms"


def test_bucket_filter(all_buckets):
    only = b.load_buckets(only=["A", "C"])
    assert [x.id for x in only] == ["A", "C"]


def test_missing_bucket_filter_fails_loud():
    with pytest.raises(ValueError):
        b.load_buckets(only=["ZZZ"])


def test_keyword_file_parsing(tmp_path):
    path = tmp_path / "kw.txt"
    path.write_text(
        "# a comment\n"
        "Kubernetes|K8s\n"
        "CI/CD|continuous delivery\n"
        "\n"
        "Terraform\n"
        "distributed systems\n"
        "Linux|Docker  # trailing comment\n"
        "# 6-10: these are NOT top-5\n"
        "PostgreSQL|Postgres\n",
        encoding="utf-8")
    top, rest = b.parse_keyword_file(path)
    assert top == [["kubernetes", "k8s"], ["ci/cd", "continuous delivery"],
                   ["terraform"], ["distributed systems"], ["linux", "docker"]]
    assert rest == [["postgresql", "postgres"]]


def test_devops_ad_picks_bucket_c(all_buckets):
    job = {
        "title": "Site Reliability Engineer (m/w/d)",
        "description": ("You will run our Kubernetes platform, own Terraform "
                        "modules, extend CI/CD pipelines and improve "
                        "observability with Prometheus and Grafana on Linux."),
    }
    bucket, fit = b.best_bucket(job, all_buckets)
    assert bucket.id == "C"
    assert bucket.cv == "Vlad_Brincoveanu_CV_DevOps_SRE.pdf"
    assert fit > 60


def test_streaming_ad_picks_bucket_a(all_buckets):
    job = {
        "title": "Senior Backend Engineer - Distributed Systems",
        "description": ("Event-driven architecture on Apache Kafka, event "
                        "sourcing and CQRS, scalable REST APIs, PostgreSQL, "
                        "fault tolerance at high throughput."),
    }
    bucket, _ = b.best_bucket(job, all_buckets)
    assert bucket.id == "A"


def test_fullstack_ad_picks_bucket_b(all_buckets):
    job = {
        "title": "Senior Full-stack Engineer (.NET / Angular)",
        "description": ("TypeScript and Angular front end against an ASP.NET "
                        "Web API, PostgreSQL, Agile team, CI/CD to Azure."),
    }
    bucket, _ = b.best_bucket(job, all_buckets)
    assert bucket.id == "B"


def test_ai_ad_picks_bucket_d(all_buckets):
    job = {
        "title": "AI Engineer - Agentic Systems",
        "description": ("Build LLM agents with RAG over a vector database, "
                        "Model Context Protocol tool use, Python, shipped to "
                        "production on Kubernetes."),
    }
    bucket, _ = b.best_bucket(job, all_buckets)
    assert bucket.id == "D"


def test_bucket_c_excludes_known_gap_roles(all_buckets):
    """Per the Revolut post-mortem: DR/BCP and audit-readiness are real gaps,
    so bucket C must not be recommended for roles that lead on them."""
    job = {
        "title": "Site Reliability Engineer - Disaster Recovery",
        "description": ("Own disaster recovery and business continuity, "
                        "Kubernetes, Terraform, CI/CD, observability, Linux."),
    }
    only_c = b.load_buckets(only=["C"])
    assert b.score_bucket(job, only_c[0]) == 0.0


def test_title_hits_outrank_description_hits(all_buckets):
    only_c = b.load_buckets(only=["C"])[0]
    # Only the 6-10 keywords, so neither side is clamped at 100.
    words = " ".join(syn[0] for syn in only_c.rest)
    in_title = {"title": words, "description": ""}
    in_desc = {"title": "Engineer", "description": words}
    assert b.score_bucket(in_title, only_c) > b.score_bucket(in_desc, only_c)


def test_scores_are_clamped_to_100(all_buckets):
    only_c = b.load_buckets(only=["C"])[0]
    job = {"title": " ".join(syn[0] for syn in only_c.top + only_c.rest),
           "description": ""}
    assert b.score_bucket(job, only_c) == 100.0


def test_full_description_match_scores_100(all_buckets):
    only_c = b.load_buckets(only=["C"])[0]
    job = {"title": "Engineer",
           "description": " ".join(syn[0] for syn in only_c.top + only_c.rest)}
    assert b.score_bucket(job, only_c) == 100.0


def test_irrelevant_job_scores_zero_and_gets_no_bucket(all_buckets):
    job = {"title": "Pastry Chef", "description": "Croissants at dawn."}
    bucket, fit = b.best_bucket(job, all_buckets)
    assert bucket is None and fit == 0.0


def test_short_keywords_respect_word_boundaries(all_buckets):
    """'agent' must not fire on 'management' -- the classic substring false
    positive that would make bucket D match half the market."""
    only_d = b.load_buckets(only=["D"])[0]
    job = {"title": "Management Consultant", "description": "Stakeholder management."}
    assert b.score_bucket(job, only_d) == 0.0


def test_keywords_with_metacharacters_match(all_buckets):
    """'.net', 'c#' and 'ci/cd' contain regex metacharacters; they must be
    matched literally, not compiled as patterns."""
    only_b = b.load_buckets(only=["B"])[0]
    job = {"title": ".NET Developer", "description": "CI/CD pipelines, C# services."}
    assert b.score_bucket(job, only_b) > 0


def test_annotate_tags_jobs_in_place(all_buckets):
    jobs = [{"title": "DevOps Engineer",
             "description": "Kubernetes, Terraform, CI/CD, Linux, observability."}]
    b.annotate(jobs, all_buckets)
    assert jobs[0]["bucket"] == "C"
    assert jobs[0]["bucket_cv"].endswith(".pdf")
    assert jobs[0]["bucket_fit"] > 0


def test_search_terms_union_is_deduped(all_buckets):
    terms = b.all_search_terms(all_buckets)
    assert len(terms) == len(set(terms))
    assert "devops engineer" in terms and "fullstack developer" in terms
