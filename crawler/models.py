"""Pydantic models — JobQuery, RawJob, NormalizedJob."""
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field, field_validator


class JobQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    max_results: int = 100
    since: datetime | None = None

    @field_validator("max_results")
    @classmethod
    def _clamp_max_results(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_results must be >= 1")
        return v


class RawJob(BaseModel):
    """Listing from search results — minimal fields, no description."""
    source: str
    source_id: str
    url: HttpUrl
    title: str
    company: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    fetched_at: datetime


class NormalizedJob(BaseModel):
    """Full job record after fetch_detail — persisted to DB."""
    source: str
    source_id: str
    url: HttpUrl
    title: str
    company: str
    location: str
    description: str
    salary: str | None = None
    employment_type: str | None = None
    posted_at: datetime | None = None
    content_hash: str  # SHA256 hex
    fetched_at: datetime
    raw_html: str | None = None  # grill-me amendment 4: opt-in per source (AMS sets it)
