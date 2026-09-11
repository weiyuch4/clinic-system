from datetime import date, datetime, timedelta, timezone

_TW = timezone(timedelta(hours=8))

from db import _conn
from models import ExcludedEntry, FollowupEntry, ManualPickupEntry, MsptManualEntry, MsptStage, MsptSubmittableEntry, OnHoldEntry, Patient

RECONTACT_DAYS = 7
AUTO_EXCLUDE_DAYS = 60  # called entries older than this auto-appear in 已排除

_CREATE_CONTACTS = """
    CREATE TABLE IF NOT EXISTS contacts (
        chart_number    TEXT NOT NULL,
        category        TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        disease_name    TEXT NOT NULL,
        days_overdue    INTEGER NOT NULL,
        mspt_stage      TEXT,
        contact_reason  TEXT,
        last_visit_date TEXT,
        attempt         INTEGER NOT NULL,
        contacted_at    TEXT NOT NULL,
        contacted_time  TEXT,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, category, due_date)
    )
"""

_CREATE_SUBMITTED = """
    CREATE TABLE IF NOT EXISTS submitted (
        chart_number          TEXT NOT NULL,
        mspt_stage            TEXT NOT NULL,
        name                  TEXT NOT NULL,
        birth_date            TEXT NOT NULL,
        blood_report_date     TEXT NOT NULL,
        days_since_last_stage INTEGER NOT NULL,
        submitted_at          TEXT NOT NULL,
        clinic_id             INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, mspt_stage)
    )
"""

_CREATE_EXCLUDED = """
    CREATE TABLE IF NOT EXISTS excluded (
        chart_number    TEXT NOT NULL,
        category        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        mspt_stage      TEXT,
        due_date        TEXT,
        last_visit_date TEXT,
        last_stage      TEXT,
        reason          TEXT NOT NULL,
        note            TEXT DEFAULT '',
        excluded_at     TEXT NOT NULL,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, category)
    )
"""

_CREATE_MANUAL_PICKUPS = """
    CREATE TABLE IF NOT EXISTS manual_pickups (
        chart_number TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        birth_date   TEXT NOT NULL,
        pickup_date  TEXT NOT NULL,
        ps_days      INTEGER NOT NULL,
        recorded_at  TEXT NOT NULL,
        nurse        TEXT DEFAULT '',
        clinic_id    INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_MSPT_PHONE_COMPLETED = """
    CREATE TABLE IF NOT EXISTS mspt_phone_completed (
        chart_number    TEXT NOT NULL,
        mspt_stage      TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        blood_draw_date TEXT,
        completed_at    TEXT NOT NULL,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, mspt_stage, due_date)
    )
"""

_CREATE_MSPT_BLOOD_USED = """
    CREATE TABLE IF NOT EXISTS mspt_blood_used (
        nat_id       TEXT NOT NULL,
        stage        TEXT NOT NULL,
        draw_date    TEXT NOT NULL,
        recorded_at  TEXT NOT NULL,
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (nat_id, stage)
    )
"""

_CREATE_MSPT_COMPLETED = """
    CREATE TABLE IF NOT EXISTS mspt_completed (
        chart_number    TEXT NOT NULL,
        mspt_stage      TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        last_visit_date TEXT,
        last_stage      TEXT,
        days_overdue    INTEGER NOT NULL,
        completed_at    TEXT NOT NULL,
        completed_time  TEXT,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, mspt_stage, due_date)
    )
"""

_CREATE_ON_HOLD = """
    CREATE TABLE IF NOT EXISTS on_hold (
        id              SERIAL PRIMARY KEY,
        chart_number    TEXT,
        category        TEXT,
        due_date        TEXT,
        name            TEXT NOT NULL,
        birth_date      TEXT,
        disease_name    TEXT,
        days_overdue    INTEGER,
        mspt_stage      TEXT,
        last_stage      TEXT,
        last_visit_date TEXT,
        note            TEXT NOT NULL,
        held_at         TEXT NOT NULL,
        nurse           TEXT DEFAULT '',
        is_manual       INTEGER DEFAULT 0,
        clinic_id       INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_MSPT_MANUAL = """
    CREATE TABLE IF NOT EXISTS mspt_manual (
        chart_number    TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        mspt_stage      TEXT NOT NULL,
        completed_date  TEXT NOT NULL,
        nurse           TEXT DEFAULT '',
        marked_at       TEXT NOT NULL,
        clinic_id       INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_MSPT_CHECKEDIN = """
    CREATE TABLE IF NOT EXISTS mspt_checkedin (
        chart_number    TEXT NOT NULL,
        mspt_stage      TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        last_visit_date TEXT,
        last_stage      TEXT,
        days_overdue    INTEGER NOT NULL,
        contact_reason  TEXT,
        checkedin_at    TEXT NOT NULL,
        checkedin_time  TEXT,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, mspt_stage, due_date)
    )
"""

_CREATE_HEP_RETURNED_COMPLETED = """
    CREATE TABLE IF NOT EXISTS hep_returned_completed (
        chart_number    TEXT NOT NULL,
        last_visit_date TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        disease_name    TEXT,
        days_overdue    INTEGER NOT NULL,
        completed_at    TEXT NOT NULL,
        completed_time  TEXT,
        nurse           TEXT DEFAULT '',
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, last_visit_date)
    )
"""

_CREATE_LINE_NOTIFICATION_LOG = """
    CREATE TABLE IF NOT EXISTS line_notification_log (
        id           SERIAL PRIMARY KEY,
        chart_number TEXT NOT NULL,
        name         TEXT NOT NULL,
        birth_date   TEXT NOT NULL,
        category     TEXT NOT NULL,
        template     TEXT NOT NULL,
        status       TEXT NOT NULL,
        detail       TEXT,
        dry_run      INTEGER NOT NULL,
        nurse        TEXT DEFAULT '',
        sent_at      TEXT NOT NULL,
        sent_time    TEXT,
        undone_at    TEXT,
        undone_by    TEXT,
        clinic_id    INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_LINE_UNLINKED = """
    CREATE TABLE IF NOT EXISTS line_unlinked (
        chart_number TEXT NOT NULL PRIMARY KEY,
        name         TEXT NOT NULL,
        flagged_at   TEXT NOT NULL,
        nurse        TEXT DEFAULT '',
        clinic_id    INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_LINE_RECENTLY_SENT = """
    CREATE TABLE IF NOT EXISTS line_recently_sent (
        chart_number TEXT NOT NULL,
        template     TEXT NOT NULL,
        name         TEXT NOT NULL,
        last_sent_at TEXT NOT NULL,
        nurse        TEXT DEFAULT '',
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chart_number, template)
    )
