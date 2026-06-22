from pathlib import Path
from crawler import config

def test_db_path_default():
    assert config.DB_PATH == Path("data/jobs.db")

def test_source_timeout():
    assert config.SOURCE_TIMEOUT_SECONDS == 600

def test_circuit_breaker_thresholds():
    assert config.CIRCUIT_BREAKER_THRESHOLD == 5
    assert config.CIRCUIT_BREAKER_BLOCKED_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_CAPTCHA_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_COOKIE_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_SCHEMA_THRESHOLD == 1

def test_ams_config_present():
    # grill-me amendment 6: base URL + cookie domain
    assert config.AMS_BASE_URL == "https://jobs.ams.at/public/"
    assert config.AMS_COOKIE_DOMAIN == ".ams.at"
    assert config.AMS_RATE_LIMIT_PER_MIN == 10
    assert config.AMS_REQUEST_JITTER_SECONDS == 2
    assert config.AMS_CAPTCHA_TUNE_THRESHOLD == 0.001
    assert config.AMS_CAPTCHA_TUNE_RUNS == 3

def test_retry_backoffs():
    assert config.RETRY_BACKOFF_FAST == (1, 2, 4)
    assert config.RETRY_BACKOFF_SLOW == (1, 5, 15)

def test_coverage_gate():
    assert config.COVERAGE_GATE == 0.90