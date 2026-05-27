import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Generator

from models import ExcludedEntry, FollowupEntry, MsptStage, MsptSubmittableEntry, Patient

DB_PATH = "contacts.db"
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
        PRIMARY KEY (chart_number, category)
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
        PRIMARY KEY (chart_number, mspt_stage, due_date)
    )
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.commit()
    conn.close()


def init() -> None:
    with _conn() as conn:
        conn.execute(_CREATE_CONTACTS)
        conn.execute(_CREATE_SUBMITTED)
        conn.execute(_CREATE_EXCLUDED)
        conn.execute(_CREATE_MSPT_COMPLETED)
        # Migrations for existing databases
        for col in ("last_visit_date TEXT", "contacted_time TEXT"):
            try:
                conn.execute(f"ALTER TABLE contacts ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE mspt_completed ADD COLUMN completed_time TEXT")
        except sqlite3.OperationalError:
            pass


def _followup_to_row(entry: FollowupEntry, attempt: int) -> tuple:
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
        datetime.now().strftime('%H:%M'),
    )


def mark_contacted(entry: FollowupEntry) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO contacts
               (chart_number, category, due_date, name, birth_date, disease_name,
                days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                contacted_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                   attempt=1, contacted_at=excluded.contacted_at,
                   contacted_time=excluded.contacted_time""",
            _followup_to_row(entry, 1),
        )


def mark_called(entry: FollowupEntry) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO contacts
               (chart_number, category, due_date, name, birth_date, disease_name,
                days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                contacted_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                   attempt=2, contacted_at=excluded.contacted_at,
                   contacted_time=excluded.contacted_time""",
            _followup_to_row(entry, 2),
        )


def unmark(chart_number: str, category: str, due_date: date) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM contacts WHERE chart_number=? AND category=? AND due_date=?",
            (chart_number, category, due_date.isoformat()),
        )


def get_hidden_keys() -> set[tuple[str, str, str]]:
    """Keys to exclude from the pending list entirely.
    Includes: attempt=2 (permanent) and attempt=1 within the 7-day window."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, category, due_date FROM contacts
               WHERE attempt=2 OR (attempt=1 AND contacted_at > ?)""",
            (cutoff,),
        ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def get_call_required_keys() -> set[tuple[str, str, str]]:
    """Keys of attempt=1 contacts that have expired — re-surface with call flag."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, category, due_date FROM contacts WHERE attempt=1 AND contacted_at <= ?",
            (cutoff,),
        ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def _rows_to_followup_entries(rows: list) -> list[FollowupEntry]:
    return [
        FollowupEntry(
            patient=Patient(
                chart_number=r[0],
                name=r[1],
                birth_date=date.fromisoformat(r[2]),
            ),
            disease_name=r[3],
            category=r[4],
            due_date=date.fromisoformat(r[5]),
            days_overdue=r[6],
            mspt_stage=r[7],
            contact_reason=r[8],
            last_visit_date=date.fromisoformat(r[9]) if r[9] else None,
        )
        for r in rows
    ]


def get_contacted_with_dates() -> list[tuple[FollowupEntry, date]]:
    """Entries in the 7-day window paired with their contacted_at date, for return-visit filtering."""
    cutoff = (date.today() - timedelta(days=RECONTACT_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                      days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at,
                      contacted_time
               FROM contacts WHERE attempt=1 AND contacted_at > ?""",
            (cutoff,),
        ).fetchall()
    return [
        (
            _rows_to_followup_entries([r[:10]])[0].model_copy(
                update={"contacted_time": r[11]}
            ),
            date.fromisoformat(r[10])
        )
        for r in rows
    ]


def get_contacted_entries() -> list[FollowupEntry]:
    """Entries currently in the 7-day hiding window (attempt=1, recent)."""
    return [e for e, _ in get_contacted_with_dates()]


