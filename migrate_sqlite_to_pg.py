"""
One-time migration: copies all data from contacts.db and auth.db into PostgreSQL.
Usage: DATABASE_URL=postgresql://... python migrate_sqlite_to_pg.py
Reads DATABASE_URL from environment or .env file automatically.
"""
import os, sqlite3
from dotenv import load_dotenv
load_dotenv()
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]

def migrate_file(sqlite_path: str, pg_conn) -> None:
    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    tables = sq.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (tname,) in tables:
        rows = sq.execute(f"SELECT * FROM {tname}").fetchall()
        if not rows:
            print(f"  {tname}: 0 rows, skipping")
            continue
        cols = rows[0].keys()
        col_list = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        values = [tuple(r[c] for c in cols) for r in rows]
        with pg_conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO {tname} ({col_list}) VALUES %s ON CONFLICT DO NOTHING",
                values
            )
        pg_conn.commit()
        print(f"  {tname}: {len(rows)} rows migrated")
    sq.close()

pg = psycopg2.connect(DATABASE_URL)
print("Migrating contacts.db...")
migrate_file("contacts.db", pg)
print("Migrating auth.db...")
migrate_file("auth.db", pg)
print("Resetting sequences...")
serial_tables = [
    'refresh_tokens', 'users', 'on_hold', 'nurses', 'bulletin_notes',
    'salary_records', 'line_notification_log', 'clinic_contacts', 'lab_reports', 'clinics',
]
with pg.cursor() as cur:
    for t in serial_tables:
        cur.execute(f"SELECT MAX(id) FROM {t}")
        row = cur.fetchone()
        max_id = row[0] if row and row[0] is not None else 0
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), %s)", (max(max_id, 1),))
        print(f"  {t}: sequence -> {max(max_id, 1)}")
pg.commit()
pg.close()
print("Done.")
