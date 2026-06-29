import struct
import os

dbf_path = r"c:\Users\weiyu\OneDrive\Documents\Visual Studio\clinic-system\mock\Data\S\PATDB.DBF"

with open(dbf_path, 'rb') as f:
    # Read 32-byte header
    hdr = f.read(32)
    num_records = struct.unpack_from('<I', hdr, 4)[0]
    header_size = struct.unpack_from('<H', hdr, 8)[0]
    record_size = struct.unpack_from('<H', hdr, 10)[0]
    
    print(f"DBF File: {os.path.basename(dbf_path)}")
    print(f"Number of records: {num_records}")
    print(f"Header size: {header_size}")
    print(f"Record size: {record_size}")
    print("\n" + "="*70)
    print("FIELD DESCRIPTORS (32-byte each, starting at byte 32):")
    print("="*70)
    
    fields = []
    f.seek(32)
    idx = 0
    while True:
        fd = f.read(32)
        if not fd or fd[0] == 0x0D:
            break
        name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
        field_type = chr(fd[11])
        flen = fd[16]
        decimals = fd[17]
        fields.append((name, field_type, flen, decimals))
        idx += 1
        print(f"{idx:2d}. {name:12s} Type:{field_type} Len:{flen:3d} Decimals:{decimals}")
    
    print("\n" + "="*70)
    print("SAMPLE DATA - First 5 records")
    print("="*70)
    
    # Read first 5 data records
    f.seek(header_size)
    count = 0
    for _ in range(min(5, num_records)):
        raw = f.read(record_size)
        if not raw or raw[0] == 0x2A:  # deleted record marker
            continue
        
        count += 1
        row = {}
        offset = 1
        for name, ftype, flen, _ in fields:
            val = raw[offset:offset + flen]
            try:
                decoded = val.decode('big5').strip()
            except:
                decoded = val.decode('latin-1', errors='replace').strip()
            row[name] = decoded
            offset += flen
        
        print(f"\nRecord {count}:")
        print(f"  ID (National ID): {row.get('ID', 'N/A')}")
        print(f"  NAME: {row.get('NAME', 'N/A')}")
        
        # Show all phone-like fields
        for fname in sorted(row.keys()):
            val = row[fname]
            if 'TEL' in fname.upper() or 'CEL' in fname.upper() or 'MOBILE' in fname.upper() or 'PHONE' in fname.upper():
                print(f"  {fname}: {val}")
            elif fname in ('BIRTH', 'SEX', 'ADDR', 'EMAIL'):
                print(f"  {fname}: {val[:40] if len(val) > 40 else val}")

print("\n" + "="*70)
print("Field list complete.")
