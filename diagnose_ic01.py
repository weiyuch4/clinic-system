"""
Diagnostic: dump all IC + P file fields for a patient to find the IC01 signal.

Usage:
    python diagnose_ic01.py <national_id>

Example:
    python diagnose_ic01.py L222359095

Prints every field from the main IC file and matching P file records for that
patient, grouped by H_TYPE, so you can spot what differs between a regular
01西醫 visit and a true IC01 慢性病連續處方箋 visit.
"""

import sys
import os
import glob
import struct

# Load IC_DATA_PATH from config (supports config_local.py override)
from config import IC_DATA_PATH


def _parse_dbf(path: str) -> tuple[list[str], list[dict]]:
    """Return (field_names, records) for a DBF file."""
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
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace')
            flen = fd[16]
            fields.append((name, flen))

        f.seek(header_size)
        records = []
        for _ in range(num_records):
            raw = f.read(record_size)
            if not raw or raw[0] == 0x2A:
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
            records.append(row)
    return [f[0] for f in fields], records


def _ic_main_files() -> list[str]:
    result = []
    for path in glob.glob(os.path.join(IC_DATA_PATH, 'IC?????.DBF')):
        stem = os.path.basename(path)[2:-4]
        if len(stem) == 5 and stem.isdigit():
            result.append(path)
    return sorted(result)


def _print_record(label: str, fields: list[str], row: dict):
    print(f"\n  [{label}]")
    for f in fields:
        v = row.get(f, '')
        if v:  # only print non-empty fields to keep output readable
            print(f"    {f:<16} = {v!r}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_ic01.py <national_id>")
        sys.exit(1)

    nat_id = sys.argv[1].strip()
    print(f"\nSearching for patient: {nat_id}")
    print(f"IC data path: {IC_DATA_PATH}\n")

    found_any = False

    for ic_path in _ic_main_files():
        month = os.path.basename(ic_path)[2:-4]
        p_path = ic_path[:-4] + 'P.DBF'

        try:
            ic_fields, ic_records = _parse_dbf(ic_path)
        except Exception as e:
            print(f"  [!] Could not read {ic_path}: {e}")
            continue

        # Find all IC records for this patient
        patient_records = [r for r in ic_records if r.get('ID', '').strip() == nat_id]
        if not patient_records:
            continue

        found_any = True
        print(f"{'='*60}")
        print(f"  File: IC{month}.DBF  ({len(patient_records)} record(s) for this patient)")
        print(f"{'='*60}")

        # Build CODE_F → IC record map for this patient
        cf_to_ic: dict[str, dict] = {}
        for r in patient_records:
            cf = r.get('CODE_F', '').strip()
            h_type = r.get('H_TYPE', '').strip()
            date = r.get('DATE', '').strip()
            label = f"IC main | H_TYPE={h_type!r} | DATE={date} | CODE_F={cf}"
            _print_record(label, ic_fields, r)
            if cf:
                cf_to_ic[cf] = r

        # Now dump the matching P file records
        if cf_to_ic and os.path.exists(p_path):
            try:
                p_fields, p_records = _parse_dbf(p_path)
                matching_p = [r for r in p_records if r.get('CODE_F', '').strip() in cf_to_ic]
                if matching_p:
                    print(f"\n  --- P file records (IC{month}P.DBF) ---")
                    for r in matching_p:
                        cf = r.get('CODE_F', '').strip()
                        ic_r = cf_to_ic.get(cf, {})
                        h_type = ic_r.get('H_TYPE', '?')
                        drug = r.get('DRUG_NO', '').strip()
                        long_flag = r.get('LONG', '').strip()
                        label = f"P | CODE_F={cf} | H_TYPE={h_type!r} | DRUG_NO={drug} | LONG={long_flag!r}"
                        _print_record(label, p_fields, r)
            except Exception as e:
                print(f"  [!] Could not read {p_path}: {e}")

    if not found_any:
        print(f"No records found for {nat_id} in any IC file under {IC_DATA_PATH}")
        print("Check that the national ID is correct and that IC files are present.")


if __name__ == '__main__':
    main()
