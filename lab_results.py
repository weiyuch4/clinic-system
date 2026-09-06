"""
Lab results reader for the web API.

Reads blood test results from:
  - ZZ_DIR/bioc.dbf      (各項檢驗 BIO)
  - ZZ_DIR/CBCC.DBF      (CBC 血球計數)
  - ZZ_DIR/PAT_HIST.DBF  (national ID → 6-digit patient code, change-log only)
  - IC_DIR/IC?????.DBF   (IC visit files — fallback for patients not in PAT_HIST)

ZZ_DIR and IC_DIR are set in config.py and overridden per-machine in config_local.py
(on PC1 these were Z:\\ network drive paths; on the doctor's PC they are local paths).

Returns structured JSON-ready dicts for the frontend modal.
"""

import glob as _glob
import json
import os
import re
import struct
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import config

ZZ_DIR = config.ZZ_DIR
IC_DIR = config.IC_DIR_LAB

# Labels (from OLD_BIO_LABELS/NEW_BIO_LABELS below) considered part of the
# MSPT (代謝症候群) metabolic panel — used to decide whether a recent blood
# draw already covers the 追2/追3 blood-test requirement.
# PROVISIONAL list — to be replaced with the precise marker list.
MSPT_PANEL_LABELS = {
    'Glucose (AC)', 'HbA1c', 'T-Chol (總膽固醇)', 'TG (三酸甘油脂)', 'HDL', 'LDL',
}

# New platform started 2026-04-01 (ROC 115/04/01 = raw DATE 'B50401').
# Old and new platforms store different tests in the same VAR columns.
_NEW_PLATFORM_DATE = 'B50317'  # actual first date in EXAMPLAT.DBF (March 17, 2026)

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
# 5-minute TTL so lab results added during the day are visible within one poll cycle.
# The delta disk cache makes re-checks cheap (4-byte header read + new records only).
_CACHE_TTL_SECONDS = 5 * 60

# Disk cache for BIO DBF rows.  Keyed by total record count (not mtime) so that
# appending new lab results only requires reading the new records, not the whole file.
_BIO_DISK_CACHE_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / "clinic-bio-cache"
_bio_disk_write_lock = __import__('threading').Lock()  # prevents concurrent .tmp corruption


def _read_dbf_header(f) -> tuple[int, int, int, list]:
    """Read DBF header from an open binary file.
    Returns (record_count, header_size, record_size, fields).
    fields = list of (name, byte_offset_within_record, length).
    """
    f.seek(0)
    hdr = f.read(32)
    if len(hdr) < 32 or hdr[0] not in (0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x83, 0xF5):
        return 0, 0, 0, []
    record_count = struct.unpack_from('<I', hdr, 4)[0]
    header_size  = struct.unpack_from('<H', hdr, 8)[0]
    record_size  = struct.unpack_from('<H', hdr, 10)[0]
    fields: list = []
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
    return record_count, header_size, record_size, fields


def _parse_dbf_records(f, header_size: int, record_size: int, fields: list,
                        start: int = 0) -> list[dict]:
    """Parse records from an open DBF file starting at record index `start`."""
    rows: list[dict] = []
    f.seek(header_size + start * record_size)
    while True:
        raw = f.read(record_size)
        if not raw or len(raw) < record_size:
            break
        if raw[0] == 0x2A:   # deleted record marker
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
        if row:  # skip fully-empty records to avoid bloating the disk cache
            rows.append(row)
    return rows


