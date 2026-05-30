"""
Diagnostic: locate blood test result files (檢驗平台 / 各項檢驗) on this PC.

Searches all fixed drives for DBF files (and MDB/accdb) whose path or
field names suggest lab data.  Prints each candidate with its field list so
you can identify the right files.

Usage:
    python find_lab_data.py [search_root]

    search_root defaults to every fixed drive (C:\, D:\, ...).
    You can narrow it, e.g.:  python find_lab_data.py D:\YaoSheng

Output is saved to  find_lab_data_output.txt  in the same folder as this
script so you can share it easily.
"""

import os
import sys
import struct
import string
import ctypes
import time

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "find_lab_data_output.txt")

# ── folder / file name keywords that suggest lab data ────────────────────────
FOLDER_KEYWORDS = [
    'bio', 'lab', 'inspect', 'urin', 'cbc', 'dscv',
    '檢驗', '驗血', '化驗', '生化', '血液', '報告',
    'result', 'report', 'test',
]

# DBF field name keywords that suggest a lab result table
FIELD_KEYWORDS = [
    'result', 'value', 'val', 'rslt',
    'item', 'code', 'test', 'exam',
    '項目', '結果', '數值', '代碼',
    'alt', 'gpt', 'creat', 'gluc', 'hba', 'hdl', 'ldl',
    'wbc', 'rbc', 'hgb', 'plt',
]

# Paths to always skip (slow, irrelevant)
SKIP_DIRS = {
    'windows', 'system32', 'syswow64', 'winsxs',
    '$recycle.bin', 'programdata\\microsoft',
    'appdata\\local\\microsoft', 'appdata\\roaming\\microsoft',
}


def _fixed_drives() -> list[str]:
    """Return all fixed (non-removable) drive roots on Windows."""
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            root = f"{letter}:\\"
            try:
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                if dtype == 3:  # DRIVE_FIXED
                    drives.append(root)
            except Exception:
                pass
    return drives


def _should_skip(dirpath: str) -> bool:
    low = dirpath.lower()
    for s in SKIP_DIRS:
        if s in low:
            return True
    return False


def _folder_is_candidate(dirpath: str) -> bool:
    low = dirpath.lower()
    for kw in FOLDER_KEYWORDS:
        if kw in low:
            return True
    return False


def _read_dbf_fields(path: str) -> list[str] | None:
    """Return list of field names from a DBF header, or None on error."""
    try:
        with open(path, 'rb') as f:
            hdr = f.read(32)
            if len(hdr) < 32:
                return None
            # Basic DBF signature check
            if hdr[0] not in (0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x83, 0xF5):
                return None
            fields = []
            f.seek(32)
            for _ in range(200):  # max 200 fields
                fd = f.read(32)
                if not fd or fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
                if name:
                    fields.append(name)
            return fields if fields else None
    except Exception:
        return None


def _fields_are_candidate(fields: list[str]) -> bool:
    low = [f.lower() for f in fields]
    for kw in FIELD_KEYWORDS:
        for f in low:
            if kw in f:
                return True
    return False


def _read_dbf_sample(path: str, max_rows: int = 3) -> list[dict]:
    """Return up to max_rows records from a DBF file."""
    try:
        with open(path, 'rb') as f:
            hdr = f.read(32)
            num_records = struct.unpack_from('<I', hdr, 4)[0]
            header_size = struct.unpack_from('<H', hdr, 8)[0]
            record_size = struct.unpack_from('<H', hdr, 10)[0]

            fields: list[tuple[str, int]] = []
            f.seek(32)
            while True:
                fd = f.read(32)
                if fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
                flen = fd[16]
                fields.append((name, flen))

            f.seek(header_size)
            rows = []
            for _ in range(min(num_records, max_rows * 5)):  # skip deleted rows
                raw = f.read(record_size)
                if not raw:
                    break
                if raw[0] == 0x2A:  # deleted
                    continue
                row: dict[str, str] = {}
                offset = 1
                for name, flen in fields:
                    val = raw[offset:offset + flen]
                    try:
                        row[name] = val.decode('big5').strip()
                    except Exception:
                        row[name] = val.decode('latin-1').strip()
                    offset += flen
                rows.append(row)
                if len(rows) >= max_rows:
                    break
            return rows
    except Exception:
        return []


def main():
    roots = sys.argv[1:] if len(sys.argv) > 1 else _fixed_drives()
    if not roots:
        roots = ['C:\\']

    print(f"Searching drives/paths: {roots}")
    print(f"Output will also be saved to: {OUTPUT_FILE}\n")

    candidates: list[tuple[str, list[str], list[dict]]] = []
    scanned = 0
    start = time.time()

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if _should_skip(dirpath):
                dirnames.clear()
                continue

            folder_match = _folder_is_candidate(dirpath)

            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ('.dbf', '.mdb', '.accdb'):
                    continue

                fpath = os.path.join(dirpath, fname)
                scanned += 1

                # For MDB/accdb just note the path — can't easily read without driver
                if ext in ('.mdb', '.accdb'):
                    if folder_match or any(kw in fname.lower() for kw in FOLDER_KEYWORDS + ['bio', 'lab', 'inspect']):
                        candidates.append((fpath, ['(Access database — cannot peek inside)'], []))
                    continue

                fields = _read_dbf_fields(fpath)
                if fields is None:
                    continue

                if folder_match or _fields_are_candidate(fields):
                    rows = _read_dbf_sample(fpath, max_rows=2)
                    candidates.append((fpath, fields, rows))

    elapsed = time.time() - start

    lines = []
    lines.append(f"Search complete — scanned {scanned} database files in {elapsed:.1f}s")
    lines.append(f"Found {len(candidates)} candidate file(s)\n")
    lines.append("=" * 70)

    for path, fields, rows in candidates:
        lines.append(f"\nFILE: {path}")
        lines.append(f"  Fields ({len(fields)}): {', '.join(fields)}")
        if rows:
            lines.append("  Sample rows:")
            for row in rows:
                non_empty = {k: v for k, v in row.items() if v}
                lines.append(f"    {non_empty}")
        lines.append("")

    output = "\n".join(lines)
    print(output)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
