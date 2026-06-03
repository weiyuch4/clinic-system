"""
Find a specific patient in Z:\\01\\ per-patient DBF files and dump all their
visit records with full field values, to decode what each A-field means.

Usage:
    python decode_patient_files.py <national_id> [<national_id2> ...]

Example:
    python decode_patient_files.py Q220406513 B220080204
"""

import sys
import os
import glob
import struct


# Adjust if your Z:\01\ is mounted differently
CHART_PATH = r'Z:\01'


def _parse_dbf(path: str) -> tuple[list[tuple[str, int]], list[dict]]:
    with open(path, 'rb') as f:
        hdr = f.read(32)
        if len(hdr) < 32:
            return [], []
        header_size = struct.unpack_from('<H', hdr, 8)[0]
        record_size = struct.unpack_from('<H', hdr, 10)[0]
        fields: list[tuple[str, int]] = []
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
        records = []
        while True:
            raw = f.read(record_size)
            if not raw or len(raw) < record_size:
                break
            if raw[0] == 0x2A:
                continue
            row: dict[str, str] = {}
            offset = 1
            for name, flen in fields:
                try:
                    val = raw[offset:offset + flen].decode('cp950', errors='replace').strip()
                except Exception:
                    val = raw[offset:offset + flen].decode('latin-1', errors='replace').strip()
                row[name] = val
                offset += flen
            records.append(row)
    return fields, records


def find_patient_code(nat_id: str) -> list[str]:
    """Search all *11.DBF files for the patient's national ID. Returns patient codes found."""
    found = set()
    pattern = os.path.join(CHART_PATH, '*11.DBF')
    files = sorted(glob.glob(pattern))
    print(f"  Searching {len(files)} *11.DBF files for {nat_id!r}...")

    for path in files:
        try:
            _, records = _parse_dbf(path)
        except Exception:
            continue
        for r in records:
            # Check common ID fields
            for key in ('A7', 'A15'):
                if r.get(key, '').strip() == nat_id:
                    pat_code = os.path.basename(path)[:-5]  # strip '11.DBF'
                    if pat_code not in found:
                        found.add(pat_code)
                        print(f"    Found in {os.path.basename(path)} via field {key!r}")
    return sorted(found)


def dump_patient_chart(nat_id: str, pat_code: str):
    base = os.path.join(CHART_PATH, pat_code)
    print(f"\n{'='*72}")
    print(f"  Patient: {nat_id}   Patient code: {pat_code}")
    print(f"{'='*72}")

    for suffix in ('10', '11', '12', '19'):
        path = base + suffix + '.DBF'
        if not os.path.exists(path):
            continue
        try:
            fields, records = _parse_dbf(path)
        except Exception as e:
            print(f"\n  [{suffix}.DBF] ERROR: {e}")
            continue

        # Filter to records belonging to this patient
        patient_records = []
        for r in records:
            for key in ('A7', 'A15'):
                if r.get(key, '').strip() == nat_id:
                    patient_records.append(r)
                    break
            else:
                # For 10/19 files, maybe only 1 record total
                if suffix in ('10', '19') and not patient_records:
                    patient_records.append(r)

        print(f"\n  [{suffix}.DBF] {len(records)} total records, "
              f"{len(patient_records)} for this patient")
        print(f"  Fields: {', '.join(n for n, _ in fields)}")

        # Sort 11/12 by A12 (likely visit date/sequence) to show recent first
        if suffix in ('11', '12') and patient_records:
            patient_records.sort(key=lambda r: r.get('A12', ''), reverse=True)

        for i, r in enumerate(patient_records[:10]):
            non_empty = {k: v for k, v in r.items() if v}
            print(f"    [{i+1}] {non_empty}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python decode_patient_files.py <national_id> [...]")
        sys.exit(1)

    if not os.path.isdir(CHART_PATH):
        print(f"ERROR: Chart path not found: {CHART_PATH!r}")
        print("Edit CHART_PATH at the top of this script.")
        sys.exit(1)

    for nat_id in sys.argv[1:]:
        nat_id = nat_id.strip()
        print(f"\nLooking up {nat_id!r}...")
        codes = find_patient_code(nat_id)
        if not codes:
            print(f"  NOT FOUND in any *11.DBF file.")
            continue
        for code in codes:
            dump_patient_chart(nat_id, code)
    print()


if __name__ == '__main__':
    main()
