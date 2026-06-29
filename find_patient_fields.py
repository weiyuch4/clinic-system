import sys
import struct

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python find_patient_fields.py <PATDB_PATH> <ID_OR_CHART_NUMBER> [search_term ...]")
    sys.exit(1)

path = sys.argv[1]
target_id = sys.argv[2]
search_terms = sys.argv[3:] if len(sys.argv) > 3 else ["0424755212", "0981204200"]

with open(path, "rb") as f:
    header = f.read(32)
    num_records = struct.unpack("<I", header[4:8])[0]
    header_len = struct.unpack("<H", header[8:10])[0]
    record_len = struct.unpack("<H", header[10:12])[0]

    fields = []
    while True:
        desc = f.read(32)
        if desc[0:1] == b"\x0d":
            break
        name = desc[0:11].rstrip(b"\x00").decode("ascii", errors="replace")
        flen = desc[16]
        fields.append((name, flen))

    f.seek(header_len)
    found = False
    for i in range(num_records):
        raw = f.read(record_len)
        if not raw or len(raw) < record_len:
            break
        if raw[0:1] == b"*":  # deleted record marker
            continue

        offset = 1
        row = {}
        for name, flen in fields:
            val_bytes = raw[offset:offset + flen]
            try:
                val = val_bytes.decode("cp950", errors="replace").strip()
            except Exception:
                val = val_bytes.decode("latin-1", errors="replace").strip()
            row[name] = val
            offset += flen

        if row.get("ID", "") == target_id or row.get("IDNO1", "") == target_id:
            found = True
            print(f"Found record #{i} (ID={row.get('ID')!r}, IDNO1={row.get('IDNO1')!r}, NAME={row.get('NAME')!r}):\n")
            for name, flen in fields:
                marker = ""
                for term in search_terms:
                    if term and term in row[name]:
                        marker = f"   <-- CONTAINS {term!r}"
                print(f"  {name:12s} = {row[name]!r}{marker}")
            break

    if not found:
        print(f"No record found with ID or IDNO1 == {target_id!r}")
