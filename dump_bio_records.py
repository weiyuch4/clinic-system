#!/usr/bin/env python3
"""
Dump every raw VAR field from a patient's BIO lab records (bioc.dbf +
BIO2C.DBF), across both the old and new reporting platforms, so we can
see exactly which VAR slot holds HBsAg / Anti-HCV / AFP on the NEW
platform (since 2026-04-01) — lab_results.py's NEW_BIO_LABELS dict
doesn't currently map them.

Run on PC1: python dump_bio_records.py P220094718
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab_results as lr

if len(sys.argv) < 2:
    print("Usage: python dump_bio_records.py <nat_id>")
    sys.exit(1)

NAT_ID = sys.argv[1].strip().upper()

patient_code = lr._find_patient_code(NAT_ID)
print(f"nat_id={NAT_ID!r}  ->  patient_code={patient_code!r}\n")
if not patient_code:
    print("No patient code found — can't look up BIO records.")
    sys.exit(1)

for dbf_name in ('bioc.dbf', 'BIO2C.DBF'):
    path = os.path.join(lr.ZZ_DIR, dbf_name)
    if not os.path.isfile(path):
        print(f"({dbf_name} not found at {path})")
        continue
    rows = [r for r in lr._iter_rows(path) if r.get('CODE', '').strip() == patient_code]
    rows.sort(key=lr._bio_display_date, reverse=True)
    print("=" * 70)
    print(f"{dbf_name} — {len(rows)} record(s) for this patient")
    print("=" * 70)
    for row in rows:
        raw_date = row.get('DATE', '')
        is_new = raw_date.strip() >= lr._NEW_PLATFORM_DATE
        display_date = lr._bio_display_date(row)
        print(f"\n  -- record date={display_date}  (raw DATE={raw_date!r}, platform={'NEW' if is_new else 'OLD'}) --")
        for k in sorted(row.keys(), key=lambda x: (len(x), x)):
            v = row[k]
            if not v:
                continue
            print(f"    {k:8s} = {v!r}")

print()
print("=" * 70)
print("WHAT TO LOOK FOR")
print("=" * 70)
print("""
For any record marked platform=NEW, look for a value that looks like
HBsAg / Anti-HCV / AFP result text (e.g. "陰性"/"陽性"/"Negative"/
"Positive", or a numeric AFP value typically a small number like 1-10
ng/mL). It may appear under an unmapped VARxx column, or inside VAR41
as free text (e.g. "HBsAg:陰性 Anti-HCV:陰性 AFP:3.2"). Tell me which
VAR number (or the VAR41 text pattern) it is and I'll add it to
NEW_BIO_LABELS / the parser.
""")
