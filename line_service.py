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
            # LINE Login channel ID — the LIFF access token's client_id must match it
            cur.execute(
                "ALTER TABLE line_settings ADD COLUMN IF NOT EXISTS "
                "login_channel_id TEXT NOT NULL DEFAULT ''"
            )
            # Setup situation chosen in the wizard: '' (not set) | 'new' | 'own' | 'vendor'
            cur.execute(
                "ALTER TABLE line_settings ADD COLUMN IF NOT EXISTS "
                "line_mode TEXT NOT NULL DEFAULT ''"
            )


# ── Clinic lookup (public LINE URLs carry the clinic slug) ────────────────────

def clinic_id_for_slug(slug: str) -> int | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM clinics WHERE slug = %s", (slug,))
            row = cur.fetchone()
    return row["id"] if row else None


def slug_for_clinic(clinic_id: int) -> str:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM clinics WHERE id = %s", (clinic_id,))
            row = cur.fetchone()
    return row["slug"] if row else ""


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
                "SELECT channel_access_token, channel_secret, liff_id, is_active, message_templates, "
                "login_channel_id, line_mode "
                "FROM line_settings WHERE clinic_id = %s",
                (clinic_id,),
            )
            row = cur.fetchone()
    if row:
        return dict(row)
    return {
        "channel_access_token": "", "channel_secret": "", "liff_id": "",
        "is_active": 0, "message_templates": "{}", "login_channel_id": "", "line_mode": "",
    }


def set_line_mode(clinic_id: int, mode: str, actor: str = "system") -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_settings (clinic_id, line_mode, updated_at) VALUES (%s, %s, %s)
                   ON CONFLICT (clinic_id) DO UPDATE SET line_mode = EXCLUDED.line_mode, updated_at = EXCLUDED.updated_at""",
                (clinic_id, mode, now),
            )
    log_audit(clinic_id, "settings_change", "", actor, f"line_mode={mode}")


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
    login_channel_id: str = "",
    line_mode: str = "",
    actor: str = "system",
) -> None:
    """Empty token/secret/login_channel_id/line_mode keep the stored value."""
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_settings
                       (clinic_id, channel_access_token, channel_secret, liff_id, is_active,
                        login_channel_id, line_mode, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (clinic_id) DO UPDATE SET
                       channel_access_token = CASE WHEN EXCLUDED.channel_access_token != '' THEN EXCLUDED.channel_access_token ELSE line_settings.channel_access_token END,
                       channel_secret       = CASE WHEN EXCLUDED.channel_secret != '' THEN EXCLUDED.channel_secret ELSE line_settings.channel_secret END,
                       login_channel_id     = CASE WHEN EXCLUDED.login_channel_id != '' THEN EXCLUDED.login_channel_id ELSE line_settings.login_channel_id END,
                       line_mode            = CASE WHEN EXCLUDED.line_mode != '' THEN EXCLUDED.line_mode ELSE line_settings.line_mode END,
                       liff_id              = EXCLUDED.liff_id,
                       is_active            = EXCLUDED.is_active,
                       updated_at           = EXCLUDED.updated_at""",
                (clinic_id, token, secret, liff_id, 1 if is_active else 0,
                 login_channel_id, line_mode, now),
            )
    changed = []
    if token:
        changed.append("token")
    if secret:
        changed.append("secret")
    if login_channel_id:
        changed.append("login_channel_id")
    if line_mode:
        changed.append(f"line_mode={line_mode}")
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
            # One LINE account maps to one chart: rebinding moves it instead of violating UNIQUE(line_user_id)
            cur.execute(
                "DELETE FROM line_bindings WHERE line_user_id = %s AND clinic_id = %s AND chart_number != %s",
                (line_user_id, clinic_id, chart_number),
            )
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


def patient_matches(chart_number: str, birth_date: str, clinic_id: int) -> bool:
    """True if the clinic's synced records contain this national ID with this birth date (YYYY-MM-DD)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM synced_candidates "
                "WHERE clinic_id = %s AND chart_number = %s AND birth_date = %s LIMIT 1",
                (clinic_id, chart_number, birth_date),
            )
            return cur.fetchone() is not None


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
                "SELECT COUNT(*) AS n FROM line_bindings WHERE clinic_id = %s", (clinic_id,)
            )
            return cur.fetchone()["n"]


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


def _reply(token: str, reply_token: str, messages: list[dict]) -> dict:
    """Reply messages are free (don't count toward the monthly quota); reply tokens are single-use."""
    try:
        resp = requests.post(
            f"{_LINE_API}/message/reply",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"replyToken": reply_token, "messages": messages},
            timeout=10,
        )
        return {"status": resp.status_code, "body": resp.text}
    except Exception as e:
        return {"status": 0, "body": str(e)}


