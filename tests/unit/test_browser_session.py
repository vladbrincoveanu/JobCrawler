import json
import time
from pathlib import Path
import pytest
from crawler.browser import SessionCookieStore


def test_save_and_load(tmp_path: Path):
    store = SessionCookieStore(tmp_path / "session.json")
    cookies = [
        {"name": "SM2_SESSION", "value": "abc", "domain": ".ams.at", "path": "/",
         "expires": -1, "httpOnly": True, "secure": True},
    ]
    store.save(cookies)
    loaded = store.load()
    assert loaded == cookies


def test_load_missing_returns_empty(tmp_path: Path):
    store = SessionCookieStore(tmp_path / "nonexistent.json")
    assert store.load() == []


def test_load_corrupted_returns_empty(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    store = SessionCookieStore(p)
    assert store.load() == []


def test_save_creates_dirs(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "session.json"
    store = SessionCookieStore(nested)
    store.save([{"name": "X", "value": "1", "domain": ".ams.at", "path": "/",
                 "expires": -1, "httpOnly": False, "secure": False}])
    assert nested.exists()