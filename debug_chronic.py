"""
Debug why specific patients' IC01 (or AE連續) visits are not being captured
by _query_chronic_prescriptions in database.py.

Usage:
    python debug_chronic.py <national_id> [<national_id2> ...]

Example:
    python debug_chronic.py A123456789 B234567890
"""

import sys
import os
import glob
import struct
from datetime import date, timedelta

from config import IC_DATA_PATH

SEARCH_DAYS = 365
CHRONIC_GRACE    = 5
MAX_OVERDUE_DAYS = 60

# ── DBF reader ────────────────────────────────────────────────────────────────

def _parse_dbf(path: str) -> list[dict]:
    with open(path, 'rb') as f:
        hdr = f.read(32)
        header_size = struct.unpack_from('<H', hdr, 8)[0]
        record_size = struct.unpack_from('<H', hdr, 10)[0]
        fields: list[tuple[str, int]] = []
        f.seek(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            flen = fd[16]
            if name:
                fields.append((name, flen))
        f.seek(header_size)
        records = []
        while True:
            raw = f.read(record_size)
            if not raw or len(raw) < record_size:
                break
            if raw[0] == 0x2A:
                continue
            row: dict[str, str] = {}
            offset = 1
            for name, flen in fields:
                try:
                    val = raw[offset:offset + flen].decode('cp950', errors='replace').strip()
                except Exception:
                    val = raw[offset:offset + flen].decode('latin-1', errors='replace').strip()
                row[name] = val
                offset += flen
            records.append(row)
    return records


def _roc_to_date(s: str) -> date | None:
    s = s.strip()
    if len(s) != 7 or not s.isdigit():
        return None
    try:
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None


def _ic_files_since(since: date) -> list[str]:
    result = []
    for path in glob.glob(os.path.join(IC_DATA_PATH, 'IC?????.DBF')):
        stem = os.path.basename(path)[2:-4]
        if not (len(stem) == 5 and stem.isdigit()):
            continue
        result.append(path)
    return sorted(result)


# ── Main debug logic ──────────────────────────────────────────────────────────

def debug_patient(nat_id: str, as_of: date):
    since = as_of - timedelta(days=SEARCH_DAYS)
    ic_files = _ic_files_since(since)

    print(f"\n{'='*70}")
    print(f"  Patient: {nat_id}    (checking as of {as_of})")
    print(f"  Scanning {len(ic_files)} IC file(s) from {IC_DATA_PATH}")
    print(f"{'='*70}")

    ae_best   = None  # best AE連續 record
    ic01_best = None  # best 01西醫 KIND=08 record
    all_visits: list[dict] = []  # every chronic-relevant hit for this patient

    for ic_path in ic_files:
        stem = os.path.basename(ic_path)[2:-4]
        p_path = ic_path[:-4] + 'P.DBF'

        try:
            records = _parse_dbf(ic_path)
        except Exception as e:
            print(f"  [!] Could not read {ic_path}: {e}")
            continue

        for r in records:
            if r.get('ID', '').strip() != nat_id:
                continue

            h_type = r.get('H_TYPE', '').strip()
            kind   = r.get('KIND',   '').strip()
            v_date = _roc_to_date(r.get('DATE', ''))
            cf     = r.get('CODE_F', '').strip()
            m20    = r.get('M20', '').strip()
            m33    = r.get('M33', '').strip()

            is_ae   = h_type == 'AE連續'
            is_ic01 = h_type == '01西醫' and kind == '08'

            entry = {
                'file':   f'IC{stem}.DBF',
                'h_type': h_type,
                'kind':   kind,
                'date':   v_date,
                'date_raw': r.get('DATE', '').strip(),
                'cf':     cf,
                'm20':    m20,
                'm33':    m33,
                'is_ae':  is_ae,
                'is_ic01': is_ic01,
                'p_path': p_path,
            }
            all_visits.append(entry)

            if not is_ae and not is_ic01:
                continue
            if not v_date:
                continue

            target_best = ae_best if is_ae else ic01_best
            if target_best is None or v_date > target_best['date']:
                if is_ae:
                    ae_best = entry
                else:
                    ic01_best = entry

    # ── Print all visits found ────────────────────────────────────────────────

    if not all_visits:
        print(f"\n  ✗ No records found for this patient in any IC file.")
        return

    # Separate into chronic-relevant and everything else
    chronic_hits = [v for v in all_visits if v['is_ae'] or v['is_ic01']]
    other_hits   = [v for v in all_visits if not v['is_ae'] and not v['is_ic01']]

    print(f"\n  All visits for this patient: {len(all_visits)} record(s) across IC files")

    if chronic_hits:
        print(f"\n  ── Chronic-relevant visits (AE連續 or 01西醫/KIND=08) ──")
        for v in sorted(chronic_hits, key=lambda x: x['date'] or date.min, reverse=True):
            tag = '✓ AE連續' if v['is_ae'] else '✓ IC01 (KIND=08)'
            print(f"    {tag:<22}  date={v['date_raw']!r} → {v['date']}  "
                  f"KIND={v['kind']!r}  M20={v['m20']!r}  M33={v['m33']!r}  "
                  f"CF={v['cf']!r}  [{v['file']}]")
    else:
        print(f"\n  ✗ No AE連續 or KIND=08 records found.")

    if other_hits:
        print(f"\n  ── Other 01西醫 visits (not captured as IC01 — KIND is not '08') ──")
        for v in sorted(other_hits, key=lambda x: x['date'] or date.min, reverse=True):
            print(f"    H_TYPE={v['h_type']!r}  KIND={v['kind']!r}  "
                  f"date={v['date_raw']!r} → {v['date']}  CF={v['cf']!r}  [{v['file']}]")

    # ── Show what the algorithm chose ────────────────────────────────────────

    print(f"\n  ── Algorithm decision ──")

    if ae_best and ic01_best:
        use_ic01 = ic01_best['date'] > ae_best['date']
        print(f"    Both AE連續 and IC01 found.")
        print(f"    AE連續 best:  {ae_best['date']}  [{ae_best['file']}]")
        print(f"    IC01    best: {ic01_best['date']}  [{ic01_best['file']}]")
        print(f"    → Using {'IC01' if use_ic01 else 'AE連續'} (more recent)")
        chosen = ic01_best if use_ic01 else ae_best
    elif ic01_best:
        print(f"    IC01 only:  {ic01_best['date']}  [{ic01_best['file']}]")
        use_ic01 = True
        chosen = ic01_best
    elif ae_best:
        print(f"    AE連續 only: {ae_best['date']}  [{ae_best['file']}]")
        use_ic01 = False
        chosen = ae_best
    else:
        print(f"    ✗ No chronic visit selected — patient will NOT appear in list.")
        return

    # ── Check PS lookup ───────────────────────────────────────────────────────

    print(f"\n  ── Prescription days (PS) lookup ──")

    ps = None
    if use_ic01:
        m20 = chosen['m20']
        if m20.isdigit() and int(m20) > 0:
            ps = int(m20)
            print(f"    M20 on IC01 record = {m20!r} → PS = {ps} days")
        else:
            print(f"    M20 = {m20!r} (missing/invalid) → checking P file fallback...")
            p_path = chosen['p_path']
            cf = chosen['cf']
            if cf and os.path.exists(p_path):
                try:
                    for r in _parse_dbf(p_path):
                        if r.get('CODE_F', '').strip() == cf and r.get('LONG', '').strip() == '1':
                            ps_val = r.get('PS', '').strip()
                            if ps_val.isdigit() and int(ps_val) > 0:
                                ps = int(ps_val)
                                print(f"    P file LONG=1 record: PS = {ps_val!r} → PS = {ps} days")
                                break
                    else:
                        print(f"    ✗ No LONG=1 record in P file for CF={cf!r}")
                except Exception as e:
                    print(f"    [!] Could not read P file: {e}")
            else:
                print(f"    P file not found or no CF: {p_path}")
        if ps is None:
            print(f"    ✗ No PS found — patient will be SKIPPED (this is likely the bug)")
            return
    else:
        cf = chosen['cf']
        p_path = chosen['p_path']
        if cf and os.path.exists(p_path):
            try:
                for r in _parse_dbf(p_path):
                    if r.get('CODE_F', '').strip() == cf and r.get('LONG', '').strip() == '1':
                        ps_val = r.get('PS', '').strip()
                        if ps_val.isdigit() and int(ps_val) > 0:
                            ps = int(ps_val)
                            print(f"    P file LONG=1 record: PS = {ps_val!r} → PS = {ps} days")
                            break
                if ps is None:
                    ps = 28
                    print(f"    No LONG=1 record found → defaulting to 28 days")
            except Exception as e:
                ps = 28
                print(f"    [!] Could not read P file ({e}) → defaulting to 28 days")
        else:
            ps = 28
            print(f"    No P file or no CF → defaulting to 28 days")

    # ── Show overdue window check ─────────────────────────────────────────────

    last_visit = chosen['date']
    due_date   = last_visit + timedelta(days=ps)
    days_overdue = (as_of - due_date).days

    print(f"\n  ── Overdue window check ──")
    print(f"    Last visit:   {last_visit}")
    print(f"    PS:           {ps} days")
    print(f"    Due date:     {due_date}  (last_visit + {ps}d)")
    print(f"    As of:        {as_of}")
    print(f"    Days overdue: {days_overdue}")

    if days_overdue < CHRONIC_GRACE:
        print(f"    ✗ Not overdue yet (need >= {CHRONIC_GRACE} days) — patient not shown yet")
    elif days_overdue > MAX_OVERDUE_DAYS:
        print(f"    ✗ Too overdue ({days_overdue} > {MAX_OVERDUE_DAYS}) — patient dropped from list")
    else:
        print(f"    ✓ In follow-up window ({CHRONIC_GRACE}–{MAX_OVERDUE_DAYS} days overdue)")
        print(f"    → Patient SHOULD appear in 慢簽 list")


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_chronic.py <national_id> [<national_id2> ...]")
        sys.exit(1)

    as_of = date.today()
    for nat_id in sys.argv[1:]:
        debug_patient(nat_id.strip(), as_of)
    print()


if __name__ == '__main__':
    main()
