"""
Monthly stock count (點貨) and ordering.

A nurse counts every item once a month, then orders what is running low. Usage between
two counts = earlier count + what arrived in between − later count, and the order
suggestion is built from the average of the last few months' usage.
"""
import math
from datetime import date, datetime, timedelta, timezone

from db import _conn

_TW = timezone(timedelta(hours=8))

_CREATE_ITEMS = """
    CREATE TABLE IF NOT EXISTS inventory_items (
        id          SERIAL PRIMARY KEY,
        clinic_id   INTEGER NOT NULL DEFAULT 1,
        name        TEXT NOT NULL,
        unit        TEXT NOT NULL DEFAULT '個',
        location    TEXT NOT NULL DEFAULT '',
        sort_order  INTEGER NOT NULL DEFAULT 0,
        pack_size   INTEGER NOT NULL DEFAULT 1,
        pack_unit   TEXT NOT NULL DEFAULT '',
        min_stock   DOUBLE PRECISION NOT NULL DEFAULT 0,
        supplier    TEXT NOT NULL DEFAULT '',
        note        TEXT NOT NULL DEFAULT '',
        active      BOOLEAN NOT NULL DEFAULT TRUE,
        created_at  TEXT NOT NULL
    )
"""

# One count per clinic per month; it stays open until a nurse marks it done
_CREATE_COUNTS = """
    CREATE TABLE IF NOT EXISTS inventory_counts (
        id            SERIAL PRIMARY KEY,
        clinic_id     INTEGER NOT NULL DEFAULT 1,
        month         TEXT NOT NULL,
        started_at    TEXT NOT NULL,
        started_by    TEXT NOT NULL DEFAULT '',
        completed_at  TEXT,
        completed_by  TEXT NOT NULL DEFAULT '',
        UNIQUE (clinic_id, month)
    )
"""

_CREATE_COUNT_LINES = """
    CREATE TABLE IF NOT EXISTS inventory_count_lines (
        count_id    INTEGER NOT NULL,
        item_id     INTEGER NOT NULL,
        clinic_id   INTEGER NOT NULL DEFAULT 1,
        qty         DOUBLE PRECISION NOT NULL,
        counted_by  TEXT NOT NULL DEFAULT '',
        counted_at  TEXT NOT NULL,
        PRIMARY KEY (count_id, item_id)
    )
"""

# qty / received_qty are in the item's base unit (e.g. 盒), even when ordered by the pack
_CREATE_ORDERS = """
    CREATE TABLE IF NOT EXISTS inventory_orders (
        id            SERIAL PRIMARY KEY,
        clinic_id     INTEGER NOT NULL DEFAULT 1,
        item_id       INTEGER NOT NULL,
        count_id      INTEGER,
        qty           DOUBLE PRECISION NOT NULL,
        status        TEXT NOT NULL DEFAULT 'ordered',
        ordered_at    TEXT NOT NULL,
        ordered_by    TEXT NOT NULL DEFAULT '',
        received_qty  DOUBLE PRECISION,
        received_at   TEXT,
        received_by   TEXT NOT NULL DEFAULT ''
    )
"""

_ITEM_FIELDS = ("name", "unit", "location", "pack_size", "pack_unit", "min_stock", "supplier", "note")


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_ITEMS)
            cur.execute(_CREATE_COUNTS)
            cur.execute(_CREATE_COUNT_LINES)
            cur.execute(_CREATE_ORDERS)


def _now() -> str:
    return datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")


def _this_month() -> str:
    return datetime.now(_TW).strftime("%Y-%m")


# ── Items ─────────────────────────────────────────────────────────────────────

def list_items(clinic_id: int, include_archived: bool = False) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, unit, location, sort_order, pack_size, pack_unit, min_stock, "
                "supplier, note, active FROM inventory_items "
                "WHERE clinic_id = %s" + ("" if include_archived else " AND active") +
                " ORDER BY location, sort_order, id",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def _clean_item(data: dict) -> dict:
    out = {
        "name": str(data.get("name") or "").strip(),
        "unit": str(data.get("unit") or "").strip() or "個",
        "location": str(data.get("location") or "").strip(),
        "pack_unit": str(data.get("pack_unit") or "").strip(),
        "supplier": str(data.get("supplier") or "").strip(),
        "note": str(data.get("note") or "").strip(),
    }
    try:
        out["pack_size"] = max(1, int(data.get("pack_size") or 1))
    except (TypeError, ValueError):
        out["pack_size"] = 1
    try:
        out["min_stock"] = max(0.0, float(data.get("min_stock") or 0))
    except (TypeError, ValueError):
        out["min_stock"] = 0.0
    return out


