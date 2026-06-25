"""
Browser automation for sending Alleypin LINE preset-text notifications,
driving the actual Alleypin web page in a dedicated Chrome profile (the
nurse logs in once; the session persists in alleypin_profile/).

No Alleypin API exists, so this drives the real page: search by DOB,
verify the matched row's national ID, open the patient-tracking picker,
click the preset-text template by its exact visible text.

Safety notes:
  - Every match is verified by national ID (data-e2e-id="users-list-table-
    col-tw-id") before anything is clicked, to guard against DOB collisions.
  - dry_run=True runs every step except the final template click, so
    selectors can be verified without sending anything real.
"""
import asyncio
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeoutError

import config

PROFILE_DIR = Path(__file__).parent / "alleypin_profile"

SEARCH_INPUT_SELECTOR = '[data-e2e-id="users-search-input"]'
ROW_SELECTOR = 'tr:has([data-e2e-id="users-list-table-col-tw-id"])'
TWID_SELECTOR = '[data-e2e-id="users-list-table-col-tw-id"]'
NAME_SELECTOR = '[data-e2e-id="users-list-table-col-name"]'
TRACKING_CELL_SELECTOR = '[data-e2e-id="users-list-table-col-patient-tracking"]'


def to_roc_slash_date(d: date) -> str:
    """Convert a Gregorian date to Alleypin's expected ROC 'YYY/MM/DD' search format."""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


async def _find_patient_row(page: Page, chart_number: str, dob_roc: str, expected_name: str = ""):
    """Search by DOB, return the row Locator matching chart_number, or None with a reason."""
    search = page.locator(SEARCH_INPUT_SELECTOR)
    await search.click()
    await search.fill("")
    await search.fill(dob_roc)
    await search.press("Enter")
    await page.wait_for_timeout(1200)  # let results settle

    rows = page.locator(ROW_SELECTOR)
    count = await rows.count()
    if count == 0:
        return None, f"no search results for DOB {dob_roc}"

    for i in range(count):
        row = rows.nth(i)
        twid = (await row.locator(TWID_SELECTOR).inner_text()).strip()
        if twid != chart_number:
            continue
        if expected_name:
            name = (await row.locator(NAME_SELECTOR).inner_text()).strip()
            if name != expected_name:
                return None, f"tw-id matched but name differs (got {name!r}, expected {expected_name!r})"
        return row, "matched"

    return None, f"{count} result(s) found but none match chart_number {chart_number}"


async def send_one(page: Page, chart_number: str, dob_roc: str, name: str,
                    template_text: str, dry_run: bool) -> dict:
    """Search, verify, open the picker, and click (or dry-run stop before clicking)
    the named template for one patient. Returns a result dict with 'status'."""
    base = {'chart_number': chart_number, 'name': name}
    try:
        row, reason = await _find_patient_row(page, chart_number, dob_roc, name)
        if row is None:
            return {**base, 'status': 'not_found', 'detail': reason}

        clickable = row.locator(TRACKING_CELL_SELECTOR).locator('.cursor-pointer').first
        await clickable.click()
        await page.wait_for_timeout(600)

        span = page.locator(f'span:text-is("{template_text}")')
        container = span.locator('xpath=ancestor::div[contains(@class, "cursor-pointer")][1]')
        try:
            await container.wait_for(timeout=3000)
        except PWTimeoutError:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'template_not_found', 'detail': f'template {template_text!r} not found in modal'}

        if dry_run:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'dry_run_ok', 'detail': f'would click {template_text!r}'}

        await container.click()
        await page.wait_for_timeout(500)
        return {**base, 'status': 'sent', 'detail': f'clicked {template_text!r}'}

    except Exception as e:
        return {**base, 'status': 'error', 'detail': str(e)}


async def run_batch(targets: list[dict], dry_run: bool, headless: bool = False, slow_mo: int = 300) -> list[dict]:
    """targets: [{'chart_number', 'dob_roc' or 'dob' (date), 'name', 'template'}, ...]
    Launches a dedicated, persistent Chrome profile (session persists across runs —
    log in once manually on the first run) and processes each target in order.
    """
    results = []
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, slow_mo=slow_mo,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(config.ALLEYPIN_URL)
        await page.wait_for_load_state("networkidle")

        for t in targets:
            dob_roc = t.get('dob_roc') or to_roc_slash_date(t['dob'])
            result = await send_one(page, t['chart_number'], dob_roc, t.get('name', ''), t['template'], dry_run)
            results.append(result)
            print(f"  [{result['status']}] {result['chart_number']} {result.get('name', '')}: {result['detail']}")

        await context.close()
    return results
