"""
LINE Messaging API integration — direct OA binding and push messages.
Replaces the browser-automation AlleyPin path over time as patients bind.

Tables created here:
  line_bindings  — chart_number ↔ line_user_id mappings
  line_settings  — per-clinic LINE OA credentials
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import requests

from db import _conn

_DEFAULT_TEMPLATES: dict[str, str] = {
    "慢簽": "您好，您的慢性病連續處方箋即將到期，請儘快回診領取新的處方箋。感謝您的配合！",
    "代謝症候群": "您好，您的代謝症候群追蹤時間到了，請回診接受健康評估。感謝您的配合！",
    "B肝": "您好，您的B型肝炎追蹤時間到了，請回診接受檢查。感謝您的配合！",
}

_TW = timezone(timedelta(hours=8))
_LINE_API = "https://api.line.me/v2/bot"

_CREATE_LINE_BINDINGS = """
    CREATE TABLE IF NOT EXISTS line_bindings (
        id              SERIAL PRIMARY KEY,
        chart_number    TEXT NOT NULL,
        line_user_id    TEXT NOT NULL,
        display_name    TEXT NOT NULL DEFAULT '',
        bound_at        TEXT NOT NULL,
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        UNIQUE (chart_number, clinic_id),
        UNIQUE (line_user_id, clinic_id)
    )
"""

_CREATE_LINE_SETTINGS = """
    CREATE TABLE IF NOT EXISTS line_settings (
        clinic_id               INTEGER PRIMARY KEY,
        channel_access_token    TEXT NOT NULL DEFAULT '',
        channel_secret          TEXT NOT NULL DEFAULT '',
        liff_id                 TEXT NOT NULL DEFAULT '',
        is_active               INTEGER NOT NULL DEFAULT 0,
        updated_at              TEXT NOT NULL DEFAULT ''
    )
"""

_CREATE_LINE_AUDIT_LOG = """
    CREATE TABLE IF NOT EXISTS line_audit_log (
        id           SERIAL PRIMARY KEY,
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        action       TEXT NOT NULL,
        chart_number TEXT NOT NULL DEFAULT '',
        actor        TEXT NOT NULL DEFAULT '',
        detail       TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_LINE_BINDINGS)
            cur.execute(_CREATE_LINE_SETTINGS)
            cur.execute(_CREATE_LINE_AUDIT_LOG)
            # Phase 2: add message_templates column (safe on existing installs)
            cur.execute(
                "ALTER TABLE line_settings ADD COLUMN IF NOT EXISTS "
                "message_templates TEXT NOT NULL DEFAULT '{}'"
            )


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_audit(
    clinic_id: int,
    action: str,
    chart_number: str = "",
    actor: str = "system",
    detail: str = "",
) -> None:
    """Write one audit entry. Failures are swallowed — never let logging break callers."""
    try:
        now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO line_audit_log (clinic_id, action, chart_number, actor, detail, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (clinic_id, action, chart_number, actor, detail[:500], now),
                )
    except Exception:
        pass


def get_audit_log(clinic_id: int = 1, limit: int = 200) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action, chart_number, actor, detail, created_at "
                "FROM line_audit_log WHERE clinic_id = %s "
                "ORDER BY id DESC LIMIT %s",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings(clinic_id: int = 1) -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_access_token, channel_secret, liff_id, is_active, message_templates "
                "FROM line_settings WHERE clinic_id = %s",
                (clinic_id,),
            )
            row = cur.fetchone()
    if row:
        return dict(row)
    return {
        "channel_access_token": "", "channel_secret": "", "liff_id": "",
        "is_active": 0, "message_templates": "{}",
    }


def get_message_templates(clinic_id: int = 1) -> dict[str, str]:
    """Return per-category message text, merging stored overrides onto defaults."""
    s = get_settings(clinic_id)
    try:
        stored = json.loads(s.get("message_templates") or "{}")
    except Exception:
        stored = {}
    result = dict(_DEFAULT_TEMPLATES)
    result.update({k: v for k, v in stored.items() if v})
    return result