def get_bot_info(token: str) -> dict | None:
    """Account name/picture for the token's channel; None if the token is invalid."""
    try:
        r = requests.get(f"{_LINE_API}/info", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    d = r.json()
    return {
        "display_name": d.get("displayName", ""),
        "picture_url": d.get("pictureUrl", ""),
        "basic_id": d.get("basicId", ""),
        "chat_mode": d.get("chatMode", ""),
    }


def get_webhook_info(token: str) -> dict | None:
    try:
        r = requests.get(f"{_LINE_API}/channel/webhook/endpoint",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException:
        return None
    return r.json() if r.status_code == 200 else None


def setup_webhook(token: str, webhook_url: str) -> dict:
    """Point the channel's webhook at webhook_url and send LINE's test event to it.
    Returns {webhook_set, test_ok, test_reason, webhook_active}."""
    auth_h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out = {"webhook_set": False, "test_ok": False, "test_reason": "", "webhook_active": False}
    try:
        r = requests.put(f"{_LINE_API}/channel/webhook/endpoint", headers=auth_h,
                         json={"endpoint": webhook_url}, timeout=10)
        out["webhook_set"] = r.status_code == 200
        if not out["webhook_set"]:
            out["test_reason"] = f"SET_FAILED_{r.status_code}"
            return out
        t = requests.post(f"{_LINE_API}/channel/webhook/test", headers=auth_h,
                          json={"endpoint": webhook_url}, timeout=20)
        if t.status_code == 200:
            td = t.json()
            out["test_ok"] = bool(td.get("success"))
            out["test_reason"] = f"{td.get('reason', '')} {td.get('detail', '')}".strip()
    except requests.RequestException as e:
        out["test_reason"] = f"CONNECTION_ERROR {e}"
    info = get_webhook_info(token)
    out["webhook_active"] = bool(info and info.get("active"))
    return out


def create_liff_app(login_channel_id: str, login_channel_secret: str, endpoint_url: str) -> dict:
    """Create the binding LIFF app in a LINE Login channel. Returns {liff_id} or {error}."""
    try:
        tok = requests.post(
            "https://api.line.me/v2/oauth/accessToken",
            data={"grant_type": "client_credentials", "client_id": login_channel_id,
                  "client_secret": login_channel_secret},
            timeout=10,
        )
        if tok.status_code != 200:
            return {"error": "LINE Login 的 Channel ID 或 Channel secret 不正確"}
        access = tok.json().get("access_token", "")
        r = requests.post(
            "https://api.line.me/liff/v1/apps",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            json={
                "view": {"type": "full", "url": endpoint_url},
                "description": "病患綁定",
                "scope": ["openid", "profile"],
                "botPrompt": "normal",
            },
            timeout=10,
        )
    except requests.RequestException:
        return {"error": "無法連線到 LINE，請稍後再試"}
    if r.status_code != 200:
        return {"error": f"LINE 無法建立綁定頁（{r.status_code}），請改用手動設定"}
    liff_id = r.json().get("liffId", "")
    return {"liff_id": liff_id} if liff_id else {"error": "LINE 未回傳 LIFF ID，請改用手動設定"}


def verify_liff_token(access_token: str, login_channel_id: str) -> dict | None:
    """Verify a LIFF access token server-side and return {userId, displayName}, or None.
    Per LINE docs: never trust a userId sent by the page — check the token was issued
    for our LINE Login channel, then read the profile with it."""
    if not access_token or not login_channel_id:
        return None
    v = requests.get(
        "https://api.line.me/oauth2/v2.1/verify",
        params={"access_token": access_token}, timeout=5,
    )
    if v.status_code != 200:
        return None
    info = v.json()
    if str(info.get("client_id", "")) != str(login_channel_id) or int(info.get("expires_in", 0)) <= 0:
        return None
    p = requests.get(
        "https://api.line.me/v2/profile",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=5,
    )
    if p.status_code != 200:
        return None
    prof = p.json()
    if not prof.get("userId"):
        return None
    return {"userId": prof["userId"], "displayName": prof.get("displayName", "")}


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


def get_friend_count(clinic_id: int = 1) -> int | None:
    """Current number of friends (LINE insight; available for the previous day). None if unavailable."""
    token = (get_settings(clinic_id).get("channel_access_token") or "").strip()
    if not token:
        return None
    day = (datetime.now(_TW) - timedelta(days=1)).strftime("%Y%m%d")
    try:
        r = requests.get(
            f"{_LINE_API}/insight/followers", params={"date": day},
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        d = r.json() if r.status_code == 200 else {}
        if d.get("status") != "ready":
            return None
        return int(d.get("followers", 0)) - int(d.get("blocks", 0))
    except (requests.RequestException, ValueError):
        return None


def broadcast_bind_invite(clinic_id: int = 1) -> dict:
    """Broadcast the binding invitation to every friend of the account (incl. friends who
    added it before the Messaging API was enabled and never triggered a follow event).
    Counts toward the monthly message quota once per friend."""
    settings = get_settings(clinic_id)
    token = settings.get("channel_access_token", "")
    liff_id = settings.get("liff_id", "")
    if not token:
        return {"status": "error", "detail": "LINE尚未設定憑證"}
    if not liff_id:
        return {"status": "error", "detail": "尚未設定病患綁定頁（LIFF ID）"}
    msg_text = (
        "您好！請點擊以下連結，輸入身分證字號與生日完成 LINE 綁定，"
        "日後即可透過 LINE 接收診所的回診與健康提醒。\n\n"
        f"https://liff.line.me/{liff_id}\n\n"
        "（已綁定者請忽略此訊息）"
    )
    try:
        resp = requests.post(
            f"{_LINE_API}/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": msg_text}]},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"status": "error", "detail": f"LINE 連線失敗：{e}"}
    if resp.status_code == 429:
        return {"status": "error", "detail": "已超過本月訊息則數上限"}
    if resp.status_code != 200:
        return {"status": "error", "detail": f"LINE 回應 {resp.status_code}"}
    log_audit(clinic_id, "broadcast_invite", "", "admin", "")
    return {"status": "ok"}


