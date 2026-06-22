import pytest
from crawler.exceptions import (
    CrawlerError, FetchError, RateLimited, Blocked, CaptchaEncountered,
    CookieExpired, SPAWaitTimeout, Timeout, HTTPError, NetworkError,
    ParseError, SchemaChanged, MissingField, StorageError, MigrationError, ConstraintError,
)

def test_crawler_error_is_base():
    assert issubclass(FetchError, CrawlerError)
    assert issubclass(ParseError, CrawlerError)
    assert issubclass(StorageError, CrawlerError)

def test_fetch_error_subtypes():
    for cls in (RateLimited, Blocked, CaptchaEncountered, CookieExpired,
                SPAWaitTimeout, Timeout, HTTPError, NetworkError):
        assert issubclass(cls, FetchError), f"{cls.__name__} not FetchError"

def test_ratelimited_retry_after():
    e = RateLimited("429", retry_after=5)
    assert e.retry_after == 5
    assert str(e) == "429"

def test_parse_error_subtypes():
    assert issubclass(SchemaChanged, ParseError)
    assert issubclass(MissingField, ParseError)

def test_storage_error_subtypes():
    assert issubclass(MigrationError, StorageError)
    assert issubclass(ConstraintError, StorageError)

def test_crawler_error_can_be_raised_and_caught():
    with pytest.raises(CrawlerError):
        raise RateLimited("test")
    with pytest.raises(FetchError):
        raise CaptchaEncountered("captcha detected")