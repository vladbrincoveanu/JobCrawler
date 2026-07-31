"""Tests for --profile and --profile-only.

--profile is what every *scheduled* run uses: the runner has no CV PDF. The PDF
is never committed (the repository is public) and is too large for a GitHub
Actions secret (48KB cap, ~76KB base64), so the runner reads the ~600-byte
derived profile instead. That also saves a PDF parse and an LLM extraction call
on every wake.

--profile-only is the dashboard's "register a new CV" path: extract the profile
and exit, so adding a CV costs a second instead of a full multi-minute scan.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout


@pytest.fixture
def profile_file(tmp_path):
    path = tmp_path / "backend.json"
    path.write_text(json.dumps({
        "skills": {"dotnet": 10, "kafka": 6},
        "role_titles": ["backend engineer", "software engineer"],
        "source": "llm",
    }))
    return path


def test_load_profile_file_returns_the_file_verbatim(profile_file):
    assert scout.load_profile_file(profile_file) == {
        "skills": {"dotnet": 10, "kafka": 6},
        "role_titles": ["backend engineer", "software engineer"],
        "source": "llm",
    }


def test_load_profile_file_rejects_a_profile_with_no_skills(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"skills": {}, "role_titles": ["x"], "source": "llm"}))
    with pytest.raises(ValueError, match="no skills"):
        scout.load_profile_file(path)


def test_load_profile_file_rejects_a_profile_with_no_role_titles(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"skills": {"dotnet": 10}, "role_titles": [], "source": "llm"}))
    with pytest.raises(ValueError, match="no role_titles"):
        scout.load_profile_file(path)


def test_profile_flag_never_reads_the_pdf(monkeypatch, tmp_path, profile_file):
    """The runner has no PDF at all. Reading one would crash the scheduled run."""
    def explode(_path):
        raise AssertionError("extract_cv_text must not be called with --profile")

    monkeypatch.setattr(scout, "extract_cv_text", explode)
    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [
        {"title": "Senior .NET Engineer", "company": "Bosch", "location": "Wien",
         "posted": "2026-07-30", "url": "https://example.com/1",
         "description": "dotnet kafka", "ats_type": "test"},
    ])
    out = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--profile", str(profile_file), "--sources", "apis",
        "--no-llm", "--json-out", str(out), "--top", "5",
    ])

    assert scout.main() == 0
    result = json.loads(out.read_text())
    assert result["cv"] == str(profile_file)
    assert result["profile_source"] == "llm"
    assert result["jobs"][0]["match_pct"] > 0


def test_profile_flag_scores_identically_to_the_pdf_path(monkeypatch, tmp_path, profile_file):
    """Same profile in, same score out -- the flag changes where the profile
    comes from, and nothing else."""
    job = {"title": "Senior .NET Engineer", "company": "Bosch", "location": "Wien",
           "posted": "2026-07-30", "url": "https://example.com/1",
           "description": "dotnet kafka", "ats_type": "test"}
    profile = json.loads(profile_file.read_text())

    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [dict(job)])
    out_a = tmp_path / "a.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--profile", str(profile_file), "--sources", "apis",
        "--no-llm", "--json-out", str(out_a),
    ])
    assert scout.main() == 0

    monkeypatch.setattr(scout, "load_profile", lambda *a, **k: profile)
    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [dict(job)])
    out_b = tmp_path / "b.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--cv", str(tmp_path / "fake.pdf"), "--sources", "apis",
        "--no-llm", "--json-out", str(out_b),
    ])
    assert scout.main() == 0

    a, b = json.loads(out_a.read_text()), json.loads(out_b.read_text())
    assert [j["score"] for j in a["jobs"]] == [j["score"] for j in b["jobs"]]
    assert [j["match_pct"] for j in a["jobs"]] == [j["match_pct"] for j in b["jobs"]]


def test_profile_only_extracts_and_exits_without_scanning(monkeypatch, tmp_path):
    """Registering a CV must not pay for a scan: it is a UI interaction."""
    def explode(*a, **k):
        raise AssertionError("--profile-only must not query any job source")

    monkeypatch.setattr(scout, "fetch_free_apis", explode)
    monkeypatch.setattr(scout, "extract_cv_text",
                        lambda _p: "C# .NET Azure Kafka backend engineer")

    from pypdf import PdfWriter
    pdf = tmp_path / "cv.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as fh:
        writer.write(fh)

    monkeypatch.setattr(sys, "argv", ["scout.py", "--profile-only", str(pdf)])
    assert scout.main() == 0

    written = scout._profile_cache_path(pdf)
    assert written.exists()
    assert json.loads(written.read_text())["skills"]
