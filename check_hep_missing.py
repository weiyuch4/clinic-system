#!/usr/bin/env python3
"""
Diagnose why 5 patients weren't found — likely Big5 character variant issue.
Run on PC1: python check_hep_missing.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import _ic_main_files, _parse_dbf_cached

MISSING = ['王俐云', '陳子茜', '陳鉞坤', '黃晴', '黃沛晴']

def hex_str(s):
    return ' '.join(f'U+{ord(c):04X}({c})' for c in s)

print("Expected name codepoints:")
for name in MISSING:
    print(f"  {name}: {hex_str(name)}")
print()

# Collect all hep patient names from IC files
all_names: dict[str, str] = {}  # name → last seen name (raw from DBF)

ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

HEP_PREFIXES = (
    '07030', '07031', '07032', '07033',
    '07041', '07044', '07054',
    'B16', 'B17', 'B18', 'B19',
    'V0261', 'V0262', 'Z2251', 'Z2252',
)

def is_hep(code):
    c = code.strip().upper().replace('.', '')
    return any(c.startswith(p) for p in HEP_PREFIXES)

print(f"Scanning {len(_ic_main_files())} IC files for all patients with hep codes...", flush=True)

for path in _ic_main_files():
    try:
        for r in _parse_dbf_cached(path):
            if r.get('H_TYPE', '') not in ('01西醫', 'AE連續'):
                continue
            has_hep = any(is_hep(r.get(f, '')) for f in ICD_FIELDS)
            if not has_hep:
                continue
            name = r.get('NAME', '').strip()
            if name:
                all_names[name] = name
    except Exception:
        pass

print(f"Total unique hepatitis patient names in IC files: {len(all_names)}\n")

# For each missing name, search for names that share the same family name
# and look visually similar (potential encoding variants)
print("Searching for similar names in IC data:")
print("=" * 70)

for target in MISSING:
    family = target[0]   # first character (surname)
    rest   = target[1:]  # given name

    # Find all names starting with the same surname
    candidates = [n for n in all_names if n.startswith(family)]

    print(f"\nTarget: {target}  [{hex_str(target)}]")
    if not candidates:
        print(f"  No patients with surname '{family}' found in hep data at all.")
        continue

    # Show candidates whose length matches or is close
    close = [n for n in candidates if len(n) == len(target)]
    print(f"  Same-surname same-length candidates ({len(close)}):")
    for n in sorted(close):
        match = '*** EXACT MATCH ***' if n == target else ''
        print(f"    {n}  [{hex_str(n)}]  {match}")

    # Also try byte-level: encode target as Big5 and compare
    try:
        target_big5 = target.encode('big5')
    except UnicodeEncodeError as e:
        print(f"  NOTE: Cannot encode '{target}' to Big5: {e}")
        print(f"        This means the character you typed doesn't exist in Big5 — the IC file must use a variant.")
        # Try encoding char by char to find which one fails
        for i, ch in enumerate(target):
            try:
                ch.encode('big5')
            except UnicodeEncodeError:
                print(f"        Problematic character: '{ch}' at position {i}  U+{ord(ch):04X}")
                # Search for any name with the family name and same length where problematic char area matches
                print(f"        Candidates with surname '{family}' and length {len(target)}:")
                for n in sorted(close)[:20]:
                    print(f"          {n}  [{hex_str(n)}]")
        continue

    # Try to find the name by encoding each candidate as Big5 and comparing bytes
    print(f"  Big5 bytes of target: {target_big5.hex()}")
    for n in sorted(close):
        try:
            n_big5 = n.encode('big5')
            if n_big5 == target_big5:
                print(f"  *** BYTE MATCH FOUND: '{n}' encodes to same Big5 bytes as target ***")
        except UnicodeEncodeError:
            pass
