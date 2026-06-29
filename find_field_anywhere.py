import sys
import struct
import os
import glob
import re

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python find_field_anywhere.py <DIR_OR_GLOB> <SEARCH_TERM> [ANCHOR_ID]")
    print("  Two-stage scan: Stage 1 reads field headers + samples a few records from")
    print("  every .DBF file (fast) to shortlist specific fields whose SAMPLE VALUES")
    print("  actually look like phone numbers (not just fields of a plausible length —")
    print("  that alone matched 1610/1830 files here, far too broad to brute-force).")
    print("  Stage 2 then does the full record scan only on those shortlisted fields.")
    sys.exit(1)

search_arg = sys.argv[1]
term = sys.argv[2]
anchor = sys.argv[3] if len(sys.argv) > 3 else None

PHONE_RE = re.compile(r"^09\d{8}$")  # exact Taiwan mobile format: 09 + 8 digits = 10 chars, nothing else
SAMPLE_SIZE = 25
SEP_CHARS = str.maketrans("", "", "-. ()\t")


def strip_seps(s):
    return s.translate(SEP_CHARS)

if os.path.isdir(search_arg):
    dbf_files = sorted(glob.glob(os.path.join(search_arg, "*.DBF")) + glob.glob(os.path.join(search_arg, "*.dbf")))
else:
    dbf_files = sorted(set(glob.glob(search_arg)))

print(f"Stage 1: sampling up to {SAMPLE_SIZE} records from {len(dbf_files)} file(s)...")

candidates = []  # (path, fields, num_records, header_len, record_len, phone_field_names)
for path in dbf_files:
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

            f.seek(header_len)
            confirmed = set()
            sampled = 0
            while sampled < SAMPLE_SIZE:
                raw = f.read(record_len)
                if not raw or len(raw) < record_len:
                    break
                sampled += 1
                if raw[0:1] == b"*":
                    continue
                offset = 1
                for name, ftype, flen in fields:
                    val_bytes = raw[offset:offset + flen]
                    if name in phoneish_fields and name not in confirmed:
                        try:
                            val = val_bytes.decode("cp950", errors="replace").strip()
                        except Exception:
                            val = val_bytes.decode("latin-1", errors="replace").strip()
                        if PHONE_RE.match(strip_seps(val)):
                            confirmed.add(name)
                    offset += flen

            if confirmed:
                candidates.append((path, fields, num_records, header_len, record_len, sorted(confirmed)))
    except Exception:
        continue

total_candidate_records = sum(c[2] for c in candidates)
print(f"Stage 1 done: {len(candidates)} file(s) have a field whose sampled values look like "
      f"real phone numbers, {total_candidate_records} records total to scan.\n")
for path, fields, num_records, header_len, record_len, phone_fields in candidates:
    print(f"  {os.path.basename(path):16s} fields={phone_fields} ({num_records} records)")
print()

if not candidates:
    print("No candidate fields found — the number may live in a non-character field, "
          "a memo (.FPT) field, or a file not matched by this glob pattern.")
    sys.exit(0)

print(f"Stage 2: scanning those fields for {term!r}"
      + (f" (anchored to records also containing {anchor!r})" if anchor else "") + "...\n")

found_any = False
for path, fields, num_records, header_len, record_len, phone_fields in candidates:
    fname = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            f.seek(header_len)
            for i in range(num_records):
                raw = f.read(record_len)
                if not raw or len(raw) < record_len:
                    break
                if raw[0:1] == b"*":
                    continue

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

                matching_fields = [
                    n for n in phone_fields
                    if term in row.get(n, "") or term in strip_seps(row.get(n, ""))
                ]
                if not matching_fields:
                    continue
                if anchor and not any(anchor in v for v in row.values()):
                    continue

                found_any = True
                print(f"[{fname}] record #{i}: match in field(s) {matching_fields}")
                for name, _, _ in fields:
                    if row[name]:
                        print(f"    {name:12s} = {row[name]!r}")
                print()
    except Exception as e:
        print(f"[{fname}] ERROR: {e}")

if not found_any:
    print("No matches found across any candidate field.")
