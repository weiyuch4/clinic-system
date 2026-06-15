import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Generator

from models import ExcludedEntry, FollowupEntry, ManualPickupEntry, MsptManualEntry, MsptStage, MsptSubmittableEntry, OnHoldEntry, Patient

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

_CREATE_MANUAL_PICKUPS = """
    CREATE TABLE IF NOT EXISTS manual_pickups (
        chart_number TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        birth_date   TEXT NOT NULL,
        pickup_date  TEXT NOT NULL,
        ps_days      INTEGER NOT NULL,
        recorded_at  TEXT NOT NULL
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

_CREATE_ON_HOLD = """
    CREATE TABLE IF NOT EXISTS on_hold (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
        is_manual       INTEGER DEFAULT 0
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
        marked_at       TEXT NOT NULL
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
        PRIMARY KEY (chart_number, mspt_stage, due_date)
    )
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with _conn() as conn:
        conn.execute(_CREATE_CONTACTS)
        conn.execute(_CREATE_SUBMITTED)
        conn.execute(_CREATE_EXCLUDED)
        conn.execute(_CREATE_MSPT_COMPLETED)
        conn.execute(_CREATE_MSPT_CHECKEDIN)
        conn.execute(_CREATE_MSPT_MANUAL)
        conn.execute(_CREATE_ON_HOLD)
        conn.execute(_CREATE_MANUAL_PICKUPS)
        # Migrations for existing databases
        for col in ("last_visit_date TEXT", "contacted_time TEXT", "nurse TEXT DEFAULT ''"):
            try:
                conn.execute(f"ALTER TABLE contacts ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        for col in ("completed_time TEXT", "nurse TEXT DEFAULT ''"):
            try:
                conn.execute(f"ALTER TABLE mspt_completed ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        for tbl in ("excluded", "manual_pickups"):
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN nurse TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass


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
        datetime.now().strftime('%H:%M'),
        nurse,
    )


def mark_contacted(entry: FollowupEntry, nurse: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO contacts
               (chart_number, category, due_date, name, birth_date, disease_name,
                days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                contacted_time, nurse)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                   attempt=1, contacted_at=excluded.contacted_at,
                   contacted_time=excluded.contacted_time, nurse=excluded.nurse""",
            _followup_to_row(entry, 1, nurse),
        )


def mark_called(entry: FollowupEntry, nurse: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO contacts
               (chart_number, category, due_date, name, birth_date, disease_name,
                days_overdue, mspt_stage, contact_reason, last_visit_date, attempt, contacted_at,
                contacted_time, nurse)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chart_number, category, due_date) DO UPDATE SET
                   attempt=2, contacted_at=excluded.contacted_at,
                   contacted_time=excluded.contacted_time, nurse=excluded.nurse""",
            _followup_to_row(entry, 2, nurse),
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

def mark_excluded(entry: FollowupEntry, reason: str, note: str = '', nurse: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO excluded
               (chart_number, category, name, birth_date, mspt_stage, due_date,
                last_visit_date, last_stage, reason, note, excluded_at, nurse)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.patient.chart_number, entry.category,
                entry.patient.name, entry.patient.birth_date.isoformat(),
                entry.mspt_stage,
                entry.due_date.isoformat() if entry.due_date else None,
                entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                entry.last_stage, reason, note, date.today().isoformat(), nurse,
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


# ── MSPT completed (完成MSPT) ──────────────────────────────────────────────

def mark_mspt_completed(entry: FollowupEntry, nurse: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mspt_completed
               (chart_number, mspt_stage, due_date, name, birth_date,
                last_visit_date, last_stage, days_overdue, completed_at, completed_time, nurse)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.patient.chart_number, entry.mspt_stage,
                entry.due_date.isoformat(),
                entry.patient.name, entry.patient.birth_date.isoformat(),
                entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                entry.last_stage, entry.days_overdue, date.today().isoformat(),
                datetime.now().strftime('%H:%M'), nurse,
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


def mark_mspt_checkedin(entry: FollowupEntry, nurse: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mspt_checkedin
               (chart_number, mspt_stage, due_date, name, birth_date,
                last_visit_date, last_stage, days_overdue, contact_reason,
                checkedin_at, checkedin_time, nurse)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.patient.chart_number, entry.mspt_stage,
                entry.due_date.isoformat(),
                entry.patient.name, entry.patient.birth_date.isoformat(),
                entry.last_visit_date.isoformat() if entry.last_visit_date else None,
                entry.last_stage, entry.days_overdue, entry.contact_reason,
                date.today().isoformat(), datetime.now().strftime('%H:%M'), nurse,
            ),
        )


def unmark_mspt_checkedin(chart_number: str, mspt_stage: str, due_date: str) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM mspt_checkedin WHERE chart_number=? AND mspt_stage=? AND due_date=?",
            (chart_number, mspt_stage, due_date),
        )


def get_mspt_checkedin_keys() -> set[tuple[str, str, str]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, mspt_stage, due_date FROM mspt_checkedin"
        ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def get_mspt_checkedin_entries() -> list[FollowupEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                      last_visit_date, last_stage, days_overdue, contact_reason,
                      checkedin_at, checkedin_time, nurse
               FROM mspt_checkedin ORDER BY checkedin_at DESC, checkedin_time DESC""",
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
            contact_reason=r[8],
            category='代謝症候群',
            contacted_at=date.fromisoformat(r[9]) if r[9] else None,
            contacted_time=r[10],
            nurse=r[11] or "",
        )
        for r in rows
    ]


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
                      contacted_at, contacted_time, attempt, nurse
               FROM contacts WHERE contacted_at = ?
               ORDER BY contacted_time NULLS LAST""",
            (target_date_iso,),
        ).fetchall()
        mc_rows = conn.execute(
            """SELECT chart_number, mspt_stage, due_date, name, birth_date,
                      last_visit_date, last_stage, days_overdue, completed_at, completed_time, nurse
               FROM mspt_completed WHERE completed_at = ?
               ORDER BY completed_time NULLS LAST""",
            (target_date_iso,),
        ).fetchall()
        excl_rows = conn.execute(
            """SELECT chart_number, name, birth_date, category, mspt_stage,
                      due_date, last_visit_date, last_stage, reason, note, nurse
               FROM excluded WHERE excluded_at = ?""",
            (target_date_iso,),
        ).fetchall()
        pickup_rows = conn.execute(
            """SELECT chart_number, name, birth_date, pickup_date, ps_days, nurse
               FROM manual_pickups WHERE recorded_at = ?""",
            (target_date_iso,),
        ).fetchall()

    contacted, called = [], []
    for r in contact_rows:
        entry = _rows_to_followup_entries([r[:10]])[0].model_copy(
            update={
                "contacted_at": date.fromisoformat(r[10]) if r[10] else None,
                "contacted_time": r[11],
                "nurse": r[13] or "",
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
            nurse=r[10] or "",
        )
        for r in mc_rows
    ]
    excluded = [
        ExcludedEntry(
            patient=Patient(chart_number=r[0], name=r[1], birth_date=date.fromisoformat(r[2])),
            category=r[3],
            mspt_stage=r[4],
            due_date=date.fromisoformat(r[5]) if r[5] else None,
            last_visit_date=date.fromisoformat(r[6]) if r[6] else None,
            last_stage=r[7],
            reason=r[8],
            note=r[9] or '',
            excluded_at=date.fromisoformat(target_date_iso),
            nurse=r[10] or "",
        )
        for r in excl_rows
    ]
    manual_pickups = [
        ManualPickupEntry(
            chart_number=r[0], name=r[1], birth_date=date.fromisoformat(r[2]),
            pickup_date=date.fromisoformat(r[3]), ps_days=r[4],
            next_due=date.fromisoformat(r[3]) + timedelta(days=r[4]),
            nurse=r[5] or "",
        )
        for r in pickup_rows
    ]
    return {
        "contacted": contacted, "called": called, "mspt_completed": mspt_completed,
        "excluded": excluded, "manual_pickups": manual_pickups,
    }


def mark_manual_pickup(entry: FollowupEntry, pickup_date: date, ps_days: int, nurse: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO manual_pickups
               (chart_number, name, birth_date, pickup_date, ps_days, recorded_at, nurse)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.patient.chart_number,
                entry.patient.name,
                entry.patient.birth_date.isoformat(),
                pickup_date.isoformat(),
                ps_days,
                date.today().isoformat(),
                nurse,
            ),
        )


def unmark_manual_pickup(chart_number: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM manual_pickups WHERE chart_number = ?", (chart_number,))


def get_manual_pickup_map() -> dict[str, tuple[str, int]]:
    """Returns {chart_number: (pickup_date_iso, ps_days)} for suppression filtering."""
    with _conn() as conn:
        rows = conn.execute("SELECT chart_number, pickup_date, ps_days FROM manual_pickups").fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def get_manual_pickup_entries() -> list[ManualPickupEntry]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, name, birth_date, pickup_date, ps_days FROM manual_pickups ORDER BY recorded_at DESC"
        ).fetchall()
    return [
        ManualPickupEntry(
            chart_number=r[0],
            name=r[1],
            birth_date=date.fromisoformat(r[2]),
            pickup_date=date.fromisoformat(r[3]),
            ps_days=r[4],
            next_due=date.fromisoformat(r[3]) + timedelta(days=r[4]),
        )
        for r in rows
    ]


def mark_mspt_manual(chart_number: str, name: str, birth_date: date, mspt_stage: str,
                     completed_date: date, nurse: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mspt_manual
               (chart_number, name, birth_date, mspt_stage, completed_date, nurse, marked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (chart_number, name, birth_date.isoformat(), mspt_stage,
             completed_date.isoformat(), nurse, date.today().isoformat()),
        )


def unmark_mspt_manual(chart_number: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM mspt_manual WHERE chart_number = ?", (chart_number,))


def get_mspt_manual_overrides() -> dict[str, dict]:
    """Returns {chart_number: {'stage': str, 'date': date}} for post-processing in get_report."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, mspt_stage, completed_date FROM mspt_manual"
        ).fetchall()
    return {r[0]: {'stage': r[1], 'date': date.fromisoformat(r[2])} for r in rows}


def get_mspt_manual_entries() -> list[MsptManualEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT chart_number, name, birth_date, mspt_stage, completed_date, nurse, marked_at
               FROM mspt_manual ORDER BY marked_at DESC"""
        ).fetchall()
    return [
        MsptManualEntry(
            chart_number=r[0], name=r[1], birth_date=date.fromisoformat(r[2]),
            mspt_stage=r[3], completed_date=date.fromisoformat(r[4]),
            nurse=r[5] or '', marked_at=date.fromisoformat(r[6]),
        )
        for r in rows
    ]


def get_activity_stats(month: str) -> dict[str, dict[str, int]]:
    """month: 'YYYY-MM'. Returns {nurse: {contacted, called, mspt, excluded, pickup}}."""
    prefix = month + "-%"
    with _conn() as conn:
        c_rows  = conn.execute(
            "SELECT nurse, attempt, COUNT(*) FROM contacts WHERE contacted_at LIKE ? GROUP BY nurse, attempt",
            (prefix,)).fetchall()
        m_rows  = conn.execute(
            "SELECT nurse, COUNT(*) FROM mspt_completed WHERE completed_at LIKE ? GROUP BY nurse",
            (prefix,)).fetchall()
        ex_rows = conn.execute(
            "SELECT nurse, COUNT(*) FROM excluded WHERE excluded_at LIKE ? GROUP BY nurse",
            (prefix,)).fetchall()
        pk_rows = conn.execute(
            "SELECT nurse, COUNT(*) FROM manual_pickups WHERE recorded_at LIKE ? GROUP BY nurse",
            (prefix,)).fetchall()

    stats: dict[str, dict[str, int]] = {}

    def _row(nurse: str) -> dict[str, int]:
        key = nurse or "（未選擇）"
        if key not in stats:
            stats[key] = {"contacted": 0, "called": 0, "mspt": 0, "excluded": 0, "pickup": 0}
        return stats[key]

    for nurse, attempt, count in c_rows:
        row = _row(nurse)
        if attempt == 1:
            row["contacted"] += count
        else:
            row["called"] += count
    for nurse, count in m_rows:
        _row(nurse)["mspt"] += count
    for nurse, count in ex_rows:
        _row(nurse)["excluded"] += count
    for nurse, count in pk_rows:
        _row(nurse)["pickup"] += count

    return stats


def mark_on_hold(entry: FollowupEntry, note: str, nurse: str = '') -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO on_hold
               (chart_number, category, due_date, name, birth_date, disease_name,
                days_overdue, mspt_stage, last_stage, last_visit_date, note, held_at, nurse, is_manual)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
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
            ),
        )
        return cur.lastrowid


def mark_on_hold_manual(name: str, note: str, nurse: str = '', category: str | None = None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO on_hold (name, category, note, held_at, nurse, is_manual)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (name, category, note, date.today().isoformat(), nurse),
        )
        return cur.lastrowid


def remove_on_hold(hold_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM on_hold WHERE id = ?", (hold_id,))


def get_on_hold_keys() -> set[tuple[str, str, str]]:
    """(chart_number, category, due_date) for non-manual entries — used to filter the main list."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chart_number, category, due_date FROM on_hold WHERE is_manual = 0 AND chart_number IS NOT NULL"
        ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def get_on_hold_entries() -> list[OnHoldEntry]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, chart_number, category, due_date, name, birth_date, disease_name,
                      days_overdue, mspt_stage, last_stage, last_visit_date, note, held_at, nurse, is_manual
               FROM on_hold ORDER BY held_at DESC"""
        ).fetchall()
    result = []
    for r in rows:
        is_manual = bool(r[14])
        result.append(OnHoldEntry(
            hold_id=r[0],
            patient=Patient(
                chart_number=r[1] or '',
                name=r[4],
                birth_date=date.fromisoformat(r[5]) if r[5] else date.today(),
            ) if not is_manual else None,
            category=r[2],
            due_date=date.fromisoformat(r[3]) if r[3] else None,
            days_overdue=r[7],
            mspt_stage=r[8],
            last_stage=r[9],
            last_visit_date=date.fromisoformat(r[10]) if r[10] else None,
            disease_name=r[6],
            note=r[11],
            held_at=date.fromisoformat(r[12]),
            nurse=r[13] or '',
            is_manual=is_manual,
            manual_name=r[4] if is_manual else '',
        ))
    return result


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


