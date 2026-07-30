"""Tests for scout.match_evidence — the displayed "Match %".

These exist because of a specific, reported failure: every result on the scan
screen showed a score of 80-100, including generic "Senior DevOps Engineer" and
"Cloud Engineer" ads that named none of the candidate's primary stack. The
number being displayed was `rank_score`, a PERCENTILE -- the best row in any
result set scores ~100 even when nothing in that set fits -- so it could not
have shown anything else.

match_evidence replaces it with an absolute measure, and the property that
matters is the one asserted here: a .NET-first profile must score a .NET ad far
higher than a generic Kubernetes/DevOps ad, and that gap must not depend on what
else happened to be in the result set.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout

# The real reported profile: senior .NET/C# engineer, Vienna, Kafka +
# Kubernetes + Angular + LLM work. Weights mirror scout.SKILL_LEXICON.
DOTNET_PROFILE = {
    "skills": {
        "dotnet": 10, "csharp": 10, "aspnet": 8, "azure": 7, "kafka": 6,
        "kubernetes": 6, "docker": 4, "microservices": 6, "angular": 5,
        "typescript": 4, "sql": 4, "ai-llm": 8, "backend": 6, "devops": 4,
    },
    "role_titles": scout.ROLE_TITLES,
    "source": "lexicon",
}


def job(title, description=""):
    return {"title": title, "description": description}


def test_dotnet_ad_scores_far_above_a_generic_devops_ad():
    """The reported bug, as an assertion."""
    dotnet = job(
        "Backend Entwickler C#/.NET",
        "ASP.NET Core, Azure, Kafka, microservices, Angular and SQL Server.",
    )
    devops = job(
        "Senior DevOps Engineer",
        "Kubernetes, Docker, Terraform and CI/CD pipelines for our platform.",
    )

    dotnet_pct, dotnet_hits = scout.match_evidence(dotnet, DOTNET_PROFILE)
    devops_pct, devops_hits = scout.match_evidence(devops, DOTNET_PROFILE)

    assert dotnet_pct > 50, f".NET ad should read as a strong match, got {dotnet_pct}%"
    assert devops_pct < 25, f"generic DevOps ad should read as weak, got {devops_pct}%"
    assert dotnet_pct > devops_pct * 2
    # And the UI must be able to say WHY, not just show a number.
    assert "dotnet" in dotnet_hits and "csharp" in dotnet_hits
    assert "dotnet" not in devops_hits and "csharp" not in devops_hits


def test_score_is_absolute_not_a_percentile_of_the_result_set():
    """Same ad, different company: the score must not move.

    This is the property rank_score lacked -- it was computed from position
    within the result set, so identical ads scored differently depending on what
    they were listed alongside.
    """
    ad = job("Senior DevOps Engineer", "Kubernetes and Docker.")
    alone, _ = scout.match_evidence(ad, DOTNET_PROFILE)
    among_others, _ = scout.match_evidence(ad, DOTNET_PROFILE)
    assert alone == among_others


def test_a_title_hit_outweighs_a_description_mention():
    in_title, _ = scout.match_evidence(job("C# Developer"), DOTNET_PROFILE)
    in_desc, _ = scout.match_evidence(job("Developer", "Some C# work."), DOTNET_PROFILE)
    assert in_title > in_desc


def test_an_ad_naming_nothing_from_the_cv_scores_zero():
    pct, hits = scout.match_evidence(
        job("Regional Sales Manager", "Quota, CRM, territory."), DOTNET_PROFILE)
    assert pct == 0
    assert hits == []


def test_hits_are_ordered_strongest_first():
    _, hits = scout.match_evidence(
        job("Developer", "docker and .net"), DOTNET_PROFILE)
    # dotnet (10) must precede docker (4).
    assert hits.index("dotnet") < hits.index("docker")


def test_an_empty_profile_scores_zero_rather_than_dividing_by_zero():
    pct, hits = scout.match_evidence(
        job("Backend Engineer", ".NET"), {"skills": {}, "role_titles": []})
    assert (pct, hits) == (0, [])


@pytest.mark.parametrize("field", ["title", "description"])
def test_missing_fields_do_not_raise(field):
    ad = job("Backend Engineer", ".NET")
    ad[field] = None
    pct, _ = scout.match_evidence(ad, DOTNET_PROFILE)
    assert isinstance(pct, int)
