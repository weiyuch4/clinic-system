"""
Review Automation — post-visit satisfaction collection via LINE.

Flow:
  1. Staff sends a review invite (LINE push) to a bound patient.
  2. Patient opens /review/{token} → taps a star rating (1–5).
  3. Rating ≥ threshold  → patient is shown a Google Maps button.
     Rating < threshold  → patient is shown a private feedback form.
  4. Private feedback stored in review_feedback; Google Maps clicks tracked.

Tables:
  review_settings   — per-clinic config
  review_requests   — one row per sent invite (tracks status + rating)
  review_feedback   — private feedback text from unhappy patients
"""
import secrets
from datetime import datetime, timedelta, timezone

import requests

from db import _conn

_TW = timezone(timedelta(hours=8))

_DEFAULT_MESSAGE = (
    "感謝您今天蒞臨本診所！\n\n"
    "您的意見對我們非常重要，請花一點時間為我們評分，謝謝！\n\n"
    "{review_url}"
)

# ── Tables ────────────────────────────────────────────────────────────────────

_CREATE_REVIEW_SETTINGS = """
    CREATE TABLE IF NOT EXISTS review_settings (
        clinic_id         INTEGER PRIMARY KEY,
        enabled           INTEGER NOT NULL DEFAULT 0,
        google_maps_url   TEXT    NOT NULL DEFAULT '',
        threshold         INTEGER NOT NULL DEFAULT 4,
        message_template  TEXT    NOT NULL DEFAULT '',
        base_url          TEXT    NOT NULL DEFAULT '',
        updated_at        TEXT    NOT NULL DEFAULT ''
    )
"""

_CREATE_REVIEW_REQUESTS = """
    CREATE TABLE IF NOT EXISTS review_requests (
        id            SERIAL PRIMARY KEY,
        clinic_id     INTEGER NOT NULL DEFAULT 1,
        chart_number  TEXT    NOT NULL DEFAULT '',
        line_user_id  TEXT    NOT NULL DEFAULT '',
        patient_name  TEXT    NOT NULL DEFAULT '',
        token         TEXT    NOT NULL UNIQUE,
        status        TEXT    NOT NULL DEFAULT 'sent',
        rating        INTEGER NOT NULL DEFAULT 0,
        sent_at       TEXT    NOT NULL,
        responded_at  TEXT    NOT NULL DEFAULT ''
    )
"""

_CREATE_REVIEW_FEEDBACK = """
    CREATE TABLE IF NOT EXISTS review_feedback (
        id           SERIAL PRIMARY KEY,
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        request_id   INTEGER NOT NULL REFERENCES review_requests(id) ON DELETE CASCADE,
        content      TEXT    NOT NULL,
        submitted_at TEXT    NOT NULL
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_REVIEW_SETTINGS)
            cur.execute(_CREATE_REVIEW_REQUESTS)
            cur.execute(_CREATE_REVIEW_FEEDBACK)


# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings(clinic_id: int) -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM review_settings WHERE clinic_id=%s", (clinic_id,)
            )
            row = cur.fetchone()
    if not row:
        return {
            "clinic_id": clinic_id,
            "enabled": False,
            "google_maps_url": "",
            "threshold": 4,
            "message_template": _DEFAULT_MESSAGE,
            "base_url": "",
            "updated_at": "",
        }
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    if not d.get("message_template"):
        d["message_template"] = _DEFAULT_MESSAGE
    return d


def save_settings(
    clinic_id: int,
    *,
    enabled: bool | None = None,
    google_maps_url: str | None = None,
    threshold: int | None = None,
    message_template: str | None = None,
    base_url: str | None = None,
) -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT clinic_id FROM review_settings WHERE clinic_id=%s", (clinic_id,)
            )
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(
                    "INSERT INTO review_settings (clinic_id, message_template, updated_at) "
                    "VALUES (%s, %s, %s)",
                    (clinic_id, _DEFAULT_MESSAGE, now),
                )
            fields: list[tuple] = [("updated_at", now)]
            if enabled is not None:
                fields.append(("enabled", 1 if enabled else 0))
            if google_maps_url is not None:
                fields.append(("google_maps_url", google_maps_url[:500]))
            if threshold is not None:
                fields.append(("threshold", max(1, min(5, int(threshold)))))
            if message_template is not None:
                fields.append(("message_template", message_template[:2000]))
            if base_url is not None:
                fields.append(("base_url", base_url.rstrip("/")))

            set_clause = ", ".join(f"{f} = %s" for f, _ in fields)
            values = [v for _, v in fields] + [clinic_id]
            cur.execute(
                f"UPDATE review_settings SET {set_clause} WHERE clinic_id=%s", values
            )


# ── Send invite ───────────────────────────────────────────────────────────────

def send_review_invite(
    clinic_id: int,
    chart_number: str,
    line_user_id: str,
    patient_name: str,
    access_token: str,
    base_url: str,
    message_template: str,
) -> dict:
    """Create a review request and push the LINE invite. Returns {ok, request_id}."""
    token = secrets.token_urlsafe(24)
    review_url = f"{base_url}/review/{token}"
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO review_requests
                   (clinic_id, chart_number, line_user_id, patient_name, token, status, sent_at)
                   VALUES (%s, %s, %s, %s, %s, 'sent', %s) RETURNING id""",
                (clinic_id, chart_number, line_user_id, patient_name, token, now),
            )
            req_id = cur.fetchone()["id"]

    text = message_template.replace("{review_url}", review_url)
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"to": line_user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        if r.status_code != 200:
            _set_request_status(req_id, "failed")
            return {"ok": False, "detail": f"LINE error {r.status_code}"}
    except Exception as e:
        _set_request_status(req_id, "failed")
        return {"ok": False, "detail": str(e)}

    return {"ok": True, "request_id": req_id}


