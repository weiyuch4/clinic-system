"""
AI Auto-reply service — LINE message handling with Gemini/Claude backend.

Tables:
  ai_agent_settings     — per-clinic config (provider, keys, prompt, schedule, enabled)
  ai_knowledge_base     — knowledge articles for the AI context
  ai_conversations      — conversation history (last N turns per patient)
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import requests

from db import _conn

_TW = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

# Conversation history: keep last N messages per patient to give context
_HISTORY_TURNS = 6   # 3 exchanges (user + assistant each)
_MAX_KB_CHARS = 6000  # max chars of knowledge base injected per request

# ── Table definitions ─────────────────────────────────────────────────────────

_CREATE_AI_SETTINGS = """
    CREATE TABLE IF NOT EXISTS ai_agent_settings (
        clinic_id         INTEGER PRIMARY KEY,
        enabled           INTEGER NOT NULL DEFAULT 0,
        provider          TEXT    NOT NULL DEFAULT 'gemini',
        gemini_api_key    TEXT    NOT NULL DEFAULT '',
        claude_api_key    TEXT    NOT NULL DEFAULT '',
        model_name        TEXT    NOT NULL DEFAULT '',
        system_prompt     TEXT    NOT NULL DEFAULT '',
        schedule_json     TEXT    NOT NULL DEFAULT '{}',
        updated_at        TEXT    NOT NULL DEFAULT ''
    )
"""

_CREATE_AI_KB = """
    CREATE TABLE IF NOT EXISTS ai_knowledge_base (
        id           SERIAL PRIMARY KEY,
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        title        TEXT    NOT NULL,
        content      TEXT    NOT NULL,
        category     TEXT    NOT NULL DEFAULT '',
        is_active    INTEGER NOT NULL DEFAULT 1,
        sort_order   INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT    NOT NULL,
        updated_at   TEXT    NOT NULL
    )
"""

_CREATE_AI_CONVERSATIONS = """
    CREATE TABLE IF NOT EXISTS ai_conversations (
        id             SERIAL PRIMARY KEY,
        clinic_id      INTEGER NOT NULL DEFAULT 1,
        line_user_id   TEXT    NOT NULL,
        chart_number   TEXT    NOT NULL DEFAULT '',
        role           TEXT    NOT NULL,
        content        TEXT    NOT NULL,
        created_at     TEXT    NOT NULL
    )
"""

_CREATE_AI_CONV_IDX = """
    CREATE INDEX IF NOT EXISTS idx_ai_conv_user
    ON ai_conversations (clinic_id, line_user_id, id DESC)
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_AI_SETTINGS)
            cur.execute(_CREATE_AI_KB)
            cur.execute(_CREATE_AI_CONVERSATIONS)
            cur.execute(_CREATE_AI_CONV_IDX)


# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings(clinic_id: int) -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM ai_agent_settings WHERE clinic_id = %s", (clinic_id,)
            )
            row = cur.fetchone()
    if not row:
        return {
            "clinic_id": clinic_id,
            "enabled": False,
            "provider": "gemini",
            "gemini_api_key": "",
            "claude_api_key": "",
            "model_name": "",
            "system_prompt": _DEFAULT_SYSTEM_PROMPT,
            "schedule_json": {},
            "updated_at": "",
        }
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    try:
        d["schedule_json"] = json.loads(d.get("schedule_json") or "{}")
    except Exception:
        d["schedule_json"] = {}
    # Never expose API keys to caller — mask them
    for k in ("gemini_api_key", "claude_api_key"):
        if d.get(k):
            d[k + "_set"] = True
            d[k] = "***"
        else:
            d[k + "_set"] = False
    return d


