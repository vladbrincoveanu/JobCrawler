"""SourceAdapter Protocol — contract for all job sources."""
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from crawler.models import JobQuery, NormalizedJob, RawJob


@runtime_checkable
class SourceAdapter(Protocol):
    """Every source adapter implements this. Spec § SourceAdapter contract."""
    name: str

    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]: ...

    async def fetch_detail(self, raw: RawJob) -> NormalizedJob: ...
