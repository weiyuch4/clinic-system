"""Permanent record of what each nurse did, for the admin back office (後台) only.

One row per button press that changes patient follow-up state: who (nurse name and whether
it was proven by the nurse's PIN), what (action label), which patient, when (Taiwan time).
Rows are never updated or deleted — an undo (撤銷) is logged as its own row, so a count can
always be traced back to the records behind it.

Logging happens in one ASGI middleware, after the endpoint has succeeded, so endpoints need
no changes and a failed request leaves no row. A logging failure never breaks the request.

Never surface any of this to nurses (no changelog entry, no nurse-facing page or help text).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import anyio

import auth
from db import _conn

logger = logging.getLogger(__name__)
_TW = timezone(timedelta(hours=8))

_CREATE = """
    CREATE TABLE IF NOT EXISTS activity_log (
        id             BIGSERIAL PRIMARY KEY,
        clinic_id      INTEGER NOT NULL DEFAULT 1,
        created_at     TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS' Taiwan time
        nurse          TEXT NOT NULL DEFAULT '',
        nurse_verified BOOLEAN NOT NULL DEFAULT FALSE,
        action         TEXT NOT NULL,
        category       TEXT NOT NULL DEFAULT '',
        chart_number   TEXT NOT NULL DEFAULT '',
        patient_name   TEXT NOT NULL DEFAULT '',
        stage          TEXT NOT NULL DEFAULT '',
        detail         TEXT NOT NULL DEFAULT '',
        account        TEXT NOT NULL DEFAULT ''    -- the logged-in clinic account
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
            cur.execute("CREATE INDEX IF NOT EXISTS activity_log_clinic_time ON activity_log (clinic_id, created_at)")


# ── Nurse proof ─────────────────────────────────────────────────────────────────
# After a correct PIN the server hands the page a signed token naming that nurse. The page
# sends it with every request; a valid token is the only way a row is marked verified.

def sign_nurse(clinic_id: int, name: str) -> str:
    payload = f"{clinic_id}|{name}|{int(time.time())}".encode()
    sig = hmac.new(auth.JWT_SECRET.encode(), b"nurse:" + payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(sig).decode().rstrip("="))


def verify_nurse(token: str, clinic_id: int) -> str | None:
    try:
        p64, s64 = token.split(".", 1)
        payload = base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4))
        sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4))
        good = hmac.new(auth.JWT_SECRET.encode(), b"nurse:" + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        cid, name, _ts = payload.decode().split("|", 2)
        return name if int(cid) == clinic_id and name else None
    except Exception:
        return None


# ── What gets logged ────────────────────────────────────────────────────────────
# (method, path regex) -> action label. Path groups named `chart` / `id` are picked up.
_ACTIONS: list[tuple[str, re.Pattern, str]] = [(m, re.compile(p + r"$"), a) for m, p, a in [
    ("POST",   r"/api/contacted",                      "已通知"),
    ("POST",   r"/api/called",                         "再次通知"),
    ("DELETE", r"/api/contacted",                      "撤銷已通知"),
    ("POST",   r"/api/submitted",                      "已登VPN"),
    ("DELETE", r"/api/submitted",                      "撤銷"),          # detail says which
    ("POST",   r"/api/mspt-phone-complete",            "電話完成"),
    ("POST",   r"/api/mspt-blood-invalid",             "抽血不符"),
    ("POST",   r"/api/mspt-waive-blood",               "免抽血"),
    ("POST",   r"/api/mspt-completed",                 "回診完成"),
    ("DELETE", r"/api/mspt-completed",                 "撤銷回診完成"),
    ("POST",   r"/api/mspt-checkedin",                 "已報到"),
    ("DELETE", r"/api/mspt-checkedin",                 "撤銷已報到"),
    ("POST",   r"/api/mspt-manual",                    "手動登錄MSPT"),
    ("DELETE", r"/api/mspt-manual",                    "撤銷手動登錄MSPT"),
    ("POST",   r"/api/excluded",                       "排除"),
    ("PATCH",  r"/api/excluded",                       "修改排除"),
    ("DELETE", r"/api/excluded",                       "撤銷排除"),
    ("DELETE", r"/api/auto-excluded",                  "撤銷自動排除"),
    ("POST",   r"/api/on-hold",                        "暫緩"),
    ("POST",   r"/api/on-hold/manual",                 "暫緩（手動新增）"),
    ("DELETE", r"/api/on-hold",                        "撤銷暫緩"),
    ("POST",   r"/api/hep-returned-completed",         "已登VPN"),
    ("DELETE", r"/api/hep-returned-completed",         "撤銷已登VPN"),
    ("POST",   r"/api/hep-reintake",                   "重新收案"),
    ("DELETE", r"/api/hep-reintake",                   "撤銷重新收案"),
    ("POST",   r"/api/hep-manual-returned",            "標記已回診"),
    ("DELETE", r"/api/hep-manual-returned",            "撤銷已回診"),
    ("POST",   r"/api/ckd-manual-inactive",            "標記不再追蹤"),
    ("DELETE", r"/api/ckd-manual-inactive",            "撤銷不再追蹤"),
    ("POST",   r"/api/manual-pickup",                  "手動取藥"),
    ("DELETE", r"/api/manual-pickup",                  "撤銷手動取藥"),
    ("POST",   r"/api/line-unlinked",                  "未加LINE"),
    ("DELETE", r"/api/line-unlinked/(?P<chart>[^/]+)", "撤銷未加LINE"),
    ("POST",   r"/api/send-line-notifications",        "LINE通知（整批）"),
    ("POST",   r"/api/send-line-notifications/cancel", "取消LINE通知"),
    ("POST",   r"/api/line/push-one",                  "LINE通知（單人）"),
    ("POST",   r"/api/blood-dismiss",                  "抽血不需通知"),
    ("POST",   r"/api/blood-notified",                 "抽血已通知"),
    ("DELETE", r"/api/blood-notified",                 "撤銷抽血已通知"),
    ("POST",   r"/api/blood-physical",                 "抽血紙本"),
    ("DELETE", r"/api/blood-physical",                 "撤銷抽血紙本"),
    ("POST",   r"/api/blood-physical/done",            "抽血紙本完成"),
    ("PATCH",  r"/api/blood-recall/(?P<id>\d+)",       "抽血回診更新"),
    ("PUT",    r"/api/contact-prefs/(?P<chart>[^/]+)", "修改聯絡偏好"),
    ("POST",   r"/api/inventory/count/(?P<id>\d+)/complete",   "完成點貨"),
    ("POST",   r"/api/inventory/orders/(?P<id>\d+)/receive",   "到貨"),
]]
_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _match(method: str, path: str) -> tuple[str, dict] | None:
    for m, rx, label in _ACTIONS:
        if m == method:
            hit = rx.match(path)
            if hit:
                return label, hit.groupdict()
    return None


def _pick(body: dict, *keys: str) -> str:
    """First non-empty value among body, body.entry, body.entry.patient, body.patient."""
    entry = body.get("entry") if isinstance(body.get("entry"), dict) else {}
    srcs = [body, entry, entry.get("patient") or {}, body.get("patient") or {}]
    for k in keys:
        for s in srcs:
            if isinstance(s, dict) and s.get(k) not in (None, ""):
                return str(s[k])
    return ""


def _row(label: str, groups: dict, body: dict, resp: dict) -> dict:
    chart = groups.get("chart") or _pick(body, "chart_number")
    detail = []
    if label == "撤銷":
        label = "撤銷已登VPN" if body.get("keep_completion") else "撤銷完成"
    if body.get("reason"):
        detail.append(str(body["reason"]))
    if body.get("note"):
        detail.append(str(body["note"]))
    if body.get("draw_date"):
        detail.append("抽血 " + str(body["draw_date"]))
    if body.get("completed_date"):
        detail.append("完成日 " + str(body["completed_date"]))
    if body.get("hold_id"):
        detail.append("暫緩 #" + str(body["hold_id"]))
    if groups.get("id"):
        detail.append("#" + groups["id"])
    if label == "LINE通知（整批）" and isinstance(resp, dict):
        if resp.get("total") is not None:
            detail.append(f"共 {resp['total']} 人")
        if body.get("dry_run"):
            detail.append("試送")
    return {
        "action": label,
        "category": _pick(body, "category"),
        "chart_number": unquote(chart),
        # nat_id (blood pages) is deliberately not stored; the name is enough to trace it.
        "patient_name": _pick(body, "name"),
        "stage": _pick(body, "mspt_stage", "stage"),
        "detail": "；".join(detail)[:300],
    }


def _write(clinic_id: int, account: str, nurse: str, verified: bool, row: dict) -> None:
    import db as _db
    _db.set_clinic_id(clinic_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            name = row["patient_name"]
            if not name and row["chart_number"]:
                cur.execute("SELECT name FROM synced_candidates WHERE clinic_id=%s AND chart_number=%s LIMIT 1",
                            (clinic_id, row["chart_number"]))
                r = cur.fetchone()
                name = r["name"] if r else ""
            cur.execute(
                """INSERT INTO activity_log (clinic_id, created_at, nurse, nurse_verified, action, category,
                                             chart_number, patient_name, stage, detail, account)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (clinic_id, datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S"), nurse, verified,
                 row["action"], row["category"], row["chart_number"], name, row["stage"],
                 row["detail"], account),
            )


class ActivityLogMiddleware:
    """Pure ASGI so the request body can be read without disturbing the endpoint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _METHODS:
            return await self.app(scope, receive, send)
        hit = _match(scope["method"], scope["path"])
        if not hit:
            return await self.app(scope, receive, send)

        body_parts: list[bytes] = []
        resp_parts: list[bytes] = []
        status = {"code": 500}

        async def _recv():
            msg = await receive()
            if msg["type"] == "http.request":
                body_parts.append(msg.get("body", b""))
            return msg

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            elif msg["type"] == "http.response.body" and sum(map(len, resp_parts)) < 65536:
                resp_parts.append(msg.get("body", b""))
            await send(msg)

        await self.app(scope, _recv, _send)
        if status["code"] >= 400:
            return
        try:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            tok = headers.get("authorization", "")
            try:
                claims = auth.decode_access_token(tok[7:] if tok.startswith("Bearer ") else tok)
            except Exception:
                return  # no usable login on this request — nothing to attribute
            clinic_id = int(claims["clinic_id"])
            try:
                body = json.loads(b"".join(body_parts) or b"{}")
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            try:
                resp = json.loads(b"".join(resp_parts) or b"{}")
            except ValueError:
                resp = {}
            claimed = unquote(headers.get("x-nurse", "")) or str(body.get("nurse") or "")
            proven = verify_nurse(headers.get("x-nurse-token", ""), clinic_id)
            # Verified only when the PIN-proven nurse is the one the page says is acting.
            verified = proven is not None and (not claimed or proven == claimed)
            nurse = proven if verified else claimed
            row = _row(hit[0], hit[1], body, resp)
            await anyio.to_thread.run_sync(
                _write, clinic_id, str(claims.get("display_name", "")), nurse[:40], verified, row)
        except Exception:
            logger.exception("activity log write failed for %s %s", scope["method"], scope["path"])


# ── Reading (後台 only) ──────────────────────────────────────────────────────────

def get_month(month: str, clinic_id: int, nurse: str | None = None, limit: int = 3000) -> list[dict]:
    sql = """SELECT created_at, nurse, nurse_verified, action, category, chart_number,
                    patient_name, stage, detail
             FROM activity_log WHERE clinic_id=%s AND created_at LIKE %s"""
    args: list = [clinic_id, month + "-%"]
    if nurse is not None:
        sql += " AND nurse = %s"
        args.append("" if nurse == "（未選擇）" else nurse)
    sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
    args.append(limit)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]
