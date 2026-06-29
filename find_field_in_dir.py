import sys
import struct
import os
import glob

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python find_field_in_dir.py <DIR_OR_GLOB_PATTERN> <SEARCH_TERM> [ANCHOR_ID]")
    print('  DIR_OR_GLOB_PATTERN: a directory (scans all *.DBF in it) OR a glob')
    print('  pattern like "Z:\\S\\PAT*.DBF" to target a smaller set of files —')
    print('  use a narrow pattern first, this directory may have hundreds of files.')
    print('  ANCHOR_ID (optional): if given, only reports a hit when the SAME')
    print('  record also contains this value somewhere in one of its fields —')
    print('  use the patient ID/chart number to confirm it is the right patient.')
    sys.exit(1)

search_arg = sys.argv[1]
term = sys.argv[2]
anchor = sys.argv[3] if len(sys.argv) > 3 else None

if os.path.isdir(search_arg):
    dbf_files = sorted(glob.glob(os.path.join(search_arg, "*.DBF")) + glob.glob(os.path.join(search_arg, "*.dbf")))
else:
    dbf_files = sorted(set(glob.glob(search_arg)))
if not dbf_files:
    print(f"No .DBF files found matching {search_arg}")
    sys.exit(0)

print(f"Scanning {len(dbf_files)} DBF file(s) matching {search_arg} for {term!r}"
      + (f" (anchored to records also containing {anchor!r})" if anchor else "") + "...\n")

for path in dbf_files:
    fname = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            header = f.read(32)
            num_records = struct.unpack("<I", header[4:8])[0]
            header_len = struct.unpack("<H", header[8:10])[0]
            record_len = struct.unpack("<H", header[10:12])[0]

            fields = []
            while True:
                desc = f.read(32)
                if not desc or desc[0:1] == b"\x0d":
                    break
                name = desc[0:11].rstrip(b"\x00").decode("ascii", errors="replace")
                flen = desc[16]
                fields.append((name, flen))

            if not fields or record_len == 0:
                print(f"[{fname}] skipped (no fields / unreadable header)")
                continue

            f.seek(header_len)
            hits = 0
            for i in range(num_records):
                raw = f.read(record_len)
                if not raw or len(raw) < record_len:
                    break
                if raw[0:1] == b"*":
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

                matching_fields = [n for n, v in row.items() if term in v]
                if not matching_fields:
                    continue
                if anchor and not any(anchor in v for v in row.values()):
                    continue

                hits += 1
                print(f"[{fname}] record #{i}: match in field(s) {matching_fields}")
                for name, _ in fields:
                    if row[name]:
                        print(f"    {name:12s} = {row[name]!r}")
                print()

            if hits == 0:
                print(f"[{fname}] {num_records} records, {len(fields)} fields — no match")
    except Exception as e:
        print(f"[{fname}] ERROR: {e}")
