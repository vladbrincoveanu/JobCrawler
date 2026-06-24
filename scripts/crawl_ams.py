"""AMS crawler via Playwright DOM scraping.

AMS moved away from /public/jobs (paginated HTML) to /public/emps/
(search-first Angular SPA with API + consent wall + custom auth headers).

This script:
  1. Drives Playwright to accept consent and submit a search
  2. Scrapes rendered job cards from the results page (paginates via URL)
  3. For each card, follows the link to the detail page and scrapes
     the structured data (company, location, employment type, etc.)
  4. Persists to PostgreSQL via the repository.

This is robust against the SPA's auth tokens because we never call the
API directly — we let the browser do it and read the rendered DOM.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Page

from crawler.storage import repository as repo
from crawler.storage.db import connect

AMS_HOME = "https://jobs.ams.at/public/emps/"
AMS_RESULTS_PATH = "/public/emps/jobs"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


async def _accept_consent(page: Page) -> None:
    try:
        btn = page.locator('button:has-text("Einverstanden")').first
        if await btn.is_visible(timeout=2500):
            await btn.click()
            print("[ams] consent accepted")
            await page.wait_for_timeout(2000)
    except Exception:
        pass


async def _submit_search(page: Page, query: str) -> None:
    """Fill the job title autocomplete, click first suggestion, click Suchen."""
    title_input = page.locator('[data-testid="ams-autocomplete-input"]').first
    await title_input.click()
    await title_input.fill(query)
    await page.wait_for_timeout(2500)
    try:
        await page.locator('[data-testid="ams-selection-option"]').first.click()
        print(f"[ams] selected suggestion for query={query!r}")
    except Exception as e:
        print(f"[ams] no suggestion clicked: {e}")
    await page.wait_for_timeout(1000)
    await page.locator('button:has-text("Suchen")').first.click()
    print(f"[ams] clicked Suchen, waiting for results...")
    await page.wait_for_url(f"**{AMS_RESULTS_PATH}*", timeout=30000)
    await page.wait_for_timeout(4000)


async def _scrape_cards(page: Page) -> list[dict]:
    """Extract basic job info from rendered cards (title, company, uuid, href)."""
    return await page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('a[href*="/public/emps/jobs/"]').forEach(a => {
            const href = a.getAttribute('href');
            const m = href.match(/\\/jobs\\/([a-f0-9-]{36})/);
            if (!m) return;
            const uuid = m[1];
            if (seen.has(uuid)) return;
            seen.add(uuid);
            const card = a.closest('li, div, article') || a.parentElement;
            const fullText = (card ? card.innerText : a.innerText).trim();
            // Pattern: "Title\\nbei Company" or "Title\\nCompany"
            const lines = fullText.split('\\n').map(s => s.trim()).filter(Boolean);
            const title = lines[0] || '';
            let company = null;
            const beiMatch = fullText.match(/bei\\s+([^\\n]+)/);
            if (beiMatch) company = beiMatch[1].trim();
            else if (lines.length >= 2) company = lines[1];
            out.push({uuid, href, title, company, fullText: fullText.slice(0, 400)});
        });
        return out;
    }""")


async def _scrape_detail(page: Page, uuid: str) -> dict:
    """Fetch and parse a job detail page."""
    url = f"https://jobs.ams.at/public/emps/jobs/{uuid}"
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(3500)
    return await page.evaluate("""() => {
        const text = document.body.innerText;
        // Title: first line in the detail container
        const titleEl = document.querySelector('h1, .c-detail-title, .job-title');
        const title = titleEl ? titleEl.innerText.trim() : (text.split('\\n')[0] || '').trim();
        // Key/value pairs: <label data-testid="key-value-pair-label">Firma:</label> <content>Firma XYZ</content>
        const fields = {};
        document.querySelectorAll('[data-testid="key-value-pair-label"]').forEach((lab, i) => {
            const key = (lab.innerText || '').replace(':', '').trim();
            const content = lab.nextElementSibling;
            const val = content ? (content.innerText || '').trim() : '';
            if (key) fields[key] = val;
        });
        // Try the contact panel
        const contactEl = document.querySelector('.c-detail-contact, [class*="contact"]');
        const contact = contactEl ? contactEl.innerText.trim() : '';
        const companyInfoEl = document.querySelector('.c-detail-company-info, [class*="company-info"]');
        const companyInfo = companyInfoEl ? companyInfoEl.innerText.trim() : '';
        // Description block: look for sections after "Aufgaben" / "Anforderungen" / "Wir bieten"
        const desc = (document.querySelector('.c-detail-description, [class*="description"]') || {}).innerText || '';
        return {title, fields, contact, companyInfo, desc: desc.slice(0, 4000)};
    }""")


def _coalesce(*vals) -> str | None:
    for v in vals:
        if v:
            return v
    return None


