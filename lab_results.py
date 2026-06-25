"""
Lab results reader for the web API.

Reads blood test results from:
  - Z:\\Z\\bioc.dbf      (各項檢驗 BIO)
  - Z:\\Z\\CBCC.DBF      (CBC 血球計數)
  - Z:\\Z\\PAT_HIST.DBF  (national ID → 6-digit patient code, change-log only)
  - Z:\\IC\\IC?????.DBF  (IC visit files — fallback for patients not in PAT_HIST)

Returns structured JSON-ready dicts for the frontend modal.
"""

import glob as _glob
import os
import re
import struct
import time
import unicodedata
from datetime import date, timedelta

ZZ_DIR = r"Z:\Z"
IC_DIR = r"Z:\IC"

# Labels (from OLD_BIO_LABELS/NEW_BIO_LABELS below) considered part of the
# MSPT (代謝症候群) metabolic panel — used to decide whether a recent blood
# draw already covers the 追2/追3 blood-test requirement.
# PROVISIONAL list — to be replaced with the precise marker list.
MSPT_PANEL_LABELS = {
    'Glucose (AC)', 'HbA1c', 'T-Chol (總膽固醇)', 'TG (三酸甘油脂)', 'HDL', 'LDL',
}

# New platform started 2026-04-01 (ROC 115/04/01 = raw DATE 'B50401').
# Old and new platforms store different tests in the same VAR columns.
_NEW_PLATFORM_DATE = 'B50401'

OLD_BIO_LABELS: dict[str, str] = {
    'VAR4':  'Glucose (AC)',
    'VAR5':  'HBsAg',
    'VAR6':  'RA',
    'VAR7':  'PC Sugar',
    'VAR8':  'HBsAb',
    'VAR9':  'CRP',
    'VAR10': 'HbA1c',
    'VAR11': 'HBeAg',
    'VAR12': 'VDRL',
    'VAR13': 'HBeAb',
    'VAR14': 'IgE',
    'VAR15': 'AST (GOT)',
    'VAR16': 'HAV-IgG',
    'VAR17': 'ALT (GPT)',
    'VAR18': 'Anti-HCV',
    'VAR19': 'T3',
    'VAR20': 'GGT (r-GT)',
    'VAR21': 'TIBC',
    'VAR22': 'T4',
    'VAR23': 'ALK-P (鹼性磷酸酶)',
    'VAR24': 'Fe (鐵)',
    'VAR25': 'TSH',
    'VAR26': 'Bil-T (總膽紅素)',
    'VAR27': 'Bil-D (直接膽紅素)',
    'VAR28': 'AFP',
    'VAR29': 'T-Protein (總蛋白)',
    'VAR30': 'CEA',
    'VAR31': 'Albumin',
    'VAR32': 'BUN',
    'VAR33': 'PSA',
    'VAR34': 'Globulin (球蛋白)',
    'VAR35': 'Cr (Creatinine, 血)',
    'VAR36': 'CA-125',
    'VAR37': 'A/G ratio',
    'VAR38': 'UA (尿酸)',
    'VAR39': 'CA-199',
    'VAR40': 'eGFR',
    'VAR41': '__notes__',
    'VAR42': 'T-Chol (總膽固醇)',
    'VAR43': 'eAG',
    'VAR44': 'TG (三酸甘油脂)',
    'VAR45': 'TC/HDL ratio',
    'VAR46': 'HDL',
    'VAR47': 'Colon',
    'VAR48': 'LDL',
    'VAR49': 'Microalbumin (微白蛋白)',
}

NEW_BIO_LABELS: dict[str, str] = {
    'VAR4':  'Glucose (AC)',
    'VAR10': 'HbA1c',
    'VAR20': 'GGT (r-GT)',
    'VAR35': 'Cr (Creatinine, 血)',
    'VAR40': 'LDL',
    'VAR42': 'T-Chol (總膽固醇)',
    'VAR43': 'LDL',
    'VAR44': 'TG (三酸甘油脂)',
    'VAR45': 'TC/HDL ratio',
    'VAR46': 'HDL',
    'VAR48': 'eAG',
}

CBC_LABELS: dict[str, str] = {
    'VAR4':  'RBC (×10⁴)',
    'VAR5':  'Hb (g/dL)',
    'VAR6':  'Hct (%)',
    'VAR7':  'MCV (fL)',
    'VAR8':  'MCH (pg)',
    'VAR9':  'MCHC (g/dL)',
    'VAR12': 'WBC (×10³)',
    'VAR14': 'Band',
    'VAR15': 'Eos',
    'VAR16': 'Basophils',
    'VAR17': 'LY% (淋巴)',
    'VAR18': 'Monocytes',
    'VAR24': 'Platelet (×10³)',
}

