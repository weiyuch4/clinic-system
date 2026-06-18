#!/usr/bin/env python3
"""
Trace exactly why 5 patients appear in IC files but not in check_hep_names.py.
Run on PC1: python check_hep_trace.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import _ic_main_files, _parse_dbf_cached, _hep_type, _roc_to_date

MISSING = {'王俐云', '陳子茜', '陳鉞坤', '黃晴', '黃沛晴'}
ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

print("Tracing all records that mention these 5 patients by name...\n")

hits: dict[str, list[dict]] = {n: [] for n in MISSING}

for path in _ic_main_files():
    fname = os.path.basename(path)
    try:
        for r in _parse_dbf_cached(path):
            name = r.get('NAME', '').strip()
            if name not in MISSING:
                continue
            h_type = r.get('H_TYPE', '').strip()
            hep    = _hep_type(r)
            nat_id = r.get('ID', '').strip()
            v_date = _roc_to_date(r.get('DATE', ''))
            codes  = [r.get(f, '').strip() for f in ICD_FIELDS if r.get(f, '').strip()]
            hits[name].append({
                'file': fname, 'nat_id': nat_id, 'h_type': h_type,
                'hep': hep, 'date': v_date, 'codes': codes,
            })
    except Exception as e:
        print(f"ERROR {fname}: {e}")

for name in sorted(MISSING):
    recs = hits[name]
    print(f"{'='*60}")
    print(f"Patient: {name}  ({len(recs)} matching records in IC files)")
    if not recs:
        print("  *** NOT FOUND BY NAME IN ANY IC FILE ***")
        continue

    hep_records   = [r for r in recs if r['hep'] is not None]
    ok_h_type     = [r for r in recs if r['h_type'] in ('01西醫', 'AE連續')]
    hep_and_ok    = [r for r in recs if r['hep'] is not None and r['h_type'] in ('01西醫', 'AE連續')]

    print(f"  Total records:              {len(recs)}")
    print(f"  Records with hep ICD:       {len(hep_records)}")
    print(f"  Records with OK H_TYPE:     {len(ok_h_type)}")
    print(f"  Records with BOTH:          {len(hep_and_ok)}  ← these are what check_hep_names.py uses")
    print()

    # Show all records grouped
    for r in recs:
        flag = '✓' if (r['hep'] and r['h_type'] in ('01西醫', 'AE連續')) else '✗'
        print(f"  [{flag}] file={r['file']}  date={r['date']}  H_TYPE={r['h_type']!r}  hep={r['hep']}  codes={r['codes']}")

    if hep_and_ok:
        nat_ids = {r['nat_id'] for r in hep_and_ok}
        print(f"\n  nat_ids seen in BOTH records: {nat_ids}")
        print(f"  → These should have made it into found_by_id.")
        print(f"  → If still missing from name_to_info, two patients share the same nat_id")
        print(f"    and the other patient's record overwrote the name.")
    else:
        print(f"\n  *** REASON FOUND: No records have BOTH a hep ICD code AND an OK H_TYPE ***")
        h_types_seen = {r['h_type'] for r in recs}
        print(f"  H_TYPE values seen: {h_types_seen}")
        if hep_records:
            print(f"  Their hep records use H_TYPE: {[r['h_type'] for r in hep_records]}")
