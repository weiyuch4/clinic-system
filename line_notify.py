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
  - Every match is verified by national ID (data-e2e-id prefix
    "users-list-table-col-tw-id-") before anything is clicked, to guard against DOB collisions.
  - dry_run=True runs every step except the final template click, so
    selectors can be verified without sending anything real.
"""
import asyncio
import json
import shutil
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeoutError

import config

PROFILE_DIR = Path(__file__).parent / "alleypin_profile"
PID_FILE = Path(__file__).parent / "alleypin_browser.pid"

# Fixed CDP port so the automation browser can be found and reused across
# calls instead of being relaunched (and re-logged-in) every time.
DEBUG_PORT = 9234

SEARCH_INPUT_SELECTOR = '[data-e2e-id="users-search-input"]'
# Alleypin appends a per-patient UUID to all row-level data-e2e-id values,
# so all row selectors use prefix matching (^=) instead of exact match.
ROW_SELECTOR = '[data-e2e-id^="users-list-table-row-"]'
TWID_SELECTOR = '[data-e2e-id^="users-list-table-col-tw-id-"]'
NAME_SELECTOR = '[data-e2e-id^="users-list-table-col-name-"]'
# Outer tracking cell (td). Both the outer td and the inner trigger div share
# the "patient-tracking-" prefix; TRACKING_TRIGGER_SELECTOR pins the trigger.
TRACKING_CELL_SELECTOR = '[data-e2e-id^="users-list-table-col-patient-tracking-"]'
TRACKING_TRIGGER_SELECTOR = '[data-e2e-id^="users-list-table-col-patient-tracking-"][data-e2e-id$="-trigger"]'
# The line-binding column (chain icon) carries the LINE-linked status.
# Its SVG has class="text-green-400" when linked; use that over fill color.
LINE_LINK_SELECTOR = '[data-e2e-id^="users-list-table-col-line-binding-"]'
# No data-e2e-id on the per-tag pills inside the tracking-history popup (per the
# HTML the user pasted) — matched structurally instead: each applied tag is a
# div.inline-flex containing the template-text span and a timestamp span.ml-1.
# Scoped to direct children of the applied-tags wrapper (rounded-lg + bg-white)
# specifically because the SAME popup also lists all ~36 selectable templates
# further down in a different container (text-xs, items wrapped in
# div.cursor-pointer) — those also render as div.inline-flex with matching
# text, just with an empty timestamp span and no remove svg. An unscoped
# search matched that picker entry instead of the real tag and hung forever
# waiting for a non-existent svg inside it.
TAG_ENTRY_SELECTOR = 'div.rounded-lg.border-gray-300.bg-white > div.inline-flex'
# The selectable-template list inside the same popup — div.cursor-pointer
# items inside the text-xs results container ("搜尋結果 (36/36)"). Scoped here
# for the same reason as TAG_ENTRY_SELECTOR above: a patient who already has
# a template applied also shows it (read-only) directly in the row's own
# tracking cell, which stays in the DOM even with the popup open — an
# unscoped text search matches that too, and Playwright's strict mode then
# refuses with "resolved to 2 elements" rather than guessing which to click.
PICKER_OPTION_SELECTOR = 'div.flex.flex-wrap.gap-2.text-xs > div.cursor-pointer'

_BROWSER_CANDIDATES = [
    # Chrome
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # Edge fallback
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def to_roc_slash_date(d: date) -> str:
    """Convert a Gregorian date to Alleypin's expected ROC 'YYY/MM/DD' search format."""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def _edge_executable_path() -> str:
    for c in _BROWSER_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("chrome", "google-chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("Could not find Chrome or Edge — add its path to _BROWSER_CANDIDATES in line_notify.py")


def _is_browser_alive() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=1)
        return True
    except Exception:
        return False


