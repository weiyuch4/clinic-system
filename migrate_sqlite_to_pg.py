"""
One-time migration: copies all data from contacts.db and auth.db into PostgreSQL.
Usage: DATABASE_URL=postgresql://... python migrate_sqlite_to_pg.py
"""
import os, sqlite3
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]

def migrate_file(sqlite_path: str, pg_conn) -> None:
    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    tables = sq.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
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
pg.close()
print("Done.")
