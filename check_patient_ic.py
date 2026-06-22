#!/usr/bin/env python3
"""
Trace a specific patient's IC records to diagnose why a recent visit
(e.g. an IC02 pickup) isn't being picked up by 慢簽 tracking.

Run on PC1: python check_patient_ic.py N122601316
(defaults to N122601316 if no argument given)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from database import (
    _ic_files_since, _ic_main_files, _parse_dbf_cached, _roc_to_date,
    _query_chronic_prescriptions,
)
import contacts

NAT_ID = (sys.argv[1].strip().upper() if len(sys.argv) > 1 else "N122601316")
AS_OF = date.today()
ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

print(f"Tracing nat_id={NAT_ID!r} as of {AS_OF}\n")

# 1. Scan ALL main IC files (not just the 365-day production window) for this nat_id.
print("=" * 70)
print("ALL RECORDS FOUND (any H_TYPE) — scanning ALL IC main files")
print("=" * 70)
found_any = False
all_files = _ic_main_files()
print(f"({len(all_files)} IC main files total)\n", flush=True)
for i, path in enumerate(all_files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(all_files)} files", flush=True)
    try:
        for r in _parse_dbf_cached(path):
            if r.get('ID', '').strip().upper() != NAT_ID:
                continue
            found_any = True
            v_date = _roc_to_date(r.get('DATE', ''))
            h_type = r.get('H_TYPE', '').strip()
            cf     = r.get('CODE_F', '').strip()
            m33    = r.get('M33', '').strip()
            m26    = r.get('M26', '').strip()
            name   = r.get('NAME', '').strip()
            icd    = next((r.get(f, '').strip() for f in ICD_FIELDS if r.get(f, '').strip()), '')
            print(f"  file={os.path.basename(path):16s} date={v_date}  H_TYPE={h_type!r:10s} "
                  f"CODE_F={cf:10s} M33={m33!r:4s} M26={m26!r:4s} name={name} ICD={icd}")
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")

print()
if not found_any:
    print("  *** NOT FOUND IN ANY IC FILE under this nat_id. ***")
    print("  This means either:")
    print("    - the nat_id is mistyped, or")
    print("    - the IC file containing the June 10 visit is missing / not yet")
    print("      synced to this machine (same root cause as the earlier 手動標記已取藥 cases).")
else:
    print("  (See rows above for every record found under this nat_id.)")

# 2. Show which files _query_chronic_prescriptions actually scans (365-day window).
print()
print("=" * 70)
print("FILES SCANNED BY _query_chronic_prescriptions (365-day window)")
print("=" * 70)
since = AS_OF - timedelta(days=365)
window_files = _ic_files_since(since)
print(f"  Window: since {since}  ({len(window_files)} files)")
window_names = {os.path.basename(p) for p in window_files}
all_names = {os.path.basename(p) for p in all_files}
missing_from_window = sorted(all_names - window_names)
if missing_from_window:
    print(f"  NOTE: {len(missing_from_window)} IC main files exist but fall OUTSIDE this window")
    print(f"        (only relevant if the June 10 visit's file is one of them — it shouldn't be,")
    print(f"        since June 10 is recent).")

# 3. Check for a stale/interfering manual_pickups record.
print()
print("=" * 70)
print("CHECKING manual_pickups TABLE (contacts.db) for this patient")
print("=" * 70)
try:
    mp_map = contacts.get_manual_pickup_map()
    mp = mp_map.get(NAT_ID)
    if mp:
        print(f"  Manual pickup record found: pickup_date={mp[0]}  ps_days={mp[1]}")
        print("  (This only matters for SUPPRESSING the overdue list — it should not")
        print("   prevent a real IC record from being read.)")
    else:
        print("  No manual pickup record found for this patient.")
except Exception as e:
    print(f"  Could not read contacts.db: {e}")

# 4. Show what the real production function computes RIGHT NOW.
print()
print("=" * 70)
print("WHAT _query_chronic_prescriptions COMPUTES RIGHT NOW")
print("=" * 70)
entries = _query_chronic_prescriptions(AS_OF)
match = [e for e in entries if e.patient.chart_number == NAT_ID]
if match:
    for e in match:
        print(f"  Patient appears as OVERDUE: stage={e.chronic_stage}  last_visit={e.last_visit_date}  "
              f"due={e.due_date}  days_overdue={e.days_overdue}")
    print()
    print("  If last_visit shown above is BEFORE June 10, the June 10 visit was never")
    print("  picked up — check the 'ALL RECORDS FOUND' section above for that date.")
else:
    print("  Patient does NOT currently appear in the overdue chronic_prescriptions list.")
    print("  Either they're not overdue yet, or no qualifying AE連續/01西醫-IC01 record")
    print("  was found for them at all in the 365-day window.")
