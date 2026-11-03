"""Per-patient 不聯絡 preferences: a patient can ask not to be contacted for some lists, or at all.

Separate from 排除 (excluded): 排除 means the patient left the program; 不聯絡 means they are still
our patient but asked for no messages. Every follow-up list and every LINE send checks this.
"""
import json
from datetime import datetime, timedelta, timezone

from db import _conn

# Scope keys are the follow-up category names used everywhere else, plus 抽血 (抽血回診) and 群發 (broadcasts).
SCOPES = ("慢簽", "代謝症候群", "B肝", "慢性腎臟病", "處方", "抽血", "群發")

_TW = timezone(timedelta(hours=8))

_CREATE = """
    CREATE TABLE IF NOT EXISTS contact_prefs (
        clinic_id    INTEGER NOT NULL,
        chart_number TEXT    NOT NULL,
        name         TEXT    NOT NULL DEFAULT '',
        block_all    BOOLEAN NOT NULL DEFAULT FALSE,
        scopes       TEXT    NOT NULL DEFAULT '[]',
        note         TEXT    NOT NULL DEFAULT '',
        nurse        TEXT    NOT NULL DEFAULT '',
        updated_at   TEXT    NOT NULL,
        PRIMARY KEY (clinic_id, chart_number)
    )
"""

# Append-only: shows when a patient's request was recorded and by whom, even after it is lifted.
_CREATE_LOG = """
    CREATE TABLE IF NOT EXISTS contact_prefs_log (
        id           SERIAL PRIMARY KEY,
        clinic_id    INTEGER NOT NULL,
        chart_number TEXT    NOT NULL,
        summary      TEXT    NOT NULL,
        note         TEXT    NOT NULL DEFAULT '',
        nurse        TEXT    NOT NULL DEFAULT '',
        created_at   TEXT    NOT NULL
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
            cur.execute(_CREATE_LOG)
            cur.execute("CREATE INDEX IF NOT EXISTS contact_prefs_log_chart ON contact_prefs_log (clinic_id, chart_number)")


def _row(r: dict) -> dict:
    return {
        "chart_number": r["chart_number"],
        "name": r["name"],
        "block_all": bool(r["block_all"]),
        "scopes": [s for s in json.loads(r["scopes"] or "[]") if s in SCOPES],
        "note": r["note"],
        "nurse": r["nurse"],
        "updated_at": r["updated_at"],
    }


def summarize(block_all: bool, scopes: list[str]) -> str:
    if block_all:
        return "全部不聯絡"
    if not scopes:
        return "恢復聯絡"
    labels = {"代謝症候群": "MSPT", "慢性腎臟病": "CKD", "處方": "處方追蹤", "抽血": "抽血回診", "群發": "群發訊息"}
    return "不聯絡：" + "、".join(labels.get(s, s) for s in SCOPES if s in scopes)


def get(chart_number: str, clinic_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contact_prefs WHERE clinic_id = %s AND chart_number = %s",
                        (clinic_id, chart_number))
            r = cur.fetchone()
    return _row(r) if r else None


def get_all(clinic_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contact_prefs WHERE clinic_id = %s ORDER BY updated_at DESC", (clinic_id,))
            return [_row(r) for r in cur.fetchall()]


def get_map(clinic_id: int) -> dict[str, dict]:
    return {p["chart_number"]: p for p in get_all(clinic_id)}


def blocks(pref: dict | None, scope: str) -> bool:
    """True when this preference forbids contact for the given scope."""
    if not pref:
        return False
    return pref["block_all"] or scope in pref["scopes"]


def is_blocked(chart_number: str, scope: str, clinic_id: int) -> bool:
    return blocks(get(chart_number, clinic_id), scope)


def get_log(chart_number: str, clinic_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT summary, note, nurse, created_at FROM contact_prefs_log
                   WHERE clinic_id = %s AND chart_number = %s ORDER BY id DESC""",
                (clinic_id, chart_number),
            )
            return [dict(r) for r in cur.fetchall()]


def save(chart_number: str, name: str, block_all: bool, scopes: list[str],
         note: str, nurse: str, clinic_id: int) -> dict | None:
    """Store the patient's preference; clearing everything removes the row. Every change is logged."""
    scopes = [s for s in SCOPES if s in set(scopes)]
    note = (note or "").strip()[:500]
    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
    with _conn() as conn:
        with conn.cursor() as cur:
            if block_all or scopes:
                cur.execute(
                    """INSERT INTO contact_prefs
                       (clinic_id, chart_number, name, block_all, scopes, note, nurse, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (clinic_id, chart_number) DO UPDATE SET
                           name = EXCLUDED.name, block_all = EXCLUDED.block_all, scopes = EXCLUDED.scopes,
                           note = EXCLUDED.note, nurse = EXCLUDED.nurse, updated_at = EXCLUDED.updated_at""",
                    (clinic_id, chart_number, name or "", block_all, json.dumps(scopes, ensure_ascii=False),
                     note, nurse or "", now),
                )
            else:
                cur.execute("DELETE FROM contact_prefs WHERE clinic_id = %s AND chart_number = %s",
                            (clinic_id, chart_number))
            cur.execute(
                """INSERT INTO contact_prefs_log (clinic_id, chart_number, summary, note, nurse, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (clinic_id, chart_number, summarize(block_all, scopes), note, nurse or "", now),
            )
    return get(chart_number, clinic_id)