def _kill_stale_profile_processes() -> None:
    """Kill any existing msedge.exe process already bound to our specific
    profile directory, before attempting a fresh launch. Edge's
    single-instance behavior means launching a new process while an old one
    (even one started without --remote-debugging-port, e.g. left over from
    before that flag existed, or from a session Windows restored on its
    own) already holds this profile just silently hands off to the old one
    — our new --remote-debugging-port flag never takes effect, and
    _is_browser_alive() then waits forever for a port that's never opened.
    Best-effort: any failure here just means the launch attempt proceeds
    as before, no worse than not having this check at all."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
             "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
        )
        procs = json.loads(result.stdout or "[]")
        if isinstance(procs, dict):
            procs = [procs]
        profile_str = str(PROFILE_DIR)
        for proc_info in procs:
            cmdline = proc_info.get("CommandLine") or ""
            if profile_str in cmdline:
                # No /T (tree-kill) here on purpose: every child process of
                # the stale instance (renderer/gpu/utility) independently
                # repeats --user-data-dir in its own command line, so this
                # loop already matches and kills each of them on their own
                # merits. /T kills the matched PID's whole process *tree*,
                # which is unnecessary for that and a needless risk if any
                # matched PID ever turns out not to be what we expect.
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(proc_info["ProcessId"])],
                    capture_output=True, timeout=10,
                )
    except Exception:
        pass


def _launch_detached_browser():
    """Start Edge as an independent OS process — NOT a Playwright-managed
    child — so it keeps running after our script exits. Logging into
    Alleypin happens once here; later calls just attach via CDP.

    The PID is saved to PID_FILE so stop_browser() — possibly called from a
    completely different process later — can find and kill it directly."""
    _kill_stale_profile_processes()
    exe = _edge_executable_path()
    PROFILE_DIR.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [exe, f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={PROFILE_DIR}", config.ALLEYPIN_URL],
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid))


async def _get_page(p) -> Page:
    """Attach to the long-running automation browser, launching it first if
    it isn't already up. Never closes it — only stop_browser() does."""
    if not _is_browser_alive():
        _launch_detached_browser()
        # A cold start (first launch in a while, profile not yet warm in the
        # OS file cache) can genuinely take longer than a few seconds on
        # PC1's hardware — seen as "fails once, an immediate retry works",
        # i.e. the browser was about to finish right as we gave up too early.
        for _ in range(90):
            if _is_browser_alive():
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Edge did not start within 45s — check Edge is installed and the port is free")

    browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()
    return page


async def stop_browser() -> bool:
    """Force-close the long-running automation browser (e.g. to clear a stuck
    state, or to force a fresh login). Returns True if it was running.

    Kills by PID rather than calling browser.close() over CDP — for a browser
    Playwright didn't launch itself (i.e. attached via connect_over_cdp), close()
    only ends Playwright's connection to it and does NOT terminate the actual
    OS process, so the old browser (with whatever launch flags it started
    with) silently kept running no matter how many times this was called."""
    if not _is_browser_alive():
        return False
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
        PID_FILE.unlink(missing_ok=True)
    for _ in range(20):
        if not _is_browser_alive():
            break
        await asyncio.sleep(0.5)
    return True


def _bring_browser_to_front() -> None:
    """Raise the automation browser's OS window using Win32 SetForegroundWindow.
    page.bring_to_front() only activates the CDP tab — it does not raise the
    window on Windows due to focus-stealing prevention."""
    try:
        import ctypes
        # Our launcher PID rarely owns the visible window; search child msedge
        # processes. Fall back to any msedge/chrome with a window if no PID file.
        launcher_pid = PID_FILE.read_text().strip() if PID_FILE.exists() else ""
        if launcher_pid:
            ps_cmd = (
                f"$root={launcher_pid};"
                "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" |"
                " Where-Object { $_.ProcessId -eq $root -or $_.ParentProcessId -eq $root } |"
                " ForEach-Object { Get-Process -Id $_.ProcessId -EA SilentlyContinue } |"
                " Where-Object { $_.MainWindowHandle -ne 0 } |"
                " Select-Object -ExpandProperty MainWindowHandle -First 1"
            )
        else:
            ps_cmd = (
                "Get-Process msedge,chrome -EA SilentlyContinue |"
                " Where-Object { $_.MainWindowHandle -ne 0 } |"
                " Select-Object -ExpandProperty MainWindowHandle -First 1"
            )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=8,
        )
        hwnd_str = result.stdout.strip()
        if hwnd_str and hwnd_str.isdigit() and int(hwnd_str) != 0:
            hwnd = int(hwnd_str)
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)       # SW_RESTORE — un-minimise if needed
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


async def _navigate_if_needed(page: Page):
    """Re-navigate to the Alleypin URL if the page somehow ended up elsewhere."""
    if config.ALLEYPIN_URL not in page.url:
        await page.goto(config.ALLEYPIN_URL)
        await page.wait_for_load_state("networkidle")


