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


def init_pool(minconn=1, maxconn=20) -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    # TCP keepalives prevent Railway's NAT gateway from silently dropping idle connections.
    # Without these, reused pool connections can be dead, causing ~10s TCP-timeout hangs.
    _pool = ThreadedConnectionPool(
        minconn, maxconn, DATABASE_URL,
        keepalives=1,
        keepalives_idle=60,
        keepalives_interval=10,
        keepalives_count=5,
    )


def _get_live_conn() -> "psycopg2.extensions.connection":
    """Get a connection from the pool, discarding any that psycopg2 already knows are closed."""
    assert _pool is not None
    for _ in range(3):
        conn = _pool.getconn()
        if conn.closed == 0:
            return conn
        _pool.putconn(conn, close=True)
    return _pool.getconn()


@contextmanager
def _conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call db.init_pool() first")
    conn = _get_live_conn()
    _discard = False
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
    except psycopg2.OperationalError:
        # Connection died mid-query — discard it so the pool doesn't reuse a dead socket.
        _discard = True
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _pool.putconn(conn, close=_discard)