def save_message_templates(clinic_id: int, templates: dict[str, str]) -> None:
    raw = json.dumps(templates, ensure_ascii=False)
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_settings (clinic_id, message_templates, updated_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (clinic_id) DO UPDATE SET
                       message_templates = EXCLUDED.message_templates,
                       updated_at = EXCLUDED.updated_at""",
                (clinic_id, raw, now),
            )


def save_settings(
    clinic_id: int,
    token: str,
    secret: str,
    liff_id: str,
    is_active: bool,
    actor: str = "system",
) -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_settings
                       (clinic_id, channel_access_token, channel_secret, liff_id, is_active, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (clinic_id) DO UPDATE SET
                       channel_access_token = CASE WHEN EXCLUDED.channel_access_token != '' THEN EXCLUDED.channel_access_token ELSE line_settings.channel_access_token END,
                       channel_secret       = CASE WHEN EXCLUDED.channel_secret != '' THEN EXCLUDED.channel_secret ELSE line_settings.channel_secret END,
                       liff_id              = EXCLUDED.liff_id,
                       is_active            = EXCLUDED.is_active,
                       updated_at           = EXCLUDED.updated_at""",
                (clinic_id, token, secret, liff_id, 1 if is_active else 0, now),
            )
    changed = []
    if token:
        changed.append("token")
    if secret:
        changed.append("secret")
    if liff_id is not None:
        changed.append("liff_id")
    changed.append(f"is_active={'1' if is_active else '0'}")
    log_audit(clinic_id, "settings_change", "", actor, ",".join(changed))


# ── Bindings ──────────────────────────────────────────────────────────────────

def get_binding(chart_number: str, clinic_id: int = 1) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, line_user_id, display_name, bound_at "
                "FROM line_bindings WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_line_user_id(chart_number: str, clinic_id: int = 1) -> str | None:
    b = get_binding(chart_number, clinic_id)
    return b["line_user_id"] if b else None


