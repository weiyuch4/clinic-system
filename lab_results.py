"""
Lab results reader for the web API.

Reads blood test results from:
  - Z:\\Z\\bioc.dbf      (各項檢驗 BIO)
  - Z:\\Z\\CBCC.DBF      (CBC 血球計數)
  - Z:\\Z\\PAT_HIST.DBF  (national ID → 6-digit patient code)

Returns structured JSON-ready dicts for the frontend modal.
"""

import os
import struct

ZZ_DIR = r"Z:\Z"

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
    'VAR41': '__notes__',
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
    'VAR41': '__notes__',
    'VAR42': 'T-Chol (總膽固醇)',
    'VAR43': 'HDL',
    'VAR44': 'TG (三酸甘油脂)',
    'VAR45': 'TC/HDL ratio',
    'VAR48': 'eAG',
}

CBC_LABELS: dict[str, str] = {
    'VAR4':  'WBC (×10³)',
    'VAR5':  'Hgb (g/dL)',
    'VAR6':  'Hct (%)',
    'VAR7':  'MCV (fL)',
    'VAR8':  'MCH (pg)',
    'VAR9':  'MCHC (g/dL)',
    'VAR12': 'RBC (×10⁴)',
    'VAR14': 'NE% (嗜中性)',
    'VAR15': 'MO% (單核)',
    'VAR16': 'EO% (嗜酸)',
    'VAR17': 'LY% (淋巴)',
    'VAR18': 'BA% (嗜鹼)',
    'VAR24': 'Plt (×10³)',
}

DATE_VARS = {'VAR1', 'VAR2', 'VAR3'}


def _bio_labels_for(raw_date: str) -> dict[str, str]:
    return NEW_BIO_LABELS if raw_date.strip() >= _NEW_PLATFORM_DATE else OLD_BIO_LABELS


# ── DBF helpers ───────────────────────────────────────────────────────────────

def _iter_rows(path: str):
    try:
        with open(path, 'rb') as f:
            hdr = f.read(32)
            if len(hdr) < 32 or hdr[0] not in (0x03,0x04,0x05,0x30,0x31,0x32,0x83,0xF5):
                return
            header_size = struct.unpack_from('<H', hdr, 8)[0]
            record_size = struct.unpack_from('<H', hdr, 10)[0]
            fields = []
            offset = 1
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
            f.seek(header_size)
            while True:
                raw = f.read(record_size)
                if not raw or len(raw) < record_size:
                    break
                if raw[0] == 0x2A:
                    continue
                row: dict[str, str] = {}
                for name, off, flen in fields:
                    chunk = raw[off:off + flen]
                    try:
                        val = chunk.decode('big5').strip()
                    except Exception:
                        val = chunk.decode('latin-1').strip()
                    if val and '\x00' not in val:
                        row[name] = val
                yield row
    except Exception:
        return


def _decode_date(raw: str) -> str:
    """Convert raw 6-char date (A4=104, B5=115 prefix encoding) to YYY/MM/DD."""
    raw = raw.strip()
    if len(raw) == 6 and raw[0].isalpha():
        base = (ord(raw[0].upper()) - ord('A') + 10) * 10
        digit = int(raw[1]) if raw[1].isdigit() else 0
        return f"{base + digit}/{raw[2:4]}/{raw[4:]}"
    if len(raw) == 7:
        return f"{raw[:3]}/{raw[3:5]}/{raw[5:]}"
    if len(raw) == 6:
        return f"{raw[:2]}/{raw[2:4]}/{raw[4:]}"
    return raw


def _parse_flag(val: str) -> tuple[str, str]:
    """Split '7.1+' → ('7.1', '+'), '65.1-' → ('65.1', '-'), '92' → ('92', '')."""
    v = val.strip()
    if v and v[-1] in ('+', '-') and len(v) > 1:
        return v[:-1], v[-1]
    return v, ''


# ── Patient code lookup ───────────────────────────────────────────────────────

def _find_patient_code(national_id: str) -> str | None:
    path = os.path.join(ZZ_DIR, 'PAT_HIST.DBF')
    if not os.path.isfile(path):
        return None
    best_code, best_date = None, ''
    for row in _iter_rows(path):
        if (row.get('ID_NEW', '').strip() == national_id or
                row.get('ID_OLD', '').strip() == national_id):
            d = row.get('DATE', '').strip()
            if d >= best_date:
                best_date = d
                best_code = row.get('CODE', '').strip()
    return best_code


# ── BIO record reader ─────────────────────────────────────────────────────────

def _read_bio_records(patient_code: str, dbf_name: str) -> list[dict]:
    path = os.path.join(ZZ_DIR, dbf_name)
    if not os.path.isfile(path):
        return []
    raw_rows = [r for r in _iter_rows(path) if r.get('CODE', '').strip() == patient_code]
    raw_rows.sort(key=lambda r: r.get('DATE', ''), reverse=True)

    records = []
    for row in raw_rows:
        labels = _bio_labels_for(row.get('DATE', ''))
        items = []
        notes = ''
        for var, label in labels.items():
            val = row.get(var, '').strip()
            if not val:
                continue
            if label == '__notes__':
                notes = val
                continue
            v, flag = _parse_flag(val)
            items.append({'label': label, 'value': v, 'flag': flag})

        # Show unknown VAR fields as-is (without a label)
        labeled = set(labels.keys()) | DATE_VARS | {'CODE', 'DATE'}
        for k, val in row.items():
            if k in labeled or not val:
                continue
            v, flag = _parse_flag(val)
            items.append({'label': k, 'value': v, 'flag': flag})

        if items or notes:
            records.append({
                'date': _decode_date(row.get('DATE', '???')),
                'items': items,
                'notes': notes,
            })
    return records


def _read_cbc_records(patient_code: str) -> list[dict]:
    path = os.path.join(ZZ_DIR, 'CBCC.DBF')
    if not os.path.isfile(path):
        return []
    raw_rows = [r for r in _iter_rows(path) if r.get('CODE', '').strip() == patient_code]
    raw_rows.sort(key=lambda r: r.get('DATE', ''), reverse=True)

    records = []
    for row in raw_rows:
        items = []
        for var, label in CBC_LABELS.items():
            val = row.get(var, '').strip()
            if not val:
                continue
            v, flag = _parse_flag(val)
            items.append({'label': label, 'value': v, 'flag': flag})
        if items:
            records.append({
                'date': _decode_date(row.get('DATE', '???')),
                'items': items,
            })
    return records


# ── Public API ────────────────────────────────────────────────────────────────

def get_lab_results(national_id: str) -> dict:
    """
    Return structured lab results for a patient identified by national ID.
    Returns {'bio': [...], 'cbc': [...], 'error': str|None}.
    """
    try:
        patient_code = _find_patient_code(national_id)
        if not patient_code:
            return {'bio': [], 'cbc': [], 'patient_code': None, 'error': None}

        bio = _read_bio_records(patient_code, 'bioc.dbf')
        # Merge BIO2C if it has additional records not already covered
        bio2c = _read_bio_records(patient_code, 'BIO2C.DBF')
        existing_dates = {r['date'] for r in bio}
        for r in bio2c:
            if r['date'] not in existing_dates:
                bio.append(r)
        bio.sort(key=lambda r: r['date'], reverse=True)

        cbc = _read_cbc_records(patient_code)

        return {'bio': bio, 'cbc': cbc, 'patient_code': patient_code, 'error': None}
    except Exception as e:
        return {'bio': [], 'cbc': [], 'patient_code': None, 'error': str(e)}