"""

_CREATE_ALLEYPIN_NOT_FOUND = """
    CREATE TABLE IF NOT EXISTS alleypin_not_found (
        chart_number TEXT NOT NULL PRIMARY KEY,
        name         TEXT NOT NULL,
        flagged_at   TEXT NOT NULL,
        nurse        TEXT DEFAULT '',
        clinic_id    INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_SHIFTS = """
    CREATE TABLE IF NOT EXISTS shifts (
        nurse         TEXT NOT NULL,
        shift_date    TEXT NOT NULL,
        slot          TEXT NOT NULL,
        start_time    TEXT,
        end_time      TEXT,
        clean_start   TEXT,
        clean_end     TEXT,
        clinic_id     INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (nurse, shift_date, slot)
    )
"""

_CREATE_NURSES = """
    CREATE TABLE IF NOT EXISTS nurses (
        id         SERIAL PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        clinic_id  INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_PUBLISHED_WEEKS = """
    CREATE TABLE IF NOT EXISTS published_weeks (
        week_start TEXT NOT NULL PRIMARY KEY,
        clinic_id  INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_BULLETIN_NOTES = """
    CREATE TABLE IF NOT EXISTS bulletin_notes (
        id         SERIAL PRIMARY KEY,
        nurse      TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        clinic_id  INTEGER NOT NULL DEFAULT 1
    )
"""

_CREATE_SALARY_RECORDS = """
    CREATE TABLE IF NOT EXISTS salary_records (
        id          SERIAL PRIMARY KEY,
        nurse       TEXT NOT NULL,
        month       TEXT NOT NULL,
        attendance  INTEGER NOT NULL,
        performance INTEGER NOT NULL,
        sat_pay     INTEGER NOT NULL,
        float_bonus INTEGER NOT NULL,
        ot_pay      INTEGER NOT NULL,
        total       INTEGER NOT NULL,
        ot_entries  TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        clinic_id   INTEGER NOT NULL DEFAULT 1,
        sick_days   INTEGER NOT NULL DEFAULT 0
    )
"""

_CREATE_SYNCED_CANDIDATES = """
    CREATE TABLE IF NOT EXISTS synced_candidates (
        clinic_id       INTEGER NOT NULL,
        chart_number    TEXT NOT NULL,
        category        TEXT NOT NULL,
        name            TEXT NOT NULL,
        birth_date      TEXT NOT NULL,
        disease_name    TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        days_overdue    INTEGER NOT NULL,
        mspt_stage      TEXT,
        contact_reason  TEXT,
        last_visit_date TEXT,
        phone           TEXT NOT NULL DEFAULT '',
        mobile          TEXT NOT NULL DEFAULT '',
        synced_at       TEXT NOT NULL,
        PRIMARY KEY (clinic_id, chart_number, category, due_date)
    )
"""


_CREATE_BLOOD_DISMISSED = """
    CREATE TABLE IF NOT EXISTS blood_dismissed (
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        nat_id       TEXT NOT NULL,
        draw_date    TEXT NOT NULL,
        name         TEXT NOT NULL DEFAULT '',
        reason       TEXT NOT NULL DEFAULT '',
        dismissed_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (clinic_id, nat_id, draw_date)
    )
"""

_CREATE_SYNCED_BLOOD_PENDING = """
    CREATE TABLE IF NOT EXISTS synced_blood_pending (
        clinic_id  INTEGER PRIMARY KEY,
        payload    JSONB NOT NULL DEFAULT '[]'::jsonb,
        synced_at  TEXT NOT NULL DEFAULT ''
    )
"""

_CREATE_LAB_CACHE = """
    CREATE TABLE IF NOT EXISTS lab_cache (
        national_id  TEXT    NOT NULL,
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        data         JSONB   NOT NULL DEFAULT '{}'::jsonb,
        synced_at    TEXT    NOT NULL DEFAULT '',
        PRIMARY KEY (national_id, clinic_id)
    )
"""

_CREATE_BLOOD_NOTIFIED = """
    CREATE TABLE IF NOT EXISTS blood_notified (
        clinic_id    INTEGER NOT NULL DEFAULT 1,
        nat_id       TEXT NOT NULL,
        draw_date    TEXT NOT NULL,
        notified_at  TEXT NOT NULL,
        nurse        TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (clinic_id, nat_id, draw_date)
    )
"""

_CREATE_BLOOD_PHYSICAL = """
    CREATE TABLE IF NOT EXISTS blood_physical (
        clinic_id       INTEGER NOT NULL DEFAULT 1,
        nat_id          TEXT    NOT NULL,
        draw_date       TEXT    NOT NULL,
        name            TEXT    NOT NULL DEFAULT '',
        moved_at        TEXT    NOT NULL,
        nurse           TEXT    NOT NULL DEFAULT '',
        draw_codes      TEXT    NOT NULL DEFAULT '[]',
        draw_code_names TEXT    NOT NULL DEFAULT '[]',
        PRIMARY KEY (clinic_id, nat_id, draw_date)
    )
"""

_CREATE_NURSE_OT_LOGS = """
    CREATE TABLE IF NOT EXISTS nurse_ot_logs (
        id         SERIAL PRIMARY KEY,
        clinic_id  INTEGER NOT NULL DEFAULT 1,
        nurse      TEXT    NOT NULL,
        date       TEXT    NOT NULL,
        start_time TEXT    NOT NULL,
        end_time   TEXT    NOT NULL,
        note       TEXT    NOT NULL DEFAULT '',
        created_at TEXT    NOT NULL
    )
"""


def get_blood_dismissed(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nat_id, draw_date, name, reason, dismissed_at FROM blood_dismissed WHERE clinic_id = %s",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def add_blood_dismissed(nat_id: str, draw_date: str, name: str, reason: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO blood_dismissed (clinic_id, nat_id, draw_date, name, reason, dismissed_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (clinic_id, nat_id, draw_date) DO UPDATE SET
                       reason=EXCLUDED.reason, dismissed_at=EXCLUDED.dismissed_at""",
                (clinic_id, nat_id, draw_date, name, reason, datetime.now().isoformat(timespec='seconds')),
            )


def add_blood_notified(nat_id: str, draw_date: str, nurse: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO blood_notified (clinic_id, nat_id, draw_date, notified_at, nurse)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (clinic_id, nat_id, draw_date) DO UPDATE SET
                       notified_at=EXCLUDED.notified_at, nurse=EXCLUDED.nurse""",
                (clinic_id, nat_id, draw_date, datetime.now().isoformat(timespec='seconds'), nurse),
            )


def remove_blood_notified(nat_id: str, draw_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM blood_notified WHERE clinic_id=%s AND nat_id=%s AND draw_date=%s",
                (clinic_id, nat_id, draw_date),
            )


def get_blood_notified_keys(clinic_id: int = 1) -> set[tuple[str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nat_id, draw_date FROM blood_notified WHERE clinic_id=%s",
                (clinic_id,),
            )
            return {(r['nat_id'], r['draw_date']) for r in cur.fetchall()}


def add_blood_physical(nat_id: str, draw_date: str, name: str = '', nurse: str = '',
                       draw_codes: str = '[]', draw_code_names: str = '[]',
                       clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO blood_physical
                       (clinic_id, nat_id, draw_date, name, moved_at, nurse, draw_codes, draw_code_names)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (clinic_id, nat_id, draw_date) DO UPDATE SET
                       nurse=EXCLUDED.nurse, moved_at=EXCLUDED.moved_at,
                       draw_codes=EXCLUDED.draw_codes, draw_code_names=EXCLUDED.draw_code_names""",
                (clinic_id, nat_id, draw_date, name, datetime.now().isoformat(timespec='seconds'),
                 nurse, draw_codes, draw_code_names),
            )


def remove_blood_physical(nat_id: str, draw_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM blood_physical WHERE clinic_id=%s AND nat_id=%s AND draw_date=%s",
                (clinic_id, nat_id, draw_date),
            )


def get_blood_physical(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nat_id, draw_date, name, moved_at, nurse, draw_codes, draw_code_names FROM blood_physical WHERE clinic_id=%s ORDER BY draw_date DESC",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_blood_physical_keys(clinic_id: int = 1) -> set[tuple[str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nat_id, draw_date FROM blood_physical WHERE clinic_id=%s",
                (clinic_id,),
            )
            return {(r['nat_id'], r['draw_date']) for r in cur.fetchall()}


def get_synced_blood_pending(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM synced_blood_pending WHERE clinic_id = %s",
                (clinic_id,),
            )
            row = cur.fetchone()
            return row['payload'] if row else []


def upsert_synced_blood_pending(payload: list[dict], clinic_id: int = 1) -> None:
    import json as _json
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO synced_blood_pending (clinic_id, payload, synced_at)
                   VALUES (%s, %s::jsonb, %s)
                   ON CONFLICT (clinic_id) DO UPDATE SET
                       payload=EXCLUDED.payload, synced_at=EXCLUDED.synced_at""",
                (clinic_id, _json.dumps(payload, ensure_ascii=False, default=str),
                 datetime.now().isoformat(timespec='seconds')),
            )


def patch_blood_pending_dismiss(nat_id: str, draw_date: str, clinic_id: int = 1) -> None:
    """Remove one patient from the stored payload atomically (single SQL, no read-modify-write race)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE synced_blood_pending
                SET payload = (
                    SELECT COALESCE(jsonb_agg(day_out), '[]'::jsonb)
                    FROM (
                        SELECT
                            CASE WHEN src->>'date' = %s
                                 THEN jsonb_set(src, '{patients}',
                                      COALESCE((SELECT jsonb_agg(p)
                                                FROM jsonb_array_elements(src->'patients') p
                                                WHERE p->>'nat_id' != %s),
                                               '[]'::jsonb))
                                 ELSE src
                            END AS day_out
                        FROM jsonb_array_elements(payload) src
                    ) t
                    WHERE jsonb_array_length(day_out->'patients') > 0
                ),
                synced_at = %s
                WHERE clinic_id = %s
                """,
                (draw_date, nat_id, datetime.now().isoformat(timespec='seconds'), clinic_id),
            )


def upsert_lab_cache(lab_data: dict, clinic_id: int = 1) -> None:
    """Store parsed lab results (national_id → {bio, cbc}) pushed from sync agent."""
    import json as _json
    if not lab_data:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            for nat_id, data in lab_data.items():
                cur.execute(
                    """INSERT INTO lab_cache (national_id, clinic_id, data, synced_at)
                       VALUES (%s, %s, %s::jsonb, %s)
                       ON CONFLICT (national_id, clinic_id) DO UPDATE
                           SET data=EXCLUDED.data, synced_at=EXCLUDED.synced_at""",
                    (nat_id, clinic_id,
                     _json.dumps(data, ensure_ascii=False, default=str),
                     datetime.now().isoformat(timespec='seconds')),
                )


def get_all_lab_cache(clinic_id: int = 1) -> dict[str, dict]:
    """Fetch all lab_cache rows for a clinic in one query. Returns {national_id: data}."""
    import json as _json
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT national_id, data FROM lab_cache WHERE clinic_id=%s",
                (clinic_id,)
            )
            out: dict[str, dict] = {}
            for row in cur.fetchall():
                data = row["data"]
                if isinstance(data, str):
                    data = _json.loads(data)
                out[row["national_id"]] = data
            return out


def get_lab_cache(national_id: str, clinic_id: int = 1) -> dict:
    """Retrieve cached lab results for a patient (populated by sync agent)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM lab_cache WHERE national_id=%s AND clinic_id=%s",
                (national_id, clinic_id),
            )
            row = cur.fetchone()
            if row:
                data = row["data"]
                return data if isinstance(data, dict) else __import__('json').loads(data)
            return {'bio': [], 'cbc': [], 'patient_code': None, 'error': None}


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_CONTACTS)
            cur.execute(_CREATE_SUBMITTED)
            cur.execute(_CREATE_EXCLUDED)
            # Migrate excluded table — add columns that may be missing from older schema
            cur.execute("ALTER TABLE excluded ADD COLUMN IF NOT EXISTS nurse TEXT DEFAULT ''")
            cur.execute("ALTER TABLE excluded ADD COLUMN IF NOT EXISTS clinic_id INTEGER NOT NULL DEFAULT 1")
            cur.execute(_CREATE_MSPT_PHONE_COMPLETED)
            cur.execute(_CREATE_MSPT_BLOOD_USED)
            cur.execute(_CREATE_MSPT_COMPLETED)
            cur.execute(_CREATE_MSPT_CHECKEDIN)
            cur.execute(_CREATE_MSPT_MANUAL)
            cur.execute(_CREATE_ON_HOLD)
            cur.execute(_CREATE_MANUAL_PICKUPS)
            cur.execute(_CREATE_HEP_RETURNED_COMPLETED)
            cur.execute(_CREATE_LINE_NOTIFICATION_LOG)
            cur.execute(_CREATE_LINE_UNLINKED)
            cur.execute(_CREATE_LINE_RECENTLY_SENT)
            cur.execute(_CREATE_ALLEYPIN_NOT_FOUND)
            cur.execute(_CREATE_SHIFTS)
            cur.execute(_CREATE_NURSES)
            cur.execute(_CREATE_PUBLISHED_WEEKS)
            cur.execute(_CREATE_BULLETIN_NOTES)
            cur.execute(_CREATE_SALARY_RECORDS)
            cur.execute(_CREATE_SYNCED_CANDIDATES)
            cur.execute(_CREATE_BLOOD_DISMISSED)
            cur.execute(_CREATE_SYNCED_BLOOD_PENDING)
            cur.execute(_CREATE_LAB_CACHE)
            cur.execute(_CREATE_NURSE_OT_LOGS)
            cur.execute(_CREATE_BLOOD_NOTIFIED)
            cur.execute(_CREATE_BLOOD_PHYSICAL)
            cur.execute("ALTER TABLE blood_physical ADD COLUMN IF NOT EXISTS draw_codes TEXT NOT NULL DEFAULT '[]'")
            cur.execute("ALTER TABLE blood_physical ADD COLUMN IF NOT EXISTS draw_code_names TEXT NOT NULL DEFAULT '[]'")
            # Migrations for existing databases
            for col in ("last_visit_date TEXT", "contacted_time TEXT", "nurse TEXT DEFAULT ''"):
                cur.execute(f"ALTER TABLE contacts ADD COLUMN IF NOT EXISTS {col}")
            for col in ("completed_time TEXT", "nurse TEXT DEFAULT ''"):
                cur.execute(f"ALTER TABLE mspt_completed ADD COLUMN IF NOT EXISTS {col}")
            for tbl in ("excluded", "manual_pickups"):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS nurse TEXT DEFAULT ''")
            for col in ("clean_start TEXT", "clean_end TEXT"):
                cur.execute(f"ALTER TABLE shifts ADD COLUMN IF NOT EXISTS {col}")
            cur.execute("ALTER TABLE nurses ADD COLUMN IF NOT EXISTS pin_hash TEXT")
            cur.execute("ALTER TABLE synced_candidates ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE synced_candidates ADD COLUMN IF NOT EXISTS mobile TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE salary_records ADD COLUMN IF NOT EXISTS sick_days INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS mobile TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE on_hold ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE on_hold ADD COLUMN IF NOT EXISTS mobile TEXT NOT NULL DEFAULT ''")
            # Multi-tenant migration: add clinic_id to all tables (idempotent)
            _all_tables = [
                "alleypin_not_found", "bulletin_notes", "clinic_contacts", "contacts",
                "excluded", "hep_returned_completed", "lab_reports", "line_notification_log",
                "line_recently_sent", "line_unlinked", "manual_pickups", "mspt_checkedin",
                "mspt_completed", "mspt_manual", "nurses", "on_hold", "published_weeks",
                "salary_records", "shifts", "submitted",
            ]
            for tbl in _all_tables:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = %s AND table_schema = 'public'",
                    (tbl,),
                )
                if cur.fetchone():
                    cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS clinic_id INTEGER NOT NULL DEFAULT 1")
                    cur.execute(f"UPDATE {tbl} SET clinic_id = 1 WHERE clinic_id IS NULL")


def _followup_to_row(entry: FollowupEntry, attempt: int, nurse: str = "") -> tuple:
    return (
        entry.patient.chart_number,
        entry.category,
        entry.due_date.isoformat(),
        entry.patient.name,
        entry.patient.birth_date.isoformat(),
        entry.disease_name,
        entry.days_overdue,
        entry.mspt_stage,
        entry.contact_reason,
        entry.last_visit_date.isoformat() if entry.last_visit_date else None,
        attempt,
        date.today().isoformat(),
        datetime.now(_TW).strftime('%H:%M'),
        nurse,
        entry.phone,
        entry.mobile,
    )


def mark_contacted(entry: FollowupEntry, nurse: str = "", clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO contacts
                   (chart_number, category, due_date, name, birth_date, disease_name,
                    days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                    contacted_time, nurse, phone, mobile, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                       attempt=1, contacted_at=EXCLUDED.contacted_at,
                       contacted_time=EXCLUDED.contacted_time, nurse=EXCLUDED.nurse,
                       phone=EXCLUDED.phone, mobile=EXCLUDED.mobile""",
                _followup_to_row(entry, 1, nurse) + (clinic_id,),
            )


