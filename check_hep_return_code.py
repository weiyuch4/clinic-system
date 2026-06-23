#!/usr/bin/env python3
"""
Locate the "BC肝追蹤6M" order (hover code shown as [EX8] in the clinic HIS)
inside the IC/P DBF data, to find out which field holds it and confirm it
reliably appears when a B/C-hep patient returns for their follow-up visit.

Searches every field of every record (main IC files + their P-file
companions) for a case-insensitive substring match on "EX8" or "肝追蹤",
since we don't know in advance which field holds the code vs. the name.

Run on PC1: python check_hep_return_code.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import Counter
from database import _ic_main_files, _parse_dbf_cached, _roc_to_date

NEEDLES = ('EX8', '肝追蹤', 'BC肝')

def matches(record: dict) -> list[tuple[str, str]]:
    hits = []
    for field, val in record.items():
        if not isinstance(val, str):
            continue
        v = val.strip()
        if not v:
            continue
        vu = v.upper()
        if any(n.upper() in vu for n in NEEDLES):
            hits.append((field, v))
    return hits

field_hit_counter: Counter = Counter()   # field name -> count of matching records
value_counter: Counter = Counter()       # exact matched value -> count
p_samples: list[dict] = []
ic_samples: list[dict] = []

files = _ic_main_files()
print(f"Scanning {len(files)} IC main files + their P-file companions for {NEEDLES!r}...\n", flush=True)

for i, path in enumerate(files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(files)} files", flush=True)

    # Main IC file records
    try:
        for r in _parse_dbf_cached(path):
            hits = matches(r)
            if not hits:
                continue
            for field, val in hits:
                field_hit_counter[f"IC:{field}"] += 1
                value_counter[val] += 1
            if len(ic_samples) < 15:
                ic_samples.append({
                    'file': os.path.basename(path),
                    'nat_id': r.get('ID', '').strip(),
                    'name': r.get('NAME', '').strip(),
                    'date': _roc_to_date(r.get('DATE', '')),
                    'h_type': r.get('H_TYPE', '').strip(),
                    'cf': r.get('CODE_F', '').strip(),
                    'hits': hits,
                })
    except Exception as e:
        print(f"  ERROR (IC) {os.path.basename(path)}: {e}")

    # P-file companion
    p_path = path[:-4] + 'P.DBF'
    if not os.path.exists(p_path):
        continue
    try:
        for r in _parse_dbf_cached(p_path):
            hits = matches(r)
            if not hits:
                continue
            for field, val in hits:
                field_hit_counter[f"P:{field}"] += 1
                value_counter[val] += 1
            if len(p_samples) < 15:
                p_samples.append({
                    'file': os.path.basename(p_path),
                    'cf': r.get('CODE_F', '').strip(),
                    'drug_no': r.get('DRUG_NO', '').strip(),
                    'hits': hits,
                })
    except Exception as e:
        print(f"  ERROR (P) {os.path.basename(p_path)}: {e}")

print()
print("=" * 70)
print("WHICH FIELDS CONTAIN A MATCH")
print("=" * 70)
if not field_hit_counter:
    print("  No matches found anywhere for EX8 / 肝追蹤 / BC肝.")
    print("  The order name/code may use different text than expected —")
    print("  try re-running with different NEEDLES values.")
else:
    for field, cnt in field_hit_counter.most_common():
        print(f"  {field:20s}  {cnt:6d} records")

print()
print("=" * 70)
print("DISTINCT MATCHED VALUES (exact field contents)")
print("=" * 70)
for val, cnt in value_counter.most_common(20):
    print(f"  {cnt:6d}x  {val!r}")

if p_samples:
    print()
    print("=" * 70)
    print("SAMPLE P-FILE RECORDS (up to 15)")
    print("=" * 70)
    for s in p_samples:
        print(f"  file={s['file']:16s} CODE_F={s['cf']:10s} DRUG_NO={s['drug_no']:10s} hits={s['hits']}")

if ic_samples:
    print()
    print("=" * 70)
    print("SAMPLE MAIN-IC RECORDS (up to 15)")
    print("=" * 70)
    for s in ic_samples:
        print(f"  file={s['file']:14s} date={s['date']} nat_id={s['nat_id']:12s} name={s['name']:8s} "
              f"H_TYPE={s['h_type']!r:10s} CODE_F={s['cf']:10s} hits={s['hits']}")

print()
print("=" * 70)
print("NEXT STEP")
print("=" * 70)
print("""
If matches show up under a P-file field (most likely DRUG_NO or a
name/description field), that CODE_F links back to a main IC record via
CODE_F, which gives the patient's nat_id and visit DATE — that's the
signal we'd use to detect "patient has returned for B/C-hep follow-up."
Send back this output and I'll wire up the detection + the new
"returned, awaiting VPN entry" list.
""")
