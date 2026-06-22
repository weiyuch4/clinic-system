#!/usr/bin/env python3
"""
Verify that IC01 (連續處方箋 first dispense) detection correctly distinguishes
itself from regular 慢性病 visits. Run on PC1: python verify_ic01.py

Uses the EXACT same parsing + classification helpers as database.py's
_query_chronic_prescriptions (_ic_files_since, _parse_dbf_cached,
_p_file_has_long1, _icd_to_name), so this validates the real code path,
not a reimplementation that could itself be wrong.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from collections import Counter, defaultdict
from database import (
    _ic_files_since, _ic_main_files, _parse_dbf_cached, _roc_to_date,
    _p_file_has_long1, _icd_to_name,
)

AS_OF = date.today()
SINCE = AS_OF - timedelta(days=365)  # same window _query_chronic_prescriptions uses

files = _ic_files_since(SINCE)
print(f"Scanning {len(files)} IC files (since {SINCE}, matching production window)...\n", flush=True)

ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

m33_counter = Counter()
m26_counter = Counter()

group_a = []  # M33=1, M26=3, LONG=1 confirmed in P file  -> real IC01
group_b = []  # M33=1, M26=3, but NO LONG=1 record found  -> rejected
group_c = []  # 01西醫 with some other M33/M26 combo       -> not IC01
group_d = []  # 01西醫 with M33 and M26 both empty          -> plain chronic visit

total_01 = 0

for i, path in enumerate(files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(files)} files", flush=True)
    try:
        records = _parse_dbf_cached(path)
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")
        continue
    p_path = path[:-4] + 'P.DBF'

    for r in records:
        if r.get('H_TYPE', '') != '01西醫':
            continue
        total_01 += 1
        m33 = r.get('M33', '').strip()
        m26 = r.get('M26', '').strip()
        m33_counter[m33 or '(empty)'] += 1
        m26_counter[m26 or '(empty)'] += 1

        cf = r.get('CODE_F', '').strip()
        nat_id = r.get('ID', '').strip()
        name = r.get('NAME', '').strip()
        v_date = _roc_to_date(r.get('DATE', ''))
        icd = next((r.get(f, '') for f in ICD_FIELDS if _icd_to_name(r.get(f, ''))), '')

        rec = {
            'file': os.path.basename(path), 'nat_id': nat_id, 'name': name,
            'date': v_date, 'cf': cf, 'm33': m33, 'm26': m26,
            'icd': icd, 'disease': _icd_to_name(icd) or '',
        }

        if m33 == '1' and m26 == '3':
            has_long = _p_file_has_long1(p_path, cf)
            rec['p_path'] = p_path
            rec['has_long1'] = has_long
            (group_a if has_long else group_b).append(rec)
        elif m33 or m26:
            group_c.append(rec)
        else:
            group_d.append(rec)

if total_01 == 0:
    print("No 01西醫 records found in window — nothing to verify.")
    sys.exit(0)

print()
print("=" * 70)
print("M33 VALUE DISTRIBUTION (all 01西醫 records)")
print("=" * 70)
for val, cnt in m33_counter.most_common():
    print(f"  M33={val!r:10s}  {cnt:6d}  ({100*cnt/total_01:.2f}%)")

print()
print("=" * 70)
print("M26 VALUE DISTRIBUTION (all 01西醫 records)")
print("=" * 70)
for val, cnt in m26_counter.most_common():
    print(f"  M26={val!r:10s}  {cnt:6d}  ({100*cnt/total_01:.2f}%)")

print()
print("=" * 70)
print("CLASSIFICATION SUMMARY")
print("=" * 70)
print(f"  Total 01西醫 records scanned:                    {total_01}")
print(f"  Group A — M33=1,M26=3,LONG=1 (= real IC01):       {len(group_a)}  ({100*len(group_a)/total_01:.2f}%)")
print(f"  Group B — M33=1,M26=3, but NO LONG=1 (rejected):  {len(group_b)}")
print(f"  Group C — other M33/M26 combo (NOT IC01):         {len(group_c)}")
print(f"  Group D — M33/M26 both empty (plain visit):       {len(group_d)}")

# ── Cross-validation: do Group A patients actually get a follow-up refill? ──
print()
print("=" * 70)
print("CROSS-VALIDATION: do Group A (IC01) patients get a follow-up AE連續?")
print("=" * 70)
print("If IC01 detection is correct, patients whose prescription window has")
print("already elapsed should show an AE連續 (IC02) refill afterward.\n")

ps_lookup = {}
for rec in group_a:
    try:
        for pr in _parse_dbf_cached(rec['p_path']):
            if pr.get('CODE_F', '').strip() == rec['cf'] and pr.get('LONG', '').strip() == '1':
                ps_val = pr.get('PS', '').strip()
                if ps_val.isdigit():
                    ps_lookup[rec['cf']] = int(ps_val)
                break
    except Exception:
        pass

nat_ids_a = {rec['nat_id'] for rec in group_a}
print(f"Scanning ALL IC files for AE連續 refills for {len(nat_ids_a)} candidate patients...", flush=True)
ae_by_natid = defaultdict(list)
for path in _ic_main_files():
    try:
        for r in _parse_dbf_cached(path):
            if r.get('H_TYPE', '') != 'AE連續':
                continue
            nid = r.get('ID', '').strip()
            if nid not in nat_ids_a:
                continue
            vd = _roc_to_date(r.get('DATE', ''))
            if vd:
                ae_by_natid[nid].append(vd)
    except Exception:
        pass

confirmed = too_recent = unconfirmed = no_ps = 0
for rec in group_a:
    ps = ps_lookup.get(rec['cf'])
    if not rec['date'] or not ps:
        no_ps += 1
        continue
    window_end = rec['date'] + timedelta(days=ps + 30)  # ps days + 30-day grace
    if AS_OF < window_end:
        too_recent += 1
        continue
    ae_dates = ae_by_natid.get(rec['nat_id'], [])
    if any(rec['date'] < d <= window_end for d in ae_dates):
        confirmed += 1
    else:
        unconfirmed += 1

checkable = confirmed + unconfirmed
print(f"  Confirmed (refill found in expected window):        {confirmed}/{checkable}"
      f"  ({100*confirmed/checkable:.1f}%)" if checkable else f"  Confirmed: {confirmed}")
print(f"  Unconfirmed (window elapsed, no refill found):       {unconfirmed}/{checkable}" if checkable else f"  Unconfirmed: {unconfirmed}")
print(f"  Too recent to judge yet (window hasn't elapsed):     {too_recent}")
print(f"  Skipped (no PS found in P file):                     {no_ps}")
print()
print("  A high confirmed-rate among 'checkable' patients is strong evidence")
print("  IC01 detection is correct. Unconfirmed cases may be patients who")
print("  stopped treatment, switched clinics, or genuinely are false positives.")


def print_samples(label, group, n=15):
    print()
    print("=" * 70)
    print(f"{label} — showing up to {n} samples for manual verification")
    print("=" * 70)
    if not group:
        print("  (none)")
        return
    for rec in group[:n]:
        extra = f"  LONG1={rec.get('has_long1')}" if 'has_long1' in rec else ""
        print(f"  {rec['name']:8s}  {rec['nat_id']:12s}  {rec['date']}  CODE_F={rec['cf']:10s}  "
              f"M33={rec['m33']!r:4s} M26={rec['m26']!r:4s}  ICD={rec['icd']:8s} {rec['disease']}{extra}  file={rec['file']}")


print_samples("GROUP A (classified as IC01)", group_a)
print_samples("GROUP B (M33=1,M26=3 but rejected — no LONG=1 in P file)", group_b)
print_samples("GROUP C (other M33/M26 combo — NOT IC01)", group_c)
print_samples("GROUP D (plain 慢性病 visit, M33/M26 both empty)", group_d)

print()
print("=" * 70)
print("HOW TO VERIFY MANUALLY")
print("=" * 70)
print("""
Pick a few NAME/DATE/CODE_F rows from each group above and look them up in
the clinic system or paper chart:
  - Group A patients should be patients who picked up a NEW 3-cycle
    連續處方箋 on that date (a long-term prescription meant to be refilled).
  - Group D patients should be ordinary chronic-disease visits with a single
    dispense and no scheduled 連續處方箋 refill.
If any Group A patient does NOT look like a 連續處方箋 first-dispense, or
any Group D/C patient DOES look like one, that's a real bug — note the
NAME / DATE / CODE_F and report it.
""")
