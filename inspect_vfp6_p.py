import sys
import struct
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

path = sys.argv[1] if len(sys.argv) > 1 else r"E:\S\VFP6_P.DBF"
search = sys.argv[2] if len(sys.argv) > 2 else "0981204200"

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

    print(f"Fields: {[(n,l) for n,l in fields]}")
    print(f"Records: {num_records}\n")

    f.seek(header_len)
    type_counter = Counter()
    hits = []

    for i in range(num_records):
        raw = f.read(record_len)
        if not raw or raw[0:1] == b"*":
            continue
        offset = 1
        row = {}
        for name, flen in fields:
            try:
                val = raw[offset:offset+flen].decode("cp950", errors="replace").strip()
            except Exception:
                val = raw[offset:offset+flen].decode("latin-1", errors="replace").strip()
            row[name] = val
            offset += flen

        type_counter[row.get("TYPE", "")] += 1

        # check if any field contains our search term
        if any(search in v for v in row.values()):
            hits.append(row)

    print(f"TYPE distribution (top 20): {type_counter.most_common(20)}\n")
    print(f"Records containing {search!r}: {len(hits)}")
    for r in hits[:10]:
        print(f"  {r}")
