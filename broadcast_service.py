"""
Broadcast messaging — send LINE messages to all bound patients at once.

Tables:
  broadcasts            — broadcast records (definition + stats)
  broadcast_recipients  — per-recipient send status (populated at send time)
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from db import _conn
import line_service

_TW = timezone(timedelta(hours=8))
_LINE_API = "https://api.line.me/v2/bot"
logger = logging.getLogger(__name__)

_CREATE_BROADCASTS = """
    CREATE TABLE IF NOT EXISTS broadcasts (
        id               SERIAL PRIMARY KEY,
        clinic_id        INTEGER NOT NULL DEFAULT 1,
        name             TEXT    NOT NULL,
        content          TEXT    NOT NULL,
        audience_filter  TEXT    NOT NULL DEFAULT 'all',
        status           TEXT    NOT NULL DEFAULT 'draft',
        scheduled_at     TEXT    NOT NULL DEFAULT '',
        sent_at          TEXT    NOT NULL DEFAULT '',
        recipient_count  INTEGER NOT NULL DEFAULT 0,
        sent_count       INTEGER NOT NULL DEFAULT 0,
        failed_count     INTEGER NOT NULL DEFAULT 0,
        created_by       TEXT    NOT NULL DEFAULT '',
        created_at       TEXT    NOT NULL
    )
"""

_CREATE_BROADCAST_RECIPIENTS = """
    CREATE TABLE IF NOT EXISTS broadcast_recipients (
        id               SERIAL PRIMARY KEY,
        broadcast_id     INTEGER NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
        clinic_id        INTEGER NOT NULL DEFAULT 1,
        chart_number     TEXT    NOT NULL,
        line_user_id     TEXT    NOT NULL,
        status           TEXT    NOT NULL DEFAULT 'pending',
        sent_at          TEXT    NOT NULL DEFAULT '',
        error_detail     TEXT    NOT NULL DEFAULT ''
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_BROADCASTS)
            cur.execute(_CREATE_BROADCAST_RECIPIENTS)


# ── LINE multicast ────────────────────────────────────────────────────────────

def _multicast(token: str, user_ids: list[str], messages: list[dict]) -> dict:
    """POST to LINE multicast API (≤500 user_ids per call)."""
    try:
        resp = requests.post(
            f"{_LINE_API}/message/multicast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": user_ids, "messages": messages},
            timeout=15,
        )
        return {"status": resp.status_code, "body": resp.text}
    except Exception as e:
        return {"status": 0, "body": str(e)}


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_broadcast(
    clinic_id: int,
    name: str,
    content: str,
    audience_filter: str = "all",
    scheduled_at: str = "",
    created_by: str = "",
) -> int:
    """Insert a broadcast record. Returns new broadcast id."""
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    status = "scheduled" if scheduled_at else "draft"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO broadcasts
                   (clinic_id, name, content, audience_filter, status, scheduled_at, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (clinic_id, name[:200], content[:5000], audience_filter, status,
                 scheduled_at, created_by[:100], now),
            )
            return cur.fetchone()["id"]


def list_broadcasts(clinic_id: int, limit: int = 100) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, audience_filter, status, scheduled_at, sent_at,
                          recipient_count, sent_count, failed_count, created_by, created_at
                   FROM broadcasts WHERE clinic_id = %s
                   ORDER BY id DESC LIMIT %s""",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def get_broadcast(broadcast_id: int, clinic_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, content, audience_filter, status, scheduled_at, sent_at,
                          recipient_count, sent_count, failed_count, created_by, created_at
                   FROM broadcasts WHERE id = %s AND clinic_id = %s""",
                (broadcast_id, clinic_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_recipients(broadcast_id: int, clinic_id: int, limit: int = 500) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, line_user_id, status, sent_at, error_detail
                   FROM broadcast_recipients
                   WHERE broadcast_id = %s AND clinic_id = %s
                   ORDER BY id LIMIT %s""",
                (broadcast_id, clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def cancel_broadcast(broadcast_id: int, clinic_id: int) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE broadcasts SET status = 'cancelled'
                   WHERE id = %s AND clinic_id = %s AND status IN ('draft', 'scheduled')""",
                (broadcast_id, clinic_id),
            )
            return cur.rowcount > 0


# ── Send logic ────────────────────────────────────────────────────────────────

