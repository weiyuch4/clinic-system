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
    for entry in report.hep_followups:
        candidates.append(_entry_to_dict(entry, "B肝"))
    for entry in report.ckd_followups:
        candidates.append(_entry_to_dict(entry, "慢性腎臟病"))

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

        watch_path = config.IC_DATA_PATH

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):  _on_file_change(event)
            def on_created(self,  event):  _on_file_change(event)

        observer = Observer()
        observer.schedule(_Handler(), path=watch_path, recursive=False)
        observer.daemon = True
        observer.start()
        log.info("Watching for file changes in: %s", watch_path)
    except Exception as exc:
        log.warning("File watcher could not start (%s) — relying on 30-min poll only", exc)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Sync agent started. Cloud URL: %s", CLOUD_URL)

    _start_watcher()

    # Initial sync on startup
    do_sync()

    # 30-minute fallback loop
    while True:
        time.sleep(SYNC_INTERVAL)
        log.info("Scheduled full sync")
        do_sync()