def _set_request_status(req_id: int, status: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE review_requests SET status=%s WHERE id=%s", (status, req_id)
            )


# ── Receive rating ────────────────────────────────────────────────────────────

def get_request_by_token(token: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT rr.*, rs.threshold, rs.google_maps_url, rs.clinic_id as _cid
                   FROM review_requests rr
                   JOIN review_settings rs ON rs.clinic_id = rr.clinic_id
                   WHERE rr.token = %s""",
                (token,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def submit_rating(token: str, rating: int) -> dict:
    """
    Record the patient's rating. Returns {ok, action, google_maps_url}.
    action is 'maps' (redirect to Google) or 'feedback' (show private form).
    """
    req = get_request_by_token(token)
    if not req:
        return {"ok": False, "detail": "無效連結"}
    if req["status"] not in ("sent",):
        return {"ok": False, "detail": "already_responded"}

    rating = max(1, min(5, int(rating)))
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    threshold = req.get("threshold", 4)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE review_requests SET rating=%s, responded_at=%s, status='responded' WHERE token=%s",
                (rating, now, token),
            )

    if rating >= threshold:
        return {"ok": True, "action": "maps", "google_maps_url": req.get("google_maps_url", "")}
    else:
        return {"ok": True, "action": "feedback"}


def submit_feedback(token: str, content: str) -> bool:
    """Store private feedback from a low-rating patient."""
    req = get_request_by_token(token)
    if not req:
        return False
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO review_feedback (clinic_id, request_id, content, submitted_at)
                   VALUES (%s, %s, %s, %s)""",
                (req["clinic_id"], req["id"], content[:5000], now),
            )
            cur.execute(
                "UPDATE review_requests SET status='feedback_submitted' WHERE token=%s",
                (token,),
            )
    return True


# ── Admin queries ─────────────────────────────────────────────────────────────

def list_requests(clinic_id: int, limit: int = 100) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chart_number, patient_name, status, rating, sent_at, responded_at
                   FROM review_requests WHERE clinic_id=%s
                   ORDER BY id DESC LIMIT %s""",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def list_feedback(clinic_id: int, limit: int = 100) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT rf.id, rf.content, rf.submitted_at,
                          rr.chart_number, rr.patient_name, rr.rating
                   FROM review_feedback rf
                   JOIN review_requests rr ON rr.id = rf.request_id
                   WHERE rf.clinic_id=%s
                   ORDER BY rf.id DESC LIMIT %s""",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def get_stats(clinic_id: int) -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT
                     COUNT(*) AS total,
                     COUNT(*) FILTER (WHERE status='responded' OR status='feedback_submitted') AS responded,
                     ROUND(AVG(rating) FILTER (WHERE rating > 0)::numeric, 1) AS avg_rating,
                     COUNT(*) FILTER (WHERE rating >= 4) AS positive,
                     COUNT(*) FILTER (WHERE rating > 0 AND rating < 4) AS negative
                   FROM review_requests WHERE clinic_id=%s""",
                (clinic_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else {}
