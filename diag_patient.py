#!/usr/bin/env python3
"""Diagnose why a specific patient's IC01 is not detected.
Run: python diag_patient.py
"""
import glob, os, struct, sys

NAT_ID   = 'B221745017'
IC_DIR   = r'Z:\3'

def parse_dbf(path):
    with open(path, 'rb') as f:
        hdr = f.read(32)
        num_rec  = struct.unpack_from('<I', hdr, 4)[0]
        hdr_size = struct.unpack_from('<H', hdr, 8)[0]
        rec_size = struct.unpack_from('<H', hdr, 10)[0]
        fields = []
        f.seek(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            flen = fd[16]
            fields.append((name, flen))
        f.seek(hdr_size)
        records = []
        for _ in range(num_rec):
            raw = f.read(rec_size)
            if not raw or raw[0] == 0x2A:
                continue
            row = {}
            offset = 1
            for name, flen in fields:
                val = raw[offset:offset+flen]
                try:    row[name] = val.decode('big5').strip()
                except: row[name] = val.decode('latin-1', errors='replace').strip()
                offset += flen
            records.append(row)
    return fields, records

def main():
    # Collect all IC main files sorted newest first
    main_files = sorted(
        [p for p in glob.glob(os.path.join(IC_DIR, 'IC?????.DBF'))
         if os.path.basename(p)[2:-4].isdigit()],
        reverse=True
    )

    print(f"Looking for patient: {NAT_ID}")
    print(f"Scanning {len(main_files)} IC main files (newest first)\n")

    found = []

    for ic_path in main_files:
        stem = os.path.basename(ic_path)[2:-4]
        try:
            _, records = parse_dbf(ic_path)
        except Exception as e:
            print(f"  {stem}: ERROR {e}")
            continue

        patient_recs = [r for r in records if r.get('ID', '') == NAT_ID]
        if not patient_recs:
            continue

        h_path = os.path.join(IC_DIR, f'IC{stem}H.DBF')
        p_path = os.path.join(IC_DIR, f'IC{stem}P.DBF')

        print(f"{'='*60}")
        print(f"IC file: {os.path.basename(ic_path)}  ({len(patient_recs)} record(s))")

        for r in patient_recs:
            cf = r.get('CODE_F', '')
            print(f"\n  Main record:")
            print(f"    DATE    = {r.get('DATE','')}")
            print(f"    H_TYPE  = {r.get('H_TYPE','')}")
            print(f"    CODE_F  = {cf}")
            print(f"    CARD    = {r.get('CARD','')}")
            print(f"    KIND    = {r.get('KIND','')}")
            print(f"    M33     = {r.get('M33','(field absent)')}")
            print(f"    M26     = {r.get('M26','(field absent)')}")

            # H file lookup
            if os.path.exists(h_path):
                try:
                    _, h_recs = parse_dbf(h_path)
                    h_match = [hr for hr in h_recs if hr.get('CODE_F','') == cf]
                    if h_match:
                        hr = h_match[0]
                        print(f"\n  H file ({os.path.basename(h_path)}):")
                        print(f"    M33     = '{hr.get('M33','')}'")
                        print(f"    M26     = '{hr.get('M26','')}'")
                        # print all non-empty fields
                        extras = {k: v for k, v in hr.items()
                                  if v and k not in ('CODE_F','M33','M26')}
                        if extras:
                            print(f"    other   = {extras}")
                    else:
                        print(f"\n  H file: NO matching CODE_F record found")
                        # show all CODE_Fs in H file for context
                        sample_cfs = [hr.get('CODE_F','') for hr in h_recs[:5]]
                        print(f"           (sample CODE_Fs in H: {sample_cfs})")
                except Exception as e:
                    print(f"\n  H file ERROR: {e}")
            else:
                print(f"\n  H file: NOT FOUND ({os.path.basename(h_path)})")

            # P file lookup
            if os.path.exists(p_path):
                try:
                    _, p_recs = parse_dbf(p_path)
                    p_match = [pr for pr in p_recs if pr.get('CODE_F','') == cf]
                    if p_match:
                        print(f"\n  P file ({os.path.basename(p_path)}) — {len(p_match)} drug row(s):")
                        for pr in p_match:
                            print(f"    DRUG_NO={pr.get('DRUG_NO','')}  LONG={pr.get('LONG','')}  PS={pr.get('PS','')}  {pr.get('DRUG_NAME','')}")
                    else:
                        print(f"\n  P file: NO matching CODE_F record")
                except Exception as e:
                    print(f"\n  P file ERROR: {e}")
            else:
                print(f"\n  P file: NOT FOUND ({os.path.basename(p_path)})")

        found.append(stem)

    if not found:
        print("Patient NOT FOUND in any IC main file.")

if __name__ == '__main__':
    main()
