import contextvars
import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool: ThreadedConnectionPool | None = None

# Per-request clinic_id — set by auth.get_current_user (and sync endpoints).
# ThreadPoolExecutor inherits ContextVar values from the spawning thread.
_clinic_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "clinic_id", default=None
)


def set_clinic_id(cid: int) -> None:
    _clinic_id_ctx.set(cid)


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
        cid = _clinic_id_ctx.get()
        if cid is not None:
            with conn.cursor() as cur:
                # SET LOCAL scopes the value to this transaction only,
                # so it resets when the connection goes back to the pool.
                cur.execute(
                    "SELECT set_config('app.clinic_id', %s, true)", (str(cid),)
                )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
