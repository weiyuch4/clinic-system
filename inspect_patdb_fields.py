import sys
import struct

if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    import config
    path = config.PATDB_PATH

print(f"Reading: {path}")
with open(path, "rb") as f:
    header = f.read(32)
    num_records = struct.unpack("<I", header[4:8])[0]
    fields = []
    while True:
        desc = f.read(32)
        if desc[0:1] == b"\x0d":
            break
        name = desc[0:11].rstrip(b"\x00").decode("ascii", errors="replace")
        flen = desc[16]
        fields.append((name, flen))
    print(f"{num_records} records, {len(fields)} fields:")
    for name, flen in fields:
        print(f"  {name:12s} len={flen}")