def mark_called(entry: FollowupEntry, nurse: str = "", clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO contacts
                   (chart_number, category, due_date, name, birth_date, disease_name,
                    days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                    contacted_time, nurse, phone, mobile, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                       attempt=2, contacted_at=EXCLUDED.contacted_at,
                       contacted_time=EXCLUDED.contacted_time, nurse=EXCLUDED.nurse,
                       phone=EXCLUDED.phone, mobile=EXCLUDED.mobile""",
                _followup_to_row(entry, 2, nurse) + (clinic_id,),
            )


def unmark(chart_number: str, category: str, due_date: date, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM contacts WHERE chart_number=%s AND category=%s AND due_date=%s AND clinic_id=%s",
                (chart_number, category, due_date.isoformat(), clinic_id),
            )


def get_hidden_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    """Keys to exclude from the pending list entirely.
    Includes: attempt=2 (permanent) and attempt=1 within the 7-day window."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, category, due_date FROM contacts
                   WHERE clinic_id=%s AND (attempt=2 OR (attempt=1 AND contacted_at > %s))""",
                (clinic_id, cutoff),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["category"], r["due_date"]) for r in rows}


def get_call_required_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    """Keys of attempt=1 contacts that have expired — re-surface with call flag."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, category, due_date FROM contacts WHERE clinic_id=%s AND attempt=1 AND contacted_at <= %s",
                (clinic_id, cutoff),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["category"], r["due_date"]) for r in rows}


def _rows_to_followup_entries(rows: list) -> list[FollowupEntry]:
    return [
        FollowupEntry(
            patient=Patient(
                chart_number=r["chart_number"],
                name=r["name"],
                birth_date=date.fromisoformat(r["birth_date"]),
            ),
            disease_name=r["disease_name"],
            category=r["category"],
            due_date=date.fromisoformat(r["due_date"]),
            days_overdue=r["days_overdue"],
            mspt_stage=r["mspt_stage"],
            contact_reason=r["contact_reason"],
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            phone=r.get("phone", "") or "",
            mobile=r.get("mobile", "") or "",
        )
        for r in rows
    ]


def get_contacted_with_dates(clinic_id: int = 1) -> list[tuple[FollowupEntry, date]]:
    """Entries in the 7-day window paired with their contacted_at date, for return-visit filtering."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                          days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at,
                          contacted_time, phone, mobile
                   FROM contacts WHERE clinic_id=%s AND attempt=1 AND contacted_at > %s""",
                (clinic_id, cutoff),
            )
            rows = cur.fetchall()
    return [
        (
            _rows_to_followup_entries([r])[0].model_copy(
                update={"contacted_time": r["contacted_time"]}
            ),
            date.fromisoformat(r["contacted_at"])
        )
        for r in rows
    ]


def get_contacted_entries(clinic_id: int = 1) -> list[FollowupEntry]:
    """Entries currently in the 7-day hiding window (attempt=1, recent)."""
    return [e for e, _ in get_contacted_with_dates(clinic_id)]


def mark_submitted(entry: MsptSubmittableEntry, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO submitted
                   (chart_number, mspt_stage, name, birth_date, blood_report_date, days_since_last_stage, submitted_at, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (chart_number, mspt_stage) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       blood_report_date=EXCLUDED.blood_report_date,
                       days_since_last_stage=EXCLUDED.days_since_last_stage,
                       submitted_at=EXCLUDED.submitted_at""",
                (
                    entry.patient.chart_number,
                    entry.mspt_stage,
                    entry.patient.name,
                    entry.patient.birth_date.isoformat(),
                    entry.blood_report_date.isoformat(),
                    entry.days_since_last_stage,
                    date.today().isoformat(),
                    clinic_id,
                ),
            )


def unmark_submitted(chart_number: str, mspt_stage: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM submitted WHERE chart_number=%s AND mspt_stage=%s AND clinic_id=%s",
                (chart_number, mspt_stage, clinic_id),
            )


def get_mspt_blood_used(nat_id: str, clinic_id: int = 1) -> dict[str, str]:
    """Return {stage: draw_date_iso} for all blood draws recorded for this patient."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stage, draw_date FROM mspt_blood_used WHERE nat_id = %s AND clinic_id = %s",
                (nat_id, clinic_id),
            )
            return {row["stage"]: row["draw_date"] for row in cur.fetchall()}


def get_all_mspt_blood_used(clinic_id: int = 1) -> dict[str, dict[str, str]]:
    """Return {nat_id: {stage: draw_date_iso}} for all patients — one query for the whole clinic."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nat_id, stage, draw_date FROM mspt_blood_used WHERE clinic_id = %s",
                (clinic_id,),
            )
            result: dict[str, dict[str, str]] = {}
            for row in cur.fetchall():
                result.setdefault(row["nat_id"], {})[row["stage"]] = row["draw_date"]
            return result


def record_mspt_blood_used(nat_id: str, stage: str, draw_iso_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mspt_blood_used (nat_id, stage, draw_date, recorded_at, clinic_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (nat_id, stage) DO UPDATE
                   SET draw_date = EXCLUDED.draw_date, recorded_at = EXCLUDED.recorded_at""",
                (nat_id, stage, draw_iso_date, datetime.now().isoformat(), clinic_id),
            )


def clear_mspt_blood_used(nat_id: str, stage: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mspt_blood_used WHERE nat_id = %s AND stage = %s AND clinic_id = %s",
                (nat_id, stage, clinic_id),
            )


def get_submitted_keys(clinic_id: int = 1) -> set[tuple[str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, mspt_stage FROM submitted WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["mspt_stage"]) for r in rows}


