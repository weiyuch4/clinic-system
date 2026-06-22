#!/usr/bin/env python3
"""
Find IC records that carry a 連續處方箋 cycle marker (M26='3') but use an
H_TYPE other than 'AE連續' or '01西醫' — these are silently skipped by
_query_chronic_prescriptions today. Checks how widespread the issue is
before changing the detection logic.

Run on PC1: python check_unknown_htype.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import Counter
from database import _ic_main_files, _parse_dbf_cached, _roc_to_date

KNOWN = {'AE連續', '01西醫'}

htype_counter = Counter()       # H_TYPE -> count, among records with M26='3'
samples: dict[str, list] = {}   # H_TYPE -> sample rows (for unknown types only)

files = _ic_main_files()
print(f"Scanning {len(files)} IC main files for M26='3' records with unexpected H_TYPE...\n", flush=True)

for i, path in enumerate(files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(files)} files", flush=True)
    try:
        for r in _parse_dbf_cached(path):
            m26 = r.get('M26', '').strip()
            if m26 != '3':
                continue
            h_type = r.get('H_TYPE', '').strip()
            htype_counter[h_type] += 1
            if h_type not in KNOWN:
                samples.setdefault(h_type, [])
                if len(samples[h_type]) < 10:
                    samples[h_type].append({
                        'file': os.path.basename(path),
                        'date': _roc_to_date(r.get('DATE', '')),
                        'nat_id': r.get('ID', '').strip(),
                        'name': r.get('NAME', '').strip(),
                        'cf': r.get('CODE_F', '').strip(),
                        'm33': r.get('M33', '').strip(),
                        'icd': next((r.get(f, '').strip() for f in
                                     ('ICD','ICD1','ICD2','ICD3','ICD4','ICD5')
                                     if r.get(f, '').strip()), ''),
                    })
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")

print()
print("=" * 70)
print("H_TYPE DISTRIBUTION among records with M26='3' (連續處方箋 series marker)")
print("=" * 70)
total = sum(htype_counter.values())
for h, cnt in htype_counter.most_common():
    flag = "" if h in KNOWN else "  <-- NOT recognized by _query_chronic_prescriptions"
    print(f"  H_TYPE={h!r:10s}  {cnt:6d}  ({100*cnt/total:.2f}%){flag}")

unknown_total = sum(c for h, c in htype_counter.items() if h not in KNOWN)
print()
print(f"  Total M26='3' records: {total}")
print(f"  Recognized (AE連續/01西醫):   {total - unknown_total}")
print(f"  UNRECOGNIZED (silently skipped): {unknown_total}")

if samples:
    print()
    print("=" * 70)
    print("SAMPLES of unrecognized H_TYPE records (up to 10 each)")
    print("=" * 70)
    for h_type, rows in samples.items():
        print(f"\n  H_TYPE={h_type!r}:")
        for s in rows:
            print(f"    file={s['file']:14s} date={s['date']}  nat_id={s['nat_id']:12s} name={s['name']:8s} "
                  f"CODE_F={s['cf']:10s} M33={s['m33']!r:4s} ICD={s['icd']}")
else:
    print()
    print("  No unrecognized H_TYPE values found — this patient's 'AB療程' case")
    print("  may be the only one. Still worth fixing, but low overall impact.")
