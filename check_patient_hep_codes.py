#!/usr/bin/env python3
"""
For one patient, list every hep-ICD-coded visit (same check
_query_hep_followups uses) across their full history, and show whether
candidate order codes (P4202C, 19009C, or others passed on the command
line) appeared on each one. A real recurring hep panel should show up
consistently across most/all of these visits, roughly periodically —
not sporadically.

Run on PC1: python check_patient_hep_codes.py B120484406 P4202C 19009C
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import _ic_main_files, _parse_dbf_cached, _hep_type, _roc_to_date

if len(sys.argv) < 2:
    print("Usage: python check_patient_hep_codes.py <nat_id> [candidate_code ...]")
    sys.exit(1)

NAT_ID = sys.argv[1].strip().upper()
CANDIDATES = [c.strip().upper() for c in sys.argv[2:]] or ['P4202C', '19009C']

visits = []  # (date, file, cf, icd_fields, is_primary)

for path in _ic_main_files():
    try:
        records = _parse_dbf_cached(path)
    except Exception:
        continue

    visit_cfs = []
    for r in records:
        if r.get('ID', '').strip().upper() != NAT_ID:
            continue
        if r.get('H_TYPE', '') not in ('01西醫', 'AE連續'):
            continue
        hep = _hep_type(r)
        if not hep:
            continue
        v_date = _roc_to_date(r.get('DATE', ''))
        cf = r.get('CODE_F', '').strip()
        is_primary = _hep_type({'ICD': r.get('ICD', '')}) is not None
        icds = [r.get(f, '').strip() for f in ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5') if r.get(f, '').strip()]
        visits.append({'date': v_date, 'file': os.path.basename(path), 'cf': cf,
                        'icds': icds, 'is_primary': is_primary, 'codes': set()})
        if cf:
            visit_cfs.append(cf)

    if not visit_cfs:
        continue

    p_path = path[:-4] + 'P.DBF'
    if not os.path.exists(p_path):
        continue
    try:
        codes_by_cf = {}
        for r in _parse_dbf_cached(p_path):
            cf = r.get('CODE_F', '').strip()
            drug_no = r.get('DRUG_NO', '').strip()
            if cf and drug_no:
                codes_by_cf.setdefault(cf, set()).add(drug_no)
        for v in visits:
            if v['file'] == os.path.basename(path) and v['cf'] in codes_by_cf:
                v['codes'] = codes_by_cf[v['cf']]
    except Exception as e:
        print(f"  ERROR (P) {os.path.basename(p_path)}: {e}")

visits.sort(key=lambda v: v['date'] or '')

print(f"Hep-ICD-coded visit history for nat_id={NAT_ID!r} ({len(visits)} visits):\n")
print(f"{'date':12s} {'primary':8s} {'icds':30s} " + " ".join(f"{c:8s}" for c in CANDIDATES))
for v in visits:
    icds_str = ','.join(v['icds'])
    flags = " ".join(f"{'YES':8s}" if c in v['codes'] else f"{'-':8s}" for c in CANDIDATES)
    print(f"{str(v['date']):12s} {str(v['is_primary']):8s} {icds_str:30s} {flags}")

print()
for c in CANDIDATES:
    hits = sum(1 for v in visits if c in v['codes'])
    print(f"  {c}: present on {hits}/{len(visits)} hep-coded visits ({100*hits/len(visits):.0f}%)" if visits else f"  {c}: no visits found")