def mark_submitted(entry: MsptSubmittableEntry) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO submitted
               (chart_number, mspt_stage, name, birth_date, blood_report_date, days_since_last_stage, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.patient.chart_number,
                entry.mspt_stage,
                entry.patient.name,
                entry.patient.birth_date.isoformat(),
                entry.blood_report_date.isoformat(),
                entry.days_since_last_stage,
                date.today().isoformat(),
            ),
        )


def unmark_submitted(chart_number: str, mspt_stage: str) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM submitted WHERE chart_number=? AND mspt_stage=?",
            (chart_number, mspt_stage),
        )


def get_submitted_keys() -> set[tuple[str, str]]:
    with _conn() as conn:
        rows = conn.execute("SELECT chart_number, mspt_stage FROM submitted").fetchall()
    return {(r[0], r[1]) for r in rows}


# ── Called entries split: recent vs auto-excluded ────────────────────────────

def get_called_entries() -> list[FollowupEntry]:
    """Entries in 已二次通知 that are still within AUTO_EXCLUDE_DAYS."""
    cutoff = (date.today() - timedelta(days=AUTO_EXCLUDE_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                      days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at,
                      contacted_time
               FROM contacts WHERE attempt=2 AND contacted_at > ?""",
            (cutoff,),
        ).fetchall()
    return [
        _rows_to_followup_entries([r[:10]])[0].model_copy(
            update={
                "contacted_at": date.fromisoformat(r[10]) if r[10] else None,
                "contacted_time": r[11],
            }
        )
        for r in rows
    ]


def get_auto_excluded_entries() -> list[ExcludedEntry]:
    """Called entries older than AUTO_EXCLUDE_DAYS → shown as auto-excluded."""
    cutoff = (date.today() - timedelta(days=AUTO_EXCLUDE_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                      days_overdue, mspt_stage, contact_reason, last_visit_date, contacted_at
               FROM contacts WHERE attempt=2 AND contacted_at <= ?""",
            (cutoff,),
        ).fetchall()
    result = []
    for r in rows:
        entry = _rows_to_followup_entries([r[:10]])[0]
        result.append(ExcludedEntry(
            patient=entry.patient,
            category=entry.category,
            mspt_stage=entry.mspt_stage,
            due_date=entry.due_date,
            last_visit_date=entry.last_visit_date,
            reason='長期未回應',
            excluded_at=date.fromisoformat(r[10]) if r[10] else date.today(),
            auto=True,
        ))
    return result


# ── Manual exclusion ──────────────────────────────────────────────────────────

def mark_excluded(entry: FollowupEntry, reason: str, note: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO excluded
               (chart_number, category, name, birth_date, mspt_stage, due_date,
                last_visit_date, last_stage, reason, note, excluded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.patient.chart_number, entry.category,
                entry.patient.name, entry.patient.birth_date.isoformat(),
                entry.mspt_stage,
                entry.due_date.isoformat() if entry.due_date else None,
                entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                entry.last_stage, reason, note, date.today().isoformat(),
            ),
        )


def unmark_excluded(chart_number: str, category: str) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM excluded WHERE chart_number=? AND category=?",
            (chart_number, category),
        )


def get_excluded_keys() -> set[tuple[str, str]]:
    with _conn() as conn:
        rows = conn.execute("SELECT chart_number, category FROM excluded").fetchall()
    return {(r[0], r[1]) for r in rows}


