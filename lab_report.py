"""
Parser and storage for 院所明申報暨代檢費對帳單 (monthly lab reconciliation xlsx).
"""

import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime

import openpyxl

from db import _conn

REPORTS_DIR  = "lab_reports"

_CREATE_LAB_REPORTS = """
    CREATE TABLE IF NOT EXISTS lab_reports (
        id           SERIAL PRIMARY KEY,
        filename     TEXT NOT NULL,
        period       TEXT NOT NULL,
        clinic_name  TEXT,
        clinic_code  TEXT,
        stats_json   TEXT NOT NULL,
        file_path    TEXT NOT NULL,
        uploaded_at  TEXT NOT NULL,
        clinic_id    INTEGER NOT NULL DEFAULT 1
    )
"""


def init() -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_LAB_REPORTS)


# ── Parsing ───────────────────────────────────────────────────────────────────

def _kv(text: str) -> dict[str, str]:
    """Extract all key:value pairs from a header row string."""
    return {k: v for k, v in re.findall(r'(\S+?)\s*:\s*(-?[\w.]+)', text)}


def _num(d: dict, key: str):
    v = d.get(key)
    if v is None:
        return None
    try:
        return int(v) if '.' not in v else float(v)
    except ValueError:
        return None


def parse(path: str) -> dict:
    """Parse an xlsx reconciliation file. Returns a stats dict ready for storage."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # Header rows
    h3 = _kv(str(rows[2][0] or ''))
    h5 = _kv(str(rows[4][0] or ''))

    stated = {
        '院所代號': h3.get('院所代號'),
        '院所名稱': h3.get('院所名稱'),
        '代檢件數': _num(h3, '代檢件數'),
        '代檢費用': _num(h3, '代檢費用'),
        '申報件數': _num(h3, '申報件數'),
        '申報點數': _num(h5, '申報點數'),
        '代收稅額': _num(h5, '代收稅額'),
        '應收金額': _num(h5, '應收金額'),
        '暫收款':   _num(h5, '暫收款'),
    }

    # Data rows start at index 7 (row 8)
    data = [r for r in rows[7:] if r[0] and any(c is not None for c in r)]

    # Period from first data row date (e.g. '115/04/01' → '115-04')
    period = ''
    for r in data:
        m = re.match(r'(\d{3})/(\d{2})/', str(r[0]))
        if m:
            period = f"{m.group(1)}-{m.group(2)}"
            break

    # Computed sums
    comp_pts = sum(r[5] for r in data if isinstance(r[5], (int, float)))
    comp_tax = round(sum(r[6] for r in data if isinstance(r[6], (int, float))), 2)
    comp_fee = sum(r[7] for r in data if isinstance(r[7], (int, float)))

    # Unique visit-days with at least one NHI claim
    claim_visits = len({(r[0], r[1]) for r in data
                        if isinstance(r[5], (int, float)) and r[5] > 0})

    unique_patients = len({r[1] for r in data if r[1]})
    working_days    = len({r[0] for r in data if r[0]})

    # 備註: strip to canonical N / P / NP
    note_counts: dict[str, int] = {}
    for r in data:
        raw = str(r[8]).strip() if r[8] else ''
        key = raw.strip() or '（無）'
        note_counts[key] = note_counts.get(key, 0) + 1

    # Top tests by order count
    test_freq = Counter(r[4] for r in data if r[4]).most_common(10)

    # Top tests by 申報點數
    test_pts: dict[str, float] = defaultdict(float)
    for r in data:
        if r[4] and isinstance(r[5], (int, float)):
            test_pts[r[4]] += r[5]
    test_pts_top = sorted(test_pts.items(), key=lambda x: -x[1])[:10]

    return {
        'period': period,
        'stated': stated,
        'computed': {
            '申報點數': int(comp_pts),
            '代收稅額': comp_tax,
            '代檢費用': int(comp_fee),
            '申報件數': claim_visits,
        },
        'summary': {
            'unique_patients': unique_patients,
            'working_days':    working_days,
            'total_lines':     len(data),
            'note_counts':     note_counts,
        },
        'top_tests_freq': [{'name': n, 'count': c} for n, c in test_freq],
        'top_tests_pts':  [{'name': n, 'pts': int(p)} for n, p in test_pts_top],
    }


# ── Storage ───────────────────────────────────────────────────────────────────

def save_report(tmp_path: str, original_filename: str, clinic_id: int = 1) -> int:
    """Parse + store a report. Returns new row id."""
    stats = parse(tmp_path)

    stated   = stats['stated']
    period   = stats['period']
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest     = os.path.join(REPORTS_DIR, f"{ts}_{original_filename}")
    shutil.copy2(tmp_path, dest)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO lab_reports
                   (filename, period, clinic_name, clinic_code, stats_json, file_path, uploaded_at, clinic_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    original_filename,
                    period,
                    stated.get('院所名稱'),
                    stated.get('院所代號'),
                    json.dumps(stats, ensure_ascii=False),
                    dest,
                    datetime.now().isoformat(timespec='seconds'),
                    clinic_id,
                ),
            )
            return cur.fetchone()["id"]


def list_reports(clinic_id: int = 1) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, filename, period, clinic_name, uploaded_at FROM lab_reports WHERE clinic_id = %s ORDER BY id DESC",
                (clinic_id,),
            )
            return [
                {'id': r["id"], 'filename': r["filename"], 'period': r["period"],
                 'clinic_name': r["clinic_name"], 'uploaded_at': r["uploaded_at"]}
                for r in cur.fetchall()
            ]


def get_report(report_id: int, clinic_id: int = 1) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, filename, period, clinic_name, uploaded_at, stats_json FROM lab_reports WHERE id=%s AND clinic_id=%s",
                (report_id, clinic_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        'id': row["id"], 'filename': row["filename"], 'period': row["period"],
        'clinic_name': row["clinic_name"], 'uploaded_at': row["uploaded_at"],
        **json.loads(row["stats_json"]),
    }


def delete_report(report_id: int, clinic_id: int = 1) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_path FROM lab_reports WHERE id=%s AND clinic_id=%s",
                (report_id, clinic_id),
            )
            row = cur.fetchone()
            if not row:
                return False
            cur.execute(
                "DELETE FROM lab_reports WHERE id=%s AND clinic_id=%s",
                (report_id, clinic_id),
            )
            file_path = row["file_path"]
    try:
        os.remove(file_path)
    except OSError:
        pass
    return True
