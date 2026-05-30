"""
Read blood test results for a specific patient.

Searches:
  1. Z:\\01\\UPEXAMD\\         -- 檢驗平台 results (EH + ER DBF files, newest first)
  2. Z:\\Z\\bioc.dbf           -- older 各項檢驗 BIO results
  3. Z:\\Z\\BIO2C.DBF          -- older BIO (alternate/backup file)
  4. Z:\\Z\\CBCC.DBF           -- CBC blood count results

Usage:
    python read_lab_results.py <national_id>

    national_id: 10-character Taiwan national ID (e.g. B123124596)

Output is also saved to read_lab_results_output.txt in the same folder.
"""

import os
import sys
import struct

UPEXAMD_ROOT = r"Z:\01\UPEXAMD"
ZZ_DIR       = r"Z:\Z"
OUTPUT_FILE  = os.path.join(os.path.dirname(__file__), "read_lab_results_output.txt")

# ── VAR column labels for bioc.dbf / BIO2C.DBF ───────────────────────────────
# New platform started 2026-04-01 (ROC 115/04/01 = raw DATE 'B50401').
# Old and new platforms store different tests in the same VAR columns.
_NEW_PLATFORM_DATE = 'B50401'

OLD_BIO_LABELS: dict[str, str] = {
    'VAR4':  'Glucose (AC)',
    'VAR5':  'HBsAg',
    'VAR8':  'HBsAb',
    'VAR10': 'T-Protein (總蛋白)',
    'VAR14': 'IgE',
    'VAR15': 'AST (GOT)',
    'VAR17': 'ALT (GPT)',
    'VAR18': 'Anti-HCV',
    'VAR20': 'GGT (r-GT)',
    'VAR21': 'TIBC',
    'VAR23': 'ALK-P (鹼性磷酸酶)',
    'VAR24': 'Fe (鐵)',
    'VAR25': 'TSH',
    'VAR26': 'Bil-T (總膽紅素)',
    'VAR29': 'HbA1c',
    'VAR31': 'Albumin',
    'VAR32': 'BUN',
    'VAR34': 'Globulin (球蛋白)',
    'VAR35': 'Cr (Creatinine, 血)',
    'VAR37': 'A/G ratio',
    'VAR38': 'UA (尿酸)',
    'VAR40': 'eGFR',
    'VAR41': '備註 / 特殊檢查',
    'VAR42': 'T-Chol (總膽固醇)',
    'VAR43': 'HDL',
    'VAR44': 'TG (三酸甘油脂)',
    'VAR45': 'TC/HDL ratio',
    'VAR48': 'LDL',
}

NEW_BIO_LABELS: dict[str, str] = {
    'VAR4':  'Glucose (AC)',
    'VAR10': 'HbA1c',
    'VAR20': 'GGT (r-GT)',
    'VAR29': 'HbA1c',
    'VAR35': 'Cr (Creatinine, 血)',
    'VAR40': 'LDL',
    'VAR41': '備註 / 特殊檢查',
    'VAR42': 'T-Chol (總膽固醇)',
    'VAR43': 'HDL',
    'VAR44': 'TG (三酸甘油脂)',
    'VAR45': 'TC/HDL ratio',
    'VAR48': 'eAG',
}


def _bio_labels_for_date(raw_date: str) -> dict[str, str]:
    return NEW_BIO_LABELS if raw_date.strip() >= _NEW_PLATFORM_DATE else OLD_BIO_LABELS

# ── VAR column labels for CBCC.DBF ───────────────────────────────────────────
# VAR1-3 = year/month/day (skip), VAR4+ = CBC values in standard order.
CBC_LABELS: dict[str, str] = {
    'VAR1': '',   # year
    'VAR2': '',   # month
    'VAR3': '',   # day
    'VAR4':  'WBC (×10³)',
    'VAR5':  'Hgb (g/dL)',
    'VAR6':  'Hct (%)',
    'VAR7':  'MCV (fL)',
    'VAR8':  'MCH (pg)',
    'VAR9':  'MCHC (g/dL)',
    'VAR10': 'RDW',
    'VAR11': '',
    'VAR12': 'RBC (×10⁴)',
    'VAR13': '',
    'VAR14': 'NE% (嗜中性)',
    'VAR15': 'MO% (單核)',
    'VAR16': 'EO% (嗜酸)',
    'VAR17': 'LY% (淋巴)',
    'VAR18': 'BA% (嗜鹼)',
    'VAR24': 'Plt (×10³)',
}


