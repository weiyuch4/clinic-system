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

        found_in_file = []
        for r in records:
            if r.get('ID', '').strip() != nat_id:
                continue

            h_type = r.get('H_TYPE', '').strip()
            kind   = r.get('KIND',   '').strip()
            v_date = _roc_to_date(r.get('DATE', ''))
            cf     = r.get('CODE_F', '').strip()
            m20    = r.get('M20', '').strip()
            m33    = r.get('M33', '').strip()

            is_ae       = h_type == 'AE連續'
            is_01nishi  = h_type == '01西醫'

            entry = {
                'file':     f'IC{stem}.DBF',
                'h_type':   h_type,
                'kind':     kind,
                'date':     v_date,
                'date_raw': r.get('DATE', '').strip(),
                'cf':       cf,
                'm20':      m20,
                'm33':      m33,
                'is_ae':    is_ae,
                'is_01':    is_01nishi,
                'p_path':   p_path,
                'ic_row':   r,
            }
            all_visits.append(entry)
            found_in_file.append(f"H_TYPE={h_type!r} KIND={kind!r} DATE={r.get('DATE','').strip()!r}")

            if not is_ae:
                continue
            if not v_date:
                continue

            if ae_best is None or v_date > ae_best['date']:
                ae_best = entry

        if found_in_file:
            print(f"  [{stem}] {len(found_in_file)} record(s): " + " | ".join(found_in_file))

    # ── Print all visits found ────────────────────────────────────────────────

    if not all_visits:
        print(f"\n  ✗ No records found for this patient in any IC file.")
        return

    ae_hits   = [v for v in all_visits if v['is_ae']]
    nishi_hits = [v for v in all_visits if v['is_01']]

    print(f"\n  All visits for this patient: {len(all_visits)} record(s) across IC files")

    if ae_hits:
        print(f"\n  ── AE連續 visits (captured) ──")
        for v in sorted(ae_hits, key=lambda x: x['date'] or date.min, reverse=True):
            print(f"    ✓ AE連續  date={v['date_raw']!r} → {v['date']}  "
                  f"M33={v['m33']!r}  CF={v['cf']!r}  [{v['file']}]")

    # Check every 01西醫 visit for LONG=1 in P file and dump all fields so we
    # can spot what distinguishes a real IC01 from a regular 慢性病 visit.
    if nishi_hits:
        print(f"\n  ── 01西醫 visits — P file LONG=1 detail (most recent 2 years) ──")
        cutoff = as_of - timedelta(days=730)
        recent = [v for v in nishi_hits if v['date'] and v['date'] >= cutoff]
        for v in sorted(recent, key=lambda x: x['date'] or date.min, reverse=True):
            p_path = v['p_path']
            cf     = v['cf']
            long1_records = []
            if cf and os.path.exists(p_path):
                try:
                    for pr in _parse_dbf(p_path):
                        if pr.get('CODE_F', '').strip() == cf and pr.get('LONG', '').strip() == '1':
                            long1_records.append(pr)
                except Exception:
                    pass
            if long1_records:
                print(f"\n    KIND={v['kind']!r}  date={v['date_raw']!r} → {v['date']}  "
                      f"CF={cf!r}  [{v['file']}]  ← HAS LONG=1")
                # Dump IC main file fields (skip obvious/known ones)
                ic_skip = {'ID', 'NAME', 'BIRTH', 'DATE', 'CODE_F', 'H_TYPE', 'KIND'}
                ic_fields_str = '  '.join(
                    f"{k}={v['ic_row'][k]!r}" for k in v['ic_row']
                    if v['ic_row'][k].strip() and k not in ic_skip
                )
                if ic_fields_str:
                    print(f"      IC: {ic_fields_str}")
                for pr in long1_records:
                    # Print every non-empty field
                    fields_str = '  '.join(
                        f"{k}={pr[k]!r}" for k in pr if pr[k].strip()
                        and k not in ('CODE_F',)
                    )
                    print(f"      P: {fields_str}")
            else:
                print(f"    KIND={v['kind']!r}  date={v['date_raw']!r} → {v['date']}  "
                      f"CF={cf!r}  [{v['file']}]  (no LONG=1)")

    # ── Show what the algorithm chose ────────────────────────────────────────

    print(f"\n  ── Algorithm decision (current code — AE連續 only) ──")

    if ae_best:
        print(f"    AE連續 best: {ae_best['date']}  [{ae_best['file']}]")
        chosen = ae_best
    else:
        print(f"    ✗ No AE連續 found — patient will NOT appear in list.")
        return

    # ── Check PS lookup ───────────────────────────────────────────────────────

    print(f"\n  ── Prescription days (PS) lookup ──")

    ps = None
    if False:  # placeholder — ic01_best path kept for structure
        pass
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