def mark_mspt_phone_completed(entry: FollowupEntry, nurse: str = "", blood_draw_date: str | None = None, clinic_id: int = 1) -> None:
    """Record a phone-contact completion: marks entry as contacted AND adds to phone_completed
    so it flows into 可申報 without needing a clinic visit."""
    mark_contacted(entry, nurse, clinic_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mspt_phone_completed
                   (chart_number, mspt_stage, due_date, name, birth_date, blood_draw_date, completed_at, nurse, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (chart_number, mspt_stage, due_date) DO UPDATE SET
                       blood_draw_date = EXCLUDED.blood_draw_date,
                       completed_at = EXCLUDED.completed_at,
                       nurse = EXCLUDED.nurse""",
                (
                    entry.patient.chart_number, entry.mspt_stage, entry.due_date.isoformat(),
                    entry.patient.name, entry.patient.birth_date.isoformat(),
                    blood_draw_date, date.today().isoformat(), nurse, clinic_id,
                ),
            )


def get_mspt_phone_completed_submittable(clinic_id: int = 1) -> list:
    """Return phone-completed entries as MsptSubmittableEntry objects for the 可申報 queue."""
    from models import MsptSubmittableEntry, Patient
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, mspt_stage, due_date, name, birth_date, blood_draw_date, completed_at
                   FROM mspt_phone_completed WHERE clinic_id = %s""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    results = []
    for row in rows:
        blood_iso = row["blood_draw_date"] or row["completed_at"]
        try:
            blood_date = date.fromisoformat(blood_iso)
        except (ValueError, TypeError):
            blood_date = date.today()
        results.append(MsptSubmittableEntry(
            patient=Patient(
                chart_number=row["chart_number"],
                name=row["name"],
                birth_date=date.fromisoformat(row["birth_date"]),
            ),
            mspt_stage=row["mspt_stage"],
            blood_report_date=blood_date,
            days_since_last_stage=0,
        ))
    return results


def get_mspt_phone_completed_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, mspt_stage, due_date FROM mspt_phone_completed WHERE clinic_id = %s",
                (clinic_id,),
            )
            return {(r["chart_number"], r["mspt_stage"], r["due_date"]) for r in cur.fetchall()}


def unmark_mspt_phone_completed(chart_number: str, mspt_stage: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mspt_phone_completed WHERE chart_number = %s AND mspt_stage = %s AND clinic_id = %s",
                (chart_number, mspt_stage, clinic_id),
            )


# ── Called entries split: recent vs auto-excluded ────────────────────────────

def get_called_entries(clinic_id: int = 1) -> list[FollowupEntry]:
    """Entries in 已二次通知 that are still within AUTO_EXCLUDE_DAYS."""
    cutoff = (date.today() - timedelta(days=AUTO_EXCLUDE_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                          days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at,
                          contacted_time, phone, mobile
                   FROM contacts WHERE clinic_id=%s AND attempt=2 AND contacted_at > %s""",
                (clinic_id, cutoff),
            )
            rows = cur.fetchall()
    return [
        _rows_to_followup_entries([r])[0].model_copy(
            update={
                "contacted_at": date.fromisoformat(r["contacted_at"]) if r["contacted_at"] else None,
                "contacted_time": r["contacted_time"],
            }
        )
        for r in rows
    ]


def get_auto_excluded_entries(clinic_id: int = 1) -> list[ExcludedEntry]:
    """Called entries older than AUTO_EXCLUDE_DAYS → shown as auto-excluded."""
    cutoff = (date.today() - timedelta(days=AUTO_EXCLUDE_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                          days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at
                   FROM contacts WHERE clinic_id=%s AND attempt=2 AND contacted_at <= %s""",
                (clinic_id, cutoff),
            )
            rows = cur.fetchall()
    result = []
    for r in rows:
        entry = _rows_to_followup_entries([r])[0]
        result.append(ExcludedEntry(
            patient=entry.patient,
            category=entry.category,
            mspt_stage=entry.mspt_stage,
            due_date=entry.due_date,
            last_visit_date=entry.last_visit_date,
            reason='長期未回應',
            excluded_at=date.fromisoformat(r["contacted_at"]) if r["contacted_at"] else date.today(),
            auto=True,
        ))
    return result


# ── Manual exclusion ──────────────────────────────────────────────────────────

def mark_excluded(entry: FollowupEntry, reason: str, note: str = '', nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO excluded
                   (chart_number, category, name, birth_date, mspt_stage, due_date,
                    last_visit_date, last_stage, reason, note, excluded_at, nurse, clinic_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chart_number, category) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       mspt_stage=EXCLUDED.mspt_stage, due_date=EXCLUDED.due_date,
                       last_visit_date=EXCLUDED.last_visit_date, last_stage=EXCLUDED.last_stage,
                       reason=EXCLUDED.reason, note=EXCLUDED.note,
                       excluded_at=EXCLUDED.excluded_at, nurse=EXCLUDED.nurse""",
                (
                    entry.patient.chart_number, entry.category,
                    entry.patient.name, entry.patient.birth_date.isoformat(),
                    entry.mspt_stage,
                    entry.due_date.isoformat() if entry.due_date else None,
                    entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                    entry.last_stage, reason, note, date.today().isoformat(), nurse, clinic_id,
                ),
            )


def unmark_excluded(chart_number: str, category: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM excluded WHERE chart_number=%s AND category=%s AND clinic_id=%s",
                (chart_number, category, clinic_id),
            )


def get_excluded_keys(clinic_id: int = 1) -> set[tuple[str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, category FROM excluded WHERE clinic_id=%s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["category"]) for r in rows}


def get_excluded_entries(clinic_id: int = 1) -> list[ExcludedEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, category, name, birth_date, mspt_stage, due_date,
                          last_visit_date, last_stage, reason, note, excluded_at
                   FROM excluded WHERE clinic_id=%s ORDER BY excluded_at DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(ExcludedEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            category=r["category"],
            mspt_stage=r["mspt_stage"],
            due_date=date.fromisoformat(r["due_date"]) if r["due_date"] else None,
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            last_stage=r["last_stage"],
            reason=r["reason"],
            note=r["note"] or '',
            excluded_at=date.fromisoformat(r["excluded_at"]),
            auto=False,
        ))
    return result


# ── MSPT completed (完成MSPT) ──────────────────────────────────────────────

def mark_mspt_completed(entry: FollowupEntry, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mspt_completed
                   (chart_number, mspt_stage, due_date, name, birth_date,
                    last_visit_date, last_stage, days_overdue, completed_at, completed_time, nurse, clinic_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chart_number, mspt_stage, due_date) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       last_visit_date=EXCLUDED.last_visit_date, last_stage=EXCLUDED.last_stage,
                       days_overdue=EXCLUDED.days_overdue, completed_at=EXCLUDED.completed_at,
                       completed_time=EXCLUDED.completed_time, nurse=EXCLUDED.nurse""",
                (
                    entry.patient.chart_number, entry.mspt_stage,
                    entry.due_date.isoformat(),
                    entry.patient.name, entry.patient.birth_date.isoformat(),
                    entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                    entry.last_stage, entry.days_overdue, date.today().isoformat(),
                    datetime.now(_TW).strftime('%H:%M'), nurse, clinic_id,
                ),
            )


def unmark_mspt_completed(chart_number: str, mspt_stage: str, due_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mspt_completed WHERE chart_number=%s AND mspt_stage=%s AND due_date=%s AND clinic_id=%s",
                (chart_number, mspt_stage, due_date, clinic_id),
            )


def get_mspt_completed_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, mspt_stage, due_date FROM mspt_completed WHERE clinic_id=%s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["mspt_stage"], r["due_date"]) for r in rows}


def mark_mspt_checkedin(entry: FollowupEntry, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mspt_checkedin
                   (chart_number, mspt_stage, due_date, name, birth_date,
                    last_visit_date, last_stage, days_overdue, contact_reason,
                    checkedin_at, checkedin_time, nurse, clinic_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chart_number, mspt_stage, due_date) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       last_visit_date=EXCLUDED.last_visit_date, last_stage=EXCLUDED.last_stage,
                       days_overdue=EXCLUDED.days_overdue, contact_reason=EXCLUDED.contact_reason,
                       checkedin_at=EXCLUDED.checkedin_at, checkedin_time=EXCLUDED.checkedin_time,
                       nurse=EXCLUDED.nurse""",
                (
                    entry.patient.chart_number, entry.mspt_stage,
                    entry.due_date.isoformat(),
                    entry.patient.name, entry.patient.birth_date.isoformat(),
                    entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                    entry.last_stage, entry.days_overdue, entry.contact_reason,
                    date.today().isoformat(), datetime.now().strftime('%H:%M'), nurse, clinic_id,
                ),
            )


def unmark_mspt_checkedin(chart_number: str, mspt_stage: str, due_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mspt_checkedin WHERE chart_number=%s AND mspt_stage=%s AND due_date=%s AND clinic_id=%s",
                (chart_number, mspt_stage, due_date, clinic_id),
            )


def get_mspt_checkedin_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, mspt_stage, due_date FROM mspt_checkedin WHERE clinic_id=%s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["mspt_stage"], r["due_date"]) for r in rows}


def get_mspt_checkedin_entries(clinic_id: int = 1) -> list[FollowupEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                          last_visit_date, last_stage, days_overdue, contact_reason,
                          checkedin_at, checkedin_time, nurse
                   FROM mspt_checkedin WHERE clinic_id=%s ORDER BY checkedin_at DESC, checkedin_time DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        FollowupEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            disease_name='代謝症候群',
            mspt_stage=r["mspt_stage"],
            due_date=date.fromisoformat(r["due_date"]),
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            last_stage=r["last_stage"],
            days_overdue=r["days_overdue"],
            contact_reason=r["contact_reason"],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r["checkedin_at"]) if r["checkedin_at"] else None,
            contacted_time=r["checkedin_time"],
            nurse=r["nurse"] or "",
        )
        for r in rows
    ]


