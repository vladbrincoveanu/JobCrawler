import pytest
from crawler.browser import _detect_anti_bot
from crawler.exceptions import CaptchaEncountered, Blocked


def test_detect_captcha_title():
    with pytest.raises(CaptchaEncountered):
        _detect_anti_bot(title="captcha", body="<html>captcha</html>", url="https://jobs.ams.at/public/jobs")


def test_detect_403_raises_blocked():
    with pytest.raises(Blocked):
        _detect_anti_bot(title="Access Denied", body="", url="https://jobs.ams.at/x", status=403)


def test_detect_access_denied_body():
    with pytest.raises(Blocked):
        _detect_anti_bot(title="Jobs", body="access denied", url="https://jobs.ams.at/x")


def test_detect_verify_url():
    with pytest.raises(CaptchaEncountered):
        _detect_anti_bot(title="Verify", body="", url="https://jobs.ams.at/verify")


def test_normal_page_passes():
    _detect_anti_bot(title="Jobs - AMS", body="<html>jobs</html>", url="https://jobs.ams.at/public/jobs")