DATE_VARS = {'VAR1', 'VAR2', 'VAR3'}


def _bio_labels_for(raw_date: str) -> dict[str, str]:
    return NEW_BIO_LABELS if raw_date.strip() >= _NEW_PLATFORM_DATE else OLD_BIO_LABELS


def _bio_display_date(row: dict) -> str:
    """VAR1/2/3 hold the actual lab/order date on both platforms; DATE is system entry date."""
    return _parse_var_date(row) or _decode_date(row.get('DATE', '')) or '???'


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
                        val = chunk.decode('cp950', errors='replace').strip()
                    except Exception:
                        val = chunk.decode('latin-1', errors='replace').strip()
                    val = unicodedata.normalize('NFKC', val)
                    if val and '\x00' not in val:
                        row[name] = val
                yield row
    except Exception:
        return


_dbf_rows_cache: dict[str, tuple[float, list[dict]]] = {}  # path -> (cached_at, rows)
_CACHE_TTL_SECONDS = 30  # covers one report's full MSPT scan; short enough that
                          # same-day lab updates show up on the next request


def _cached_rows(path: str) -> list[dict]:
    """Parse a DBF file and cache the rows briefly. has_recent_metabolic_panel()
    calls into this once per 追2/追3 MSPT entry (hundreds per report) — without
    this, that's hundreds of full-file rescans of bioc.dbf per request."""
    now = time.time()
    cached = _dbf_rows_cache.get(path)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]
    rows = list(_iter_rows(path))
    _dbf_rows_cache[path] = (now, rows)
    return rows


def _parse_var_date(row: dict) -> str:
    """Parse VAR1/VAR2/VAR3 (actual lab/order date) into YYY/MM/DD.

    Old-platform nurses entered 2-digit years (e.g. 14 for ROC 114).
    New platform stores full 3-digit years (e.g. 115).
    Year resolution uses _decode_date so it handles all DATE formats (alpha, 7-digit).
    """
    try:
        y_raw = int(row.get('VAR1', '').strip())
        m    = int(row.get('VAR2', '').strip())
        d    = int(row.get('VAR3', '').strip())
    except (ValueError, AttributeError):
        return ''
    if y_raw <= 0 or not (1 <= m <= 12) or not (1 <= d <= 31):
        return ''

    if y_raw >= 100:
        return f"{y_raw:03d}/{m:02d}/{d:02d}"

    # 2-digit year: decode the system DATE field (handles alpha + 7-digit formats)
    decoded = _decode_date(row.get('DATE', ''))
    if decoded and '/' in decoded:
        entry_year = int(decoded.split('/')[0])
        for candidate in (entry_year, entry_year - 1):
            if candidate % 100 == y_raw:
                return f"{candidate:03d}/{m:02d}/{d:02d}"

    return ''


def _decode_date(raw: str) -> str:
    """Convert raw date to YYY/MM/DD (year always 3 digits so string sort works correctly)."""
    raw = raw.strip()
    if len(raw) == 6 and raw[0].isalpha():
        base = (ord(raw[0].upper()) - ord('A') + 10) * 10
        digit = int(raw[1]) if raw[1].isdigit() else 0
        return f"{base + digit:03d}/{raw[2:4]}/{raw[4:]}"
    if len(raw) == 7:
        return f"{raw[:3]}/{raw[3:5]}/{raw[5:]}"
    if len(raw) == 6:
        return f"{int(raw[:2]):03d}/{raw[2:4]}/{raw[4:]}"
    return raw


def _parse_new_platform_notes(text: str) -> list[dict]:
    """Parse VAR41 structured text from new platform into individual items.
    Input:  'Cr(u):243.79 CKD:0期 eGFR(CKD-EPI):127.37 Upcr:57.4 Urine pro:14'
    Output: [{'label': 'Cr(u)', 'value': '243.79', 'flag': ''}, ...]
    """
    items = []
    for key, val in re.findall(r'([^:]+?):\s*(\S+)', text):
        key = key.strip()
        if key:
            v, flag = _parse_flag(val)
            items.append({'label': key, 'value': v, 'flag': flag})
    return items


def _parse_flag(val: str) -> tuple[str, str]:
    """Split '7.1+' → ('7.1', '+'), '65.1-' → ('65.1', '-'), '92' → ('92', '')."""
    v = val.strip()
    if v and v[-1] in ('+', '-') and len(v) > 1:
        return v[:-1], v[-1]
    return v, ''


# ── Patient code lookup ───────────────────────────────────────────────────────

_patient_code_cache: dict[str, str] = {}  # national_id → 6-digit patient code