async def _ensure_logged_in(page: Page):
    """Fail loudly if the page doesn't look logged in, rather than letting
    every subsequent patient search silently come back not_found. Matters
    most after a PC reboot — Alleypin's session cookie doesn't appear to
    survive a clean browser shutdown, so the freshly-launched browser may
    come up on a login page instead of the patient list."""
    try:
        await page.locator(SEARCH_INPUT_SELECTOR).wait_for(timeout=5000)
    except PWTimeoutError:
        raise RuntimeError(
            "尚未登入 Alleypin（找不到搜尋欄位）。請執行 python test_line_notify.py --stop，"
            "等視窗開啟後手動登入一次。"
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

    cn_upper = chart_number.upper()
    # Use filter(has=...) to let Playwright resolve in one browser round-trip
    # instead of looping with a separate inner_text() call per row.
    matching = rows.filter(has=page.locator(TWID_SELECTOR, has_text=cn_upper))
    match_count = await matching.count()
    if match_count == 0:
        return None, f"{count} result(s) found but none match chart_number {chart_number}"

    row = matching.first
    if expected_name:
        name = (await row.locator(NAME_SELECTOR).inner_text()).strip()
        if name != expected_name:
            print(f"  [name-warn] {chart_number}: Alleypin shows {name!r}, expected {expected_name!r} — proceeding on ID match")
    return row, "matched"


async def _is_line_linked(row) -> bool:
    """Whether this patient's LINE account is linked to Alleypin. Sending a
    template to an unlinked patient is accepted by the picker exactly like a
    normal send, but never actually delivers anything — checking this first
    avoids wasting a click on a send that would silently go nowhere."""
    count = await row.locator(f'{LINE_LINK_SELECTOR} svg.text-green-400').count()
    return count > 0


def _parse_alleypin_timestamp(text: str) -> date | None:
    """Parse a tag's displayed timestamp, e.g. '2026/05/12 11:04' (Gregorian,
    unlike the ROC-format DOB search box)."""
    text = text.strip()
    if not text:
        return None
    try:
        y, m, d = text.split(' ')[0].split('/')
        return date(int(y), int(m), int(d))
    except (ValueError, IndexError):
        return None


async def _last_sent_at(row, template_text: str) -> date | None:
    """Read the row's own tracking cell (visible without opening the popup)
    for an existing tag matching this template, returning when it was last
    sent, or None if it's never been sent to this patient."""
    entry = row.locator(f'{TRACKING_CELL_SELECTOR} div.inline-flex').filter(has_text=template_text)
    if await entry.count() == 0:
        return None
    ts_text = await entry.first.locator('span.ml-1').inner_text()
    return _parse_alleypin_timestamp(ts_text)


async def send_one(page: Page, chart_number: str, dob_roc: str, name: str,
                    template_text: str, dry_run: bool) -> dict:
    """Search, verify, open the picker, and click (or dry-run stop before clicking)
    the named template for one patient. Returns a result dict with 'status'."""
    base = {'chart_number': chart_number, 'name': name}
    try:
        print(f"  [search] {chart_number} {name} DOB={dob_roc}")
        row, reason = await _find_patient_row(page, chart_number, dob_roc, name)
        if row is None:
            return {**base, 'status': 'not_found', 'detail': reason}
        print(f"  [found] {chart_number}")

        linked = await _is_line_linked(row)
        print(f"  [line_linked={linked}] {chart_number}")
        if not linked:
            return {**base, 'status': 'line_not_linked', 'detail': 'patient has not linked LINE to Alleypin — would not be delivered'}

        last_sent = await _last_sent_at(row, template_text)
        if last_sent is not None:
            days_since = (date.today() - last_sent).days
            if days_since < config.RECENT_SEND_THRESHOLD_DAYS:
                return {
                    **base, 'status': 'recently_sent', 'last_sent_at': last_sent.isoformat(),
                    'detail': f'same template already sent {days_since} day(s) ago ({last_sent.isoformat()}) — skipping to avoid a duplicate',
                }

        print(f"  [open_picker] {chart_number}")
        clickable = row.locator(TRACKING_TRIGGER_SELECTOR)
        await clickable.click()

        # Scoped to the picker's own list (div.cursor-pointer items inside the
        # text-xs results container), not just "any cursor-pointer ancestor of
        # matching text" — a patient who already has this exact template applied
        # also shows it directly in the row's tracking cell (visible even with
        # the popup open), which an unscoped search would also match, causing
        # Playwright's strict mode to refuse with "resolved to 2 elements".
        container = page.locator(PICKER_OPTION_SELECTOR).filter(has_text=template_text)
        try:
            # 5000ms covers both the popup animation and template render time;
            # returns as soon as the element is visible — no fixed pre-wait needed.
            await container.first.wait_for(timeout=5000)
        except PWTimeoutError:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'template_not_found', 'detail': f'picker opened but template {template_text!r} not found'}

        print(f"  [template_found] {chart_number} → {template_text!r}")

        if dry_run:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'dry_run_ok', 'detail': f'would click {template_text!r}'}

        # Alleypin picker options toggle on each click. When a template was
        # previously sent its inner div has border-gray-900 (highlighted);
        # clicking once de-selects it (border-gray-300). We must click again
        # to re-select before committing.
        inner_cls = await container.first.locator("div.inline-flex").get_attribute("class") or ""
        pre_highlighted = "border-gray-900" in inner_cls
        print(f"  [picker_state] {chart_number} pre_highlighted={pre_highlighted}")

        # Scroll the template option into view within the picker's own scrollable
        # container before clicking — Playwright's click() scrolls within the
        # page window but not within a custom overflow div.
        await container.first.scroll_into_view_if_needed()
        await container.first.click()
        await page.wait_for_timeout(400)

        if pre_highlighted:
            print(f"  [re-select] {chart_number} was pre-highlighted — clicking again to re-select")
            await container.first.scroll_into_view_if_needed()
            await container.first.click()
            await page.wait_for_timeout(400)

        # Clicking outside the modal commits the selection.
        await page.locator(SEARCH_INPUT_SELECTOR).click()
        await page.wait_for_timeout(1000)
        print(f"  [sent] {chart_number} clicked {template_text!r}")
        return {**base, 'status': 'sent', 'detail': f'clicked {template_text!r}'}

    except Exception as e:
        return {**base, 'status': 'error', 'detail': str(e)}