def save_settings(
    clinic_id: int,
    *,
    enabled: bool | None = None,
    provider: str | None = None,
    gemini_api_key: str | None = None,
    claude_api_key: str | None = None,
    model_name: str | None = None,
    system_prompt: str | None = None,
    schedule_json: dict | None = None,
) -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT clinic_id FROM ai_agent_settings WHERE clinic_id = %s", (clinic_id,)
            )
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(
                    "INSERT INTO ai_agent_settings (clinic_id, system_prompt, schedule_json, updated_at) "
                    "VALUES (%s, %s, '{}', %s)",
                    (clinic_id, _DEFAULT_SYSTEM_PROMPT, now),
                )

            fields: list[tuple] = [("updated_at", now)]
            if enabled is not None:
                fields.append(("enabled", 1 if enabled else 0))
            if provider is not None:
                fields.append(("provider", provider[:50]))
            if gemini_api_key is not None and gemini_api_key != "***":
                fields.append(("gemini_api_key", gemini_api_key.strip()))
            if claude_api_key is not None and claude_api_key != "***":
                fields.append(("claude_api_key", claude_api_key.strip()))
            if model_name is not None:
                fields.append(("model_name", model_name[:100]))
            if system_prompt is not None:
                fields.append(("system_prompt", system_prompt[:8000]))
            if schedule_json is not None:
                fields.append(("schedule_json", json.dumps(schedule_json)))

            set_clause = ", ".join(f"{f} = %s" for f, _ in fields)
            values = [v for _, v in fields] + [clinic_id]
            cur.execute(
                f"UPDATE ai_agent_settings SET {set_clause} WHERE clinic_id = %s",
                values,
            )


# ── Knowledge base ────────────────────────────────────────────────────────────

def list_kb(clinic_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, content, category, is_active, sort_order, created_at, updated_at
                   FROM ai_knowledge_base WHERE clinic_id = %s
                   ORDER BY sort_order, id""",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def upsert_kb(
    clinic_id: int,
    title: str,
    content: str,
    category: str = "",
    is_active: bool = True,
    sort_order: int = 0,
    kb_id: int | None = None,
) -> int:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            if kb_id:
                cur.execute(
                    """UPDATE ai_knowledge_base
                       SET title=%s, content=%s, category=%s, is_active=%s,
                           sort_order=%s, updated_at=%s
                       WHERE id=%s AND clinic_id=%s""",
                    (title[:200], content[:10000], category[:100],
                     1 if is_active else 0, sort_order, now, kb_id, clinic_id),
                )
                return kb_id
            else:
                cur.execute(
                    """INSERT INTO ai_knowledge_base
                       (clinic_id, title, content, category, is_active, sort_order, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (clinic_id, title[:200], content[:10000], category[:100],
                     1 if is_active else 0, sort_order, now, now),
                )
                return cur.fetchone()["id"]


def delete_kb(kb_id: int, clinic_id: int) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ai_knowledge_base WHERE id=%s AND clinic_id=%s",
                (kb_id, clinic_id),
            )
            return cur.rowcount > 0


def _get_kb_context(clinic_id: int) -> str:
    """Return active KB articles as a formatted string for injection into the AI prompt."""
    items = [r for r in list_kb(clinic_id) if r["is_active"]]
    if not items:
        return ""
    parts = []
    total = 0
    for item in items:
        chunk = f"【{item['title']}】\n{item['content']}"
        if total + len(chunk) > _MAX_KB_CHARS:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


# ── Conversation history ──────────────────────────────────────────────────────

def get_history(clinic_id: int, line_user_id: str) -> list[dict]:
    """Return last N turns for a user, oldest first."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT role, content FROM (
                     SELECT role, content, id FROM ai_conversations
                     WHERE clinic_id=%s AND line_user_id=%s
                     ORDER BY id DESC LIMIT %s
                   ) sub ORDER BY id""",
                (clinic_id, line_user_id, _HISTORY_TURNS),
            )
            return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]


def append_history(
    clinic_id: int,
    line_user_id: str,
    chart_number: str,
    role: str,
    content: str,
) -> None:
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ai_conversations
                   (clinic_id, line_user_id, chart_number, role, content, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (clinic_id, line_user_id, chart_number, role, content[:2000], now),
            )
            # Prune old rows — keep last 50 per user
            cur.execute(
                """DELETE FROM ai_conversations WHERE id IN (
                     SELECT id FROM ai_conversations
                     WHERE clinic_id=%s AND line_user_id=%s
                     ORDER BY id DESC OFFSET 50
                   )""",
                (clinic_id, line_user_id),
            )


def list_conversations(clinic_id: int, limit: int = 50) -> list[dict]:
    """Return recent conversation entries for admin review."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT line_user_id, chart_number, role, content, created_at
                   FROM ai_conversations WHERE clinic_id=%s
                   ORDER BY id DESC LIMIT %s""",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Schedule check ────────────────────────────────────────────────────────────