def add_item(clinic_id: int, data: dict) -> int:
    d = _clean_item(data)
    with _conn() as conn:
        with conn.cursor() as cur:
            # New items go to the end of their location
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM inventory_items "
                "WHERE clinic_id = %s AND location = %s",
                (clinic_id, d["location"]),
            )
            order = cur.fetchone()["n"]
            cur.execute(
                "INSERT INTO inventory_items (clinic_id, name, unit, location, sort_order, pack_size, "
                "pack_unit, min_stock, supplier, note, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (clinic_id, d["name"], d["unit"], d["location"], order, d["pack_size"],
                 d["pack_unit"], d["min_stock"], d["supplier"], d["note"], _now()),
            )
            return cur.fetchone()["id"]


def update_item(clinic_id: int, item_id: int, data: dict) -> bool:
    d = _clean_item(data)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_items SET " + ", ".join(f"{k} = %s" for k in _ITEM_FIELDS) +
                " WHERE id = %s AND clinic_id = %s",
                tuple(d[k] for k in _ITEM_FIELDS) + (item_id, clinic_id),
            )
            return cur.rowcount > 0


def set_item_active(clinic_id: int, item_id: int, active: bool) -> bool:
    """Archive instead of delete so past counts and usage history stay intact."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_items SET active = %s WHERE id = %s AND clinic_id = %s",
                (active, item_id, clinic_id),
            )
            return cur.rowcount > 0


def reorder_items(clinic_id: int, item_ids: list[int]) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(item_ids):
                cur.execute(
                    "UPDATE inventory_items SET sort_order = %s WHERE id = %s AND clinic_id = %s",
                    (i, item_id, clinic_id),
                )


# ── Counts ────────────────────────────────────────────────────────────────────

def _count_row(cur, clinic_id: int, where: str, params: tuple) -> dict | None:
    cur.execute(
        "SELECT id, month, started_at, started_by, completed_at, completed_by FROM inventory_counts "
        "WHERE clinic_id = %s AND " + where + " ORDER BY month DESC LIMIT 1",
        (clinic_id,) + params,
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _lines(cur, count_id: int) -> dict[int, dict]:
    cur.execute(
        "SELECT item_id, qty, counted_by, counted_at FROM inventory_count_lines WHERE count_id = %s",
        (count_id,),
    )
    return {r["item_id"]: dict(r) for r in cur.fetchall()}


def get_current_count(clinic_id: int) -> dict:
    """This month's count (open or done) with its lines, plus the previous finished count's
    quantities so the counting screen can show last month's number next to each item."""
    month = _this_month()
    with _conn() as conn:
        with conn.cursor() as cur:
            current = _count_row(cur, clinic_id, "month = %s", (month,))
            prev = _count_row(cur, clinic_id, "month < %s AND completed_at IS NOT NULL", (month,))
            lines = _lines(cur, current["id"]) if current else {}
            prev_lines = _lines(cur, prev["id"]) if prev else {}
    return {
        "month": month,
        "count": current,
        "lines": {str(k): v["qty"] for k, v in lines.items()},
        "previous": prev,
        "previous_lines": {str(k): v["qty"] for k, v in prev_lines.items()},
    }


def start_count(clinic_id: int, nurse: str) -> dict:
    month = _this_month()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO inventory_counts (clinic_id, month, started_at, started_by) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (clinic_id, month) DO NOTHING",
                (clinic_id, month, _now(), nurse),
            )
            return _count_row(cur, clinic_id, "month = %s", (month,))


def _open_count_id(cur, clinic_id: int, count_id: int) -> int | None:
    cur.execute(
        "SELECT id FROM inventory_counts WHERE id = %s AND clinic_id = %s AND completed_at IS NULL",
        (count_id, clinic_id),
    )
    r = cur.fetchone()
    return r["id"] if r else None


