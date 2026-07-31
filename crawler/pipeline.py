"""Per-source crawl orchestrator with circuit breaker. Spec § Data Flow."""
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import psycopg

from crawler import config
from crawler.exceptions import (
    Blocked,
    CaptchaEncountered,
    CookieExpired,
    CrawlerError,
    FetchError,
    SchemaChanged,
)
from crawler.models import JobQuery
from crawler.sources.base import SourceAdapter
from crawler.storage import repository as repo


def _safe_log_error(conn: psycopg.Connection, run_id: int, source: str,
                    url: str | None, error_type: str, error_message: str) -> None:
    """Persist error but swallow DB errors so logging never crashes a run."""
    try:
        repo.record_error(
            conn, run_id,
            stage=source,
            message=f"{error_type}: {error_message}",
            context={"url": str(url)} if url else None,
        )
    except psycopg.Error:
        pass


@dataclass
class SourceResult:
    adapter_name: str
    status: str = ""  # success | partial | failed | crashed (empty until finalized)
    counters: dict[str, int] = field(default_factory=lambda: {"inserted": 0, "updated": 0, "errors": 0, "found": 0})
    error: str | None = None


class _CircuitBreaker:
    """Per-source, per-run, in-memory. Resets on run boundary."""

    def __init__(self, name: str):
        self.name = name
        self._consecutive_fetch_errors = 0
        self._opened = False

    def record(self, exc: Exception) -> None:
        if isinstance(exc, Blocked) or isinstance(exc, (CaptchaEncountered, CookieExpired, SchemaChanged)):
            self._opened = True
        elif isinstance(exc, FetchError):
            self._consecutive_fetch_errors += 1
            if self._consecutive_fetch_errors >= config.CIRCUIT_BREAKER_THRESHOLD:
                self._opened = True
        else:
            self._consecutive_fetch_errors = 0

    @property
    def is_open(self) -> bool:
        return self._opened


# Backward-compat alias for callers/tests that import CircuitOpen.
CircuitOpen = _CircuitBreaker


async def run_source(conn: psycopg.Connection, adapter: SourceAdapter,
                     query: JobQuery, run_id: int, *, dry_run: bool = False) -> SourceResult:
    """Crawl a single source. Returns SourceResult (never raises).

    If dry_run=True: skip upsert_job calls (count only). Errors still logged.
    """
    result = SourceResult(adapter_name=adapter.name)
    breaker = _CircuitBreaker(adapter.name)
    try:
        async with asyncio.timeout(config.SOURCE_TIMEOUT_SECONDS):
            async for raw in adapter.search(query):
                result.counters["found"] += 1
                try:
                    detail = await adapter.fetch_detail(raw)
                    if dry_run:
                        result.counters["inserted"] += 1  # count only
                    else:
                        row = repo.upsert_job(
                            conn,
                            source=detail.source,
                            source_id=detail.source_id,
                            url=str(detail.url),
                            title=detail.title,
                            company=detail.company,
                            location=detail.location,
                            description=detail.description,
                        )
                        action = "inserted" if row["created"] else "updated"
                        result.counters[action] += 1
                except CrawlerError as e:
                    breaker.record(e)
                    if not dry_run:
                        _safe_log_error(conn, run_id, adapter.name, str(raw.url),
                                        type(e).__name__, str(e))
                    result.counters["errors"] += 1
                    # Breaker records the open state for visibility, but we keep
                    # draining the current search iteration so partial progress is
                    # always persisted before this run ends.
        if result.status == "":
            result.status = "success" if result.counters["errors"] == 0 else "partial"
        return result
    except TimeoutError:
        result.status = "failed"
        result.error = f"source timeout after {config.SOURCE_TIMEOUT_SECONDS}s"
        return result
    except CrawlerError as e:
        breaker.record(e)
        result.status = "failed"
        result.error = f"{type(e).__name__}: {e}"
        if not dry_run:
            _safe_log_error(conn, run_id, adapter.name, None, type(e).__name__, str(e))
        return result
    except Exception as e:
        result.status = "crashed"
        result.error = f"unexpected {type(e).__name__}: {e}"
        if not dry_run:
            _safe_log_error(conn, run_id, adapter.name, None, type(e).__name__, str(e))
        return result


async def run(conn: psycopg.Connection, adapters: Sequence[SourceAdapter],
              query: JobQuery, run_id: int, *, dry_run: bool = False) -> list[SourceResult]:
    """Fan out to all sources. Always returns list (gather with no return_exceptions)."""
    return await asyncio.gather(*[run_source(conn, a, query, run_id, dry_run=dry_run) for a in adapters])