def mark_hep_returned_completed(entry: FollowupEntry, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hep_returned_completed
                   (chart_number, last_visit_date, name, birth_date, disease_name,
                    days_overdue, completed_at, completed_time, nurse, clinic_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chart_number, last_visit_date) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       disease_name=EXCLUDED.disease_name, days_overdue=EXCLUDED.days_overdue,
                       completed_at=EXCLUDED.completed_at, completed_time=EXCLUDED.completed_time,
                       nurse=EXCLUDED.nurse""",
                (
                    entry.patient.chart_number,
                    entry.last_visit_date.isoformat(),
                    entry.patient.name, entry.patient.birth_date.isoformat(),
                    entry.disease_name, entry.days_overdue,
                    date.today().isoformat(), datetime.now().strftime('%H:%M'), nurse, clinic_id,
                ),
            )


def unmark_hep_returned_completed(chart_number: str, last_visit_date: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM hep_returned_completed WHERE chart_number=%s AND last_visit_date=%s AND clinic_id=%s",
                (chart_number, last_visit_date, clinic_id),
            )


def get_hep_returned_completed_keys(clinic_id: int = 1) -> set[tuple[str, str]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, last_visit_date FROM hep_returned_completed WHERE clinic_id=%s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["last_visit_date"]) for r in rows}


def get_hep_completed_latest_map(clinic_id: int = 1) -> dict[str, str]:
    """Returns {chart_number: most recent completed last_visit_date} for
    suppressing 待聯絡 entries a nurse has manually marked 完成B肝 on."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, MAX(last_visit_date) AS max_date FROM hep_returned_completed WHERE clinic_id=%s GROUP BY chart_number",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {r["chart_number"]: r["max_date"] for r in rows}


def get_hep_returned_completed_entries(clinic_id: int = 1) -> list[FollowupEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, last_visit_date, name, birth_date, disease_name,
                          days_overdue, completed_at, completed_time, nurse
                   FROM hep_returned_completed WHERE clinic_id=%s ORDER BY completed_at DESC, completed_time DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        FollowupEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            disease_name=r["disease_name"],
            due_date=date.fromisoformat(r["last_visit_date"]),
            days_overdue=r["days_overdue"],
            last_visit_date=date.fromisoformat(r["last_visit_date"]),
            category='B肝',
            contacted_at=date.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
            contacted_time=r["completed_time"],
            nurse=r["nurse"] or "",
        )
        for r in rows
    ]


def log_line_notification(
    chart_number: str, name: str, birth_date: str, category: str, template: str,
    status: str, detail: str, dry_run: bool, nurse: str = '', clinic_id: int = 1,
) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_notification_log
                   (chart_number, name, birth_date, category, template, status, detail,
                    dry_run, nurse, sent_at, sent_time, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (chart_number, name, birth_date, category, template, status, detail,
                 int(dry_run), nurse, date.today().isoformat(), datetime.now().strftime('%H:%M'), clinic_id),
            )
            return cur.fetchone()["id"]


def get_line_notification_log(limit: int = 300, clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chart_number, name, birth_date, category, template, status, detail,
                          dry_run, nurse, sent_at, sent_time, undone_at, undone_by
                   FROM line_notification_log WHERE clinic_id=%s ORDER BY id DESC LIMIT %s""",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def get_line_notification_log_entry(log_id: int, clinic_id: int = 1) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chart_number, name, birth_date, category, template, status, detail,
                          dry_run, nurse, sent_at, sent_time, undone_at, undone_by
                   FROM line_notification_log WHERE id = %s AND clinic_id = %s""",
                (log_id, clinic_id),
            )
            row = cur.fetchone()
    return dict(row) if row is not None else None


def mark_line_notification_undone(log_id: int, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE line_notification_log SET undone_at = %s, undone_by = %s WHERE id = %s AND clinic_id = %s",
                (datetime.now().strftime('%Y-%m-%d %H:%M'), nurse, log_id, clinic_id),
            )


def flag_line_unlinked(chart_number: str, name: str, nurse: str = '', clinic_id: int = 1) -> None:
    """Mark a patient as having no LINE account linked to Alleypin, so the
    main dashboard can tag them in their existing pending list (across
    whichever categories they appear in) to contact by phone instead."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_unlinked (chart_number, name, flagged_at, nurse, clinic_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT(chart_number) DO UPDATE SET
                       flagged_at=EXCLUDED.flagged_at, nurse=EXCLUDED.nurse""",
                (chart_number, name, date.today().isoformat(), nurse, clinic_id),
            )


def clear_line_unlinked(chart_number: str, clinic_id: int = 1) -> None:
    """Called when a later send to this patient actually succeeds — their
    LINE is evidently linked now, so the flag no longer applies."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM line_unlinked WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )


def get_line_unlinked_chart_numbers(clinic_id: int = 1) -> set[str]:
    """Bulk-fetch flagged chart numbers for applying the tag while building
    a report, instead of querying once per patient."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number FROM line_unlinked WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {r["chart_number"] for r in rows}


def flag_alleypin_not_found(chart_number: str, name: str, nurse: str = '', clinic_id: int = 1) -> None:
    """Mark a patient as not found in Alleypin's own patient list at all
    (distinct from line_unlinked — found but not LINE-linked), so the main
    dashboard can tag them to contact by phone instead."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO alleypin_not_found (chart_number, name, flagged_at, nurse, clinic_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT(chart_number) DO UPDATE SET
                       flagged_at=EXCLUDED.flagged_at, nurse=EXCLUDED.nurse""",
                (chart_number, name, date.today().isoformat(), nurse, clinic_id),
            )


def clear_alleypin_not_found(chart_number: str, clinic_id: int = 1) -> None:
    """Called whenever a later attempt actually finds this patient on
    Alleypin (sent, line_not_linked, or recently_sent all imply they were
    found this time) — the flag no longer applies."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM alleypin_not_found WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )


def get_alleypin_not_found_chart_numbers(clinic_id: int = 1) -> set[str]:
    """Bulk-fetch flagged chart numbers for applying the tag while building
    a report, instead of querying once per patient."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number FROM alleypin_not_found WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {r["chart_number"] for r in rows}


def record_line_sent(chart_number: str, template: str, name: str, last_sent_at: str, nurse: str = '', clinic_id: int = 1) -> None:
    """Record the most recent known send date for a (patient, template) pair —
    called whether a send just succeeded (last_sent_at = today) or was skipped
    as a recent duplicate (last_sent_at = whatever Alleypin already showed).
    Either way this is the freshest known date, so it's always an upsert."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO line_recently_sent (chart_number, template, name, last_sent_at, nurse, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT(chart_number, template) DO UPDATE SET
                       name=EXCLUDED.name, last_sent_at=EXCLUDED.last_sent_at, nurse=EXCLUDED.nurse""",
                (chart_number, template, name, last_sent_at, nurse, clinic_id),
            )


def get_line_recently_sent_map(clinic_id: int = 1) -> dict[tuple[str, str], str]:
    """Bulk-fetch {(chart_number, template): last_sent_at} so a report can
    compute "days since" freshly against today, rather than baking in a
    stale day-count at write time."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, template, last_sent_at FROM line_recently_sent WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["template"]): r["last_sent_at"] for r in rows}


def get_mspt_completed_entries(clinic_id: int = 1) -> list[FollowupEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                          last_visit_date, last_stage, days_overdue, completed_at
                   FROM mspt_completed WHERE clinic_id=%s ORDER BY completed_at DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        FollowupEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            disease_name='代謝症候群',
            mspt_stage=r["mspt_stage"],
            due_date=date.fromisoformat(r["due_date"]),
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            last_stage=r["last_stage"],
            days_overdue=r["days_overdue"],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r["completed_at"]),
        )
        for r in rows
    ]


def get_print_history(target_date_iso: str, clinic_id: int = 1) -> dict:
    """Return all contacts recorded on a given date, split by attempt (1=contacted, 2=called)
    plus any MSPT completions recorded on the same date."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                          days_overdue, mspt_stage, contact_reason, last_visit_date,
                          contacted_at, contacted_time, attempt, nurse
                   FROM contacts WHERE clinic_id=%s AND contacted_at = %s
                   ORDER BY contacted_time NULLS LAST""",
                (clinic_id, target_date_iso),
            )
            contact_rows = cur.fetchall()
            cur.execute(
                """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                          last_visit_date, last_stage, days_overdue, completed_at, completed_time, nurse
                   FROM mspt_completed WHERE clinic_id=%s AND completed_at = %s
                   ORDER BY completed_time NULLS LAST""",
                (clinic_id, target_date_iso),
            )
            mc_rows = cur.fetchall()
            cur.execute(
                """SELECT chart_number, name, birth_date, category, mspt_stage,
                          due_date, last_visit_date, last_stage, reason, note, nurse
                   FROM excluded WHERE clinic_id=%s AND excluded_at = %s""",
                (clinic_id, target_date_iso),
            )
            excl_rows = cur.fetchall()
            cur.execute(
                """SELECT chart_number, name, birth_date, pickup_date, ps_days, nurse
                   FROM manual_pickups WHERE clinic_id=%s AND recorded_at = %s""",
                (clinic_id, target_date_iso),
            )
            pickup_rows = cur.fetchall()

    contacted, called = [], []
    for r in contact_rows:
        entry = _rows_to_followup_entries([r])[0].model_copy(
            update={
                "contacted_at": date.fromisoformat(r["contacted_at"]) if r["contacted_at"] else None,
                "contacted_time": r["contacted_time"],
                "nurse": r["nurse"] or "",
            }
        )
        (contacted if r["attempt"] == 1 else called).append(entry)

    mspt_completed = [
        FollowupEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            disease_name='代謝症候群',
            mspt_stage=r["mspt_stage"],
            due_date=date.fromisoformat(r["due_date"]),
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            last_stage=r["last_stage"],
            days_overdue=r["days_overdue"],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
            contacted_time=r["completed_time"],
            nurse=r["nurse"] or "",
        )
        for r in mc_rows
    ]
    excluded = [
        ExcludedEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            category=r["category"],
            mspt_stage=r["mspt_stage"],
            due_date=date.fromisoformat(r["due_date"]) if r["due_date"] else None,
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            last_stage=r["last_stage"],
            reason=r["reason"],
            note=r["note"] or '',
            excluded_at=date.fromisoformat(target_date_iso),
            nurse=r["nurse"] or "",
        )
        for r in excl_rows
    ]
    manual_pickups = [
        ManualPickupEntry(
            chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"]),
            pickup_date=date.fromisoformat(r["pickup_date"]), ps_days=r["ps_days"],
            next_due=date.fromisoformat(r["pickup_date"]) + timedelta(days=r["ps_days"]),
            nurse=r["nurse"] or "",
        )
        for r in pickup_rows
    ]
    return {
        "contacted": contacted, "called": called, "mspt_completed": mspt_completed,
        "excluded": excluded, "manual_pickups": manual_pickups,
    }


def mark_manual_pickup(entry: FollowupEntry, pickup_date: date, ps_days: int, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO manual_pickups
                   (chart_number, name, birth_date, pickup_date, ps_days, recorded_at, nurse, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (chart_number) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       pickup_date=EXCLUDED.pickup_date, ps_days=EXCLUDED.ps_days,
                       recorded_at=EXCLUDED.recorded_at, nurse=EXCLUDED.nurse""",
                (
                    entry.patient.chart_number,
                    entry.patient.name,
                    entry.patient.birth_date.isoformat(),
                    pickup_date.isoformat(),
                    ps_days,
                    date.today().isoformat(),
                    nurse,
                    clinic_id,
                ),
            )