async def undo_one(page: Page, chart_number: str, dob_roc: str, name: str,
                    template_text: str, dry_run: bool) -> dict:
    """Remove a previously-applied preset-text tag from a patient's tracking
    history, identified by template text alone. We already know exactly
    which template was sent to this patient (it's recorded at send time), so
    there's no ambiguity to resolve — the same pasted history shows no two
    tags with identical text active at once.

    UNVERIFIED against the real Alleypin page — written from HTML the user
    pasted, not yet tested live. Validate carefully before trusting it.
    """
    base = {'chart_number': chart_number, 'name': name}
    try:
        row, reason = await _find_patient_row(page, chart_number, dob_roc, name)
        if row is None:
            return {**base, 'status': 'not_found', 'detail': reason}

        clickable = row.locator(TRACKING_TRIGGER_SELECTOR)
        await clickable.click()
        await page.wait_for_timeout(600)

        # has_text does a substring match on the entry's whole text content,
        # not an exact match on one span — robust to however the timestamp
        # actually renders (own span, or appended after the name in the same one).
        entry = page.locator(TAG_ENTRY_SELECTOR).filter(has_text=template_text)
        try:
            await entry.first.wait_for(timeout=3000)
        except PWTimeoutError:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'tag_not_found', 'detail': f'no tag matching {template_text!r} found in modal'}

        remove_icon = entry.first.locator('svg')
        if dry_run:
            await page.keyboard.press("Escape")
            return {**base, 'status': 'dry_run_ok', 'detail': f'would remove {template_text!r}'}

        await remove_icon.click()
        await page.wait_for_timeout(300)
        # Same commit pattern as send_one() — clicking outside persists the change.
        await page.locator(SEARCH_INPUT_SELECTOR).click()
        await page.wait_for_timeout(800)
        return {**base, 'status': 'sent', 'detail': f'removed {template_text!r}'}

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
        _bring_browser_to_front()

        for t in targets:
            dob_roc = t.get('dob_roc') or to_roc_slash_date(t['dob'])
            result = await send_one(page, t['chart_number'], dob_roc, t.get('name', ''), t['template'], dry_run)
            results.append(result)
            print(f"  [{result['status']}] {result['chart_number']} {result.get('name', '')}: {result['detail']}")
            if on_result:
                on_result(result)

        # The commit for each patient relies on the next patient's search
        # filling the input and pressing Enter. The last patient has no
        # subsequent search, so do a dummy submit to finalise its commit.
        try:
            search = page.locator(SEARCH_INPUT_SELECTOR)
            await search.click()
            await search.fill("")
            await search.press("Enter")
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    return results


async def run_undo(target: dict, dry_run: bool) -> dict:
    """Single-patient counterpart to run_batch(), for undo_one(). target:
    {'chart_number', 'dob_roc' or 'dob' (date), 'name', 'template'}."""
    async with async_playwright() as p:
        page = await _get_page(p)
        await _navigate_if_needed(page)
        await _ensure_logged_in(page)
        _bring_browser_to_front()

        dob_roc = target.get('dob_roc') or to_roc_slash_date(target['dob'])
        result = await undo_one(
            page, target['chart_number'], dob_roc, target.get('name', ''),
            target['template'], dry_run,
        )
        print(f"  [undo:{result['status']}] {result['chart_number']} {result.get('name', '')}: {result['detail']}")
        try:
            search = page.locator(SEARCH_INPUT_SELECTOR)
            await search.click()
            await search.fill("")
            await search.press("Enter")
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        return result
