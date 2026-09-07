"""
Run from the project folder:
    venv\Scripts\python debug_mspt_patient.py B122516910
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
from datetime import date, timedelta

if len(sys.argv) < 2:
    sys.exit("Usage: venv\\Scripts\\python debug_mspt_patient.py <nat_id>")
TARGET = sys.argv[1]

# Use the same config as the main app
import database as db
from config import IC_DATA_PATH

since = date.today() - timedelta(days=2 * 365)

print(f"Searching IC files in: {IC_DATA_PATH}")
print(f"Target nat_id: {TARGET}\n")

for ic_path in db._ic_files_since(since):
    month_cf_to_id = {}
    month_cf_dates = {}
    try:
        for r in db._parse_dbf_cached(ic_path):
            v_date = db._roc_to_date(r.get('DATE', ''))
            cf = r.get('CODE_F', '').strip()
            nat_id = r.get('ID', '').strip()
            if not cf or not nat_id:
                continue
            month_cf_to_id[cf] = nat_id
            month_cf_dates[cf] = v_date
    except Exception as e:
        print(f"  Error reading {ic_path}: {e}")
        continue

    p_path = ic_path[:-4] + 'P.DBF'
    if not os.path.exists(p_path):
        continue
    try:
        for r in db._parse_dbf_cached(p_path):
            cf = r.get('CODE_F', '').strip()
            nat_id = month_cf_to_id.get(cf)
            if nat_id != TARGET:
                continue
            drug = r.get('DRUG_NO', '').strip()
            stage = db._MSPT_CODE_MAP.get(drug)
            v_date = month_cf_dates.get(cf)
            if stage:
                print(f"MSPT hit in {os.path.basename(p_path)}")
                print(f"  CODE_F={cf}  DRUG_NO={drug}  stage={stage}  date={v_date}")
    except Exception as e:
        print(f"  Error reading {p_path}: {e}")

print("\nDone.")
