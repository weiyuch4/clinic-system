"""
check_mspt_missing.py — Run on doctor's PC to find why patients from
the NHI MSPT list are absent from our tracking system.

Usage:  python check_mspt_missing.py  <path-to-NHI-xls>
        python check_mspt_missing.py  MSPT報表.xls

The script queries the cloud DB, compares against the XLS, then scans
local IC files to determine the root cause for each missing patient.
Output: check_mspt_missing_results.txt
"""

import sys, os, glob
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

script_dir = Path(__file__).parent
os.chdir(script_dir)
from dotenv import load_dotenv
load_dotenv(override=True)

# ── Step 1: Read NHI XLS ─────────────────────────────────────────────────────

xls_path = sys.argv[1] if len(sys.argv) > 1 else None
if not xls_path:
    # Look for any .xls / .xlsx in current directory
    candidates = list(script_dir.glob('MSPT*.xls')) + list(script_dir.glob('MSPT*.xlsx'))
    if candidates:
        xls_path = str(candidates[0])
        print(f"Found XLS: {xls_path}")
    else:
        sys.exit("Usage: python check_mspt_missing.py <path-to-NHI-xls>\n"
                 "Copy the NHI MSPT report XLS into this directory first.")

try:
    import xlrd
    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_index(0)
except ImportError:
    sys.exit("Run:  pip install xlrd")

nhi_all = []
for r in range(1, sh.nrows):
    row = [sh.cell_value(r, c) for c in range(sh.ncols)]
    nhi_all.append({
        'name':       str(row[1]).strip(),
        'birth_date': str(row[2]).strip().replace('/', '-'),
        'stage':      str(row[5]).strip(),
        'visit_date': str(row[4]).strip(),
    })
print(f"NHI XLS: {len(nhi_all)} patients")

# ── Step 2: Query cloud DB for synced MSPT candidates ────────────────────────

import psycopg2, psycopg2.extras
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
    "SELECT name, birth_date FROM synced_candidates "
    "WHERE clinic_id=1 AND category LIKE %s",
    ('%代謝症候群%',)
)
db_rows = cur.fetchall()
cur.close(); conn.close()
print(f"Cloud DB MSPT candidates: {len(db_rows)}")

db_keys = {(r['name'], str(r['birth_date']) if r['birth_date'] else '') for r in db_rows}
db_names = {}
for r in db_rows:
    db_names.setdefault(r['name'], []).append(str(r['birth_date']) if r['birth_date'] else '')

missing = []
for p in nhi_all:
    if (p['name'], p['birth_date']) not in db_keys:
        missing.append(p)

print(f"Missing from cloud DB: {len(missing)} patients")

# ── Step 3: Scan local IC files to diagnose each missing patient ──────────────

import lab_results  # provides _iter_rows DBF reader
import config

IC_DIR = config.IC_DATA_PATH  # E:\ic
MSPT_CODES = {'P7501C', 'P7502C', 'P75022C', 'P75023C', 'P7503C'}

def roc_to_date(s):
    s = (s or '').strip()
    if len(s) != 7 or not s.isdigit():
        return None
    try:
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except Exception:
        return None

# ── Scan all IC + P files into memory ────────────────────────────────────────
# Index: lower(name) → list of patient dicts

print(f"\nScanning IC files in: {IC_DIR}")
all_ic = sorted(p for p in glob.glob(os.path.join(IC_DIR, 'IC?????.DBF'))
                if os.path.basename(p)[2:-4].isdigit())
print(f"Found {len(all_ic)} IC files — scanning (may take 1-2 min)...")

# name_lower → {nat_id, birth_date, code_f, mspt_codes, ic_months, visit_count}
by_name: dict[str, dict] = {}

for idx, ic_path in enumerate(all_ic):
    month_stem = os.path.basename(ic_path)[2:-4]  # e.g. '11409'

    # Read P file first: build code_f → mspt codes found
    p_path = ic_path[:-4] + 'P.DBF'
    cf_mspt: dict[str, set] = {}
    if os.path.exists(p_path):
        try:
            for pr in lab_results._iter_rows(p_path):
                cf  = pr.get('CODE_F', '').strip()
                dn  = pr.get('DRUG_NO', '').strip()
                if cf and dn in MSPT_CODES:
                    cf_mspt.setdefault(cf, set()).add(dn)
        except Exception:
            pass

    # Read IC file
    try:
        for r in lab_results._iter_rows(ic_path):
            name = r.get('NAME', '').strip()
            if not name:
                continue
            nat_id = r.get('ID', '').strip()
            cf     = r.get('CODE_F', '').strip()
            birth  = roc_to_date(r.get('BIRTH', ''))

            key = name.lower()
            if key not in by_name:
                by_name[key] = {
                    'name':       name,
                    'nat_id':     nat_id,
                    'birth_date': birth.isoformat() if birth else '',
                    'code_f':     cf,
                    'mspt_codes': set(),
                    'ic_months':  set(),
                    'visit_count': 0,
                }
            rec = by_name[key]
            rec['ic_months'].add(month_stem)
            rec['visit_count'] += 1
            if cf in cf_mspt:
                rec['mspt_codes'].update(cf_mspt[cf])
            # Keep most recent nat_id / birth / code_f
            if nat_id:
                rec['nat_id'] = nat_id
            if birth:
                rec['birth_date'] = birth.isoformat()
            if cf:
                rec['code_f'] = cf
    except Exception as e:
        print(f"  Warning: could not read {os.path.basename(ic_path)}: {e}")

    if (idx + 1) % 20 == 0:
        print(f"  ... {idx+1}/{len(all_ic)} files scanned, {len(by_name)} unique names so far")