def _detail_to_record(uuid: str, href: str, basic: dict, detail: dict) -> dict:
    f = detail.get("fields", {})
    # Common German field labels
    company = _coalesce(f.get("Unternehmen"), basic.get("company"))
    location = _coalesce(f.get("Arbeitsort"), f.get("Standort"))
    employment_type = _coalesce(f.get("Arbeitszeit"), f.get("Dienstverhältnis"))
    salary = f.get("Gehalt") or f.get("Entlohnung")
    description_parts = []
    for key in ("Beschreibung", "Aufgaben", "Anforderungen", "Wir bieten"):
        if f.get(key):
            description_parts.append(f"{key}:\n{f[key]}")
    if detail.get("desc"):
        description_parts.append(detail["desc"])
    if detail.get("contact"):
        description_parts.append(f"Kontakt:\n{detail['contact']}")
    description = "\n\n".join(description_parts) or None

    # Stash extra fields in raw_payload (JSONB column)
    raw_payload = {
        "fields": f,
        "contact": detail.get("contact"),
        "company_info": detail.get("companyInfo"),
        "salary": salary,
        "employment_type": employment_type,
        "card_text": basic.get("fullText"),
    }

    # Title — strip any "bei Company" trailing line that the SPA renders into the heading
    raw_title = _coalesce(detail.get("title"), basic.get("title"), "") or ""
    title = raw_title.split("\n")[0].strip()
    if title.lower().startswith("bei "):
        title = ""

    return {
        "source": "ams",
        "source_id": uuid,
        "url": f"https://jobs.ams.at{href}",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "raw_payload": raw_payload,
    }


async def crawl(query: str, limit: int, conn, run_id: int) -> dict:
    counters = {"found": 0, "inserted": 0, "updated": 0, "errors": 0}

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(user_agent=UA)
        page = await ctx.new_page()
        await page.goto(AMS_HOME, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        await _accept_consent(page)

        await _submit_search(page, query)

        page_no = 1
        while counters["found"] < limit:
            if page_no > 1:
                # Navigate by appending page param to current URL
                cur = page.url
                if "page=" in cur:
                    new_url = cur.replace(f"page={page_no - 1}", f"page={page_no}")
                else:
                    sep = "&" if "?" in cur else "?"
                    new_url = f"{cur}{sep}page={page_no}"
                await page.goto(new_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(4000)
                await _accept_consent(page)

            cards = await _scrape_cards(page)
            print(f"[ams] page {page_no}: {len(cards)} cards")
            if not cards:
                break

            for c in cards:
                if counters["found"] >= limit:
                    break
                counters["found"] += 1
                # Per-job savepoint so a single bad row doesn't lose the whole page
                sp = f"sp_{counters['found']}"
                try:
                    conn.execute(f"SAVEPOINT {sp}")
                    detail = await _scrape_detail(page, c["uuid"])
                    rec = _detail_to_record(c["uuid"], c["href"], c, detail)
                    row = repo.upsert_job(conn, **rec)
                    conn.execute(f"RELEASE SAVEPOINT {sp}")
                    counters["inserted" if row["created"] else "updated"] += 1
                    print(f"  [{counters['found']}/{limit}] {rec['title']!r} @ {rec['company']!r} ({rec['location']!r})")
                except Exception as e:
                    counters["errors"] += 1
                    try:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        repo.record_error(conn, run_id, stage="detail",
                                          message=f"{type(e).__name__}: {e}",
                                          context={"uuid": c["uuid"]})
                    except Exception:
                        conn.rollback()
                        try:
                            repo.record_error(conn, run_id, stage="detail",
                                              message=f"{type(e).__name__}: {e}",
                                              context={"uuid": c["uuid"]})
                        except Exception:
                            pass
                    print(f"  [{counters['found']}/{limit}] ERROR {c['uuid']}: {type(e).__name__}: {e}")

            conn.commit()
            page_no += 1
            if page_no > 20:  # safety cap
                print("[ams] hit page cap, stopping")
                break

        await b.close()
    return counters


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Software", help="Job title keyword")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    conn = connect()
    repo.upsert_source(conn, "ams")
    run_id = repo.start_run(conn, "ams")

    try:
        if args.dry_run:
            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True)
                ctx = await b.new_context(user_agent=UA)
                page = await ctx.new_page()
                await page.goto(AMS_HOME, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)
                await _accept_consent(page)
                await _submit_search(page, args.query)
                cards = await _scrape_cards(page)
                await b.close()
            print(f"\nDRY RUN: {len(cards)} cards visible on page 1")
            for c in cards[:args.limit]:
                print(f"  {c['uuid'][:8]}  {c['title']!r}  @  {c['company']!r}")
            repo.finish_run(conn, run_id, status="success", jobs_found=0, jobs_new=0)
            conn.commit()
            conn.close()
            return 3

        counters = await crawl(args.query, args.limit, conn, run_id)
        status = "success" if counters["errors"] == 0 else "partial"
        repo.finish_run(conn, run_id, status=status,
                        jobs_found=counters["found"],
                        jobs_new=counters["inserted"])
        conn.commit()
        conn.close()
        print(f"\n[ams] DONE status={status} counters={counters}")
        return 0 if status == "success" else 1

    except Exception as e:
        conn.rollback()
        try:
            repo.record_error(conn, run_id, stage="crawl", message=f"{type(e).__name__}: {e}")
            repo.finish_run(conn, run_id, status="failed", jobs_found=0, jobs_new=0)
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))