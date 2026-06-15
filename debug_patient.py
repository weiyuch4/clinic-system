#!/usr/bin/env python3
"""Trace exactly why A121443480 is/isn't detected. Run: python debug_patient.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from database import _ic_files_since, _parse_dbf_cached, _roc_to_date, _icd_to_name, _p_file_has_long1

TARGET = 'A121443480'
as_of  = date.today()
since  = as_of - timedelta(days=365)

print(f"as_of={as_of}  since={since}\n")

ae_best   = {}
ic01_best = {}

for ic_path in _ic_files_since(since):
    try:
        records = _parse_dbf_cached(ic_path)
    except Exception as e:
        print(f"  ERROR reading {ic_path}: {e}")
        continue
    p_path = ic_path[:-4] + 'P.DBF'

    for r in records:
        if r.get('ID', '').strip() != TARGET:
            continue

        h_type   = r.get('H_TYPE', '')
        is_ae    = h_type == 'AE連續'
        is_nishi = h_type == '01西醫'
        if not is_ae and not is_nishi:
            print(f"  SKIP  {os.path.basename(ic_path)} H_TYPE={h_type!r} (not AE/01)")
            continue

        v_date = _roc_to_date(r.get('DATE', ''))
        cf     = r.get('CODE_F', '').strip()
        m33    = r.get('M33', '').strip()
        m26    = r.get('M26', '').strip()
        name   = r.get('NAME', '').strip()
        birth  = _roc_to_date(r.get('BIRTH', ''))

        print(f"  FOUND {os.path.basename(ic_path)} H_TYPE={h_type} DATE={r.get('DATE','')} "
              f"M33={m33!r} M26={m26!r} CF={cf} name={name!r} birth={birth}")

        if not v_date or v_date > as_of:
            print(f"    → SKIP: v_date={v_date} out of range")
            continue

        if is_nishi:
            if nat_id_already := (TARGET in ic01_best and v_date <= ic01_best[TARGET]['date']):
                print(f"    → SKIP: older than existing ic01_best {ic01_best[TARGET]['date']}")
                continue
            if not (m33 == '1' and m26 == '3'):
                print(f"    → SKIP: not IC01 (M33={m33!r} M26={m26!r})")
                continue
            if not _p_file_has_long1(p_path, cf):
                print(f"    → SKIP: no LONG=1 in P file for CF={cf}")
                continue
            ic01_best[TARGET] = {'date': v_date, 'code_fs': [cf], 'name': name, 'birth': birth,
                                  'icd': '', 'ic_path': ic_path}
            print(f"    → STORED in ic01_best")

        if is_ae:
            target = ae_best
            if TARGET not in target or v_date > target[TARGET]['date']:
                target[TARGET] = {'date': v_date, 'code_fs': [cf], 'm33': m33,
                                   'name': name, 'birth': birth, 'icd': '', 'ic_path': ic_path}
                print(f"    → STORED in ae_best (date={v_date} m33={m33!r})")
            elif v_date == target[TARGET]['date']:
                print(f"    → MERGED into ae_best same-date")

print()
print(f"ae_best:   {ae_best.get(TARGET)}")
print(f"ic01_best: {ic01_best.get(TARGET)}")

ae   = ae_best.get(TARGET)
ic01 = ic01_best.get(TARGET)
if not ae and not ic01:
    print("\nNeither ae_best nor ic01_best has this patient → NOT DETECTED")
    sys.exit()

use_ic01 = ic01 is not None and (ae is None or ic01['date'] > ae['date'])
v = ic01 if use_ic01 else ae
print(f"\nuse_ic01={use_ic01}  v={v}")

if not v['name'] or not v['birth']:
    print(f"→ SKIP: missing name={v['name']!r} or birth={v['birth']}")
    sys.exit()

from database import _parse_dbf_cached
from database import CHRONIC_GRACE_DAYS, MAX_CHRONIC_OVERDUE_DAYS

# Build ps_lookup
ps_lookup = {}
p_path = v['ic_path'][:-4] + 'P.DBF'
if os.path.exists(p_path):
    for r in _parse_dbf_cached(p_path):
        cf = r.get('CODE_F', '').strip()
        if cf in v['code_fs'] and cf not in ps_lookup and r.get('LONG', '').strip() == '1':
            ps_val = r.get('PS', '').strip()
            if ps_val.isdigit() and int(ps_val) > 0:
                ps_lookup[cf] = int(ps_val)
                print(f"ps_lookup[{cf!r}] = {int(ps_val)}")

if use_ic01:
    ps = next((ps_lookup[cf] for cf in v['code_fs'] if cf in ps_lookup), None)
    if not ps:
        print(f"→ SKIP: no PS found for IC01 code_fs={v['code_fs']}")
        sys.exit()
    total_ps = ps
else:
    total_ps = sum(ps_lookup.get(cf, 28) for cf in v['code_fs']) if v['code_fs'] else 28

due_date     = v['date'] + timedelta(days=total_ps)
days_overdue = (as_of - due_date).days
print(f"\ndate={v['date']}  total_ps={total_ps}  due={due_date}  days_overdue={days_overdue}")
print(f"GRACE={CHRONIC_GRACE_DAYS}  MAX={MAX_CHRONIC_OVERDUE_DAYS}")

if not (CHRONIC_GRACE_DAYS <= days_overdue <= MAX_CHRONIC_OVERDUE_DAYS):
    print(f"→ SKIP: days_overdue={days_overdue} outside [{CHRONIC_GRACE_DAYS}, {MAX_CHRONIC_OVERDUE_DAYS}]")
else:
    stage = 'IC02' if use_ic01 else ('IC01' if v.get('m33') == '3' else 'IC03')
    print(f"→ WOULD BE DETECTED  stage={stage}")