def bind_patient(
    chart_number: str,
    line_user_id: str,
    display_name: str = "",
    clinic_id: int = 1,
    actor: str = "system",
) -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_bindings
                       (chart_number, line_user_id, display_name, bound_at, clinic_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (chart_number, clinic_id) DO UPDATE SET
                       line_user_id = EXCLUDED.line_user_id,
                       display_name = EXCLUDED.display_name,
                       bound_at     = EXCLUDED.bound_at""",
                (chart_number, line_user_id, display_name, now, clinic_id),
            )
    log_audit(clinic_id, "bind", chart_number, actor, f"display_name={display_name}")


def unbind_patient(chart_number: str, clinic_id: int = 1, actor: str = "system") -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM line_bindings WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )
            deleted = cur.rowcount > 0
    if deleted:
        log_audit(clinic_id, "unbind", chart_number, actor, "")
    return deleted


def get_all_bindings(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, line_user_id, display_name, bound_at "
                "FROM line_bindings WHERE clinic_id = %s ORDER BY bound_at DESC",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_binding_count(clinic_id: int = 1) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM line_bindings WHERE clinic_id = %s", (clinic_id,)
            )
            return cur.fetchone()[0]


def bulk_import_bindings(
    rows: list[dict], clinic_id: int = 1, actor: str = "system"
) -> dict:
    """rows: list of {chart_number, line_user_id, display_name (optional)}
    Returns {imported, skipped, errors}."""
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    imported = skipped = 0
    errors: list[dict] = []
    imported_cns: list[str] = []
    with _conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cn = (r.get("chart_number") or "").strip()
                uid = (r.get("line_user_id") or "").strip()
                dn = (r.get("display_name") or "").strip()
                if not cn or not uid:
                    skipped += 1
                    continue
                try:
                    cur.execute("SAVEPOINT sp_row")
                    cur.execute(
                        """INSERT INTO line_bindings
                               (chart_number, line_user_id, display_name, bound_at, clinic_id)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (chart_number, clinic_id) DO UPDATE SET
                               line_user_id = EXCLUDED.line_user_id,
                               display_name = EXCLUDED.display_name,
                               bound_at     = EXCLUDED.bound_at""",
                        (cn, uid, dn, now, clinic_id),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_row")
                    imported += 1
                    imported_cns.append(cn)
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_row")
                    errors.append({"chart_number": cn, "error": "重複或格式錯誤"})
    if imported_cns:
        log_audit(
            clinic_id,
            "bulk_import",
            "",
            actor,
            f"imported={imported} charts={','.join(imported_cns[:20])}",
        )
    return {"imported": imported, "skipped": skipped, "errors": errors}


# ── LINE Messaging API ────────────────────────────────────────────────────────

def _push(token: str, user_id: str, messages: list[dict]) -> dict:
    try:
        resp = requests.post(
            f"{_LINE_API}/message/push",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": user_id, "messages": messages},
            timeout=10,
        )
        return {"status": resp.status_code, "body": resp.text}
    except Exception as e:
        return {"status": 0, "body": str(e)}


def push_text(chart_number: str, text: str, clinic_id: int = 1) -> dict:
    """Push a plain-text message to a bound patient."""
    settings = get_settings(clinic_id)
    token = settings.get("channel_access_token", "")
    if not token:
        return {"status": "error", "detail": "LINE尚未設定憑證"}
    uid = get_line_user_id(chart_number, clinic_id)
    if not uid:
        return {"status": "not_bound", "detail": "此病患尚未綁定LINE"}
    result = _push(token, uid, [{"type": "text", "text": text}])
    return result


def push_category_message(
    chart_number: str,
    category: str,
    clinic_id: int = 1,
    actor: str = "system",
) -> dict:
    """Push the clinic-configured message for a follow-up category to a bound patient.
    Returns the raw _push result dict ({status: int, body: str})."""
    s = get_settings(clinic_id)
    token = (s.get("channel_access_token") or "").strip()
    if not token:
        return {"status": 0, "body": "no_token"}
    uid = get_line_user_id(chart_number, clinic_id)
    if not uid:
        return {"status": 0, "body": "not_bound"}
    templates = get_message_templates(clinic_id)
    text = templates.get(category, "")
    if not text:
        return {"status": 0, "body": "no_template"}
    result = _push(token, uid, [{"type": "text", "text": text}])
    log_audit(
        clinic_id,
        "push",
        chart_number,
        actor,
        f"category={category} status={result.get('status')}",
    )
    return result


def broadcast_bind_invite(clinic_id: int = 1) -> dict:
    """Send binding invitation to ALL existing LINE followers (from line_bindings).
    Also sends to any user who followed but hasn't bound yet — but we only know
    about users who have already sent us a message, not silent followers."""
    settings = get_settings(clinic_id)
    token = settings.get("channel_access_token", "")
    liff_id = settings.get("liff_id", "")
    if not token:
        return {"status": "error", "detail": "LINE尚未設定憑證"}
    bind_url = f"https://liff.line.me/{liff_id}" if liff_id else ""
    msg_text = (
        "您好！請點擊以下連結，輸入您的病歷號碼，完成LINE身份綁定，"
        "以便接收診所健康提醒訊息。\n\n"
        + (bind_url if bind_url else "（請聯絡診所取得綁定連結）")
    )
    bindings = get_all_bindings(clinic_id)
    sent = failed = 0
    for b in bindings:
        r = _push(token, b["line_user_id"], [{"type": "text", "text": msg_text}])
        if r["status"] == 200:
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed}


# ── Webhook ───────────────────────────────────────────────────────────────────

def verify_signature(body_bytes: bytes, signature: str, channel_secret: str) -> bool:
    expected = hmac.new(
        channel_secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).digest()
    return hmac.compare_digest(base64.b64encode(expected).decode(), signature)


def process_webhook(body: dict, clinic_id: int = 1) -> None:
    """Handle LINE webhook events (follow, unfollow, message)."""
    settings = get_settings(clinic_id)
    token = settings.get("channel_access_token", "")
    liff_id = settings.get("liff_id", "")

    for event in body.get("events", []):
        etype = event.get("type")
        user_id = event.get("source", {}).get("userId", "")
        if not user_id:
            continue

        if etype == "follow" and token:
            # New follower — send binding invite
            bind_url = f"https://liff.line.me/{liff_id}" if liff_id else ""
            msg = (
                "歡迎加入！請點擊以下連結，輸入您的病歷號碼，完成身份綁定，"
                "以便接收診所健康提醒。"
            )
            messages: list[dict] = [{"type": "text", "text": msg}]
            if bind_url:
                messages.append({"type": "text", "text": bind_url})
            _push(token, user_id, messages)

        elif etype == "unfollow":
            # Patient unfollowed — remove binding
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT chart_number FROM line_bindings "
                        "WHERE line_user_id = %s AND clinic_id = %s",
                        (user_id, clinic_id),
                    )
                    row = cur.fetchone()
                    chart = row["chart_number"] if row else ""
                    cur.execute(
                        "DELETE FROM line_bindings WHERE line_user_id = %s AND clinic_id = %s",
                        (user_id, clinic_id),
                    )
            if chart:
                log_audit(clinic_id, "webhook_unfollow", chart, "patient", f"line_user_id={user_id[:8]}…")
