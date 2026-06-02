"""
Dump every 01西醫 and AE連續 record for a patient from recent IC files,
showing whether LONG=1 is set in the P file.

Goal: find what field distinguishes IC01 (慢連續) from 慢性病.

Known ground truth for Q220406513:
  115/02/26 = 慢性病   115/03/03 = IC01   115/03/31 = IC02
  115/04/01 = 一般     115/04/29 = IC03
  115/05/22 = 慢性病   115/05/26 = IC01

Usage:
    python dump_nishi.py <national_id> [<national_id2> ...]

Example:
    python dump_nishi.py Q220406513
"""

import sys
import os
import glob
import struct

from config import IC_DATA_PATH

KNOWN = {
    '1150226': '慢性病',
    '1150303': 'IC01',
    '1150331': 'IC02',
    '1150401': '一般',
    '1150429': 'IC03',
    '1150522': '慢性病',
    '1150526': 'IC01',
}

SKIP_IC  = {'ID', 'NAME', 'BIRTH', 'SAVE', 'SAVE2', 'CARD_NO', 'SAMID',
            'PARENT_B', 'PARENT_N', 'DOCTOR', 'DATETIME', 'M15', 'M52'}
SKIP_P   = {'CODE_F', 'SAVE', 'DRUG_1AME'}


def _parse_dbf(path: str) -> list[dict]:
    with open(path, 'rb') as f:
        hdr = f.read(32)
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
    return records


def dump_patient(nat_id: str) -> None:
    all_ic = sorted(glob.glob(os.path.join(IC_DATA_PATH, 'IC?????.DBF')))
    # Only the most recent 12 files (1 year) to keep output manageable
    recent = all_ic[-12:] if len(all_ic) > 12 else all_ic

    print(f"\n{'='*72}")
    print(f"  Patient: {nat_id}")
    print(f"  Files: {', '.join(os.path.basename(f) for f in recent)}")
    print(f"{'='*72}")

    for ic_path in recent:
        p_path = ic_path[:-4] + 'P.DBF'
        try:
            records = _parse_dbf(ic_path)
        except Exception as e:
            print(f"  [ERROR {os.path.basename(ic_path)}] {e}")
            continue

        for r in records:
            if r.get('ID', '').strip() != nat_id:
                continue
            h_type = r.get('H_TYPE', '').strip()
            if h_type not in ('01西醫', 'AE連續'):
                continue

            date_raw = r.get('DATE', '').strip()
            kind     = r.get('KIND',   '').strip()
            cf       = r.get('CODE_F', '').strip()
            label    = KNOWN.get(date_raw, '')
            label_str = f'  ← [{label}]' if label else ''

            print(f"\n  {os.path.basename(ic_path)}  H_TYPE={h_type!r}  KIND={kind!r}"
                  f"  DATE={date_raw!r}  CF={cf!r}{label_str}")

            # IC row — show all non-empty, non-boring fields
            ic_str = '  '.join(
                f"{k}={v!r}" for k, v in r.items()
                if v.strip() and k not in SKIP_IC
            )
            if ic_str:
                print(f"    IC: {ic_str}")

            # P file — show every drug row for this CF
            if not cf or not os.path.exists(p_path):
                print(f"    P:  (no P file or no CF)")
                continue
            try:
                p_records = [pr for pr in _parse_dbf(p_path)
                             if pr.get('CODE_F', '').strip() == cf]
            except Exception as e:
                print(f"    P:  [ERROR] {e}")
                continue

            if not p_records:
                print(f"    P:  (no P records for this CF)")
                continue

            has_long = any(pr.get('LONG', '').strip() == '1' for pr in p_records)
            long_marker = '  *** LONG=1 ***' if has_long else '  (no LONG=1)'
            print(f"    P:{long_marker}  ({len(p_records)} drug(s))")
            for pr in p_records:
                p_str = '  '.join(
                    f"{k}={v!r}" for k, v in pr.items()
                    if v.strip() and k not in SKIP_P
                )
                print(f"      {p_str}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python dump_nishi.py <national_id> [<national_id2> ...]")
        sys.exit(1)
    for nat_id in sys.argv[1:]:
        dump_patient(nat_id.strip())
    print()


if __name__ == '__main__':
    main()
