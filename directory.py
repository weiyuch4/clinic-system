"""
Clinic contact directory — phone numbers/notes staff need to look up
(pharmacies, hospitals, suppliers, etc). Distinct from contacts.py, which
tracks patient follow-up contact history, not general clinic contacts.
Shares the same SQLite file since it's a small, simple table.
"""
import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Generator

DB_PATH = "contacts.db"

_CREATE_CLINIC_CONTACTS = """
    CREATE TABLE IF NOT EXISTS clinic_contacts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        category   TEXT DEFAULT '',
        phone      TEXT DEFAULT '',
        note       TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        nurse      TEXT DEFAULT ''
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
        conn.execute(_CREATE_CLINIC_CONTACTS)


def list_contacts() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, category, phone, note, created_at, nurse FROM clinic_contacts "
            "ORDER BY category, name"
        ).fetchall()
    cols = ('id', 'name', 'category', 'phone', 'note', 'created_at', 'nurse')
    return [dict(zip(cols, r)) for r in rows]


def add_contact(name: str, category: str, phone: str, note: str, nurse: str = '') -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO clinic_contacts (name, category, phone, note, created_at, nurse) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, category, phone, note, date.today().isoformat(), nurse),
        )
        return cur.lastrowid


def update_contact(contact_id: int, name: str, category: str, phone: str, note: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE clinic_contacts SET name=?, category=?, phone=?, note=? WHERE id=?",
            (name, category, phone, note, contact_id),
        )
        return cur.rowcount > 0


def delete_contact(contact_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM clinic_contacts WHERE id = ?", (contact_id,))
        return cur.rowcount > 0