def unmark_manual_pickup(chart_number: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM manual_pickups WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )


def get_manual_pickup_map(clinic_id: int = 1) -> dict[str, tuple[str, int]]:
    """Returns {chart_number: (pickup_date_iso, ps_days)} for suppression filtering."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, pickup_date, ps_days FROM manual_pickups WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {r["chart_number"]: (r["pickup_date"], r["ps_days"]) for r in rows}


def get_manual_pickup_entries(clinic_id: int = 1) -> list[ManualPickupEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, name, birth_date, pickup_date, ps_days FROM manual_pickups WHERE clinic_id = %s ORDER BY recorded_at DESC",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        ManualPickupEntry(
            chart_number=r["chart_number"],
            name=r["name"],
            birth_date=date.fromisoformat(r["birth_date"]),
            pickup_date=date.fromisoformat(r["pickup_date"]),
            ps_days=r["ps_days"],
            next_due=date.fromisoformat(r["pickup_date"]) + timedelta(days=r["ps_days"]),
        )
        for r in rows
    ]


def mark_mspt_manual(chart_number: str, name: str, birth_date: date, mspt_stage: str,
                     completed_date: date, nurse: str = '', clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mspt_manual
                   (chart_number, name, birth_date, mspt_stage, completed_date, nurse, marked_at, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (chart_number) DO UPDATE SET
                       name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                       mspt_stage=EXCLUDED.mspt_stage, completed_date=EXCLUDED.completed_date,
                       nurse=EXCLUDED.nurse, marked_at=EXCLUDED.marked_at""",
                (chart_number, name, birth_date.isoformat(), mspt_stage,
                 completed_date.isoformat(), nurse, date.today().isoformat(), clinic_id),
            )


def unmark_mspt_manual(chart_number: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mspt_manual WHERE chart_number = %s AND clinic_id = %s",
                (chart_number, clinic_id),
            )


def get_mspt_manual_overrides(clinic_id: int = 1) -> dict[str, dict]:
    """Returns {chart_number: {'stage': str, 'date': date}} for post-processing in get_report."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, mspt_stage, completed_date FROM mspt_manual WHERE clinic_id = %s",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {r["chart_number"]: {'stage': r["mspt_stage"], 'date': date.fromisoformat(r["completed_date"])} for r in rows}


def get_mspt_manual_entries(clinic_id: int = 1) -> list[MsptManualEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, mspt_stage, completed_date, nurse, marked_at
                   FROM mspt_manual WHERE clinic_id = %s ORDER BY marked_at DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        MsptManualEntry(
            chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"]),
            mspt_stage=r["mspt_stage"], completed_date=date.fromisoformat(r["completed_date"]),
            nurse=r["nurse"] or '', marked_at=date.fromisoformat(r["marked_at"]),
        )
        for r in rows
    ]


def get_activity_stats(month: str, clinic_id: int = 1) -> dict[str, dict[str, int]]:
    """month: 'YYYY-MM'. Returns {nurse: {contacted, called, mspt, excluded, pickup}}."""
    prefix = month + "-%"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nurse, attempt, COUNT(*) AS cnt FROM contacts WHERE clinic_id=%s AND contacted_at LIKE %s GROUP BY nurse, attempt",
                (clinic_id, prefix))
            c_rows = cur.fetchall()
            cur.execute(
                "SELECT nurse, COUNT(*) AS cnt FROM mspt_completed WHERE clinic_id=%s AND completed_at LIKE %s GROUP BY nurse",
                (clinic_id, prefix))
            m_rows = cur.fetchall()
            cur.execute(
                "SELECT nurse, COUNT(*) AS cnt FROM excluded WHERE clinic_id=%s AND excluded_at LIKE %s GROUP BY nurse",
                (clinic_id, prefix))
            ex_rows = cur.fetchall()
            cur.execute(
                "SELECT nurse, COUNT(*) AS cnt FROM manual_pickups WHERE clinic_id=%s AND recorded_at LIKE %s GROUP BY nurse",
                (clinic_id, prefix))
            pk_rows = cur.fetchall()

    stats: dict[str, dict[str, int]] = {}

    def _row(nurse: str) -> dict[str, int]:
        key = nurse or "（未選擇）"
        if key not in stats:
            stats[key] = {"contacted": 0, "called": 0, "mspt": 0, "excluded": 0, "pickup": 0}
        return stats[key]

    for r in c_rows:
        row = _row(r["nurse"])
        if r["attempt"] == 1:
            row["contacted"] += r["cnt"]
        else:
            row["called"] += r["cnt"]
    for r in m_rows:
        _row(r["nurse"])["mspt"] += r["cnt"]
    for r in ex_rows:
        _row(r["nurse"])["excluded"] += r["cnt"]
    for r in pk_rows:
        _row(r["nurse"])["pickup"] += r["cnt"]

    return stats


def mark_on_hold(entry: FollowupEntry, note: str, nurse: str = '', clinic_id: int = 1) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO on_hold
                   (chart_number, category, due_date, name, birth_date, disease_name,
                    days_overdue, mspt_stage, last_stage, last_visit_date, note, held_at, nurse, is_manual, phone, mobile, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                   RETURNING id""",
                (
                    entry.patient.chart_number,
                    entry.category,
                    entry.due_date.isoformat(),
                    entry.patient.name,
                    entry.patient.birth_date.isoformat(),
                    entry.disease_name,
                    entry.days_overdue,
                    entry.mspt_stage,
                    entry.last_stage,
                    entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                    note,
                    date.today().isoformat(),
                    nurse,
                    entry.phone,
                    entry.mobile,
                    clinic_id,
                ),
            )
            return cur.fetchone()["id"]


def mark_on_hold_manual(name: str, note: str, nurse: str = '', category: str | None = None, clinic_id: int = 1) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO on_hold (name, category, note, held_at, nurse, is_manual, clinic_id)
                   VALUES (%s, %s, %s, %s, %s, 1, %s)
                   RETURNING id""",
                (name, category, note, date.today().isoformat(), nurse, clinic_id),
            )
            return cur.fetchone()["id"]


def remove_on_hold(hold_id: int, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM on_hold WHERE id = %s AND clinic_id = %s",
                (hold_id, clinic_id),
            )


def get_on_hold_keys(clinic_id: int = 1) -> set[tuple[str, str, str]]:
    """(chart_number, category, due_date) for non-manual entries — used to filter the main list."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chart_number, category, due_date FROM on_hold WHERE clinic_id=%s AND is_manual = 0 AND chart_number IS NOT NULL",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return {(r["chart_number"], r["category"], r["due_date"]) for r in rows}


def get_on_hold_entries(clinic_id: int = 1) -> list[OnHoldEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chart_number, category, due_date, name, birth_date, disease_name,
                          days_overdue, mspt_stage, last_stage, last_visit_date, note, held_at, nurse, is_manual,
                          phone, mobile
                   FROM on_hold WHERE clinic_id=%s ORDER BY held_at DESC""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    result = []
    for r in rows:
        is_manual = bool(r["is_manual"])
        result.append(OnHoldEntry(
            hold_id=r["id"],
            patient=Patient(
                chart_number=r["chart_number"] or '',
                name=r["name"],
                birth_date=date.fromisoformat(r["birth_date"]) if r["birth_date"] else date.today(),
            ) if not is_manual else None,
            category=r["category"],
            due_date=date.fromisoformat(r["due_date"]) if r["due_date"] else None,
            days_overdue=r["days_overdue"],
            mspt_stage=r["mspt_stage"],
            last_stage=r["last_stage"],
            last_visit_date=date.fromisoformat(r["last_visit_date"]) if r["last_visit_date"] else None,
            disease_name=r["disease_name"],
            note=r["note"],
            held_at=date.fromisoformat(r["held_at"]),
            nurse=r["nurse"] or '',
            phone=r.get("phone", "") or "",
            mobile=r.get("mobile", "") or "",
            is_manual=is_manual,
            manual_name=r["name"] if is_manual else '',
        ))
    return result


def get_submitted_entries(clinic_id: int = 1) -> list[MsptSubmittableEntry]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, mspt_stage, blood_report_date, days_since_last_stage
                   FROM submitted WHERE clinic_id = %s""",
                (clinic_id,),
            )
            rows = cur.fetchall()
    return [
        MsptSubmittableEntry(
            patient=Patient(chart_number=r["chart_number"], name=r["name"], birth_date=date.fromisoformat(r["birth_date"])),
            mspt_stage=r["mspt_stage"],
            blood_report_date=date.fromisoformat(r["blood_report_date"]),
            days_since_last_stage=r["days_since_last_stage"],
        )
        for r in rows
    ]


def get_shifts_for_week(week_start: str, clinic_id: int = 1) -> list[dict]:
    week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT nurse, shift_date, slot, start_time, end_time, clean_start, clean_end FROM shifts
                   WHERE clinic_id=%s AND shift_date BETWEEN %s AND %s""",
                (clinic_id, week_start, week_end),
            )
            return [dict(r) for r in cur.fetchall()]


