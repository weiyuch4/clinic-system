"""
Clinic contact directory — phone numbers/notes staff need to look up
(pharmacies, hospitals, suppliers, etc). Distinct from contacts.py, which
tracks patient follow-up contact history, not general clinic contacts.
"""
from datetime import date

from db import _conn

_CREATE_CLINIC_CONTACTS = """
    CREATE TABLE IF NOT EXISTS clinic_contacts (
        id         SERIAL PRIMARY KEY,
        name       TEXT NOT NULL,
        category   TEXT DEFAULT '',
        phone      TEXT DEFAULT '',
        note       TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        nurse      TEXT DEFAULT '',
        clinic_id  INTEGER NOT NULL DEFAULT 1
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_CLINIC_CONTACTS)


def list_contacts() -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, category, phone, note, created_at, nurse FROM clinic_contacts "
                "ORDER BY category, name"
            )
            return [dict(r) for r in cur.fetchall()]


def add_contact(name: str, category: str, phone: str, note: str, nurse: str = '') -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clinic_contacts (name, category, phone, note, created_at, nurse) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (name, category, phone, note, date.today().isoformat(), nurse),
            )
            return cur.fetchone()["id"]


def update_contact(contact_id: int, name: str, category: str, phone: str, note: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE clinic_contacts SET name=%s, category=%s, phone=%s, note=%s WHERE id=%s",
                (name, category, phone, note, contact_id),
            )
            return cur.rowcount > 0


def delete_contact(contact_id: int) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clinic_contacts WHERE id = %s", (contact_id,))
            return cur.rowcount > 0
