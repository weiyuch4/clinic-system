"""
Diagnose why phone numbers aren't showing.
Run on doctor's PC:
  python diagnose_phone.py "E:\S\PATDB.DBF" "E:\ic"
"""
import sys, os, struct, glob

sys.stdout.reconfigure(encoding="utf-8")

patdb_path = sys.argv[1] if len(sys.argv) > 1 else r"E:\S\PATDB.DBF"
ic_dir     = sys.argv[2] if len(sys.argv) > 2 else r"E:\ic"

def read_dbf_sample(path, max_rows=5):
    with open(path, "rb") as f:
        hdr = f.read(32)
        num_records = struct.unpack_from("<I", hdr, 4)[0]
        header_size = struct.unpack_from("<H", hdr, 8)[0]
        record_size = struct.unpack_from("<H", hdr, 10)[0]
        fields = []
        f.seek(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D: break
            name = fd[:11].rstrip(b"\x00").decode("ascii", errors="replace").strip()
            fields.append((name, fd[16]))
        f.seek(header_size)
        rows = []
        for _ in range(num_records):
            raw = f.read(record_size)
            if not raw or raw[0] == 0x2A: continue
            row = {}
            offset = 1
            for name, flen in fields:
                val = raw[offset:offset+flen]
                try: row[name] = val.decode("big5").strip()
                except: row[name] = val.decode("latin-1", errors="replace").strip()
                offset += flen
            rows.append(row)
            if len(rows) >= max_rows:
                break
    return rows, [n for n,_ in fields]

# --- PATDB sample ---
print("=== PATDB sample (first 5 non-deleted records) ===")
patdb_rows, patdb_fields = read_dbf_sample(patdb_path)
print(f"Fields: {patdb_fields}")
for r in patdb_rows:
    print(f"  NAME={r.get('NAME')!r:10s}  ID={r.get('ID')!r:12s}  IDNO1={r.get('IDNO1')!r:12s}  TEL={r.get('TEL')!r}")

# --- IC file sample ---
ic_files = sorted(glob.glob(os.path.join(ic_dir, "IC?????.DBF")))
if not ic_files:
    print(f"\nNo IC?????.DBF files found in {ic_dir!r}")
    sys.exit(1)

ic_path = ic_files[-1]  # most recent
print(f"\n=== IC file sample: {os.path.basename(ic_path)} (first 5 records) ===")
ic_rows, ic_fields = read_dbf_sample(ic_path)
print(f"Fields: {ic_fields}")
for r in ic_rows:
    print(f"  NAME={r.get('NAME')!r:10s}  ID={r.get('ID')!r:12s}")

# --- Cross-check: take first 200 IC IDs, see how many match PATDB IDs ---
print("\n=== Cross-check: do IC file IDs match PATDB IDs? ===")
patdb_id_set = set()
with open(patdb_path, "rb") as f:
    hdr = f.read(32)
    num_records = struct.unpack_from("<I", hdr, 4)[0]
    header_size = struct.unpack_from("<H", hdr, 8)[0]
    record_size = struct.unpack_from("<H", hdr, 10)[0]
    fields = []
    f.seek(32)
    while True:
        fd = f.read(32)
        if not fd or fd[0] == 0x0D: break
        fields.append((fd[:11].rstrip(b"\x00").decode("ascii", errors="replace").strip(), fd[16]))
    id_offset = 1
    for name, flen in fields:
        if name == "ID": break
        id_offset += flen
    id_len = next(flen for name, flen in fields if name == "ID")
    tel_offset = 1
    for name, flen in fields:
        if name == "TEL": break
        tel_offset += flen
    tel_len = next(flen for name, flen in fields if name == "TEL")

    f.seek(header_size)
    tel_not_empty = 0
    for _ in range(num_records):
        raw = f.read(record_size)
        if not raw or raw[0] == 0x2A: continue
        try: pid = raw[id_offset:id_offset+id_len].decode("big5").strip()
        except: pid = raw[id_offset:id_offset+id_len].decode("latin-1", errors="replace").strip()
        try: tel = raw[tel_offset:tel_offset+tel_len].decode("big5").strip()
        except: tel = raw[tel_offset:tel_offset+tel_len].decode("latin-1", errors="replace").strip()
        if pid: patdb_id_set.add(pid)
        if tel: tel_not_empty += 1

print(f"PATDB: {len(patdb_id_set)} unique non-empty ID values, {tel_not_empty} records with TEL")

ic_ids = set()
for r in read_dbf_sample(ic_path, max_rows=200)[0]:
    pid = r.get("ID", "").strip()
    if pid: ic_ids.add(pid)

matched = ic_ids & patdb_id_set
print(f"IC sample IDs: {len(ic_ids)}, matched in PATDB: {len(matched)}")
if matched:
    print(f"  Sample matches: {list(matched)[:5]}")
else:
    print("  NO MATCHES — the ID fields don't align between IC files and PATDB!")
    print(f"  Sample IC IDs:    {list(ic_ids)[:5]}")
    print(f"  Sample PATDB IDs: {list(patdb_id_set)[:5]}")
