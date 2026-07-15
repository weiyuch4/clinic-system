"""
Verify that VFP6_P.CODE is the 1-based sequential record number in PATDB.
Run on doctor's PC:
  python verify_vfp6p_join.py "E:\S\PATDB.DBF" "E:\S\VFP6_P.DBF" "0911111111"
"""
import sys
import struct

sys.stdout.reconfigure(encoding="utf-8")

patdb_path = sys.argv[1] if len(sys.argv) > 1 else r"E:\S\PATDB.DBF"
vfp6p_path = sys.argv[2] if len(sys.argv) > 2 else r"E:\S\VFP6_P.DBF"
search_tel  = sys.argv[3] if len(sys.argv) > 3 else "0911111111"

def read_dbf_fields(f):
    header = f.read(32)
    num_records = struct.unpack("<I", header[4:8])[0]
    header_len  = struct.unpack("<H", header[8:10])[0]
    record_len  = struct.unpack("<H", header[10:12])[0]
    fields = []
    while True:
        desc = f.read(32)
        if not desc or desc[0:1] == b"\x0d":
            break
        name = desc[0:11].rstrip(b"\x00").decode("ascii", errors="replace")
        flen = desc[16]
        fields.append((name, flen))
    return num_records, header_len, record_len, fields

def read_record(f, header_len, record_len, fields, idx):
    f.seek(header_len + idx * record_len)
    raw = f.read(record_len)
    if not raw or raw[0:1] == b"*":
        return None
    offset = 1
    row = {}
    for name, flen in fields:
        row[name] = raw[offset:offset+flen].decode("cp950", errors="replace").strip()
        offset += flen
    return row

# Step 1: find the CODE in VFP6_P for our test number
print(f"Step 1: searching VFP6_P for {search_tel!r} ...")
with open(vfp6p_path, "rb") as f:
    n, hl, rl, fields = read_dbf_fields(f)
    f.seek(hl)
    hit_code = None
    for i in range(n):
        raw = f.read(rl)
        if not raw or raw[0:1] == b"*":
            continue
        offset = 1
        row = {}
        for name, flen in fields:
            row[name] = raw[offset:offset+flen].decode("cp950", errors="replace").strip()
            offset += flen
        if row.get("DESC") == search_tel and row.get("TYPE") == "P1":
            hit_code = row["CODE"]
            print(f"  Found: TYPE={row['TYPE']} CODE={row['CODE']!r} DESC={row['DESC']!r}")
            break

if not hit_code:
    print("  Not found in VFP6_P.")
    sys.exit(1)

# Step 2: interpret CODE as 1-based record index, read that PATDB record
try:
    rec_idx = int(hit_code) - 1  # 1-based → 0-based
except ValueError:
    print(f"  CODE {hit_code!r} is not numeric, can't use as record index.")
    sys.exit(1)

print(f"\nStep 2: reading PATDB record #{int(hit_code)} (0-based index {rec_idx}) ...")
with open(patdb_path, "rb") as f:
    n2, hl2, rl2, fields2 = read_dbf_fields(f)
    row2 = read_record(f, hl2, rl2, fields2, rec_idx)

if row2:
    print(f"  NAME={row2.get('NAME')!r}  IDNO1={row2.get('IDNO1')!r}  TEL={row2.get('TEL')!r}")
    print(f"\nDoes this look like the patient you entered {search_tel!r} for? (Y/N)")
else:
    print(f"  Record #{int(hit_code)} is deleted or out of range.")
