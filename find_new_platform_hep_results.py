#!/usr/bin/env python3
"""
Find recent (post 2026-04-01 "new platform") patients with a confirmed
BC肝追蹤6M order (P4202C, via database.py's hep detection) and dump their
raw BIO record around that visit date, to find which VAR slot now holds
HBsAg / Anti-HCV / AFP on the new platform — NEW_BIO_LABELS in
lab_results.py doesn't currently map them, so they silently don't show
in the 檢驗結果 modal for any draw after 2026-04-01.

Run on PC1: python find_new_platform_hep_results.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
import database
import lab_results as lr

NEW_PLATFORM_CUTOFF = date(2026, 4, 1)

print("Scanning for hep patients with a confirmed P4202C order on/after 2026-04-01...\n", flush=True)

info = database._scan_hep_patient_info(date(2099, 1, 1))  # far-future as_of to include everyone
candidates = [(nat_id, p) for nat_id, p in info.items() if p['last_visit'] and p['last_visit'] >= NEW_PLATFORM_CUTOFF]
candidates.sort(key=lambda x: x[1]['last_visit'], reverse=True)

print(f"Found {len(candidates)} hep patients with a P4202C-confirmed visit on/after 2026-04-01.\n")
for nat_id, p in candidates[:15]:
    print(f"  nat_id={nat_id:12s} name={p['name']:8s} last_visit={p['last_visit']}")

if not candidates:
    print("\nNo post-2026-04-01 hep panel visits found yet — try again once one exists.")
    sys.exit(0)

print()
print("=" * 70)
print("RAW BIO RECORDS NEAR THE VISIT DATE (top 5 candidates)")
print("=" * 70)

for nat_id, p in candidates[:5]:
    visit_date = p['last_visit']
    patient_code = lr._find_patient_code(nat_id)
    print(f"\nnat_id={nat_id}  name={p['name']}  visit_date={visit_date}  patient_code={patient_code}")
    if not patient_code:
        print("  (no patient_code found via PAT_HIST/IC fallback)")
        continue

    found_nearby = False
    for dbf_name in ('bioc.dbf', 'BIO2C.DBF'):
        path = os.path.join(lr.ZZ_DIR, dbf_name)
        if not os.path.isfile(path):
            continue
        rows = [r for r in lr._iter_rows(path) if r.get('CODE', '').strip() == patient_code]
        for row in rows:
            display_date = lr._bio_display_date(row)
            try:
                y, m, d = (int(x) for x in display_date.split('/'))
                row_date = date(y + 1911 if y < 1911 else y, m, d) if y < 1000 else date(y, m, d)
            except Exception:
                row_date = None
            if row_date and abs((row_date - visit_date).days) > 30:
                continue
            found_nearby = True
            print(f"  [{dbf_name}] record date={display_date} (raw DATE={row.get('DATE','')!r})")
            for k in sorted(row.keys(), key=lambda x: (len(x), x)):
                v = row[k]
                if v:
                    print(f"      {k:8s} = {v!r}")
    if not found_nearby:
        print("  (no BIO record found within 30 days of the visit date)")

print()
print("=" * 70)
print("WHAT TO LOOK FOR")
print("=" * 70)
print("""
In the dumped records above, look for a value that looks like HBsAg /
Anti-HCV results (e.g. "陰性"/"陽性"/"Negative"/"Positive"/a +/- flag) or
an AFP-like small decimal (typically 1-10 ng/mL). Compare against what
your HIS shows for the same patient/date to confirm which VAR field is
which. Tell me the VAR numbers and I'll add them to NEW_BIO_LABELS so
they show up correctly in the 檢驗結果 modal again.
""")
