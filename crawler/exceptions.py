"""Typed exception hierarchy. Spec § Error Handling."""


class CrawlerError(Exception):
    """Base for all JobCrawler errors."""


class FetchError(CrawlerError):
    """Source fetch failure. Retry policy in spec § Retry policy."""


class RateLimited(FetchError):
    def __init__(self, msg: str, retry_after: int | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class Blocked(FetchError):
    """403 / anti-bot block. Circuit-break per spec."""


class CaptchaEncountered(FetchError):
    """AMS anti-bot challenge page. No auto-solve. Circuit-break."""


class CookieExpired(FetchError):
    """SM2_SESSION invalid mid-session. Refresh + 1 retry."""


class SPAWaitTimeout(FetchError):
    """Page selector never appeared. 1 retry (likely transient)."""


class Timeout(FetchError):
    """Connect/read timeout."""


class HTTPError(FetchError):
    """Other 4xx/5xx. 5xx retries, 4xx (non-429) does not."""


class NetworkError(FetchError):
    """DNS, conn refused. SLOW backoff."""


class ParseError(CrawlerError):
    """Source response shape issue."""


class SchemaChanged(ParseError):
    """Selectors/JSON shape broke. Circuit-break."""


class MissingField(ParseError):
    """Required field absent. Skip job, log."""


class StorageError(CrawlerError):
    """DB layer error."""


class MigrationError(StorageError):
    """Schema migration failed."""


class ConstraintError(StorageError):
    """UNIQUE/CHECK constraint violation. Should not happen post-upsert."""