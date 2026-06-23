#!/usr/bin/env python3
"""
For every visit that carries a hep B/C ICD code (the same check
_query_hep_followups uses), look up the P-file order codes (DRUG_NO)
billed on that visit, and tally which codes appear most often.

A real "BC肝追蹤6M"-type panel should show up on a large, consistent
fraction of these visits — much higher than codes that are just
incidental (e.g. routine diabetes labs that happen to be ordered the
same day). Also breaks results out by whether the hep ICD was in the
primary ICD field vs. only a secondary ICD1-5 field, since a hep code
listed only as a secondary/standing diagnosis is weaker evidence the
visit was actually for hep monitoring.

Run on PC1: python check_hep_order_codes.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import Counter, defaultdict
from database import _ic_main_files, _parse_dbf_cached, _hep_type, _roc_to_date

total_visits = 0
primary_hep_visits = 0      # ICD field itself is a hep code
secondary_only_visits = 0   # hep code only in ICD1-5, not ICD

# DRUG_NO -> count of hep-coded visits that included it
code_counter_all = Counter()
code_counter_primary = Counter()

# Sample CODE_F -> (file, nat_id, date) for a few visits, to cross-check manually
samples = []

files = _ic_main_files()
print(f"Scanning {len(files)} IC main files for hep-ICD-coded visits...\n", flush=True)

for i, path in enumerate(files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(files)} files", flush=True)

    try:
        records = _parse_dbf_cached(path)
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")
        continue

    hep_visits = []  # (cf, is_primary, nat_id, date)
    for r in records:
        if r.get('H_TYPE', '') not in ('01西醫', 'AE連續'):
            continue
        hep = _hep_type(r)
        if not hep:
            continue
        total_visits += 1
        is_primary = _hep_type({'ICD': r.get('ICD', '')}) is not None
        if is_primary:
            primary_hep_visits += 1
        else:
            secondary_only_visits += 1
        cf = r.get('CODE_F', '').strip()
        if cf:
            hep_visits.append((cf, is_primary, r.get('ID', '').strip(), r.get('DATE', '')))
            if len(samples) < 20:
                samples.append((os.path.basename(path), cf, is_primary, r.get('ID', '').strip(), r.get('DATE', '')))

    if not hep_visits:
        continue

    p_path = path[:-4] + 'P.DBF'
    if not os.path.exists(p_path):
        continue
    try:
        p_by_cf = defaultdict(set)
        for r in _parse_dbf_cached(p_path):
            cf = r.get('CODE_F', '').strip()
            drug_no = r.get('DRUG_NO', '').strip()
            if cf and drug_no:
                p_by_cf[cf].add(drug_no)
    except Exception as e:
        print(f"  ERROR (P) {os.path.basename(p_path)}: {e}")
        continue

    for cf, is_primary, nat_id, dt in hep_visits:
        for drug_no in p_by_cf.get(cf, ()):
            code_counter_all[drug_no] += 1
            if is_primary:
                code_counter_primary[drug_no] += 1

print()
print("=" * 70)
print("HEP-ICD-CODED VISIT BREAKDOWN")
print("=" * 70)
print(f"  Total hep-ICD-coded visits (01西醫/AE連續):      {total_visits}")
print(f"  Hep code in PRIMARY ICD field:                   {primary_hep_visits}")
print(f"  Hep code ONLY in secondary ICD1-5 fields:         {secondary_only_visits}")

print()
print("=" * 70)
print("TOP 25 DRUG_NO CODES CO-OCCURRING WITH ANY HEP-CODED VISIT")
print("=" * 70)
for code, cnt in code_counter_all.most_common(25):
    pct = 100 * cnt / total_visits if total_visits else 0
    print(f"  {code:10s}  {cnt:6d} visits  ({pct:.1f}% of all hep-coded visits)")

print()
print("=" * 70)
print("TOP 25 DRUG_NO CODES CO-OCCURRING WITH PRIMARY-ICD HEP VISITS ONLY")
print("=" * 70)
for code, cnt in code_counter_primary.most_common(25):
    pct = 100 * cnt / primary_hep_visits if primary_hep_visits else 0
    print(f"  {code:10s}  {cnt:6d} visits  ({pct:.1f}% of primary-ICD hep visits)")

print()
print("=" * 70)
print("SAMPLE VISITS (up to 20, for manual cross-check)")
print("=" * 70)
for fname, cf, is_primary, nat_id, dt in samples:
    print(f"  file={fname:14s} CODE_F={cf:10s} primary_icd={is_primary!s:5s} nat_id={nat_id:12s} date={dt}")

print()
print("=" * 70)
print("HOW TO READ THIS")
print("=" * 70)
print("""
Look for a DRUG_NO code with a HIGH percentage in the "PRIMARY-ICD" table
(ideally 70%+) — that's a strong candidate for the actual hep monitoring
panel, since it consistently appears specifically when hep is the visit's
main diagnosis (not just a carried-forward comorbidity). Cross-check a
couple of the sample CODE_F values against your HIS to confirm the code's
real name. Send back this output and I'll wire up detection using
whichever code(s) you confirm.
""")