def set_line(clinic_id: int, count_id: int, item_id: int, qty: float | None, nurse: str) -> bool:
    """Save one counted quantity (None clears it). Only open counts can be changed."""
    with _conn() as conn:
        with conn.cursor() as cur:
            if _open_count_id(cur, clinic_id, count_id) is None:
                return False
            if qty is None:
                cur.execute(
                    "DELETE FROM inventory_count_lines WHERE count_id = %s AND item_id = %s",
                    (count_id, item_id),
                )
            else:
                cur.execute(
                    """INSERT INTO inventory_count_lines (count_id, item_id, clinic_id, qty, counted_by, counted_at)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (count_id, item_id) DO UPDATE SET
                           qty = EXCLUDED.qty, counted_by = EXCLUDED.counted_by, counted_at = EXCLUDED.counted_at""",
                    (count_id, item_id, clinic_id, qty, nurse, _now()),
                )
    return True


def complete_count(clinic_id: int, count_id: int, nurse: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_counts SET completed_at = %s, completed_by = %s "
                "WHERE id = %s AND clinic_id = %s AND completed_at IS NULL",
                (_now(), nurse, count_id, clinic_id),
            )
            return cur.rowcount > 0


def reopen_count(clinic_id: int, count_id: int) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_counts SET completed_at = NULL, completed_by = '' "
                "WHERE id = %s AND clinic_id = %s",
                (count_id, clinic_id),
            )
            return cur.rowcount > 0


# ── Orders ────────────────────────────────────────────────────────────────────

def place_orders(clinic_id: int, lines: list[dict], nurse: str, count_id: int | None) -> int:
    placed = 0
    with _conn() as conn:
        with conn.cursor() as cur:
            for ln in lines:
                try:
                    item_id = int(ln.get("item_id"))
                    qty = float(ln.get("qty"))
                except (TypeError, ValueError):
                    continue
                if qty <= 0:
                    continue
                cur.execute(
                    "INSERT INTO inventory_orders (clinic_id, item_id, count_id, qty, ordered_at, ordered_by) "
                    "SELECT %s, id, %s, %s, %s, %s FROM inventory_items WHERE id = %s AND clinic_id = %s",
                    (clinic_id, count_id, qty, _now(), nurse, item_id, clinic_id),
                )
                placed += cur.rowcount
    return placed


