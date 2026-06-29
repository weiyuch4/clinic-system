import sys
import struct
import os
import glob
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python find_field_anywhere.py <DIR_OR_GLOB> <SEARCH_TERM> [ANCHOR_ID]")
    print("  Single full pass: for every .DBF file, decodes every record's character")
    print("  fields sized 8-14 chars (phone-like) and checks each one against the")
    print("  search term. Every record in every file is checked — no sampling.")
    print("  ANCHOR_ID is informational only — every match is shown regardless, with a")
    print("  note on whether ANCHOR_ID also appears in that same record. Different 燿聖")
    print("  tables may key a patient by different identifiers (national ID, IDNO, an")
    print("  internal sequence code, etc.), so requiring the anchor to match would risk")
    print("  silently hiding the real answer if this table uses a different key.")
    sys.exit(1)

search_arg = sys.argv[1]
term = sys.argv[2]
anchor = sys.argv[3] if len(sys.argv) > 3 else None

SEP_CHARS = str.maketrans("", "", "-. ()\t")


def strip_seps(s):
    return s.translate(SEP_CHARS)


if os.path.isdir(search_arg):
    dbf_files = sorted(glob.glob(os.path.join(search_arg, "*.DBF")) + glob.glob(os.path.join(search_arg, "*.dbf")))
else:
    dbf_files = sorted(set(glob.glob(search_arg)))

print(f"Scanning {len(dbf_files)} DBF file(s), every record, for {term!r}"
      + (f" (anchor {anchor!r} is informational only)" if anchor else "") + "...\n")

start_time = time.time()
found_any = False
total_records_scanned = 0

for fi, path in enumerate(dbf_files):
    fname = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            header = f.read(32)
            if len(header) < 32:
                continue
            num_records = struct.unpack("<I", header[4:8])[0]
            header_len = struct.unpack("<H", header[8:10])[0]
            record_len = struct.unpack("<H", header[10:12])[0]
            if num_records == 0 or record_len == 0:
                continue

            fields = []
            while True:
                desc = f.read(32)
                if not desc or desc[0:1] == b"\x0d":
                    break
                name = desc[0:11].rstrip(b"\x00").decode("ascii", errors="replace")
                ftype = chr(desc[11]) if desc[11] else "?"
                flen = desc[16]
                fields.append((name, ftype, flen))

            phoneish_fields = [n for n, t, l in fields if t == "C" and 8 <= l <= 14]
            if not phoneish_fields:
                continue

            print(f"[{fi + 1}/{len(dbf_files)}] scanning {fname} ({num_records} records, "
                  f"fields {phoneish_fields})...", flush=True)

            f.seek(header_len)
            for i in range(num_records):
                raw = f.read(record_len)
                if not raw or len(raw) < record_len:
                    break
                total_records_scanned += 1
                if raw[0:1] == b"*":
                    continue

                offset = 1
                phone_vals = {}
                offsets = {}
                for name, ftype, flen in fields:
                    if name in phoneish_fields:
                        try:
                            val = raw[offset:offset + flen].decode("cp950", errors="replace").strip()
                        except Exception:
                            val = raw[offset:offset + flen].decode("latin-1", errors="replace").strip()
                        phone_vals[name] = val
                        offsets[name] = offset
                    offset += flen

                matching_fields = [
                    n for n, v in phone_vals.items()
                    if term in v or term in strip_seps(v)
                ]
                if not matching_fields:
                    continue

                # full row decode only on an actual match, to avoid wasting time on misses
                offset = 1
                row = {}
                for name, ftype, flen in fields:
                    val_bytes = raw[offset:offset + flen]
                    try:
                        val = val_bytes.decode("cp950", errors="replace").strip()
                    except Exception:
                        val = val_bytes.decode("latin-1", errors="replace").strip()
                    row[name] = val
                    offset += flen

                anchor_present = anchor and any(anchor in v for v in row.values())
                found_any = True
                anchor_note = "" if not anchor else f"  [anchor {anchor!r} {'FOUND' if anchor_present else 'not found'} in this record]"
                print(f"  >>> [{fname}] record #{i}: match in field(s) {matching_fields}{anchor_note}")
                for name, _, _ in fields:
                    if row[name]:
                        print(f"        {name:12s} = {row[name]!r}")
                print()
    except Exception as e:
        print(f"[{fname}] ERROR: {e}")

elapsed = time.time() - start_time
print(f"\nDone. Scanned {total_records_scanned} records in {elapsed:.1f}s.")
if not found_any:
    print("No matches found anywhere.")
