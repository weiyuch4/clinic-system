"""
Scan all DBF files in the clinic data directories and show their field
structures plus a few sample records.  Goal: find where 慢性病 status
and 慢簽 (連續處方箋) information is stored in the patient record files.

Usage:
    python -X utf8 scan_dbf_fields.py
"""

import os
import glob
import struct

# ── paths to scan ─────────────────────────────────────────────────────────────
# Edit these if data lives elsewhere on PC1.
SCAN_DIRS = [
    r'Z:\\',
    r'Z:\\IC',
    r'Z:\\Z',
]
MAX_DEPTH  = 2   # how many sub-levels below each SCAN_DIR to recurse
SAMPLE_N   = 3   # how many records to show per file


# ── DBF reader ────────────────────────────────────────────────────────────────

def _iter_dbf(path):
    try:
        with open(path, 'rb') as f:
            hdr = f.read(32)
            if len(hdr) < 32 or hdr[0] not in (
                    0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x83, 0xF5):
                return
            num_records = struct.unpack_from('<I', hdr, 4)[0]
            header_size = struct.unpack_from('<H', hdr, 8)[0]
            record_size = struct.unpack_from('<H', hdr, 10)[0]
            fields = []
            f.seek(32)
            while True:
                fd = f.read(32)
                if not fd or fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
                flen = fd[16]
                if name:
                    fields.append((name, flen))
            f.seek(header_size)
            yield from _read_records(f, fields, record_size, num_records)
    except Exception:
        return


def _read_records(f, fields, record_size, num_records):
    seen = 0
    while True:
        raw = f.read(record_size)
        if not raw or len(raw) < record_size:
            break
        if raw[0] == 0x2A:   # deleted record
            continue
        row = {}
        offset = 1
        for name, flen in fields:
            chunk = raw[offset:offset + flen]
            try:
                val = chunk.decode('cp950', errors='replace').strip()
            except Exception:
                val = chunk.decode('latin-1', errors='replace').strip()
            row[name] = val
            offset += flen
        yield row
        seen += 1


def _fields_of(path):
    try:
        with open(path, 'rb') as f:
            hdr = f.read(32)
            if len(hdr) < 32 or hdr[0] not in (
                    0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x83, 0xF5):
                return None, []
            num_records = struct.unpack_from('<I', hdr, 4)[0]
            fields = []
            f.seek(32)
            while True:
                fd = f.read(32)
                if not fd or fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
                flen = fd[16]
                if name:
                    fields.append((name, flen))
            return num_records, fields
    except Exception:
        return None, []


# ── file discovery ────────────────────────────────────────────────────────────

def _find_dbf_files(base_dirs, max_depth):
    seen = set()
    result = []
    for base in base_dirs:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            # limit recursion depth
            depth = root[len(base):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []
            for fn in files:
                if fn.upper().endswith('.DBF'):
                    p = os.path.join(root, fn)
                    norm = os.path.normcase(p)
                    if norm not in seen:
                        seen.add(norm)
                        result.append(p)
    return sorted(result)


def _is_ic_visit_file(path):
    """True for IC?????.DBF and IC?????P.DBF — already well understood."""
    stem = os.path.basename(path)[:-4].upper()
    if stem.startswith('IC') and len(stem) == 7 and stem[2:].isdigit():
        return True   # IC main file
    if stem.startswith('IC') and len(stem) == 8 and stem[2:-1].isdigit() and stem[-1] == 'P':
        return True   # IC prescription (P) file
    return False


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    files = _find_dbf_files(SCAN_DIRS, MAX_DEPTH)
    ic_files   = [f for f in files if _is_ic_visit_file(f)]
    other_files = [f for f in files if not _is_ic_visit_file(f)]

    print(f"Found {len(files)} DBF file(s) total: "
          f"{len(ic_files)} IC visit/prescription files (skipped), "
          f"{len(other_files)} other files.\n")

    for path in other_files:
        num_records, fields = _fields_of(path)
        if not fields:
            continue

        field_names = [f[0] for f in fields]
        print(f"\n{'='*70}")
        print(f"  {path}")
        print(f"  Records: {num_records if num_records is not None else '?'}")
        print(f"  Fields:  {', '.join(field_names)}")

        # Read up to SAMPLE_N non-empty records
        samples = []
        try:
            for row in _iter_dbf(path):
                filled = {k: v for k, v in row.items() if v}
                if filled:
                    samples.append(filled)
                if len(samples) >= SAMPLE_N:
                    break
        except Exception:
            pass

        if samples:
            print(f"  Sample records:")
            for i, s in enumerate(samples, 1):
                print(f"    [{i}] {s}")
        else:
            print(f"  (no non-empty records found)")

    print()


if __name__ == '__main__':
    main()
