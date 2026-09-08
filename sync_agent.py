"""
sync_agent.py — Clinic PC sync agent for Phase 3.

Reads follow-up patient data from local 燿聖 DBF files and pushes it to the
cloud app every time files change (watchdog) and every 30 minutes (fallback).

Usage:
    venv\Scripts\python sync_agent.py

Configure via .env:
    CLOUD_URL   = https://web-production-9bcca.up.railway.app
    SYNC_TOKEN  = <shared secret>
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import date, datetime

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────

CLOUD_URL   = os.environ.get("CLOUD_URL", "").rstrip("/")
SYNC_TOKEN  = os.environ.get("SYNC_TOKEN", "")
SYNC_INTERVAL = 30 * 60   # full sync every 30 minutes
DEBOUNCE_SEC  = 5          # wait this long after last file change before syncing

if not CLOUD_URL:
    sys.exit("ERROR: CLOUD_URL not set in .env")
if not SYNC_TOKEN:
    sys.exit("ERROR: SYNC_TOKEN not set in .env")

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("sync_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── DB pool ───────────────────────────────────────────────────────────────────

_db_pool_ready = False


def _ensure_db_pool() -> bool:
    """Initialize DB pool if not done yet. Returns True when ready."""
    global _db_pool_ready
    if _db_pool_ready:
        return True
    try:
        import db as _db
        import contacts as _contacts
        _db.init_pool()
        _contacts.init()
        _db_pool_ready = True
        log.info("DB pool initialized (lazy retry)")
        return True
    except Exception as exc:
        log.warning("DB pool init failed: %s", exc)
        return False


# ── Sync logic ────────────────────────────────────────────────────────────────

def _entry_to_dict(entry, category: str) -> dict:
    def _d(d):
        return d.isoformat() if d else None
    return {
        "chart_number":  entry.patient.chart_number,
        "category":      category,
        "name":          entry.patient.name,
        "birth_date":    _d(entry.patient.birth_date),
        "disease_name":  entry.disease_name,
        "due_date":      _d(entry.due_date),
        "days_overdue":  entry.days_overdue,
        "mspt_stage":    entry.mspt_stage,
        "contact_reason": entry.contact_reason,
        "last_visit_date": _d(entry.last_visit_date),
        "phone":         entry.phone,
        "mobile":        entry.mobile,
        "synced_at":     datetime.now().isoformat(timespec="seconds"),
    }


def do_sync() -> None:
    try:
        from database import get_daily_report
        report = get_daily_report(date.today())
    except Exception as exc:
        log.error("Failed to read DBF data: %s", exc)
        return

    candidates = []
    for entry in report.chronic_prescriptions:
        candidates.append(_entry_to_dict(entry, "慢簽"))
    for entry in report.mspt_followups:
        candidates.append(_entry_to_dict(entry, "代謝症候群"))
    for entry in report.mspt_inactive:
        candidates.append(_entry_to_dict(entry, "代謝症候群_inactive"))
    for entry in report.hep_followups:
        candidates.append(_entry_to_dict(entry, "B肝"))
    for entry in report.hep_inactive:
        candidates.append(_entry_to_dict(entry, "B肝_inactive"))
    for entry in report.ckd_followups:
        candidates.append(_entry_to_dict(entry, "慢性腎臟病"))
    for entry in report.ckd_inactive:
        candidates.append(_entry_to_dict(entry, "慢性腎臟病_inactive"))

    payload = {"clinic_id": 1, "candidates": candidates}
    try:
        resp = requests.post(
            f"{CLOUD_URL}/api/sync/push",
            json=payload,
            headers={"X-Sync-Token": SYNC_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        log.info("Synced %d candidates to cloud", len(candidates))
    except Exception as exc:
        log.error("Failed to push to cloud: %s", exc)

    # Blood pending sync (reads IC + BIO files, writes result JSONB to Supabase)
    try:
        if _ensure_db_pool():
            import database as _db
            import lab_results as _lab
            import contacts as _contacts
            days = _db.get_blood_draw_patients(date.today())
            for day in days:
                draw_d = date.fromisoformat(day['date'])
                for p in day['patients']:
                    found, result_date = _lab.has_results_since(p['nat_id'], draw_d)
                    p['results_back'] = found
                    p['results_date'] = result_date
            _contacts.upsert_synced_blood_pending(days)
            log.info("Synced blood pending (%d days)", len(days))
    except Exception as exc:
        log.error("Blood pending sync failed: %s", exc)


# ── File watcher ──────────────────────────────────────────────────────────────

_debounce_timer: threading.Timer | None = None
_debounce_lock  = threading.Lock()


def _on_file_change(event=None) -> None:
    global _debounce_timer
    with _debounce_lock:
        if _debounce_timer:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(DEBOUNCE_SEC, _debounced_sync)
        _debounce_timer.daemon = True
        _debounce_timer.start()


def _debounced_sync() -> None:
    log.info("File change detected, syncing...")
    do_sync()


def _start_watcher() -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        import config

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):  _on_file_change(event)
            def on_created(self,  event):  _on_file_change(event)

        handler = _Handler()

        observer = Observer()
        observer.schedule(handler, path=config.IC_DATA_PATH, recursive=False)
        # Also watch BIO/lab result files so cloud updates within 5s when results arrive
        zz_dir = getattr(config, 'ZZ_DIR', None)
        if zz_dir and os.path.isdir(zz_dir):
            observer.schedule(handler, path=zz_dir, recursive=False)
        observer.daemon = True
        observer.start()
        log.info("Watching for file changes in: %s", config.IC_DATA_PATH)
        if zz_dir and os.path.isdir(zz_dir):
            log.info("Watching for lab result changes in: %s", zz_dir)
    except Exception as exc:
        log.warning("File watcher could not start (%s) — relying on 30-min poll only", exc)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Sync agent started. Cloud URL: %s", CLOUD_URL)

    # DB pool needed for blood-pending sync (reads/writes Supabase directly)
    _ensure_db_pool()

    _start_watcher()

    # Initial sync on startup
    do_sync()

    # 30-minute fallback loop
    while True:
        time.sleep(SYNC_INTERVAL)
        log.info("Scheduled full sync")
        do_sync()