def set_shift(
    nurse: str, shift_date: str, slot: str, start_time: str | None, end_time: str | None,
    clean_start: str | None = None, clean_end: str | None = None, clinic_id: int = 1,
) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            if start_time is None and end_time is None:
                cur.execute(
                    "DELETE FROM shifts WHERE nurse = %s AND shift_date = %s AND slot = %s AND clinic_id = %s",
                    (nurse, shift_date, slot, clinic_id),
                )
            else:
                cur.execute(
                    """INSERT INTO shifts (nurse, shift_date, slot, start_time, end_time, clean_start, clean_end, clinic_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT(nurse, shift_date, slot) DO UPDATE SET
                           start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                           clean_start=EXCLUDED.clean_start, clean_end=EXCLUDED.clean_end""",
                    (nurse, shift_date, slot, start_time, end_time, clean_start, clean_end, clinic_id),
                )


def copy_week(from_week_start: str, to_week_start: str, clinic_id: int = 1) -> None:
    """Copies every shift entry in from_week_start's week to the same weekday in
    to_week_start's week, overwriting any existing entries there."""
    day_delta = (date.fromisoformat(to_week_start) - date.fromisoformat(from_week_start)).days
    rows = get_shifts_for_week(from_week_start, clinic_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                new_date = (date.fromisoformat(r['shift_date']) + timedelta(days=day_delta)).isoformat()
                cur.execute(
                    """INSERT INTO shifts (nurse, shift_date, slot, start_time, end_time, clean_start, clean_end, clinic_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT(nurse, shift_date, slot) DO UPDATE SET
                           start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                           clean_start=EXCLUDED.clean_start, clean_end=EXCLUDED.clean_end""",
                    (r['nurse'], new_date, r['slot'], r['start_time'], r['end_time'], r['clean_start'], r['clean_end'], clinic_id),
                )


def get_nurses(clinic_id: int = 1) -> list[str]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM nurses WHERE clinic_id = %s ORDER BY sort_order, id",
                (clinic_id,),
            )
            return [r["name"] for r in cur.fetchall()]


def get_nurses_with_pin_status(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, (pin_hash IS NOT NULL) AS has_pin FROM nurses WHERE clinic_id = %s ORDER BY sort_order, id",
                (clinic_id,),
            )
            return [{"name": r["name"], "has_pin": bool(r["has_pin"])} for r in cur.fetchall()]


def set_nurse_pin(name: str, pin: str, clinic_id: int = 1) -> None:
    import bcrypt
    if not pin.isdigit() or len(pin) != 4:
        raise ValueError("PIN 必須是 4 位數字")
    pin_hash = bcrypt.hashpw(pin.encode(), bcrypt.gensalt(10)).decode()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE nurses SET pin_hash = %s WHERE name = %s AND clinic_id = %s",
                (pin_hash, name, clinic_id),
            )


def clear_nurse_pin(name: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE nurses SET pin_hash = NULL WHERE name = %s AND clinic_id = %s",
                (name, clinic_id),
            )


def verify_nurse_pin(name: str, pin: str, clinic_id: int = 1) -> bool:
    import bcrypt
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pin_hash FROM nurses WHERE name = %s AND clinic_id = %s",
                (name, clinic_id),
            )
            row = cur.fetchone()
    if not row or not row["pin_hash"]:
        return False
    return bcrypt.checkpw(pin.encode(), row["pin_hash"].encode())


def add_nurse(name: str, clinic_id: int = 1) -> bool:
    """Returns False (no-op) if the name already exists."""
    import bcrypt
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM nurses WHERE name = %s AND clinic_id = %s",
                (name, clinic_id),
            )
            if cur.fetchone():
                return False
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS max_order FROM nurses WHERE clinic_id = %s",
                (clinic_id,),
            )
            max_order = cur.fetchone()["max_order"]
            default_pin = bcrypt.hashpw(b'0000', bcrypt.gensalt(10)).decode()
            cur.execute(
                "INSERT INTO nurses (name, sort_order, pin_hash, clinic_id) VALUES (%s, %s, %s, %s)",
                (name, max_order + 1, default_pin, clinic_id)
            )
    return True


def remove_nurse(name: str, clinic_id: int = 1) -> None:
    """Removes the nurse from the roster. Past shift/contact records under
    this name are left untouched — only the active roster shrinks."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM nurses WHERE name = %s AND clinic_id = %s",
                (name, clinic_id),
            )


def rename_nurse(old_name: str, new_name: str, clinic_id: int = 1) -> bool:
    """Returns False (no-op) if new_name is already used by a different entry.
    Updates the roster and this week's-and-future shifts table so the renamed
    person's schedule carries over; older historical logs elsewhere (contacts,
    activity stats, etc.) keep the name as it was recorded at the time."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM nurses WHERE name = %s AND name != %s AND clinic_id = %s",
                (new_name, old_name, clinic_id),
            )
            if cur.fetchone():
                return False
            cur.execute(
                "UPDATE nurses SET name = %s WHERE name = %s AND clinic_id = %s",
                (new_name, old_name, clinic_id),
            )
            cur.execute(
                "UPDATE shifts SET nurse = %s WHERE nurse = %s AND clinic_id = %s",
                (new_name, old_name, clinic_id),
            )
    return True


def publish_week(week_start: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO published_weeks (week_start, clinic_id) VALUES (%s, %s) ON CONFLICT(week_start) DO NOTHING",
                (week_start, clinic_id),
            )


def unpublish_week(week_start: str, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM published_weeks WHERE week_start = %s AND clinic_id = %s",
                (week_start, clinic_id),
            )


def is_week_published(week_start: str, clinic_id: int = 1) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM published_weeks WHERE week_start = %s AND clinic_id = %s",
                (week_start, clinic_id),
            )
            return cur.fetchone() is not None


def add_bulletin_note(nurse: str, content: str, clinic_id: int = 1) -> dict:
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bulletin_notes (nurse, content, created_at, clinic_id) VALUES (%s, %s, %s, %s) RETURNING id",
                (nurse, content, created_at, clinic_id),
            )
            note_id = cur.fetchone()["id"]
    return {"id": note_id, "nurse": nurse, "content": content, "created_at": created_at}


def get_bulletin_notes(limit: int = 100, clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nurse, content, created_at FROM bulletin_notes WHERE clinic_id = %s ORDER BY id DESC LIMIT %s",
                (clinic_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def get_bulletin_note(note_id: int, clinic_id: int = 1) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nurse, content, created_at FROM bulletin_notes WHERE id = %s AND clinic_id = %s",
                (note_id, clinic_id),
            )
            row = cur.fetchone()
    return dict(row) if row is not None else None


def delete_bulletin_note(note_id: int, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM bulletin_notes WHERE id = %s AND clinic_id = %s",
                (note_id, clinic_id),
            )


def save_salary_record(
    nurse: str, month: str, attendance: int, performance: int,
    sat_pay: int, float_bonus: int, ot_pay: int, total: int, ot_entries: str,
    clinic_id: int = 1, sick_days: int = 0,
) -> dict:
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO salary_records
                   (nurse, month, attendance, performance, sat_pay, float_bonus, ot_pay, total, ot_entries, created_at, clinic_id, sick_days)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (nurse, month, attendance, performance, sat_pay, float_bonus, ot_pay, total, ot_entries, created_at, clinic_id, sick_days),
            )
            record_id = cur.fetchone()["id"]
    return {'id': record_id, 'nurse': nurse, 'month': month, 'attendance': attendance,
            'performance': performance, 'sat_pay': sat_pay, 'float_bonus': float_bonus,
            'ot_pay': ot_pay, 'total': total, 'ot_entries': ot_entries, 'created_at': created_at,
            'sick_days': sick_days}


def get_salary_records(nurse: str, month: str, clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, nurse, month, attendance, performance, sat_pay, float_bonus,
                          ot_pay, total, ot_entries, created_at, COALESCE(sick_days,0) AS sick_days
                   FROM salary_records WHERE clinic_id = %s AND nurse = %s AND month = %s ORDER BY id DESC""",
                (clinic_id, nurse, month),
            )
            return [dict(r) for r in cur.fetchall()]


def get_yearly_sick_days(nurse: str, year: int, clinic_id: int = 1) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(COALESCE(sick_days,0)),0) AS total
                   FROM salary_records WHERE clinic_id = %s AND nurse = %s AND month LIKE %s""",
                (clinic_id, nurse, f"{year}-%"),
            )
            return int(cur.fetchone()["total"])


