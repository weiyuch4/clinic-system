import contextvars
import os
import time as _time
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool: ThreadedConnectionPool | None = None
# psycopg2 C extension objects don't support arbitrary attribute assignment,
# so we track last-used timestamps in a separate dict keyed by id(conn).
_conn_last_used: dict[int, float] = {}

# Per-request clinic_id — set by auth.get_current_user (and sync endpoints).
# ThreadPoolExecutor inherits ContextVar values from the spawning thread.
_clinic_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "clinic_id", default=None
)

# Only pre-ping connections idle longer than this. Shorter than Railway NAT timeout
# (~6 min) but long enough that hot connections skip the extra 2 RTTs entirely.
_PING_IF_IDLE_SECS = 60


def set_clinic_id(cid: int) -> None:
    _clinic_id_ctx.set(cid)


def init_pool(minconn=1, maxconn=20) -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    # TCP keepalives prevent Railway's NAT gateway from silently dropping idle
    # connections. keepalives_idle=30 means probes start after 30 s of silence,
    # well before Railway's ~6-minute NAT timeout.
    _pool = ThreadedConnectionPool(
        minconn, maxconn, DATABASE_URL,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )


def _get_live_conn() -> "psycopg2.extensions.connection":
    """Get a connection from the pool.
    Pre-pings only connections that have been idle long enough that they
    might have been dropped by Railway's NAT. Warm connections (used recently)
    skip the ping entirely to avoid 2 extra RTTs on every hot request."""
    assert _pool is not None
    now = _time.monotonic()
    for _ in range(3):
        conn = _pool.getconn()
        if conn.closed != 0:
            _conn_last_used.pop(id(conn), None)
            _pool.putconn(conn, close=True)
            continue
        last_used = _conn_last_used.get(id(conn))
        if last_used is not None and now - last_used > _PING_IF_IDLE_SECS:
            try:
                conn.cursor().execute("SELECT 1")
                conn.reset()
            except Exception:
                # InterfaceError, OperationalError, etc. — any ping failure
                _conn_last_used.pop(id(conn), None)
                _pool.putconn(conn, close=True)
                continue
        # New connections (no entry yet) are alive by definition; skip ping.
        return conn
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
        if not _discard:
            _conn_last_used[id(conn)] = _time.monotonic()
        else:
            _conn_last_used.pop(id(conn), None)
        _pool.putconn(conn, close=_discard)
