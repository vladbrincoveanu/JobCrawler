"""SourceAdapter Protocol — contract for all job sources."""
from typing import AsyncIterator, Protocol, runtime_checkable
from crawler.models import JobQuery, RawJob, NormalizedJob


@runtime_checkable
class SourceAdapter(Protocol):
    """Every source adapter implements this. Spec § SourceAdapter contract."""
    name: str

    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]: ...

    async def fetch_detail(self, raw: RawJob) -> NormalizedJob: ...