def list_open_orders(clinic_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT o.id, o.item_id, o.qty, o.ordered_at, o.ordered_by, "
                "i.name, i.unit, i.pack_size, i.pack_unit, i.supplier "
                "FROM inventory_orders o JOIN inventory_items i ON i.id = o.item_id "
                "WHERE o.clinic_id = %s AND o.status = 'ordered' ORDER BY i.supplier, i.name",
                (clinic_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def receive_order(clinic_id: int, order_id: int, qty: float, nurse: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_orders SET status = 'received', received_qty = %s, received_at = %s, "
                "received_by = %s WHERE id = %s AND clinic_id = %s AND status = 'ordered'",
                (qty, _now(), nurse, order_id, clinic_id),
            )
            return cur.rowcount > 0


def cancel_order(clinic_id: int, order_id: int) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_orders SET status = 'cancelled' "
                "WHERE id = %s AND clinic_id = %s AND status = 'ordered'",
                (order_id, clinic_id),
            )
            return cur.rowcount > 0


# ── Usage and order suggestions ───────────────────────────────────────────────

_USAGE_MONTHS = 3      # average over this many recent months
_SPIKE_FACTOR = 2.5    # flag a month whose usage is this many times the usual


def _d(ts: str) -> date:
    return date.fromisoformat(ts[:10])


def usage_history(points: list[tuple[str, float]], receipts: list[tuple[str, float]]) -> list[dict]:
    """Usage between consecutive counts, scaled to a 30-day month.
    points: [(counted_at, qty)] oldest first. receipts: [(received_at, qty)].
    A negative result means stock went up with nothing recorded as arriving — kept but
    marked so it isn't averaged in."""
    out = []
    for (t0, q0), (t1, q1) in zip(points, points[1:]):
        d0, d1 = _d(t0), _d(t1)
        days = (d1 - d0).days
        if days < 7:       # two counts in the same week say nothing about monthly usage
            continue
        arrived = sum(q for t, q in receipts if d0 < _d(t) <= d1)
        used = q0 + arrived - q1
        out.append({
            "from": t0[:10], "to": t1[:10], "start": q0, "arrived": arrived, "end": q1,
            "used": used, "monthly": used * 30 / days, "valid": used >= 0,
        })
    return out


def _round_up_packs(qty: float, pack_size: int) -> float:
    if qty <= 0:
        return 0
    return math.ceil(qty / pack_size - 1e-9) * pack_size


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"


def suggest(item: dict, stock: float | None, on_order: float, history: list[dict]) -> dict:
    """Order suggestion for one item.
    target = one month's average usage + safety stock (安全量, or 20% of usage when unset)
    order  = target − stock − already on order, rounded up to whole packs."""
    unit, pack, min_stock = item["unit"], item["pack_size"], item["min_stock"]
    valid = [h["monthly"] for h in history if h["valid"]][-_USAGE_MONTHS:]
    flags = []
    if stock is None:
        return {"suggested": None, "avg_usage": None, "reason": "本月尚未點這一項", "flags": flags}
    if min_stock and stock < min_stock:
        flags.append(f"低於安全量 {_fmt(min_stock)} {unit}")
    if history and not history[-1]["valid"]:
        flags.append("數量比上次多，但沒有到貨紀錄，請確認")
    if len(valid) >= 3 and valid[-1] > _SPIKE_FACTOR * (sum(valid[:-1]) / len(valid[:-1])):
        flags.append(f"本月用量是平常的 {valid[-1] / (sum(valid[:-1]) / len(valid[:-1])):.1f} 倍")

    have = stock + on_order
    have_txt = f"現有 {_fmt(stock)}" + (f"＋在途 {_fmt(on_order)}" if on_order else "") + f" {unit}"
    if not valid:
        # No usage history yet: just top up to the safety stock, if one is set
        if not min_stock:
            return {"suggested": None, "avg_usage": None, "flags": flags,
                    "reason": "累積 2 次點貨後才能估算用量，請先自行判斷"}
        need = _round_up_packs(min_stock - have, pack)
        return {"suggested": need, "avg_usage": None, "flags": flags,
                "reason": f"尚無用量紀錄，補到安全量 {_fmt(min_stock)} {unit}（{have_txt}）"}

    avg = sum(valid) / len(valid)
    safety = min_stock if min_stock else math.ceil(avg * 0.2)
    need = _round_up_packs(avg + safety - have, pack)
    basis = f"近 {len(valid)} 個月平均用 {_fmt(round(avg, 1))} {unit}" if len(valid) > 1 else f"上個月用 {_fmt(round(avg, 1))} {unit}"
    return {"suggested": need, "avg_usage": round(avg, 1), "flags": flags,
            "reason": f"{basis}，{have_txt}"}


def get_suggestions(clinic_id: int) -> dict:
    """Every active item with its latest count, what's on order, usage and a suggested order."""
    items = list_items(clinic_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT l.item_id, l.qty, l.counted_at, c.month FROM inventory_count_lines l "
                "JOIN inventory_counts c ON c.id = l.count_id "
                "WHERE l.clinic_id = %s ORDER BY c.month",
                (clinic_id,),
            )
            counts = cur.fetchall()
            cur.execute(
                "SELECT item_id, received_at, received_qty FROM inventory_orders "
                "WHERE clinic_id = %s AND status = 'received'",
                (clinic_id,),
            )
            receipts = cur.fetchall()
            cur.execute(
                "SELECT item_id, SUM(qty) AS q FROM inventory_orders "
                "WHERE clinic_id = %s AND status = 'ordered' GROUP BY item_id",
                (clinic_id,),
            )
            on_order = {r["item_id"]: r["q"] for r in cur.fetchall()}
            latest = _count_row(cur, clinic_id, "TRUE", ())

    points: dict[int, list] = {}
    for r in counts:
        points.setdefault(r["item_id"], []).append((r["counted_at"], r["qty"], r["month"]))
    recv: dict[int, list] = {}
    for r in receipts:
        recv.setdefault(r["item_id"], []).append((r["received_at"], r["received_qty"]))

    out = []
    for it in items:
        pts = points.get(it["id"], [])
        # Stock is only "current" if counted in the latest count
        stock = pts[-1][1] if pts and latest and pts[-1][2] == latest["month"] else None
        hist = usage_history([(t, q) for t, q, _ in pts], recv.get(it["id"], []))
        s = suggest(it, stock, on_order.get(it["id"], 0), hist)
        out.append({**it, "stock": stock, "on_order": on_order.get(it["id"], 0),
                    "history": hist[-6:], **s})
    return {"count": latest, "items": out}
