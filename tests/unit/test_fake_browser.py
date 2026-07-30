import pytest

from crawler.exceptions import CaptchaEncountered, SPAWaitTimeout
from tests.fakes.browser import FakeBrowserContext


@pytest.fixture
def fake():
    return FakeBrowserContext({
        "https://jobs.ams.at/public/jobs": '<html><body><div data-testid="job-card">job cards</div></body></html>',
        "https://jobs.ams.at/public/jobs/123": "<html><body>detail</body></html>",
    })


@pytest.mark.asyncio
async def test_goto_returns_html(fake):
    html = await fake.goto("https://jobs.ams.at/public/jobs")
    assert "job cards" in html


@pytest.mark.asyncio
async def test_goto_missing_url_raises(fake):
    with pytest.raises(SPAWaitTimeout):
        await fake.goto("https://nope.at/")


@pytest.mark.asyncio
async def test_goto_with_wait_selector_passes(fake):
    html = await fake.goto("https://jobs.ams.at/public/jobs", wait_selector='[data-testid="job-card"]')
    assert "job cards" in html


@pytest.mark.asyncio
async def test_goto_with_unmet_wait_selector_raises(fake):
    with pytest.raises(SPAWaitTimeout):
        await fake.goto("https://jobs.ams.at/public/jobs", wait_selector="[data-testid='missing']")


@pytest.mark.asyncio
async def test_captcha_fixture_raises(fake):
    fake.add_anti_bot_response("https://jobs.ams.at/captcha", title="captcha")
    with pytest.raises(CaptchaEncountered):
        await fake.goto("https://jobs.ams.at/captcha")


@pytest.mark.asyncio
async def test_cookies_roundtrip(fake):
    fake.set_cookies([{"name": "SM2_SESSION", "value": "abc", "domain": ".ams.at",
                        "path": "/", "expires": -1, "httpOnly": True, "secure": True}])
    cookies = await fake.cookies()
    assert cookies[0]["value"] == "abc"