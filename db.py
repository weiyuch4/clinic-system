import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool: ThreadedConnectionPool | None = None


def init_pool(minconn=1, maxconn=10) -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    _pool = ThreadedConnectionPool(minconn, maxconn, DATABASE_URL)


@contextmanager
def _conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call db.init_pool() first")
    conn = _pool.getconn()
    try:
        conn.autocommit = False
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