# ── Webhook ───────────────────────────────────────────────────────────────────

def verify_signature(body_bytes: bytes, signature: str, channel_secret: str) -> bool:
    expected = hmac.new(
        channel_secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).digest()
    return hmac.compare_digest(base64.b64encode(expected).decode(), signature)


_seen_event_ids: dict[str, float] = {}


def _is_duplicate(event_id: str) -> bool:
    """LINE may redeliver events; drop ones already handled in the last hour (per process)."""
    if not event_id:
        return False
    now = datetime.now().timestamp()
    if len(_seen_event_ids) > 5000:
        for k in [k for k, t in _seen_event_ids.items() if t < now - 3600]:
            _seen_event_ids.pop(k, None)
    if event_id in _seen_event_ids:
        return True
    _seen_event_ids[event_id] = now
    return False


def process_webhook(body: dict, clinic_id: int = 1) -> None:
    """Handle LINE webhook events (follow, unfollow, message). Run off the request path."""
    settings = get_settings(clinic_id)
    token = settings.get("channel_access_token", "")
    liff_id = settings.get("liff_id", "")

    for event in body.get("events", []):
        if _is_duplicate(event.get("webhookEventId", "")):
            continue
        etype = event.get("type")
        user_id = event.get("source", {}).get("userId", "")
        if not user_id:
            continue

        if etype == "follow" and token and event.get("replyToken"):
            # New follower — reply (free) with the binding invite
            msg = "歡迎加入！請點擊以下連結，輸入身分證字號與生日完成綁定，以便接收診所的回診與健康提醒。"
            messages: list[dict] = [{"type": "text", "text": msg}]
            if liff_id:
                messages.append({"type": "text", "text": f"https://liff.line.me/{liff_id}"})
            _reply(token, event["replyToken"], messages)

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

        elif etype == "message" and token:
            msg_type = event.get("message", {}).get("type", "")
            text = event.get("message", {}).get("text", "").strip()
            reply_token = event.get("replyToken", "")
            if msg_type == "text" and text and reply_token:
                # Look up chart_number (may be "" if patient not yet bound)
                chart = ""
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT chart_number FROM line_bindings "
                            "WHERE line_user_id=%s AND clinic_id=%s",
                            (user_id, clinic_id),
                        )
                        row = cur.fetchone()
                        if row:
                            chart = row["chart_number"]
                # Defer import to avoid circular import at module load time
                try:
                    import ai_agent_service as _ai
                    _ai.handle_message(
                        clinic_id, user_id, chart, text, reply_token, token
                    )
                except Exception as _e:
                    import logging as _logging
                    _logging.getLogger(__name__).error("AI handle_message error: %s", _e)
