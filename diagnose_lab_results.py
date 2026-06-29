import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"c:\Users\weiyu\OneDrive\Documents\Visual Studio\clinic-system")

import lab_results as lr

if len(sys.argv) < 2:
    print("Usage: python diagnose_lab_results.py <NATIONAL_ID>")
    sys.exit(1)

national_id = sys.argv[1].strip().upper()

print(f"ZZ_DIR = {lr.ZZ_DIR}")
print(f"IC_DIR = {lr.IC_DIR}\n")

print(f"Step 1: _find_patient_code({national_id!r})")
code = lr._find_patient_code(national_id)
print(f"  -> patient_code = {code!r}\n")

if not code:
    print("STOPPED HERE: no patient code found. PAT_HIST.DBF and IC files were both checked.")
    print("This means get_lab_results() would return empty bio/cbc with no error — matching")
    print("\"doesn't show up at all\". Need to find where this national ID's code actually lives.")
    sys.exit(0)

print(f"Step 2: scanning bioc.dbf and BIO2C.DBF for CODE == {code!r}")
import os
for dbf_name in ("bioc.dbf", "BIO2C.DBF"):
    path = os.path.join(lr.ZZ_DIR, dbf_name)
    exists = os.path.isfile(path)
    print(f"  {dbf_name}: file exists = {exists}")
    if not exists:
        continue
    rows = lr._cached_rows(path)
    matching = [r for r in rows if r.get("CODE", "").strip() == code]
    print(f"    total rows in file = {len(rows)}, rows matching this patient_code = {len(matching)}")
    for r in sorted(matching, key=lambda r: r.get("DATE", ""), reverse=True)[:5]:
        raw_date = r.get("DATE", "")
        is_new = raw_date.strip() >= lr._NEW_PLATFORM_DATE
        print(f"      DATE={raw_date!r} (new_platform={is_new})  VAR41={r.get('VAR41', '')!r}")

print("\nStep 3: full get_lab_results() result")
result = lr.get_lab_results(national_id)
print(f"  patient_code = {result['patient_code']!r}")
print(f"  error = {result['error']!r}")
print(f"  bio records = {len(result['bio'])}")
print(f"  cbc records = {len(result['cbc'])}")
for rec in result["bio"][:3]:
    print(f"    date={rec['date']}  items={rec['items']}")