def _populate_recipients(broadcast_id: int, clinic_id: int) -> int:
    """Snapshot current line_bindings into broadcast_recipients. Returns count."""
    bindings = line_service.get_all_bindings(clinic_id)
    if not bindings:
        return 0
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM broadcast_recipients WHERE broadcast_id = %s AND clinic_id = %s",
                (broadcast_id, clinic_id),
            )
            for b in bindings:
                cur.execute(
                    """INSERT INTO broadcast_recipients
                       (broadcast_id, clinic_id, chart_number, line_user_id, status)
                       VALUES (%s, %s, %s, %s, 'pending')""",
                    (broadcast_id, clinic_id, b["chart_number"], b["line_user_id"]),
                )
            cur.execute(
                "UPDATE broadcasts SET recipient_count = %s WHERE id = %s",
                (len(bindings), broadcast_id),
            )
    return len(bindings)


def execute_broadcast(broadcast_id: int, clinic_id: int) -> dict:
    """
    Send the broadcast to all bound patients. Safe to call from a background thread.
    Returns {ok, sent, failed}.
    """
    bc = get_broadcast(broadcast_id, clinic_id)
    if not bc or bc["status"] not in ("draft", "scheduled"):
        return {"ok": False, "detail": "invalid_status"}

    s = line_service.get_settings(clinic_id)
    token = (s.get("channel_access_token") or "").strip()
    if not token:
        _set_status(broadcast_id, clinic_id, "failed")
        return {"ok": False, "detail": "no_token"}

    # Atomically claim the send slot — prevents double-send races
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE broadcasts SET status = 'sending'
                   WHERE id = %s AND clinic_id = %s AND status IN ('draft', 'scheduled')""",
                (broadcast_id, clinic_id),
            )
            if cur.rowcount == 0:
                return {"ok": False, "detail": "already_sending"}

    count = _populate_recipients(broadcast_id, clinic_id)
    if count == 0:
        _set_status(broadcast_id, clinic_id, "failed")
        return {"ok": False, "detail": "no_recipients"}

    messages = [{"type": "text", "text": bc["content"]}]

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, line_user_id FROM broadcast_recipients "
                "WHERE broadcast_id = %s AND clinic_id = %s AND status = 'pending'",
                (broadcast_id, clinic_id),
            )
            rows = list(cur.fetchall())

    sent_count = failed_count = 0
    for i in range(0, len(rows), 500):
        # Check for cancellation signal between chunks
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM broadcasts WHERE id = %s AND clinic_id = %s",
                    (broadcast_id, clinic_id),
                )
                row = cur.fetchone()
                if not row or row["status"] == "cancelling":
                    break

        chunk = rows[i:i + 500]
        user_ids = [r["line_user_id"] for r in chunk]
        rec_ids = [r["id"] for r in chunk]
        result = _multicast(token, user_ids, messages)
        now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")

        if result["status"] == 200:
            sent_count += len(chunk)
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE broadcast_recipients SET status = 'sent', sent_at = %s "
                        "WHERE id = ANY(%s)",
                        (now, rec_ids),
                    )
        else:
            failed_count += len(chunk)
            err = (result.get("body") or "")[:200]
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE broadcast_recipients SET status = 'failed', error_detail = %s "
                        "WHERE id = ANY(%s)",
                        (err, rec_ids),
                    )

        if i + 500 < len(rows):
            time.sleep(0.1)  # stay within LINE rate limits

    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    if sent_count > 0 and failed_count == 0:
        final_status = "sent"
    elif sent_count > 0:
        final_status = "partial"
    else:
        final_status = "failed"

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE broadcasts
                   SET status = %s, sent_at = %s, sent_count = %s, failed_count = %s
                   WHERE id = %s AND clinic_id = %s""",
                (final_status, now, sent_count, failed_count, broadcast_id, clinic_id),
            )

    return {"ok": True, "sent": sent_count, "failed": failed_count}


def _set_status(broadcast_id: int, clinic_id: int, status: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE broadcasts SET status = %s WHERE id = %s AND clinic_id = %s",
                (status, broadcast_id, clinic_id),
            )


# ── Scheduler tick ────────────────────────────────────────────────────────────

def tick_scheduled() -> None:
    """APScheduler job (every 1 min) — fires scheduled broadcasts past their send time."""
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, clinic_id FROM broadcasts
                       WHERE status = 'scheduled' AND scheduled_at != '' AND scheduled_at <= %s
                       LIMIT 10""",
                    (now,),
                )
                due = [(r["id"], r["clinic_id"]) for r in cur.fetchall()]
    except Exception as e:
        logger.error("broadcast tick query failed: %s", e)
        return

    for broadcast_id, clinic_id in due:
        try:
            execute_broadcast(broadcast_id, clinic_id)
        except Exception as e:
            logger.error("broadcast execute failed id=%s: %s", broadcast_id, e)
