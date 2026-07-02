import sys
import struct

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python lookup_uv_app.py <UV_APP.DBF_PATH> <PAT_IDNO>")
    sys.exit(1)

path = sys.argv[1]
pat_id = sys.argv[2].strip().upper()

with open(path, "rb") as f:
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

    print(f"Fields: {[n for n,_ in fields]}")
    print(f"Searching {num_records} records for PAT_IDNO == {pat_id!r}\n")

    f.seek(header_len)
    found = 0
    for i in range(num_records):
        raw = f.read(record_len)
        if not raw or raw[0:1] == b"*":
            continue

        offset = 1
        row = {}
        for name, flen in fields:
            val = raw[offset:offset+flen].decode("cp950", errors="replace").strip()
            row[name] = val
            offset += flen

        if row.get("PAT_IDNO", "") == pat_id:
            found += 1
            print(f"Record #{i}:")
            for k, v in row.items():
                if v:
                    print(f"  {k:15s} = {v!r}")
            print()

    if found == 0:
        print(f"No record found with PAT_IDNO == {pat_id!r}")
        # show a sample to confirm field format
        f.seek(header_len)
        print("\nSample PAT_IDNO values from first 5 records:")
        for i in range(min(5, num_records)):
            raw = f.read(record_len)
            if not raw or raw[0:1] == b"*":
                continue
            offset = 1
            for name, flen in fields:
                val = raw[offset:offset+flen].decode("cp950", errors="replace").strip()
                if name == "PAT_IDNO":
                    print(f"  record {i}: PAT_IDNO={val!r}")
                offset += flen
    else:
        print(f"Found {found} records.")