def get_excluded_entries() -> list[ExcludedEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, category, name, birth_date, mspt_stage, due_date,
                      last_visit_date, last_stage, reason, note, excluded_at
               FROM excluded ORDER BY excluded_at DESC""",
        ).fetchall()
    result = []
    for r in rows:
        result.append(ExcludedEntry(
            patient=Patient(chart_number=r[0], name=r[2], birth_date=date.fromisoformat(r[3])),
            category=r[1],
            mspt_stage=r[4],
            due_date=date.fromisoformat(r[5]) if r[5] else None,
            last_visit_date=date.fromisoformat(r[6]) if r[6] else None,
            last_stage=r[7],
            reason=r[8],
            note=r[9] or '',
            excluded_at=date.fromisoformat(r[10]),
            auto=False,
        ))
    return result


# ── MSPT completed (掛MSPT完成) ──────────────────────────────────────────────

def mark_mspt_completed(entry: FollowupEntry) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mspt_completed
               (chart_number, mspt_stage, due_date, name, birth_date,
                last_visit_date, last_stage, days_overdue, completed_at, completed_time)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.patient.chart_number, entry.mspt_stage,
                entry.due_date.isoformat(),
                entry.patient.name, entry.patient.birth_date.isoformat(),
                entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                entry.last_stage, entry.days_overdue, date.today().isoformat(),
                datetime.now().strftime('%H:%M'),
            ),
        )


def unmark_mspt_completed(chart_number: str, mspt_stage: str, due_date: str) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM mspt_completed WHERE chart_number=? AND mspt_stage=? AND due_date=?",
            (chart_number, mspt_stage, due_date),
        )


def get_mspt_completed_keys() -> set[tuple[str, str, str]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, mspt_stage, due_date FROM mspt_completed"
        ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def get_mspt_completed_entries() -> list[FollowupEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                      last_visit_date, last_stage, days_overdue, completed_at
               FROM mspt_completed ORDER BY completed_at DESC""",
        ).fetchall()
    return [
        FollowupEntry(
            patient=Patient(chart_number=r[0], name=r[3], birth_date=date.fromisoformat(r[4])),
            disease_name='代謝症候群',
            mspt_stage=r[1],
            due_date=date.fromisoformat(r[2]),
            last_visit_date=date.fromisoformat(r[5]) if r[5] else None,
            last_stage=r[6],
            days_overdue=r[7],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r[8]),
        )
        for r in rows
    ]


def get_print_history(target_date_iso: str) -> dict:
    """Return all contacts recorded on a given date, split by attempt (1=contacted, 2=called)
    plus any MSPT completions recorded on the same date."""
    with _conn() as conn:
        contact_rows = conn.execute(
            """SELECT chart_number, name, birth_date, disease_name, category, due_date,
                      days_overdue, mspt_stage, contact_reason, last_visit_date,
                      contacted_at, contacted_time, attempt
               FROM contacts WHERE contacted_at = ?
               ORDER BY contacted_time NULLS LAST""",
            (target_date_iso,),
        ).fetchall()
        mc_rows = conn.execute(
            """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                      last_visit_date, last_stage, days_overdue, completed_at, completed_time
               FROM mspt_completed WHERE completed_at = ?
               ORDER BY completed_time NULLS LAST""",
            (target_date_iso,),
        ).fetchall()
    contacted, called = [], []
    for r in contact_rows:
        entry = _rows_to_followup_entries([r[:10]])[0].model_copy(
            update={
                "contacted_at": date.fromisoformat(r[10]) if r[10] else None,
                "contacted_time": r[11],
            }
        )
        (contacted if r[12] == 1 else called).append(entry)
    mspt_completed = [
        FollowupEntry(
            patient=Patient(chart_number=r[0], name=r[3], birth_date=date.fromisoformat(r[4])),
            disease_name='代謝症候群',
            mspt_stage=r[1],
            due_date=date.fromisoformat(r[2]),
            last_visit_date=date.fromisoformat(r[5]) if r[5] else None,
            last_stage=r[6],
            days_overdue=r[7],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r[8]) if r[8] else None,
            contacted_time=r[9],
        )
        for r in mc_rows
    ]
    return {"contacted": contacted, "called": called, "mspt_completed": mspt_completed}


def get_submitted_entries() -> list[MsptSubmittableEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, name, birth_date, mspt_stage, blood_report_date, days_since_last_stage
               FROM submitted""",
        ).fetchall()
    return [
        MsptSubmittableEntry(
            patient=Patient(chart_number=r[0], name=r[1], birth_date=date.fromisoformat(r[2])),
            mspt_stage=r[3],
            blood_report_date=date.fromisoformat(r[4]),
            days_since_last_stage=r[5],
        )
        for r in rows
    ]
