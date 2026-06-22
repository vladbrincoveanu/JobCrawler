import inspect
from typing import get_type_hints
from crawler.sources.base import SourceAdapter
from crawler.models import JobQuery, RawJob, NormalizedJob


def test_source_adapter_is_protocol():
    assert getattr(SourceAdapter, "_is_protocol", False) or hasattr(SourceAdapter, "_is_protocol")


def test_source_adapter_required_members():
    members = {name for name, _ in inspect.getmembers(SourceAdapter)}
    assert "name" in members
    assert "search" in members
    assert "fetch_detail" in members


def test_source_adapter_signatures():
    hints_search = get_type_hints(SourceAdapter.search)
    assert hints_search["query"] == JobQuery
    assert "return" in hints_search
