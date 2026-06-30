import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"c:\Users\weiyu\OneDrive\Documents\Visual Studio\clinic-system")

import lab_results as lr

if len(sys.argv) < 2:
    print("Usage: python diagnose_lab_results.py <NATIONAL_ID>")
    sys.exit(1)

national_id = sys.argv[1].strip().upper()

print(f"ZZ_DIR     = {lr.ZZ_DIR}")
print(f"IC_DIR_LAB = {lr.IC_DIR}")
print(f"NEW_PLATFORM_DATE cutoff = {lr._NEW_PLATFORM_DATE}\n")

print(f"Step 1: _find_patient_code({national_id!r})")
code = lr._find_patient_code(national_id)
print(f"  -> patient_code = {code!r}\n")

if not code:
    print("STOPPED: no patient code found.")
    sys.exit(0)

print(f"Step 2: all bioc.dbf rows for CODE == {code!r}")
for dbf_name in ("bioc.dbf", "BIO2C.DBF"):
    path = os.path.join(lr.ZZ_DIR, dbf_name)
    exists = os.path.isfile(path)
    print(f"\n  {dbf_name}: exists={exists}")
    if not exists:
        continue
    rows = lr._cached_rows(path)
    matching = [r for r in rows if r.get("CODE", "").strip() == code]
    print(f"  total in file={len(rows)}, matching={len(matching)}")
    for r in sorted(matching, key=lambda r: r.get("DATE", ""), reverse=True):
        raw_date = r.get("DATE", "")
        is_new = raw_date.strip() >= lr._NEW_PLATFORM_DATE
        display_date = lr._bio_display_date(r)
        non_empty_vars = {k: v for k, v in r.items()
                         if k.startswith("VAR") and v.strip()}
        var41 = r.get("VAR41", "")
        print(f"    DATE={raw_date!r} display={display_date!r} new={is_new}")
        print(f"      non-empty VARs: {list(non_empty_vars.keys())}")
        if var41:
            print(f"      VAR41={var41!r}")

print("\nStep 3: what get_lab_results() actually returns")
result = lr.get_lab_results(national_id)
print(f"  patient_code={result['patient_code']!r}  error={result['error']!r}")
print(f"  bio records returned: {len(result['bio'])}  cbc: {len(result['cbc'])}")
for rec in result["bio"]:
    labels = [i['label'] for i in rec['items']]
    print(f"    date={rec['date']}  items: {labels}")