def _find_patient_code(national_id: str) -> str | None:
    if national_id in _patient_code_cache:
        return _patient_code_cache[national_id]
    code = _lookup_patient_code(national_id)
    # Cache the negative result too — without this, every miss (e.g. Z: drive
    # unavailable, or a nat_id genuinely not in PAT_HIST/IC) re-runs the full
    # lookup every single call. Harmless when this was only called once per
    # manual lab-modal click, but has_recent_metabolic_panel() now calls it
    # for every 追2/追3 MSPT entry in the report — hundreds of times.
    _patient_code_cache[national_id] = code
    return code


def _lookup_patient_code(national_id: str) -> str | None:
    # Stage 1: PAT_HIST.DBF (change-log; fast but incomplete)
    pat_hist = os.path.join(ZZ_DIR, 'PAT_HIST.DBF')
    if os.path.isfile(pat_hist):
        best_code, best_date = None, ''
        for row in _iter_rows(pat_hist):
            if (row.get('ID_NEW', '').strip() == national_id or
                    row.get('ID_OLD', '').strip() == national_id):
                d = row.get('DATE', '').strip()
                if d >= best_date:
                    best_date = d
                    best_code = row.get('CODE', '').strip()
        if best_code:
            return best_code

    # Stage 2: IC visit files — CODE_F[:6] is the 6-digit patient code
    if os.path.isdir(IC_DIR):
        ic_files = sorted(
            (p for p in _glob.glob(os.path.join(IC_DIR, 'IC?????.DBF'))
             if os.path.basename(p)[2:-4].isdigit()),
            reverse=True,  # most-recent first so active patients found quickly
        )
        for ic_path in ic_files:
            for row in _iter_rows(ic_path):
                if row.get('ID', '').strip() == national_id:
                    cf = row.get('CODE_F', '').strip()
                    if len(cf) >= 6 and cf[:6].isdigit():
                        return cf[:6]
    return None


# ── BIO record reader ─────────────────────────────────────────────────────────

def _read_bio_records(patient_code: str, dbf_name: str) -> list[dict]:
    path = os.path.join(ZZ_DIR, dbf_name)
    if not os.path.isfile(path):
        return []
    raw_rows = [r for r in _cached_rows(path) if r.get('CODE', '').strip() == patient_code]
    raw_rows.sort(key=_bio_display_date, reverse=True)

    records = []
    for row in raw_rows:
        labels = _bio_labels_for(row.get('DATE', ''))
        is_new = labels is NEW_BIO_LABELS
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

        if is_new:
            var41 = row.get('VAR41', '').strip()
            if var41:
                items.extend(_parse_new_platform_notes(var41))

        # Show unknown VAR fields as-is (without a label); always skip VAR41
        labeled = set(labels.keys()) | DATE_VARS | {'CODE', 'DATE', 'VAR41'}
        for k, val in row.items():
            if k in labeled or not val:
                continue
            v, flag = _parse_flag(val)
            items.append({'label': k, 'value': v, 'flag': flag})

        if items or notes:
            records.append({
                'date': _bio_display_date(row),
                'items': items,
                'notes': notes,
            })
    return records


def _read_cbc_records(patient_code: str) -> list[dict]:
    path = os.path.join(ZZ_DIR, 'CBCC.DBF')
    if not os.path.isfile(path):
        return []
    raw_rows = [r for r in _cached_rows(path) if r.get('CODE', '').strip() == patient_code]
    raw_rows.sort(key=lambda r: _decode_date(r.get('DATE', '')), reverse=True)

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


def _parse_slash_date(s: str) -> date | None:
    """Parse 'YYY/MM/DD' (3-digit ROC year, as returned by _bio_display_date) into a date."""
    try:
        y, m, d = s.split('/')
        return date(int(y) + 1911, int(m), int(d))
    except (ValueError, AttributeError, TypeError):
        return None


def has_recent_metabolic_panel(national_id: str, as_of: date, window_days: int = 70) -> bool:
    """Return True if this patient has a BIO record within window_days before
    as_of that includes at least one MSPT metabolic-panel marker
    (MSPT_PANEL_LABELS) — used to decide whether a 追2/追3 MSPT stage still
    needs a fresh blood draw or already has one recent enough to use.
    """
    try:
        patient_code = _find_patient_code(national_id.strip().upper())
        if not patient_code:
            return False
        cutoff = as_of - timedelta(days=window_days)
        for dbf_name in ('bioc.dbf', 'BIO2C.DBF'):
            for record in _read_bio_records(patient_code, dbf_name):
                row_date = _parse_slash_date(record['date'])
                if not row_date or row_date < cutoff or row_date > as_of:
                    continue
                if any(item['label'] in MSPT_PANEL_LABELS for item in record['items']):
                    return True
        return False
    except Exception:
        return False