def _cached_rows(path: str) -> list[dict]:
    """Parse a BIO DBF file with two-level caching: in-memory + disk.

    Disk cache is keyed by the file's *total record count* (4 bytes from the
    DBF header) rather than mtime.  Because the lab system only ever appends
    records, a changed mtime means new rows were added — we read just those new
    rows and merge them with the cached ones.  The first cold read of a large
    file is still slow, but every subsequent restart only reads the delta
    (typically a few dozen records per day).
    """
    now = time.time()
    cached = _dbf_rows_cache.get(path)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    stem = Path(path).stem.lower()
    cache_file = _BIO_DISK_CACHE_DIR / f"{stem}.json"

    # Load whatever we already have on disk.
    disk_count: int = 0
    rows: list[dict] = []
    try:
        disk_data = json.loads(cache_file.read_text(encoding='utf-8'))
        disk_count = int(disk_data.get('record_count', 0))
        rows = disk_data.get('records', [])
    except Exception:
        pass

    wrote_cache = False
    try:
        with open(path, 'rb') as f:
            file_count, header_size, record_size, fields = _read_dbf_header(f)
            if not fields:
                pass                          # unreadable header — keep whatever we have
            elif file_count == 0 and disk_count > 0:
                # file_count=0 while disk_count>0 is almost always the lab software
                # mid-write (it zeroes the header before flushing).  Keep stale data;
                # the next poll (5 min later) will see the correct count.
                pass
            elif file_count < disk_count:
                # File was rebuilt from scratch with fewer records — full re-read.
                rows = _parse_dbf_records(f, header_size, record_size, fields)
                disk_count = file_count
                wrote_cache = True
            elif file_count == disk_count:
                pass                          # no new records
            else:
                # Append-only delta: seek past already-cached records.
                new_rows = _parse_dbf_records(f, header_size, record_size, fields,
                                              start=disk_count)
                rows = rows + new_rows
                disk_count = file_count
                wrote_cache = True
    except Exception:
        pass

    if wrote_cache or (rows and disk_count and not cache_file.exists()):
        with _bio_disk_write_lock:
            try:
                _BIO_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                tmp = str(cache_file) + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({'record_count': disk_count, 'records': rows},
                              f, ensure_ascii=False)
                os.replace(tmp, str(cache_file))
                # Remove old mtime-keyed files left over from the previous cache format.
                for old in _BIO_DISK_CACHE_DIR.glob(f"{stem}_*.json"):
                    try:
                        old.unlink()
                    except Exception:
                        pass
            except Exception:
                pass

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


# ── EXAMPLAT reader (new lab platform, 2026+) ─────────────────────────────────

def _read_examplat_records(national_id: str) -> list[dict]:
    """Read from EXAMPLAT.DBF — the newer lab platform that replaced bioc.dbf
    from around April 2026.  Schema: one row per test item (not per visit), so
    we group by date to produce the same {date, items, notes} shape as
    _read_bio_records().

    EXAMPLAT uses a completely different patient-code scheme from bioc.dbf
    (e.g. '022585' vs the zero-padded '000039'), so we look up by ID_NO
    (national ID) rather than PAT_CODE.

    Key fields used:
      ID_NO     — national ID (matches the national_id we receive)
      M_DATE    — 7-char ROC date, e.g. '1150603' → 115/06/03
      E_NAME    — Chinese test name  (中文名稱)
      E_RESULT  — result value
      E_JDG     — H/HH (high) / L/LL (low) / N (normal)
    """
    from collections import defaultdict
    path = os.path.join(ZZ_DIR, 'EXAMPLAT.DBF')
    if not os.path.isfile(path):
        return []

    matching = [r for r in _cached_rows(path) if r.get('ID_NO', '').strip() == national_id]
    if not matching:
        return []

    groups: dict[str, list] = defaultdict(list)
    for row in matching:
        date_raw = row.get('M_DATE', '').strip() or row.get('E_DATE', '').strip()
        date_display = _decode_date(date_raw) if date_raw else '???'

        name = row.get('E_NAME', '').strip() or row.get('E_NAME_EN', '').strip()
        value = row.get('E_RESULT', '').strip()
        if not name or not value:
            continue

        jdg = row.get('E_JDG', '').strip().upper()
        flag = '+' if jdg.startswith('H') else '-' if jdg.startswith('L') else ''

        groups[date_display].append({'label': name, 'value': value, 'flag': flag})

    return [
        {'date': d, 'items': groups[d], 'notes': ''}
        for d in sorted(groups.keys(), reverse=True)
        if groups[d]
    ]


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
        bio2c = _read_bio_records(patient_code, 'BIO2C.DBF')
        existing_dates = {r['date'] for r in bio}
        for r in bio2c:
            if r['date'] not in existing_dates:
                bio.append(r)

        # EXAMPLAT.DBF is the new lab platform (active from ~April 2026).
        # If a date already exists in bioc.dbf we prefer the EXAMPLAT version
        # (per-item, structured) and drop the old bioc entry for that date.
        examplat = _read_examplat_records(national_id)
        if examplat:
            examplat_dates = {r['date'] for r in examplat}
            bio = [r for r in bio if r['date'] not in examplat_dates] + examplat

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