print(f"Done. Indexed {len(by_name)} unique patient names.\n")

# ── Cross-reference missing patients ─────────────────────────────────────────

results = {
    'found_with_mspt':     [],  # in IC with MSPT codes — should sync but didn't
    'found_no_mspt':       [],  # in IC but P file has no P750xC
    'found_birth_mismatch': [], # name found but birth date differs
    'not_in_ic':           [],  # name never appears in IC files
    'partial_name_match':  [],  # typo or alternate character
}

for p in missing:
    name     = p['name']
    nhi_bd   = p['birth_date']
    key      = name.lower()

    if key in by_name:
        rec      = by_name[key]
        db_bd    = rec['birth_date']
        matches_birth = (db_bd == nhi_bd)

        entry = {
            'nhi_name':    name,
            'nhi_birth':   nhi_bd,
            'nhi_stage':   p['stage'],
            'nhi_visit':   p['visit_date'],
            'nat_id':      rec['nat_id'],
            'db_birth':    db_bd,
            'code_f':      rec['code_f'],
            'mspt_codes':  sorted(rec['mspt_codes']),
            'ic_months':   sorted(rec['ic_months']),
            'visit_count': rec['visit_count'],
        }

        if not matches_birth:
            results['found_birth_mismatch'].append(entry)
        elif rec['mspt_codes']:
            results['found_with_mspt'].append(entry)
        else:
            results['found_no_mspt'].append(entry)
    else:
        # Try partial / fuzzy: any IC name shares ≥2 chars positionally
        candidates = []
        for ic_key, ic_rec in by_name.items():
            ic_name = ic_rec['name']
            # Same character count, at least half chars match
            overlap = sum(1 for a, b in zip(name, ic_name) if a == b)
            if len(name) >= 2 and overlap >= len(name) - 1 and abs(len(name) - len(ic_name)) <= 1:
                candidates.append(ic_rec['name'])
        if candidates:
            results['partial_name_match'].append({
                'nhi_name':  name,
                'nhi_birth': nhi_bd,
                'nhi_stage': p['stage'],
                'nhi_visit': p['visit_date'],
                'candidates': candidates[:5],
            })
        else:
            results['not_in_ic'].append({
                'nhi_name':  name,
                'nhi_birth': nhi_bd,
                'nhi_stage': p['stage'],
                'nhi_visit': p['visit_date'],
            })

# ── Write results ─────────────────────────────────────────────────────────────

out_path = script_dir / 'check_mspt_missing_results.txt'
lines = []

def section(title, items, fmt):
    lines.append(f"\n{'='*60}")
    lines.append(f"{title}  ({len(items)}件)")
    lines.append('='*60)
    for item in items:
        lines.append(fmt(item))

section(
    "【A】在IC檔有MSPT申報代碼，但未同步到雲端",
    results['found_with_mspt'],
    lambda x: (
        f"  {x['nhi_name']} 生日:{x['nhi_birth']} ID:{x['nat_id']} "
        f"代碼:{x['mspt_codes']} 月份:{x['ic_months'][-3:]} 次:{x['visit_count']}"
    )
)

section(
    "【B】在IC檔有到診紀錄，但P檔沒有P750xC申報代碼",
    results['found_no_mspt'],
    lambda x: (
        f"  {x['nhi_name']} 生日:{x['nhi_birth']} ID:{x['nat_id']} "
        f"CODE_F:{x['code_f']} 月份:{x['ic_months'][-3:]} 次:{x['visit_count']}"
        f"\n    NHI階段:{x['nhi_stage']} 就醫:{x['nhi_visit']}"
    )
)

section(
    "【C】名字找到但生日不符（可能是同名不同人，或資料有誤）",
    results['found_birth_mismatch'],
    lambda x: (
        f"  {x['nhi_name']}  NHI生日:{x['nhi_birth']}  IC生日:{x['db_birth']} "
        f"ID:{x['nat_id']} CODE_F:{x['code_f']}"
    )
)

section(
    "【D】名字相近（可能字體不同），請人工核對",
    results['partial_name_match'],
    lambda x: (
        f"  NHI:{x['nhi_name']} 生日:{x['nhi_birth']} → IC可能是: {x['candidates']}"
    )
)

section(
    "【E】完全不在IC檔（從未來診，或國籍/分院問題）",
    results['not_in_ic'],
    lambda x: (
        f"  {x['nhi_name']} 生日:{x['nhi_birth']} 就醫:{x['nhi_visit']} 階段:{x['nhi_stage']}"
    )
)

lines.append(f"\n{'='*60}")
lines.append("摘要")
lines.append('='*60)
lines.append(f"  A 在IC有MSPT代碼但未同步  : {len(results['found_with_mspt'])} 人")
lines.append(f"  B 在IC但沒有P750xC代碼    : {len(results['found_no_mspt'])} 人")
lines.append(f"  C 名字符合但生日不符       : {len(results['found_birth_mismatch'])} 人")
lines.append(f"  D 名字相近（字體差異）     : {len(results['partial_name_match'])} 人")
lines.append(f"  E 完全不在IC檔            : {len(results['not_in_ic'])} 人")
lines.append(f"  合計                      : {len(missing)} 人")

output = '\n'.join(lines)
print(output)

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(output)

print(f"\n結果已存至: {out_path}")
