#!/usr/bin/env python3
"""
Check what name is actually stored for the 5 missing patients' nat_ids,
and whether any OTHER name appears with that nat_id in hep records before them.
Run on PC1: python check_hep_natid.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import _ic_main_files, _parse_dbf_cached, _hep_type, _roc_to_date

# From check_hep_trace.py output
TARGET_NATIDS = {
    'L221916363': '王俐云',
    'B221241176': '陳子茜',
    'N121030411': '陳鉞坤',
    'J221953918': '黃晴',
    'Q222276746': '黃沛晴',
}

ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

# For each nat_id, collect ALL names seen across ALL records (not just hep-coded)
# in file order — to show what name would be "first encountered" in hep records
natid_history: dict[str, list[tuple]] = {k: [] for k in TARGET_NATIDS}  # nat_id → [(file, date, name, hep, h_type)]

print(f"Scanning {len(_ic_main_files())} IC files...", flush=True)

for path in _ic_main_files():
    fname = os.path.basename(path)
    try:
        for r in _parse_dbf_cached(path):
            nat_id = r.get('ID', '').strip()
            if nat_id not in TARGET_NATIDS:
                continue
            name   = r.get('NAME', '').strip()
            h_type = r.get('H_TYPE', '').strip()
            v_date = _roc_to_date(r.get('DATE', ''))
            hep    = _hep_type(r) if h_type in ('01西醫', 'AE連續') else None
            natid_history[nat_id].append((fname, v_date, name, hep, h_type))
    except Exception as e:
        print(f"ERROR {fname}: {e}")

print()

for nat_id, expected_name in TARGET_NATIDS.items():
    recs = natid_history[nat_id]
    hep_ok_recs = [(f, d, n, h, ht) for (f, d, n, h, ht) in recs if h is not None and ht in ('01西醫', 'AE連續')]

    print(f"{'='*60}")
    print(f"Nat ID: {nat_id}  (expected name: {expected_name})")
    print(f"Total records with this nat_id: {len(recs)}")
    print(f"Hep+OK_HTYPE records: {len(hep_ok_recs)}")

    if not hep_ok_recs:
        print("  No hep records found — this shouldn't happen based on trace.")
        continue

    # What name would check_hep_names.py use?
    # It uses the FIRST name seen in the FIRST hep record, then only updates if name was empty
    stored_name = ''
    for f, d, n, h, ht in hep_ok_recs:
        if n and not stored_name:
            stored_name = n
        if stored_name:
            break

    print(f"First name stored by check_hep_names.py logic: '{stored_name}'")
    if stored_name == expected_name:
        print(f"  → Matches expected! Something else is wrong.")
    else:
        print(f"  → MISMATCH — stored '{stored_name}', expected '{expected_name}'")
        print(f"  → Patient appears in system under '{stored_name}'")

    # Show all distinct names seen for this nat_id in hep records
    names_in_hep = {}
    for f, d, n, h, ht in hep_ok_recs:
        if n and n not in names_in_hep:
            names_in_hep[n] = (f, d)
    print(f"  All names seen in hep records:")
    for n, (f, d) in names_in_hep.items():
        marker = '← expected' if n == expected_name else '← FIRST STORED' if n == stored_name else ''
        print(f"    '{n}'  first in {f} ({d})  {marker}")