def has_results_since(national_id: str, since: date) -> tuple[bool, str | None]:
    """Check whether any lab result for this patient was uploaded on or after `since`.
    Checks EXAMPLAT.DBF first (new platform, direct ID_NO lookup), then falls back
    to bioc.dbf / CBCC.DBF (old platform, requires patient-code lookup).
    Returns (found, display_date_string) — display_date is the earliest matching result date."""
    since_display = f"{since.year - 1911:03d}/{since.month:02d}/{since.day:02d}"

    # 1. EXAMPLAT (new platform) — M_DATE is a 7-digit ROC string
    examplat_path = os.path.join(ZZ_DIR, 'EXAMPLAT.DBF')
    if os.path.isfile(examplat_path):
        earliest: str | None = None
        for row in _cached_rows(examplat_path):
            if row.get('ID_NO', '').strip() != national_id:
                continue
            m_raw = (row.get('M_DATE', '') or row.get('E_DATE', '')).strip()
            m_display = _decode_date(m_raw) if m_raw else ''
            if m_display and m_display >= since_display:
                if earliest is None or m_display < earliest:
                    earliest = m_display
        if earliest:
            return True, earliest

    # 2. bioc.dbf / BIO2C.DBF / CBCC.DBF (old platform)
    patient_code = _find_patient_code(national_id)
    if patient_code:
        for dbf_name in ('bioc.dbf', 'BIO2C.DBF'):
            path = os.path.join(ZZ_DIR, dbf_name)
            if not os.path.isfile(path):
                continue
            for row in _cached_rows(path):
                if row.get('CODE', '').strip() != patient_code:
                    continue
                d = _bio_display_date(row)
                if d and d >= since_display:
                    return True, d
        cbc_path = os.path.join(ZZ_DIR, 'CBCC.DBF')
        if os.path.isfile(cbc_path):
            for row in _cached_rows(cbc_path):
                if row.get('CODE', '').strip() != patient_code:
                    continue
                d = _decode_date(row.get('DATE', ''))
                if d and d >= since_display:
                    return True, d

    return False, None


def has_recent_metabolic_panel(national_id: str, as_of: date, window_days: int = 70) -> bool:
    """Return True if this patient has a BIO record within window_days before
    as_of that includes at least one MSPT metabolic-panel marker
    (MSPT_PANEL_LABELS) — used to decide whether a 追2/追3 MSPT stage still
    needs a fresh blood draw or already has one recent enough to use.
    """
    return get_most_recent_metabolic_panel_date(national_id, as_of, window_days) is not None


def get_most_recent_metabolic_panel_date(
    national_id: str,
    as_of: date,
    window_days: int = 90,
    exclude_iso_dates: set[str] | None = None,
) -> str | None:
    """Return ISO date string of the most recent qualifying BIO metabolic-panel
    result within window_days before as_of, excluding dates in exclude_iso_dates.
    Returns None if no qualifying result is found.
    """
    try:
        patient_code = _find_patient_code(national_id.strip().upper())
        if not patient_code:
            return None
        cutoff = as_of - timedelta(days=window_days)
        exclude = exclude_iso_dates or set()
        best: date | None = None
        for dbf_name in ('bioc.dbf', 'BIO2C.DBF'):
            for record in _read_bio_records(patient_code, dbf_name):
                row_date = _parse_slash_date(record['date'])
                if not row_date or row_date < cutoff or row_date > as_of:
                    continue
                if row_date.isoformat() in exclude:
                    continue
                if any(item['label'] in MSPT_PANEL_LABELS for item in record['items']):
                    if best is None or row_date > best:
                        best = row_date
        return best.isoformat() if best else None
    except Exception:
        return None
