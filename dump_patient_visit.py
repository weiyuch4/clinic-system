#!/usr/bin/env python3
"""
Dump every field (main IC record + all P-file line items + H-file companion
records) for one patient's visit. The P-file line items are numbered in
file order — pick a visit you know included the BC肝追蹤6M order, find its
position in your HIS order list (e.g. "the 7th item"), and the matching
DRUG_NO printed here tells us the real underlying code.

Run on PC1: python dump_patient_visit.py P220094718 1150107
(date in ROC YYYMMDD format, no slashes)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import _ic_main_files, _parse_dbf_cached, _roc_to_date, _h_file_path

if len(sys.argv) < 3:
    print("Usage: python dump_patient_visit.py <nat_id> <ROC_date YYYMMDD>")
    sys.exit(1)

NAT_ID = sys.argv[1].strip().upper()
ROC_DATE = sys.argv[2].strip().replace('/', '')
TARGET_DATE = _roc_to_date(ROC_DATE.zfill(7))
if not TARGET_DATE:
    print(f"Could not parse date {ROC_DATE!r} as ROC YYYMMDD")
    sys.exit(1)

print(f"Looking for nat_id={NAT_ID!r} on {TARGET_DATE} (ROC {ROC_DATE})\n")


def dump_record(label: str, r: dict):
    print(f"  [{label}]")
    for field, val in r.items():
        v = val.strip() if isinstance(val, str) else val
        if v in ('', None):
            continue
        print(f"    {field:12s} = {v!r}")
    print()


found_any = False
for path in _ic_main_files():
    try:
        records = _parse_dbf_cached(path)
    except Exception:
        continue

    matching_cfs = []
    for r in records:
        if r.get('ID', '').strip().upper() != NAT_ID:
            continue
        v_date = _roc_to_date(r.get('DATE', ''))
        if v_date != TARGET_DATE:
            continue
        found_any = True
        print("=" * 70)
        print(f"MAIN IC RECORD — file={os.path.basename(path)}")
        print("=" * 70)
        dump_record("IC main", r)
        cf = r.get('CODE_F', '').strip()
        if cf:
            matching_cfs.append(cf)

    if not matching_cfs:
        continue

    # P-file companion — all line items for these CODE_F values
    p_path = path[:-4] + 'P.DBF'
    if os.path.exists(p_path):
        try:
            p_records = [r for r in _parse_dbf_cached(p_path) if r.get('CODE_F', '').strip() in matching_cfs]
            if p_records:
                print("=" * 70)
                print(f"P-FILE LINE ITEMS — file={os.path.basename(p_path)} ({len(p_records)} records)")
                print("=" * 70)
                print("Quick summary, numbered in file order (should match your HIS order list —")
                print("tell me which # is the BC肝追蹤6M item):\n")
                for idx, r in enumerate(p_records, 1):
                    drug_no = r.get('DRUG_NO', '').strip()
                    qty = r.get('QTY', '').strip()
                    ps = r.get('PS', '').strip()
                    no = r.get('NO', '').strip()
                    print(f"  #{idx:<3d} DRUG_NO={drug_no:12s} QTY={qty:6s} PS={ps:4s} NO={no}")
                print()
                for idx, r in enumerate(p_records, 1):
                    dump_record(f"#{idx} P CODE_F={r.get('CODE_F','').strip()}", r)
        except Exception as e:
            print(f"  ERROR reading P file: {e}")

    # H-file companion — all records for these CODE_F values
    h_path = _h_file_path(path)
    if os.path.exists(h_path):
        try:
            h_records = [r for r in _parse_dbf_cached(h_path) if r.get('CODE_F', '').strip() in matching_cfs]
            if h_records:
                print("=" * 70)
                print(f"H-FILE RECORDS — file={os.path.basename(h_path)} ({len(h_records)} records)")
                print("=" * 70)
                for r in h_records:
                    dump_record(f"H CODE_F={r.get('CODE_F','').strip()}", r)
        except Exception as e:
            print(f"  ERROR reading H file: {e}")

if not found_any:
    print("*** NOT FOUND *** — no main IC record for this nat_id on this exact date.")
    print("Double-check the nat_id and date, or the visit may be in a file outside")
    print("the scanned set.")