def is_within_schedule(schedule: dict) -> bool:
    """
    schedule_json format:
    {
      "mon": {"enabled": true, "start": "09:00", "end": "21:00"},
      "tue": {"enabled": true, "start": "09:00", "end": "21:00"},
      ...  (mon/tue/wed/thu/fri/sat/sun)
    }
    Empty schedule = always reply.
    """
    if not schedule:
        return True
    now = datetime.now(_TW)
    day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
    day_cfg = schedule.get(day_key, {})
    if not day_cfg.get("enabled", True):
        return False
    start_s = day_cfg.get("start", "")
    end_s = day_cfg.get("end", "")
    if not start_s or not end_s:
        return True
    try:
        sh, sm = int(start_s[:2]), int(start_s[3:5])
        eh, em = int(end_s[:2]), int(end_s[3:5])
        cur_min = now.hour * 60 + now.minute
        return sh * 60 + sm <= cur_min <= eh * 60 + em
    except Exception:
        return True


# ── AI providers ──────────────────────────────────────────────────────────────

def _call_gemini(api_key: str, model: str, system: str, history: list[dict], user_text: str) -> str:
    """Call Gemini API. Returns reply text or raises."""
    model_id = model or "gemini-2.0-flash-exp"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

    contents = []
    for turn in history:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.7},
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_claude(api_key: str, model: str, system: str, history: list[dict], user_text: str) -> str:
    """Call Anthropic Claude API. Returns reply text or raises."""
    model_id = model or "claude-haiku-4-5"
    messages = list(history)
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": model_id,
        "max_tokens": 1024,
        "system": system,
        "messages": messages,
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def _get_api_key_raw(clinic_id: int, provider: str) -> str:
    """Fetch the raw (unmasked) API key from DB."""
    col = "gemini_api_key" if provider == "gemini" else "claude_api_key"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {col} FROM ai_agent_settings WHERE clinic_id=%s", (clinic_id,)
            )
            row = cur.fetchone()
    return (row[col] if row else "") or ""


# ── Main entry point: handle an incoming LINE text message ────────────────────

def handle_message(
    clinic_id: int,
    line_user_id: str,
    chart_number: str,
    user_text: str,
    reply_token: str,
    access_token: str,
) -> bool:
    """
    Process an incoming LINE text message and send an AI reply.
    Returns True if a reply was sent.
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enabled, provider, model_name, system_prompt, schedule_json "
                "FROM ai_agent_settings WHERE clinic_id=%s",
                (clinic_id,),
            )
            row = cur.fetchone()

    if not row or not row["enabled"]:
        return False

    try:
        schedule = json.loads(row["schedule_json"] or "{}")
    except Exception:
        schedule = {}

    if not is_within_schedule(schedule):
        return False

    provider = row["provider"] or "gemini"
    model = row["model_name"] or ""
    api_key = _get_api_key_raw(clinic_id, provider)
    if not api_key:
        logger.warning("AI auto-reply: no API key for provider=%s clinic=%s", provider, clinic_id)
        return False

    kb_context = _get_kb_context(clinic_id)
    system = row["system_prompt"] or _DEFAULT_SYSTEM_PROMPT
    if kb_context:
        system = system + "\n\n以下是診所知識庫，請根據這些資訊回答病患問題：\n\n" + kb_context

    history = get_history(clinic_id, line_user_id)

    try:
        if provider == "gemini":
            reply_text = _call_gemini(api_key, model, system, history, user_text)
        else:
            reply_text = _call_claude(api_key, model, system, history, user_text)
    except Exception as e:
        logger.error("AI reply failed clinic=%s provider=%s: %s", clinic_id, provider, e)
        return False

    # Persist conversation
    append_history(clinic_id, line_user_id, chart_number, "user", user_text)
    append_history(clinic_id, line_user_id, chart_number, "assistant", reply_text)

    # Send reply via LINE Reply API
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": reply_text}],
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.error("LINE reply send failed: %s", e)
        return False


# ── Default system prompt ─────────────────────────────────────────────────────

_DEFAULT_SYSTEM_PROMPT = (
    "你是一位診所助理，負責透過LINE回覆病患的問題。請用親切、專業的繁體中文回答。"
    "如果病患的問題超出你的知識範圍，請建議他們直接來診所或致電詢問。"
    "回答要簡潔，避免過長的回覆。不要提供具體的醫療診斷或處方建議。"
)
