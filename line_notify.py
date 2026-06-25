"""
Browser automation for sending Alleypin LINE preset-text notifications,
driving the actual Alleypin web page in a dedicated Edge profile.

No Alleypin API exists, so this drives the real page: search by DOB,
verify the matched row's national ID, open the patient-tracking picker,
click the preset-text template by its exact visible text.

The automation browser is launched as an independent OS process (NOT via
Playwright's launch()/launch_persistent_context(), which would tie its
lifetime to our script and kill it on exit) and reused across calls by
attaching to it over CDP. This matters because Alleypin's login appears
to use a session-only cookie — Chrome/Edge discard those on a clean
shutdown by default even with a persistent profile, so a browser that
gets relaunched every call would need a fresh login every call. Logging
in once, the first time it's ever launched, and never closing it
sidesteps that. Use stop_browser() to force a clean restart if needed.

Safety notes:
  - Every match is verified by national ID (data-e2e-id="users-list-table-
    col-tw-id") before anything is clicked, to guard against DOB collisions.
  - dry_run=True runs every step except the final template click, so
    selectors can be verified without sending anything real.
"""
import asyncio
import shutil
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeoutError

import config

PROFILE_DIR = Path(__file__).parent / "alleypin_profile"

# Fixed CDP port so the automation browser can be found and reused across
# calls instead of being relaunched (and re-logged-in) every time.
DEBUG_PORT = 9234

SEARCH_INPUT_SELECTOR = '[data-e2e-id="users-search-input"]'
ROW_SELECTOR = 'tr:has([data-e2e-id="users-list-table-col-tw-id"])'
TWID_SELECTOR = '[data-e2e-id="users-list-table-col-tw-id"]'
NAME_SELECTOR = '[data-e2e-id="users-list-table-col-name"]'
TRACKING_CELL_SELECTOR = '[data-e2e-id="users-list-table-col-patient-tracking"]'

# Nurses already use Edge daily, so drive that instead of installing Chrome.
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def to_roc_slash_date(d: date) -> str:
    """Convert a Gregorian date to Alleypin's expected ROC 'YYY/MM/DD' search format."""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def _edge_executable_path() -> str:
    for c in _EDGE_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("msedge")
    if found:
        return found
    raise RuntimeError("Could not find msedge.exe — set its path in _EDGE_CANDIDATES in line_notify.py")


def _is_browser_alive() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=1)
        return True
    except Exception:
        return False


def _launch_detached_browser():
    """Start Edge as an independent OS process — NOT a Playwright-managed
    child — so it keeps running after our script exits. Logging into
    Alleypin happens once here; later calls just attach via CDP."""
    exe = _edge_executable_path()
    PROFILE_DIR.mkdir(exist_ok=True)
    args = [exe, f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={PROFILE_DIR}"]
    if config.ALLEYPIN_HEADLESS:
        args.append("--headless=new")
    args.append(config.ALLEYPIN_URL)
    subprocess.Popen(args, close_fds=True)


async def _get_page(p) -> Page:
    """Attach to the long-running automation browser, launching it first if
    it isn't already up. Never closes it — only stop_browser() does."""
    if not _is_browser_alive():
        _launch_detached_browser()
        for _ in range(30):
            if _is_browser_alive():
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Edge did not start within 15s — check Edge is installed and the port is free")

    browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()
    return page


async def stop_browser() -> bool:
    """Force-close the long-running automation browser (e.g. to clear a stuck
    state, or to force a fresh login). Returns True if it was running."""
    if not _is_browser_alive():
        return False
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        await browser.close()
    return True


async def _navigate_if_needed(page: Page):
    """Re-navigate to the Alleypin URL if the page somehow ended up elsewhere."""
    if config.ALLEYPIN_URL not in page.url:
        await page.goto(config.ALLEYPIN_URL)
        await page.wait_for_load_state("networkidle")


async def _ensure_logged_in(page: Page):
    """Fail loudly if the page doesn't look logged in, rather than letting
    every subsequent patient search silently come back not_found. Matters
    most after a PC reboot — Alleypin's session cookie doesn't appear to
    survive a clean browser shutdown, and in headless mode there's no
    visible window to notice a login page came up instead of the patient list."""
    try:
        await page.locator(SEARCH_INPUT_SELECTOR).wait_for(timeout=5000)
    except PWTimeoutError:
        raise RuntimeError(
            "尚未登入 Alleypin（找不到搜尋欄位）。請將 config.py 的 ALLEYPIN_HEADLESS "
            "暫時設為 False，執行 python test_line_notify.py --stop 後重新登入一次，"
            "再改回 True。"
        )


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
        await page.wait_for_timeout(300)
        # Clicking the template only selects it — clicking outside the modal
        # afterward is what actually commits/persists it (matches the manual
        # workflow). Without this, the tag appears briefly then reverts.
        await page.locator(SEARCH_INPUT_SELECTOR).click()
        await page.wait_for_timeout(800)
        return {**base, 'status': 'sent', 'detail': f'clicked {template_text!r}'}

    except Exception as e:
        return {**base, 'status': 'error', 'detail': str(e)}


async def run_batch(targets: list[dict], dry_run: bool, on_result=None) -> list[dict]:
    """targets: [{'chart_number', 'dob_roc' or 'dob' (date), 'name', 'template'}, ...]
    Attaches to the long-running automation browser (launching it first if
    needed) and processes each target in order. Never closes the browser —
    only stop_browser() does.

    on_result, if given, is called with each result dict right after it
    completes (e.g. so a caller can report live progress or mark a patient
    as contacted immediately rather than waiting for the whole batch).
    """
    results = []
    async with async_playwright() as p:
        page = await _get_page(p)
        await _navigate_if_needed(page)
        await _ensure_logged_in(page)

        for t in targets:
            dob_roc = t.get('dob_roc') or to_roc_slash_date(t['dob'])
            result = await send_one(page, t['chart_number'], dob_roc, t.get('name', ''), t['template'], dry_run)
            results.append(result)
            print(f"  [{result['status']}] {result['chart_number']} {result.get('name', '')}: {result['detail']}")
            if on_result:
                on_result(result)

    return results
