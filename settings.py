"""Per-clinic configurable settings stored in PostgreSQL."""
import json
import db
import nhi_blood_codes as _nhi

_DEFAULT_LAB_CHAPTERS = _nhi.DEFAULT_CHAPTERS  # ["08","09","12","14","27","30"]


def get_lab_prefixes(clinic_id: int = 1) -> list[str]:
    conn = db._pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM clinic_settings WHERE clinic_id = %s AND key = 'lab_code_prefixes'",
                (clinic_id,),
            )
            row = cur.fetchone()
        if row:
            val = row[0]
            if isinstance(val, str):
                val = json.loads(val)
            if isinstance(val, list) and val:
                return [str(p).strip() for p in val if str(p).strip()]
        return list(_DEFAULT_LAB_CHAPTERS)
    finally:
        db._pool.putconn(conn)


def get_lab_code_set(clinic_id: int = 1) -> frozenset:
    """Return the exact NHI code set for the clinic's active chapters.

    Stored prefixes can be either 2-char chapter codes (e.g. "08") that
    expand to the full chapter, or individual 6-char NHI codes (e.g.
    "08001C") that are added one at a time.
    """
    result: set[str] = set()
    for p in get_lab_prefixes(clinic_id):
        if p in _nhi.CHAPTER_CODES:
            result.update(_nhi.CHAPTER_CODES[p])
        elif p in _nhi.CODE_NAMES:
            result.add(p)
    return frozenset(result)


def save_lab_prefixes(prefixes: list[str], clinic_id: int = 1) -> None:
    cleaned = [p.strip() for p in prefixes if p.strip()]
    if not cleaned:
        raise ValueError("At least one prefix required")
    conn = db._pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clinic_settings (clinic_id, key, value, updated_at)
                VALUES (%s, 'lab_code_prefixes', %s, NOW()::text)
                ON CONFLICT (clinic_id, key) DO UPDATE
                  SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (clinic_id, json.dumps(cleaned)),
            )
        conn.commit()
    finally:
        db._pool.putconn(conn)
