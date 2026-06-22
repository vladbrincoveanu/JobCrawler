"""Named constants. Sub-project 1: no env override. Sub-project 4 wires env."""
from pathlib import Path

# Concurrency
MAX_CONCURRENT_FETCHES_PER_SOURCE: int = 4
MAX_CONCURRENT_HTTP_GLOBAL: int = 16
SOURCE_TIMEOUT_SECONDS: int = 600

# Circuit breaker (per source, per run, in-memory)
CIRCUIT_BREAKER_THRESHOLD: int = 5
CIRCUIT_BREAKER_BLOCKED_THRESHOLD: int = 1
CIRCUIT_BREAKER_CAPTCHA_THRESHOLD: int = 1
CIRCUIT_BREAKER_COOKIE_THRESHOLD: int = 1
CIRCUIT_BREAKER_SCHEMA_THRESHOLD: int = 1

# Signal handling
SIGINT_GRACE_SECONDS: int = 30

# Database
DB_BUSY_TIMEOUT_SECONDS: int = 30
DB_PATH: Path = Path("data/jobs.db")

# Retry
RETRY_MAX_ATTEMPTS: int = 3
RETRY_BACKOFF_FAST: tuple[int, ...] = (1, 2, 4)
RETRY_BACKOFF_SLOW: tuple[int, ...] = (1, 5, 15)

# Browser (AMS)
BROWSER_TIMEOUT_MS: int = 15_000
BROWSER_RETRIES_ON_TIMEOUT: int = 1
BROWSER_CAPTCHA_BACKOFF_SECONDS: int = 60
BROWSER_UA_POOL_SIZE: int = 10

# AMS (grill-me amendment 6: explicit URL/cookie domain config)
AMS_BASE_URL: str = "https://jobs.ams.at/public/"
AMS_COOKIE_DOMAIN: str = ".ams.at"
AMS_RATE_LIMIT_PER_MIN: int = 10
AMS_REQUEST_JITTER_SECONDS: int = 2
AMS_CAPTCHA_TUNE_THRESHOLD: float = 0.001
AMS_CAPTCHA_TUNE_RUNS: int = 3

# UA pool — 10 realistic desktop UAs, round-robin
UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)

# Coverage
COVERAGE_GATE: float = 0.90