#!/usr/bin/env python3
"""Check which ICD codes for hepatitis appear in IC files. Run: python check_hep.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from collections import Counter, defaultdict
from database import _ic_main_files, _parse_dbf_cached

ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

# Codes to look for
HEP_PREFIXES = (
    '07030', '07031', '07032', '07033',  # ICD-9 HBV
    '07041', '07044', '07054',            # ICD-9 HCV
    'B16', 'B17', 'B18', 'B19',          # ICD-10 viral hepatitis
    'V0261', 'V0262',                     # ICD-9 carriers
    'Z2251', 'Z2252',                     # ICD-10 carriers
)

def is_hep(code):
    c = code.strip().upper().replace('.', '').replace(' ', '')
    return any(c.startswith(p) for p in HEP_PREFIXES)

# Count unique patients and track what codes appear
patient_codes: dict[str, set[str]] = defaultdict(set)  # nat_id → set of hep ICD codes seen
code_counts = Counter()
primary_patients: dict[str, set[str]] = defaultdict(set)  # nat_id → primary ICD only

files = _ic_main_files()
print(f"Scanning {len(files)} IC files...\n")

for path in files:
    try:
        for r in _parse_dbf_cached(path):
            nat_id = r.get('ID', '').strip()
            if not nat_id:
                continue
            for i, field in enumerate(ICD_FIELDS):
                code = r.get(field, '').strip()
                if code and is_hep(code):
                    patient_codes[nat_id].add(code)
                    code_counts[code] += 1
                    if i == 0:
                        primary_patients[nat_id].add(code)
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")

print(f"Unique hepatitis ICD codes found:")
for code, count in sorted(code_counts.items(), key=lambda x: -x[1]):
    print(f"  {code:12s}  {count:5d} visits")

print(f"\nPatients with hepatitis ICD (any field):    {len(patient_codes)}")
print(f"Patients with hepatitis as PRIMARY ICD:    {len(primary_patients)}")

print(f"\nSample patients (primary ICD):")
for nat_id, codes in list(primary_patients.items())[:5]:
    print(f"  {nat_id}  codes={codes}")
