"""
Show all P-file records for a specific patient across recent IC files,
so you can identify which 藥品名稱 / DRUG_NO values indicate CKD.

Usage (on doctor's PC):
  python inspect_patient_drugs.py <ID or name>   # e.g. A123456789 or 王小明
  python inspect_patient_drugs.py <ID> 24        # look back 24 months (default 18)

Paths default to E:\\ic — edit IC_DIR below if different.
"""
import os
import struct
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

IC_DIR     = r"E:\ic"
query      = sys.argv[1] if len(sys.argv) > 1 else ""
lookback_m = int(sys.argv[2]) if len(sys.argv) > 2 else 18

if not query:
    print("Usage: python inspect_patient_drugs.py <national-ID or name>")
    sys.exit(1)

# ── DBF reader — returns (field_names, rows) ──────────────────────────────────

def read_dbf(path: str):
    fields, rows = [], []
    try:
        with open(path, "rb") as f:
            hdr        = f.read(32)
            num_rec    = struct.unpack_from("<I", hdr, 4)[0]
            hdr_size   = struct.unpack_from("<H", hdr, 8)[0]
            rec_size   = struct.unpack_from("<H", hdr, 10)[0]
            f.seek(32)
            off = 1
            while True:
                fd = f.read(32)
                if not fd or fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b"\x00").decode("ascii", errors="replace").strip()
                flen = fd[16]
                fields.append((name, off, flen))
                off += flen
            f.seek(hdr_size)
            for _ in range(num_rec):
                raw = f.read(rec_size)
                if not raw or raw[0] == 0x2A:
                    continue
                row = {}
                for name, foff, flen in fields:
                    chunk = raw[foff:foff + flen]
                    try:    row[name] = chunk.decode("big5",    errors="replace").strip()
                    except: row[name] = chunk.decode("latin-1", errors="replace").strip()
                rows.append(row)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  [error reading {path}: {e}]")
    return [f[0] for f in fields], rows

# ── Build list of IC stems to scan ───────────────────────────────────────────

today    = date.today()
roc_now  = today.year - 1911
stems    = []
y, m     = roc_now, today.month
for _ in range(lookback_m):
    stems.append(f"{y:03d}{m:02d}")
    m -= 1
    if m == 0:
        m = 12; y -= 1

# ── Scan main IC files to collect CODE_F values for this patient ──────────────

print(f"Searching for patient: {query!r}  (last {lookback_m} months)\n")

# code_f → {date, ic_path}
patient_visits: dict[str, dict] = {}

for stem in stems:
    ic_main = os.path.join(IC_DIR, f"IC{stem}.DBF")
    if not os.path.exists(ic_main):
        continue
    _, rows = read_dbf(ic_main)
    for r in rows:
        nat_id = r.get("ID",   "").strip()
        name   = r.get("NAME", "").strip()
        if query != nat_id and query != name:
            continue
        cf = r.get("CODE_F", "").strip()
        if cf:
            patient_visits[cf] = {
                "date":    r.get("DATE", ""),
                "ic_path": ic_main,
                "name":    name,
                "nat_id":  nat_id,
            }

if not patient_visits:
    print(f"Patient not found in any IC file for the past {lookback_m} months.")
    print("Check the ID/name spelling or extend the lookback: python inspect_patient_drugs.py <ID> 36")
    sys.exit(0)

# Pick one visit to show patient identity
sample = next(iter(patient_visits.values()))
print(f"Found patient: {sample['name']}  {sample['nat_id']}")
print(f"Visits found : {len(patient_visits)}  (CODE_F values)\n")

# ── Read P files and show all fields ─────────────────────────────────────────

all_p_rows   = []          # accumulate for summary
p_field_names: list[str] = []

for cf, visit in sorted(patient_visits.items(), key=lambda x: x[1]["date"]):
    p_path = visit["ic_path"][:-4] + "P.DBF"
    if not os.path.exists(p_path):
        continue
    field_names, p_rows = read_dbf(p_path)
    if not p_field_names and field_names:
        p_field_names = field_names

    matching = [r for r in p_rows if r.get("CODE_F", "").strip() == cf]
    if not matching:
        continue

    roc_date = visit["date"]
    print(f"── {roc_date}  (CODE_F {cf}) ──────────────────────────")
    for r in matching:
        # Print every non-empty field
        parts = [f"{k}={v!r}" for k, v in r.items() if v and k != "CODE_F"]
        print("  " + "  |  ".join(parts) if parts else "  (empty row)")
    all_p_rows.extend(matching)

# ── Summary: all unique DRUG_NO values seen ──────────────────────────────────

print("\n" + "=" * 70)
print("  ALL P-FILE FIELDS IN THIS FILE:")
print("  " + "  ".join(p_field_names))

print("\n  ALL UNIQUE DRUG_NO VALUES FOR THIS PATIENT:")
seen = {}
for r in all_p_rows:
    dn = r.get("DRUG_NO", "").strip()
    if dn:
        seen[dn] = seen.get(dn, 0) + 1
for code, count in sorted(seen.items(), key=lambda x: -x[1]):
    print(f"  {code:15s}  {count}x")