def update_salary_record(
    record_id: int, attendance: int, performance: int,
    sat_pay: int, float_bonus: int, ot_pay: int, total: int, ot_entries: str,
    clinic_id: int = 1, sick_days: int = 0,
) -> None:
    updated_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE salary_records SET attendance=%s, performance=%s, sat_pay=%s, float_bonus=%s,
                   ot_pay=%s, total=%s, ot_entries=%s, created_at=%s, sick_days=%s WHERE id=%s AND clinic_id=%s""",
                (attendance, performance, sat_pay, float_bonus, ot_pay, total, ot_entries, updated_at, sick_days, record_id, clinic_id),
            )


def delete_salary_record(record_id: int, clinic_id: int = 1) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM salary_records WHERE id = %s AND clinic_id = %s",
                (record_id, clinic_id),
            )


# ── Nurse self-reported overtime logs ───────────────────────────────────────────

def get_nurse_ot_logs(nurse: str, clinic_id: int = 1, month: str | None = None, legacy_nurse: str = '') -> list[dict]:
    # Include records stored under the shared JWT display_name (pre-PIN-tracking era)
    nurses = list({n for n in [nurse, legacy_nurse] if n})
    placeholders = ','.join(['%s'] * len(nurses))
    with _conn() as conn:
        with conn.cursor() as cur:
            if month:
                cur.execute(
                    f"""SELECT id, nurse, date, start_time, end_time, note, created_at
                       FROM nurse_ot_logs
                       WHERE clinic_id=%s AND nurse IN ({placeholders}) AND date LIKE %s
                       ORDER BY date, start_time""",
                    (clinic_id, *nurses, month + '%'),
                )
            else:
                cur.execute(
                    f"""SELECT id, nurse, date, start_time, end_time, note, created_at
                       FROM nurse_ot_logs
                       WHERE clinic_id=%s AND nurse IN ({placeholders})
                       ORDER BY date DESC, start_time""",
                    (clinic_id, *nurses),
                )
            return [dict(r) for r in cur.fetchall()]


def add_nurse_ot_log(nurse: str, clinic_id: int, date: str, start_time: str, end_time: str, note: str = '') -> int:
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO nurse_ot_logs (clinic_id, nurse, date, start_time, end_time, note, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (clinic_id, nurse, date, start_time, end_time, note.strip(), created_at),
            )
            return cur.fetchone()["id"]


def delete_nurse_ot_log(log_id: int, clinic_id: int = 1) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM nurse_ot_logs WHERE id=%s AND clinic_id=%s",
                (log_id, clinic_id),
            )
            return cur.rowcount > 0


def get_contact_history(q: str, clinic_id: int = 1) -> list[dict]:
    """Return all recorded events for a patient matching chart_number or name."""
    events: list[dict] = []
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, category, attempt,
                          contacted_at, contacted_time, nurse, disease_name, mspt_stage
                   FROM contacts
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY contacted_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                events.append({
                    "type": "called" if r["attempt"] >= 2 else "contacted",
                    "date": r["contacted_at"],
                    "time": r["contacted_time"],
                    "nurse": r["nurse"] or "",
                    "category": r["category"],
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": r["mspt_stage"] or r["disease_name"] or "",
                })

            cur.execute(
                """SELECT chart_number, name, category, template, status,
                          sent_at, sent_time, nurse, dry_run, undone_at
                   FROM line_notification_log
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY sent_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                detail = r["template"]
                if r["dry_run"]: detail += "（測試）"
                if r["undone_at"]: detail += "（已撤銷）"
                if r["status"] != "ok": detail += f" [{r['status']}]"
                events.append({
                    "type": "line",
                    "date": r["sent_at"],
                    "time": r["sent_time"],
                    "nurse": r["nurse"] or "",
                    "category": r["category"],
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": detail,
                })

            cur.execute(
                """SELECT chart_number, name, category, note, held_at, nurse
                   FROM on_hold
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY held_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                events.append({
                    "type": "hold",
                    "date": r["held_at"],
                    "time": None,
                    "nurse": r["nurse"] or "",
                    "category": r["category"] or "",
                    "chart_number": r["chart_number"] or "",
                    "name": r["name"],
                    "detail": r["note"] or "",
                })

            cur.execute(
                """SELECT chart_number, name, category, reason, note, excluded_at, nurse
                   FROM excluded
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY excluded_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                detail = r["reason"]
                if r["note"]: detail += f"：{r['note']}"
                events.append({
                    "type": "excluded",
                    "date": r["excluded_at"],
                    "time": None,
                    "nurse": r["nurse"] or "",
                    "category": r["category"],
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": detail,
                })

            cur.execute(
                """SELECT chart_number, name, mspt_stage, completed_at, completed_time, nurse
                   FROM mspt_completed
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY completed_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                events.append({
                    "type": "mspt_completed",
                    "date": r["completed_at"],
                    "time": r["completed_time"],
                    "nurse": r["nurse"] or "",
                    "category": "代謝症候群",
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": r["mspt_stage"] or "",
                })

            cur.execute(
                """SELECT chart_number, name, mspt_stage, checkedin_at, checkedin_time, nurse
                   FROM mspt_checkedin
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY checkedin_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                events.append({
                    "type": "checkedin",
                    "date": r["checkedin_at"],
                    "time": r["checkedin_time"],
                    "nurse": r["nurse"] or "",
                    "category": "代謝症候群",
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": r["mspt_stage"] or "",
                })

            cur.execute(
                """SELECT chart_number, name, completed_at, completed_time, nurse, disease_name
                   FROM hep_returned_completed
                   WHERE clinic_id=%s AND (chart_number=%s OR name ILIKE %s)
                   ORDER BY completed_at DESC""",
                (clinic_id, q, like),
            )
            for r in cur.fetchall():
                events.append({
                    "type": "hep_completed",
                    "date": r["completed_at"],
                    "time": r["completed_time"],
                    "nurse": r["nurse"] or "",
                    "category": "B肝",
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "detail": r["disease_name"] or "",
                })

    events.sort(key=lambda e: (e["date"] or "", e["time"] or ""), reverse=True)
    return events


def search_patients_cloud(q: str, clinic_id: int = 1, limit: int = 8) -> list[dict]:
    """Search synced_candidates by name or chart_number; returns deduplicated patients."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, MAX(name) AS name, MAX(phone) AS phone,
                          MAX(mobile) AS mobile, MAX(birth_date) AS birth_date,
                          array_agg(DISTINCT category) AS categories
                   FROM synced_candidates
                   WHERE clinic_id = %s AND (name ILIKE %s OR chart_number ILIKE %s)
                   GROUP BY chart_number
                   ORDER BY MAX(name)
                   LIMIT %s""",
                (clinic_id, like, like, limit),
            )
            rows = []
            for r in cur.fetchall():
                bd = r["birth_date"]
                rows.append({
                    "chart_number": r["chart_number"],
                    "name": r["name"],
                    "phone": r["phone"] or "",
                    "mobile": r["mobile"] or "",
                    "birth_date": bd.isoformat() if hasattr(bd, "isoformat") else (bd or ""),
                    "categories": sorted(r["categories"]),
                })
            return rows


def get_patient_profile(chart_number: str, clinic_id: int = 1) -> dict | None:
    """Return full patient data: basic info, follow-up entries, and contact history."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, name, birth_date, phone, mobile,
                          category, disease_name, due_date, days_overdue,
                          mspt_stage, contact_reason, last_visit_date, synced_at
                   FROM synced_candidates
                   WHERE clinic_id = %s AND chart_number = %s
                   ORDER BY category""",
                (clinic_id, chart_number),
            )
            rows = cur.fetchall()

    if not rows:
        return None

    first = rows[0]
    bd = first["birth_date"]
    sat = first["synced_at"]

    followups = []
    for r in rows:
        dd = r["due_date"]
        lv = r["last_visit_date"]
        followups.append({
            "category": r["category"],
            "disease_name": r["disease_name"] or "",
            "due_date": dd.isoformat() if hasattr(dd, "isoformat") else (dd or ""),
            "days_overdue": r["days_overdue"],
            "mspt_stage": r["mspt_stage"] or "",
            "contact_reason": r["contact_reason"] or "",
            "last_visit_date": lv.isoformat() if hasattr(lv, "isoformat") else (lv or ""),
        })

    history = get_contact_history(chart_number, clinic_id)

    return {
        "chart_number": first["chart_number"],
        "name": first["name"],
        "birth_date": bd.isoformat() if hasattr(bd, "isoformat") else (bd or ""),
        "phone": first["phone"] or "",
        "mobile": first["mobile"] or "",
        "synced_at": sat.isoformat() if hasattr(sat, "isoformat") else (sat or ""),
        "followups": followups,
        "history": history,
    }


def get_synced_candidates(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chart_number, category, name, birth_date, disease_name,
                          due_date, days_overdue, mspt_stage, contact_reason,
                          last_visit_date, phone, mobile, synced_at
                   FROM synced_candidates WHERE clinic_id = %s""",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def upsert_synced_candidates(candidates: list[dict], clinic_id: int = 1) -> None:
    from psycopg2.extras import execute_values
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM synced_candidates WHERE clinic_id = %s", (clinic_id,))
            if candidates:
                execute_values(
                    cur,
                    """INSERT INTO synced_candidates
                       (clinic_id, chart_number, category, name, birth_date, disease_name,
                        due_date, days_overdue, mspt_stage, contact_reason, last_visit_date,
                        phone, mobile, synced_at)
                       VALUES %s
                       ON CONFLICT (clinic_id, chart_number, category, due_date) DO UPDATE SET
                           name=EXCLUDED.name, birth_date=EXCLUDED.birth_date,
                           disease_name=EXCLUDED.disease_name,
                           days_overdue=EXCLUDED.days_overdue,
                           mspt_stage=EXCLUDED.mspt_stage,
                           contact_reason=EXCLUDED.contact_reason,
                           last_visit_date=EXCLUDED.last_visit_date,
                           phone=EXCLUDED.phone,
                           mobile=EXCLUDED.mobile,
                           synced_at=EXCLUDED.synced_at""",
                    [
                        (
                            clinic_id,
                            c["chart_number"], c["category"], c["name"], c["birth_date"],
                            c["disease_name"], c["due_date"], int(c["days_overdue"]),
                            c.get("mspt_stage"), c.get("contact_reason"), c.get("last_visit_date"),
                            c.get("phone", ""), c.get("mobile", ""),
                            c["synced_at"],
                        )
                        for c in candidates
                    ],
                )