# ── DBF reading helpers ───────────────────────────────────────────────────────

def _read_dbf_schema(path: str):
    """Return (header_size, record_size, fields: list[tuple[name, offset, length]])."""
    with open(path, 'rb') as f:
        hdr = f.read(32)
        if len(hdr) < 32:
            return None
        if hdr[0] not in (0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x83, 0xF5):
            return None
        header_size = struct.unpack_from('<H', hdr, 8)[0]
        record_size = struct.unpack_from('<H', hdr, 10)[0]
        fields = []
        offset = 1  # first byte of record is deletion flag
        f.seek(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            flen = fd[16]
            if name:
                fields.append((name, offset, flen))
            offset += flen
        return header_size, record_size, fields


def _iter_rows(path: str):
    """Yield non-deleted rows as dicts from a DBF file."""
    try:
        schema = _read_dbf_schema(path)
        if schema is None:
            return
        header_size, record_size, fields = schema
        with open(path, 'rb') as f:
            f.seek(header_size)
            while True:
                raw = f.read(record_size)
                if not raw or len(raw) < record_size:
                    break
                if raw[0] == 0x2A:  # deleted record
                    continue
                row = {}
                for name, off, flen in fields:
                    chunk = raw[off:off + flen]
                    try:
                        val = chunk.decode('big5').strip()
                    except Exception:
                        val = chunk.decode('latin-1').strip()
                    # skip null-byte-only binary fields
                    if val and not all(c == '\x00' for c in val):
                        row[name] = val
                yield row
    except Exception as e:
        print(f"  [Warning] Could not read {path}: {e}")


def _decode_roc_year(prefix: str) -> str:
    """Decode 2-char year prefix used in 6-char dates: A0-A9 = 100-109, B0-B9 = 110-119."""
    if len(prefix) == 2 and prefix[0].isalpha():
        base = (ord(prefix[0].upper()) - ord('A') + 10) * 10
        digit = int(prefix[1]) if prefix[1].isdigit() else 0
        return str(base + digit)
    return prefix  # plain digits (e.g. '92', '04')


def _roc_to_display(roc: str) -> str:
    """Convert ROC date string to YYY/MM/DD display.
    Handles: YYYMMDD (7 chars), YYMMDD (6 chars), and
    the A/B prefix encoding where A0=100, B5=115, etc.
    """
    roc = roc.strip()
    if len(roc) == 7:
        return f"{roc[:3]}/{roc[3:5]}/{roc[5:]}"
    if len(roc) == 6:
        # Check for letter-prefix year encoding (A0-A9, B0-B9, ...)
        if roc[0].isalpha():
            year = _decode_roc_year(roc[:2])
            return f"{year}/{roc[2:4]}/{roc[4:]}"
        return f"{roc[:2]}/{roc[2:4]}/{roc[4:]}"
    return roc


# ── 1. 檢驗平台 (UPEXAMD) ────────────────────────────────────────────────────

def search_eplat(national_id: str) -> list[dict]:
    """
    Walk Z:\\01\\UPEXAMD\\YYYMM\\ folders for *EH.DBF files.
    Find rows where H9 == national_id, then load corresponding ER file.
    Returns list of visit dicts sorted newest-first.
    """
    visits: dict[str, dict] = {}  # key = (date, code_f)

    if not os.path.isdir(UPEXAMD_ROOT):
        print(f"[!] UPEXAMD root not found: {UPEXAMD_ROOT}")
        return []

    # Collect all EH files, sorted descending (newest month first)
    month_dirs = sorted(
        [d for d in os.listdir(UPEXAMD_ROOT)
         if os.path.isdir(os.path.join(UPEXAMD_ROOT, d))],
        reverse=True
    )

    for month_dir in month_dirs:
        month_path = os.path.join(UPEXAMD_ROOT, month_dir)
        eh_files = sorted(
            [f for f in os.listdir(month_path) if f.upper().endswith('EH.DBF')],
            reverse=True
        )
        for eh_fname in eh_files:
            eh_path = os.path.join(month_path, eh_fname)
            # Extract YYYMMDD prefix (everything before 'EH.DBF')
            date_prefix = eh_fname[:-6]  # strip 'EH.DBF'

            patient_rows = []
            patient_code_fs = set()
            for row in _iter_rows(eh_path):
                if row.get('H9', '').strip() == national_id:
                    patient_rows.append(row)
                    patient_code_fs.add(row.get('CODE_F', '').strip())

            if not patient_rows:
                continue

            # Load corresponding ER file
            er_fname = date_prefix + 'ER.DBF'
            er_path = os.path.join(month_path, er_fname)
            er_by_panel: dict[str, list[dict]] = {}  # key = H15 (NHI code)
            if os.path.isfile(er_path):
                for row in _iter_rows(er_path):
                    if row.get('CODE_F', '').strip() in patient_code_fs:
                        panel = row.get('H15', '').strip()
                        er_by_panel.setdefault(panel, []).append(row)

            # Build visit entry
            exam_date = patient_rows[0].get('H11', date_prefix[:7]).strip()
            key = (exam_date, list(patient_code_fs)[0])
            if key not in visits:
                visits[key] = {
                    'date': exam_date,
                    'panels': [],
                    'source': 'EPLAT',
                }
            for eh_row in patient_rows:
                panel_code = eh_row.get('H15', '').strip()
                panel_name = eh_row.get('E_NAME', panel_code).strip()
                items = []
                for er_row in er_by_panel.get(panel_code, []):
                    name = er_row.get('R2', '').strip()
                    val  = er_row.get('R6_1', '').strip()
                    unit = er_row.get('R5', '').strip()
                    ref_hi = er_row.get('R6_2', '').strip()
                    method = er_row.get('R3', '').strip()
                    if name or val:
                        items.append({
                            'name': name or '—',
                            'value': val or '—',
                            'unit': unit,
                            'ref_hi': ref_hi,
                            'method': method,
                        })
                visits[key]['panels'].append({
                    'code': panel_code,
                    'name': panel_name,
                    'items': items,
                })

    return sorted(visits.values(), key=lambda v: v['date'], reverse=True)


# ── 2. Find patient 6-digit CODE from PAT_HIST ───────────────────────────────

def find_patient_code(national_id: str) -> str | None:
    """Look up 6-digit internal patient code from PAT_HIST.DBF."""
    path = os.path.join(ZZ_DIR, 'PAT_HIST.DBF')
    if not os.path.isfile(path):
        return None
    best = None
    best_date = ''
    for row in _iter_rows(path):
        id_match = (row.get('ID_NEW', '').strip() == national_id or
                    row.get('ID_OLD', '').strip() == national_id)
        if id_match:
            d = row.get('DATE', '').strip()
            if d >= best_date:
                best_date = d
                best = row.get('CODE', '').strip()
    return best


# ── 3. BIO / CBC older data ───────────────────────────────────────────────────

def search_bio_file(dbf_path: str, patient_code: str) -> list[dict]:
    """Return all rows for patient_code from a BIO-style DBF (CODE, DATE, VAR1…)."""
    if not os.path.isfile(dbf_path):
        return []
    rows = []
    for row in _iter_rows(dbf_path):
        if row.get('CODE', '').strip() == patient_code:
            rows.append(row)
    return sorted(rows, key=lambda r: r.get('DATE', ''), reverse=True)


# ── Output formatting ─────────────────────────────────────────────────────────

def format_eplat(visits: list[dict]) -> list[str]:
    lines = []
    if not visits:
        lines.append("  (no 檢驗平台 records found for this patient)")
        return lines
    for v in visits:
        lines.append(f"\n  日期: {_roc_to_display(v['date'])}")
        for panel in v['panels']:
            lines.append(f"    ▶ {panel['name']}  [{panel['code']}]")
            if panel['items']:
                for item in panel['items']:
                    ref = f"  (參考高值: {item['ref_hi']})" if item['ref_hi'] else ""
                    unit = f" {item['unit']}" if item['unit'] else ""
                    lines.append(f"       {item['name']:<30} {item['value']}{unit}{ref}")
            else:
                lines.append("       (無個別項目資料 — 可能為影像/報告類)")
    return lines


def format_bio(rows: list[dict], source: str, labels: dict[str, str] | None = None) -> list[str]:
    DATE_VARS = {'VAR1', 'VAR2', 'VAR3'}
    lines = []
    if not rows:
        lines.append(f"  (no {source} records found)")
        return lines
    for row in rows:
        date = _roc_to_display(row.get('DATE', '???'))
        lines.append(f"\n  日期: {date}")
        row_labels = labels if labels is not None else _bio_labels_for_date(row.get('DATE', ''))
        for k, v in row.items():
            if k in ('CODE', 'DATE') or k in DATE_VARS or not v:
                continue
            label = row_labels.get(k, '')
            if label == '':
                display = f"    {k:<8} {v}"
            else:
                display = f"    {label:<28} {v}"
            lines.append(display)
    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python read_lab_results.py <national_id>")
        print("Example: python read_lab_results.py B123124596")
        sys.exit(1)

    national_id = sys.argv[1].strip().upper()
    print(f"Searching for patient: {national_id}")

    output_lines = [f"Blood test results for: {national_id}", "=" * 60]

    # 1. 檢驗平台
    print("\n[1/4] Searching 檢驗平台 (UPEXAMD)...")
    eplat_visits = search_eplat(national_id)
    output_lines.append(f"\n【檢驗平台】 — {len(eplat_visits)} visit(s) found")
    output_lines += format_eplat(eplat_visits)

    # 2. Find 6-digit patient code for older BIO files
    print("[2/4] Looking up internal patient code (PAT_HIST)...")
    patient_code = find_patient_code(national_id)
    if patient_code:
        print(f"      Found patient code: {patient_code}")
    else:
        print("      Patient code not found in PAT_HIST.DBF")

    output_lines.append(f"\n內部患者代碼: {patient_code or '(未找到)'}")

    # 3. bioc.dbf
    print("[3/4] Searching bioc.dbf + BIO2C.DBF...")
    bio_rows, bio2c_rows = [], []
    if patient_code:
        bio_rows  = search_bio_file(os.path.join(ZZ_DIR, 'bioc.dbf'),  patient_code)
        bio2c_rows = search_bio_file(os.path.join(ZZ_DIR, 'BIO2C.DBF'), patient_code)

    output_lines.append(f"\n【各項檢驗 BIO (bioc.dbf)】 — {len(bio_rows)} record(s)")
    output_lines += format_bio(bio_rows, 'bioc.dbf')

    output_lines.append(f"\n【各項檢驗 BIO2C (BIO2C.DBF)】 — {len(bio2c_rows)} record(s)")
    output_lines += format_bio(bio2c_rows, 'BIO2C.DBF')

    # 4. CBCC.DBF
    print("[4/4] Searching CBCC.DBF (CBC)...")
    cbc_rows = []
    if patient_code:
        cbc_rows = search_bio_file(os.path.join(ZZ_DIR, 'CBCC.DBF'), patient_code)

    output_lines.append(f"\n【CBC 血球計數 (CBCC.DBF)】 — {len(cbc_rows)} record(s)")
    output_lines += format_bio(cbc_rows, 'CBCC.DBF', CBC_LABELS)

    # Save and print
    output = "\n".join(output_lines)
    print("\n" + output)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
