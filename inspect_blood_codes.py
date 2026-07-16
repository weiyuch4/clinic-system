"""
Show all patients who visited on a given day and every NHI procedure code
(DRUG_NO) they had in the P file, so you can identify which codes mean
"blood test ordered".

Usage (on doctor's PC):
  python inspect_blood_codes.py             # defaults to yesterday
  python inspect_blood_codes.py 2026-07-14  # specific date (Gregorian)

Paths default to E:\\ic  — edit IC_DIR below if different.
"""
import os
import struct
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")

IC_DIR = r"E:\ic"

# ── date handling ──────────────────────────────────────────────────────────────

def parse_arg_date(arg: str) -> date:
    y, m, d = arg.split("-")
    return date(int(y), int(m), int(d))

target: date = (
    parse_arg_date(sys.argv[1]) if len(sys.argv) > 1
    else date.today() - timedelta(days=1)
)

roc_year  = target.year - 1911
target_roc = f"{roc_year:03d}{target.month:02d}{target.day:02d}"   # e.g. "1150715"
ic_stem    = f"{roc_year:03d}{target.month:02d}"                    # e.g. "11507"

print(f"Target date : {target}  (ROC {roc_year}/{target.month:02d}/{target.day:02d})")
print(f"IC file stem: IC{ic_stem}.DBF + IC{ic_stem}P.DBF")
print()

# ── DBF reader ─────────────────────────────────────────────────────────────────

def read_dbf(path: str) -> list[dict]:
    rows = []
    try:
        with open(path, "rb") as f:
            hdr = f.read(32)
            num_records  = struct.unpack_from("<I", hdr, 4)[0]
            header_size  = struct.unpack_from("<H", hdr, 8)[0]
            record_size  = struct.unpack_from("<H", hdr, 10)[0]
            fields: list[tuple[str, int, int]] = []
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
            f.seek(header_size)
            for _ in range(num_records):
                raw = f.read(record_size)
                if not raw or raw[0] == 0x2A:
                    continue
                row: dict[str, str] = {}
                for name, foff, flen in fields:
                    chunk = raw[foff:foff + flen]
                    try:
                        row[name] = chunk.decode("big5", errors="replace").strip()
                    except Exception:
                        row[name] = chunk.decode("latin-1", errors="replace").strip()
                rows.append(row)
    except FileNotFoundError:
        print(f"  [file not found: {path}]")
    except Exception as e:
        print(f"  [error reading {path}: {e}]")
    return rows

# ── read main IC file — find visits on target date ────────────────────────────

ic_main = os.path.join(IC_DIR, f"IC{ic_stem}.DBF")
ic_p    = os.path.join(IC_DIR, f"IC{ic_stem}P.DBF")

print(f"Reading {ic_main} ...")
main_rows = read_dbf(ic_main)

# visits on exactly the target date
visits = [r for r in main_rows if r.get("DATE", "").strip() == target_roc]

if not visits:
    print(f"No visits found for {target} (ROC {target_roc}).")
    print("Check IC_DIR path and that the clinic was open that day.")
    sys.exit(0)

print(f"Found {len(visits)} visit record(s) on {target}.\n")

# map CODE_F → patient info (a patient may have multiple visit rows)
code_f_to_info: dict[str, dict] = {}
for r in visits:
    cf = r.get("CODE_F", "").strip()
    if cf:
        code_f_to_info[cf] = {
            "name": r.get("NAME", "").strip(),
            "id":   r.get("ID",   "").strip(),
        }

# ── read P file — procedure codes per visit ───────────────────────────────────

print(f"Reading {ic_p} ...")
p_rows = read_dbf(ic_p)

# only keep P-file rows whose CODE_F matches a visit on our target date
code_f_to_drugs: dict[str, list[str]] = defaultdict(list)
for r in p_rows:
    cf = r.get("CODE_F", "").strip()
    if cf in code_f_to_info:
        drug = r.get("DRUG_NO", "").strip()
        if drug:
            code_f_to_drugs[cf].append(drug)

# ── per-patient output ─────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print(f"  PATIENTS & PROCEDURE CODES  ({target})")
print("=" * 70)

all_codes: list[str] = []
for cf, info in sorted(code_f_to_info.items(), key=lambda x: x[1]["name"]):
    drugs = code_f_to_drugs.get(cf, [])
    all_codes.extend(drugs)
    drugs_str = "  ".join(drugs) if drugs else "(no P-file codes)"
    print(f"  {info['name']:8s}  {info['id']:12s}  {drugs_str}")

# ── frequency summary ─────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("  CODE FREQUENCY (all visits that day)")
print("=" * 70)
for code, count in Counter(all_codes).most_common():
    print(f"  {code:12s}  {count:3d}x")

print(f"\nTotal visit rows : {len(visits)}")
print(f"Total P-file codes matched: {len(all_codes)}")
