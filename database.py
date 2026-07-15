from datetime import date, timedelta
import glob
import gzip
import os
import pickle
import struct

import lab_results
from config import IC_DATA_PATH, METABOLIC_FOLLOWUP_DAYS, PATDB_PATH, QUEUE_PATH, USE_MOCK_DATA
from models import (
    DailyReport,
    FollowupEntry,
    MsptSubmittableEntry,
    MsptWaitingEntry,
    Patient,
)

# ── Constants ─────────────────────────────────────────────────────────────────

CHRONIC_GRACE_DAYS       = 5    # days after due before a 慢簽 patient surfaces
MAX_CHRONIC_OVERDUE_DAYS = 60   # days after which a 慢簽 patient drops off the list
MSPT_REOPEN_DAYS         = 365  # overdue beyond this → restart from 收案

# NHI procedure codes for 代謝症候群 tracking (DRUG_NO field in P files).
_MSPT_CODE_MAP: dict[str, str] = {
    'P7501C':  '收案',
    'P7502C':  '追1',
    'P75022C': '追2',
    'P75023C': '追3',
    'P7503C':  '年度追蹤',
}

MSPT_STAGE_NEXT: dict[str, str] = {
    '收案': '追1', '追1': '追2', '追2': '追3', '追3': '年度追蹤', '年度追蹤': '追1',
}

# All MSPT stages use the same inter-stage gap.
_MSPT_STAGE_GAP = METABOLIC_FOLLOWUP_DAYS

# Window for treating an existing blood draw as still covering a 追2/追3 stage.
MSPT_BLOOD_TEST_WINDOW_DAYS = METABOLIC_FOLLOWUP_DAYS


def mspt_needs_blood_test(mspt_stage: str, nat_id: str, as_of: date) -> bool:
    """Whether this MSPT stage needs a fresh blood draw.

    收案/年度追蹤 always do; 追1 never does; 追2/追3 only need one if no recent
    (within MSPT_BLOOD_TEST_WINDOW_DAYS) metabolic-panel result already covers
    it — a patient can have blood drawn at 追2 time and have it count for 追3,
    or vice versa, so only one of the two actually needs a fresh draw.
    """
    if mspt_stage in ('收案', '年度追蹤'):
        return True
    if mspt_stage == '追1':
        return False
    if mspt_stage in ('追2', '追3'):
        return not lab_results.has_recent_metabolic_panel(nat_id, as_of, MSPT_BLOOD_TEST_WINDOW_DAYS)
    return False

# ── DBF cache ─────────────────────────────────────────────────────────────────

# IC files are historical — once a month ends the file never changes — so caching is safe.
# The current month's file is always re-read to pick up intra-month updates.
_dbf_cache: dict[str, list[dict]] = {}

_DISK_CACHE_PATH = "dbf_cache.pkl.gz"
_DISK_CACHE_MAX_AGE_DAYS = 7  # force a full rebuild once the last one is this old


def _current_roc_month() -> str:
    d = date.today()
    return f"{d.year - 1911:03d}{d.month:02d}"


def _parse_dbf_cached(path: str) -> list[dict]:
    if _current_roc_month() in os.path.basename(path).upper():
        return _parse_dbf(path)
    if path not in _dbf_cache:
        _dbf_cache[path] = _parse_dbf(path)
    return _dbf_cache[path]


def _load_disk_cache() -> dict | None:
    """Load the persisted {'built_at', 'data'} blob if the file is readable.
    Returns None on any failure (missing or corrupt) — treated the same as
    "no cache yet" by warmup_cache()."""
    try:
        with gzip.open(_DISK_CACHE_PATH, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_disk_cache(built_at: str) -> None:
    """Persist the current _dbf_cache under the given built_at date. Callers
    pass either today's date (a full rebuild just happened) or the previous
    built_at (just filling gaps) — see warmup_cache(). Written to a temp
    file + os.replace so a crash mid-write can't leave a corrupt cache file."""
    tmp = _DISK_CACHE_PATH + '.tmp'
    try:
        with gzip.open(tmp, 'wb') as f:
            pickle.dump({'built_at': built_at, 'data': _dbf_cache}, f)
        os.replace(tmp, _DISK_CACHE_PATH)
    except Exception:
        pass


def warmup_cache() -> None:
    """Pre-load all IC (and P and H) files into the cache, then run today's
    report once so dependent caches (lab_results' patient-code lookups and
    BIO/CBC file reads, used by MSPT blood-test checks) are warm too. Call in
    a background thread at server startup so the first real user request
    doesn't pay the full parse cost.

    Closed months are persisted to disk so a restart doesn't re-pay the full
    parse cost — PC1 restarts unpredictably, possibly several times a day,
    so staleness is judged by elapsed time since the last deliberate full
    rebuild (built_at), not by restart count: built_at is only advanced when
    a rebuild actually happens, so a restart 5 minutes after the last one is
    just as fast as one a week later is slow, regardless of how many
    restarts happened in between."""
    saved = _load_disk_cache()
    is_stale = (
        saved is None
        or (date.today() - date.fromisoformat(saved['built_at'])).days >= _DISK_CACHE_MAX_AGE_DAYS
    )
    if is_stale:
        _dbf_cache.clear()
        built_at = date.today().isoformat()
    else:
        _dbf_cache.update(saved['data'])
        built_at = saved['built_at']

    for path in _ic_main_files():
        try:
            _parse_dbf_cached(path)
            p = path[:-4] + 'P.DBF'
            if os.path.exists(p):
                _parse_dbf_cached(p)
            h = _h_file_path(path)
            if os.path.exists(h):
                _parse_dbf_cached(h)
        except Exception:
            pass

    _save_disk_cache(built_at)  # always — persists gap-fills even on a non-stale restart
    try:
        get_daily_report(date.today())
    except Exception:
        pass
    # Pre-warm PATDB phone index and VFP6_P mobile index so the first user
    # request doesn't block on the 39K-record PATDB read + 180K-record VFP6_P scan.
    try:
        _load_patdb()
        _get_patdb_phone_index()
    except Exception:
        pass
    try:
        _get_vfp6p_mobile_index()
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def get_daily_report(as_of: date) -> DailyReport:
    if USE_MOCK_DATA:
        return _mock_report(as_of)
    mspt_followups, mspt_inactive = _query_mspt_followups(as_of)
    # Computed once and shared — _query_hep_followups and _query_hep_returned both
    # need it, and it alone accounts for most of a cold report's runtime (it parses
    # every IC file in the clinic's history looking for hep visits).
    hep_patient_info = _scan_hep_patient_info(as_of)
    hep_followups, hep_inactive = _query_hep_followups(as_of, hep_patient_info)
    return DailyReport(
        report_date=as_of,
        chronic_prescriptions=_query_chronic_prescriptions(as_of),
        mspt_followups=mspt_followups,
        mspt_inactive=mspt_inactive,
        mspt_submittable=[],
        mspt_waiting=[],
        hep_followups=hep_followups,
        hep_inactive=hep_inactive,
        hep_returned=_query_hep_returned(as_of, hep_patient_info),
    )


# ── DBF utilities ─────────────────────────────────────────────────────────────

def _parse_dbf(path: str) -> list[dict]:
    with open(path, 'rb') as f:
        hdr = f.read(32)
        num_records = struct.unpack_from('<I', hdr, 4)[0]
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
            fields.append((name, flen))

        f.seek(header_size)
        records = []
        for _ in range(num_records):
            raw = f.read(record_size)
            if not raw or raw[0] == 0x2A:  # 0x2A = deleted record marker
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
    return records


def _roc_to_date(s: str) -> date | None:
    """Convert 7-char ROC date string YYYMMDD to a Python date."""
    s = s.strip()
    if len(s) != 7 or not s.isdigit():
        return None
    try:
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None


def _ic_main_files() -> list[str]:
    """All IC?????.DBF files (main visit files, excluding P/H/X variants), sorted."""
    result = []
    for path in glob.glob(os.path.join(IC_DATA_PATH, 'IC?????.DBF')):
        stem = os.path.basename(path)[2:-4]  # '11504' from 'IC11504.DBF'
        if len(stem) == 5 and stem.isdigit():
            result.append(path)
    return sorted(result)


def _ic_files_since(since: date) -> list[str]:
    """IC main files whose month is >= the month of `since`."""
    result = []
    for path in _ic_main_files():
        stem = os.path.basename(path)[2:-4]
        try:
            month_start = date(int(stem[:3]) + 1911, int(stem[3:]), 1)
            if month_start >= date(since.year, since.month, 1):
                result.append(path)
        except ValueError:
            pass
    return result


def _h_file_path(ic_path: str) -> str:
    """Return the H-file path (IC?????H.DBF) for a given main IC file."""
    base = os.path.basename(ic_path)   # e.g. 'IC11504.DBF'
    stem = base[2:-4]                  # '11504'
    return os.path.join(os.path.dirname(ic_path), f"IC{stem}H.DBF")


def _load_h_lookup(ic_path: str) -> dict[str, tuple[str, str]]:
    """Load the H file for an IC main file and return {code_f: (m33, m26)}.

    M33 and M26 exist only in H files (IC?????H.DBF), not in the main IC files.
    M33: '1'=IC01, '2'=IC02, '3'=IC03.  M26: '3'=3-cycle 連續處方箋 series.
    """
    h_path = _h_file_path(ic_path)
    if not os.path.exists(h_path):
        return {}
    try:
        result: dict[str, tuple[str, str]] = {}
        for r in _parse_dbf_cached(h_path):
            cf = r.get('CODE_F', '').strip()
            if cf:
                result[cf] = (r.get('M33', '').strip(), r.get('M26', '').strip())
        return result
    except Exception:
        return {}


# ── ICD code → Chinese disease name ──────────────────────────────────────────

# Ordered list of (prefix, name); first match wins.
_ICD_MAP: list[tuple[str, str]] = [
    ('I10', '高血壓'), ('I11', '高血壓'), ('I12', '高血壓'), ('I13', '高血壓'),
    ('E10', '第一型糖尿病'), ('E11', '第二型糖尿病'), ('E13', '糖尿病'), ('E14', '糖尿病'),
    ('E78', '高血脂'),
    ('M80', '骨質疏鬆'), ('M81', '骨質疏鬆'),
    ('N18', '慢性腎臟病'),
    ('I50', '心臟衰竭'),
    ('E00', '甲狀腺功能低下'), ('E01', '甲狀腺功能低下'),
    ('E02', '甲狀腺功能低下'), ('E03', '甲狀腺功能低下'),
    ('M10', '痛風'), ('M1A', '痛風'),
    ('J45', '氣喘'),
    ('I25', '冠狀動脈疾病'), ('I20', '心絞痛'),
    ('J44', '慢性阻塞性肺病'),
    ('K74', '肝硬化'),
    # ICD-9 (pre-2016 records)
    ('401', '高血壓'), ('402', '高血壓'), ('403', '高血壓'),
    ('250', '糖尿病'),
    ('272', '高血脂'),
    ('733', '骨質疏鬆'),
    ('585', '慢性腎臟病'),
    ('428', '心臟衰竭'),
    ('244', '甲狀腺功能低下'),
    ('274', '痛風'),
    ('493', '氣喘'),
    ('414', '冠狀動脈疾病'), ('413', '心絞痛'),
]


def _icd_to_name(icd: str) -> str | None:
    icd = icd.strip().upper().replace('.', '')
    for prefix, name in _ICD_MAP:
        if icd.startswith(prefix.upper()):
            return name
    return None


# ── Chronic prescription (慢簽) query ─────────────────────────────────────────

def _p_file_has_long1(p_path: str, cf: str) -> bool:
    """Return True if the P file has any record for cf with LONG='1'."""
    if not cf or not os.path.exists(p_path):
        return False
    try:
        for r in _parse_dbf_cached(p_path):
            if r.get('CODE_F', '').strip() == cf and r.get('LONG', '').strip() == '1':
                return True
    except Exception:
        pass
    return False


def _query_chronic_prescriptions(as_of: date) -> list[FollowupEntry]:
    """Return patients whose last 慢簽 visit + prescription days is past as_of.

    Covers AE連續 (IC02/IC03 refills) and 01西醫 IC01 first prescriptions.
    IC01 is identified by M33='1' AND M26='3' in the main IC file plus LONG='1'
    in the P file. M33/M26 are sparsely populated (~1% of records) which is why
    they appeared absent in small samples, but they are real fields in the schema.
    """
    since = as_of - timedelta(days=365)

    ae_best: dict[str, dict]   = {}  # most recent AE連續 (IC02/IC03) per nat_id
    ic01_best: dict[str, dict] = {}  # most recent 01西醫 IC01 per nat_id

    for ic_path in _ic_files_since(since):
        try:
            records = _parse_dbf_cached(ic_path)
        except Exception:
            continue
        p_path = ic_path[:-4] + 'P.DBF'

        for r in records:
            h_type = r.get('H_TYPE', '')

            # M33/M26 are in the main IC file (not the H file).
            m33 = r.get('M33', '').strip()
            m26 = r.get('M26', '').strip()

            # A small number of refills are filed under H_TYPE values other than
            # AE連續 (seen in practice: AB療程, AI同日) but still carry the same
            # NHI 連續處方箋 cycle markers (M26='3', M33='2'/'3' = cycle 2/3 of 3).
            # Trust the markers over H_TYPE for these — only 01西醫 is excluded
            # since that's reserved for the IC01 first-dispense path below.
            is_ae    = h_type == 'AE連續' or (h_type != '01西醫' and m26 == '3' and m33 in ('2', '3'))
            is_nishi = h_type == '01西醫'
            if not is_ae and not is_nishi:
                continue
            v_date = _roc_to_date(r.get('DATE', ''))
            if not v_date or v_date > as_of:
                continue
            nat_id = r.get('ID', '').strip()
            if not nat_id:
                continue
            cf = r.get('CODE_F', '').strip()

            if is_nishi:
                if nat_id in ic01_best and v_date <= ic01_best[nat_id]['date']:
                    continue
                # IC01: M33='1' (first cycle) and M26='3' (3-cycle series).
                if not (m33 == '1' and m26 == '3'):
                    continue
                if not _p_file_has_long1(p_path, cf):
                    continue

            target = ae_best if is_ae else ic01_best

            icd = next(
                (r.get(f, '') for f in ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')
                 if _icd_to_name(r.get(f, ''))),
                '',
            )

            if nat_id not in target or v_date > target[nat_id]['date']:
                entry: dict = {
                    'date':    v_date,
                    'code_fs': [cf] if cf else [],
                    'name':    r.get('NAME', '').strip(),
                    'birth':   _roc_to_date(r.get('BIRTH', '')),
                    'icd':     icd,
                    'ic_path': ic_path,
                }
                if is_ae:
                    entry['m33'] = m33
                target[nat_id] = entry
            elif is_ae and v_date == target[nat_id]['date'] and cf and cf not in target[nat_id]['code_fs']:
                target[nat_id]['code_fs'].append(cf)
                # Keep the highest M33 seen (e.g. IC02 + IC03 same day → m33='3')
                cur_m33 = target[nat_id].get('m33', '')
                if m33.isdigit() and (not cur_m33.isdigit() or int(m33) > int(cur_m33)):
                    target[nat_id]['m33'] = m33

    # Build CODE_F → days-supply map from LONG=1 P-file records.
    by_p_path: dict[str, set[str]] = {}
    for src in (ae_best, ic01_best):
        for v in src.values():
            p_path = v['ic_path'][:-4] + 'P.DBF'
            if os.path.exists(p_path):
                for cf in v['code_fs']:
                    by_p_path.setdefault(p_path, set()).add(cf)

    ps_lookup: dict[str, int] = {}
    for p_path, code_fs in by_p_path.items():
        try:
            for r in _parse_dbf_cached(p_path):
                cf = r.get('CODE_F', '').strip()
                if cf in code_fs and cf not in ps_lookup and r.get('LONG', '').strip() == '1':
                    ps_val = r.get('PS', '').strip()
                    if ps_val.isdigit() and int(ps_val) > 0:
                        ps_lookup[cf] = int(ps_val)
        except Exception:
            pass

    results = []
    for nat_id in set(ae_best) | set(ic01_best):
        ae   = ae_best.get(nat_id)
        ic01 = ic01_best.get(nat_id)

        use_ic01 = ic01 is not None and (ae is None or ic01['date'] > ae['date'])
        v = ic01 if use_ic01 else ae
        if not v or not v['name'] or not v['birth']:
            continue

        if use_ic01:
            ps = next((ps_lookup[cf] for cf in v['code_fs'] if cf in ps_lookup), None)
            if not ps:
                continue  # LONG=1 confirmed during scan but PS absent — skip
            total_ps = ps
        else:
            total_ps = sum(ps_lookup.get(cf, 28) for cf in v['code_fs']) if v['code_fs'] else 28

        due_date     = v['date'] + timedelta(days=total_ps)
        days_overdue = (as_of - due_date).days
        if not (CHRONIC_GRACE_DAYS <= days_overdue <= MAX_CHRONIC_OVERDUE_DAYS):
            continue

        if use_ic01:
            next_stage = 'IC02'
        elif v.get('m33') == '3':
            next_stage = 'IC01'
        else:
            next_stage = 'IC03'

        results.append(FollowupEntry(
            patient=Patient(
                chart_number=nat_id,
                name=v['name'],
                birth_date=v['birth'],
            ),
            disease_name=_icd_to_name(v['icd']) or '慢簽',
            due_date=due_date,
            days_overdue=days_overdue,
            last_visit_date=v['date'],
            category='慢簽',
            chronic_stage=next_stage,
        ))
    return sorted(results, key=lambda e: e.days_overdue, reverse=True)


# ── MSPT (代謝症候群) query ───────────────────────────────────────────────────

def _query_mspt_followups(as_of: date) -> tuple[list[FollowupEntry], list[FollowupEntry]]:
    """Return (active_followups, inactive_patients).

    active_followups: MSPT patients whose next stage is overdue and who still visit the clinic.
    inactive_patients: patients needing 收案 restart but with no clinic visit in the past 6 months
                       — shown in the 長期未回診 section.

    Stage detection uses NHI procedure codes in the P-file DRUG_NO field.
    History is grouped by national ID because CODE_F changes across visits for the same patient.
    The P file has no DATE field, so each CODE_F's IC visit date is used as the stage date.
    """
    MAX_INACTIVE_DAYS  = 2 * 365  # ignore patients whose last MSPT activity is > 2 years old
    REOPEN_AFTER_DAYS  = 365      # > 1 year since last MSPT → case closed, needs 收案 restart
    LONG_INACTIVE_DAYS = 180      # > 6 months since any clinic visit → 長期未回診

    since = as_of - timedelta(days=MAX_INACTIVE_DAYS)

    patient_info: dict[str, dict] = {}         # nat_id → {name, birth, latest_date}
    stage_history: dict[str, list[dict]] = {}  # nat_id → [{stage, date}, ...]

    for ic_path in _ic_files_since(since):
        month_cf_to_id: dict[str, str]  = {}
        month_cf_dates: dict[str, date] = {}

        try:
            for r in _parse_dbf_cached(ic_path):
                v_date = _roc_to_date(r.get('DATE', ''))
                if not v_date or v_date > as_of:
                    continue
                cf     = r.get('CODE_F', '').strip()
                nat_id = r.get('ID', '').strip()
                if not cf or not nat_id:
                    continue

                month_cf_to_id[cf] = nat_id
                month_cf_dates[cf] = v_date

                name  = r.get('NAME', '').strip()
                birth = _roc_to_date(r.get('BIRTH', ''))
                if name and birth:
                    prev = patient_info.get(nat_id)
                    if prev is None or v_date > prev['latest_date']:
                        patient_info[nat_id] = {
                            'name': name, 'birth': birth, 'latest_date': v_date,
                        }
                # Enrollment from AC保健 is NOT used here to avoid false-positives from
                # 成人健檢 visits (same AC保健/KIND=10/FEE=300, ICD=Z0000).
                # 收案 is detected exclusively via P7501C in the P file below.
        except Exception:
            pass

        p_path = ic_path[:-4] + 'P.DBF'
        if not os.path.exists(p_path):
            continue
        try:
            for r in _parse_dbf_cached(p_path):
                cf     = r.get('CODE_F', '').strip()
                nat_id = month_cf_to_id.get(cf)
                if not nat_id:
                    continue
                stage  = _MSPT_CODE_MAP.get(r.get('DRUG_NO', '').strip())
                v_date = month_cf_dates.get(cf)
                if not stage or not v_date or v_date > as_of:
                    continue
                stage_history.setdefault(nat_id, []).append({'stage': stage, 'date': v_date})
        except Exception:
            pass

    results: list[FollowupEntry] = []
    inactive: list[FollowupEntry] = []

    for nat_id, history in stage_history.items():
        info = patient_info.get(nat_id)
        if not info:
            continue

        history.sort(key=lambda x: x['date'])
        last_stage    = history[-1]['stage']
        last_date     = history[-1]['date']
        days_inactive = (as_of - last_date).days

        if days_inactive > MAX_INACTIVE_DAYS:
            continue

        next_stage = MSPT_STAGE_NEXT.get(last_stage)
        if next_stage is None:
            continue

        due_date     = last_date + timedelta(days=_MSPT_STAGE_GAP)
        days_overdue = (as_of - due_date).days
        if days_overdue < 0:
            continue  # next stage not yet due

        entry = FollowupEntry(
            patient=Patient(chart_number=nat_id, name=info['name'], birth_date=info['birth']),
            disease_name='代謝症候群',
            due_date=due_date,
            days_overdue=days_overdue,
            category='代謝症候群',
            last_visit_date=last_date,
            last_stage=last_stage,
        )

        # Case closed: missed by > 1 year → needs 收案 restart.
        # Route to inactive (長期未回診) if no clinic visit in the past 6 months.
        if days_overdue > REOPEN_AFTER_DAYS:
            entry = entry.model_copy(update={
                'mspt_stage': '收案',
                'needs_blood_test': mspt_needs_blood_test('收案', nat_id, as_of),
                'contact_reason': '需重新收案+抽血',
            })
            if (as_of - info['latest_date']).days > LONG_INACTIVE_DAYS:
                inactive.append(entry)
            else:
                results.append(entry)
        else:
            results.append(entry.model_copy(update={
                'mspt_stage': next_stage,
                'needs_blood_test': mspt_needs_blood_test(next_stage, nat_id, as_of),
            }))

    return (
        sorted(results, key=lambda e: e.days_overdue, reverse=True),
        sorted(inactive, key=lambda e: e.last_visit_date or date.min),
    )


# ── B/C Hepatitis (B/C型肝炎) tracking ───────────────────────────────────────

HEP_FOLLOWUP_DAYS    = 161   # 追蹤間隔
HEP_CLOSE_DAYS       = 365   # 超過此天數無追蹤 → 結案
HEP_REOPEN_DAYS      = 365   # 結案後再等此天數 → 可再收案 (total 730 days since last visit)
HEP_RETURN_WINDOW_DAYS = 14  # 回診後此天數內視為「待輸入VPN」(抽血報告約3個工作日)

# NHI order code for the BC肝追蹤6M panel (confirmed against real visit data).
# A visit's hep ICD code alone isn't enough — most hep-coded visits just carry
# the diagnosis forward as a standing comorbidity (e.g. routine diabetes visit
# for a patient who happens to also have hep B/C). Only ~0.45% of hep-ICD-coded
# visits have hep as the PRIMARY diagnosis, so we additionally require this
# panel to actually be ordered that visit before counting it as a real
# B/C型肝炎追蹤 follow-up.
HEP_PANEL_DRUG_NO = 'P4202C'

# ICD-9/ICD-10 codes for B and C hepatitis (dot-stripped, prefix-matched).
_HEP_B_PREFIXES = (
    '07030', '07031', '07032', '07033',   # ICD-9 HBV
    'B16',                                 # ICD-10 acute HBV
    'B181', 'B1900', 'B1910', 'B1911',    # ICD-10 chronic HBV
    'V0261', 'Z2251',                      # ICD-9/10 HBV carrier
)
_HEP_C_PREFIXES = (
    '07041', '07044', '07054',             # ICD-9 HCV
    'B171', 'B172',                        # ICD-10 acute HCV
    'B182', 'B1920', 'B1921',              # ICD-10 chronic HCV
    'V0262', 'Z2252',                      # ICD-9/10 HCV carrier
)
_HEP_ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')


def _hep_type(r: dict) -> str | None:
    """Return 'B', 'C', 'BC', or None based on hepatitis ICD codes in the record."""
    has_b = has_c = False
    for field in _HEP_ICD_FIELDS:
        code = r.get(field, '').strip().upper().replace('.', '')
        if not code:
            continue
        if not has_b and any(code.startswith(p) for p in _HEP_B_PREFIXES):
            has_b = True
        if not has_c and any(code.startswith(p) for p in _HEP_C_PREFIXES):
            has_c = True
        if has_b and has_c:
            break
    if has_b and has_c:
        return 'BC'
    if has_b:
        return 'B'
    if has_c:
        return 'C'
    return None


def _p_file_drug_cfs(p_path: str, drug_no: str) -> set[str]:
    """Return the set of CODE_F values in a P file that have a record with this DRUG_NO.

    Built in a single pass per P file rather than scanning per-visit, since a
    main IC file can carry dozens of hep-ICD-coded visits that all need checking
    against the same (cached) P file.
    """
    if not os.path.exists(p_path):
        return set()
    try:
        return {
            r.get('CODE_F', '').strip()
            for r in _parse_dbf_cached(p_path)
            if r.get('DRUG_NO', '').strip() == drug_no and r.get('CODE_F', '').strip()
        }
    except Exception:
        return set()


def _scan_hep_patient_info(as_of: date) -> dict[str, dict]:
    """Scan ALL IC files for hepatitis-coded visits (01西醫/AE連續 with a hep
    B/C ICD code AND the BC肝追蹤6M panel order, HEP_PANEL_DRUG_NO, actually
    billed that visit) and return {nat_id: {name, birth, last_visit, first_visit, hep_type}}.

    The ICD code alone isn't a reliable signal a hep follow-up actually happened
    (see HEP_PANEL_DRUG_NO comment) — requiring the panel order filters out
    visits where hep is just a carried-forward comorbidity.

    Scans ALL IC files (not a fixed window) because hepatitis patients may not have
    visited for years yet still need 結案/再收案 tracking. Shared by both the
    overdue/inactive query and the recently-returned query below, so both stay
    in sync on what counts as a hep visit.
    """
    patient_info: dict[str, dict] = {}

    for ic_path in _ic_main_files():
        p_path = ic_path[:-4] + 'P.DBF'
        panel_cfs = _p_file_drug_cfs(p_path, HEP_PANEL_DRUG_NO)
        try:
            for r in _parse_dbf_cached(ic_path):
                if r.get('H_TYPE', '') not in ('01西醫', 'AE連續'):
                    continue
                hep = _hep_type(r)
                if not hep:
                    continue
                if r.get('CODE_F', '').strip() not in panel_cfs:
                    continue  # hep ICD present but the panel wasn't actually ordered
                nat_id = r.get('ID', '').strip()
                if not nat_id:
                    continue
                v_date = _roc_to_date(r.get('DATE', ''))
                if not v_date or v_date > as_of:
                    continue
                name  = r.get('NAME', '').strip()
                birth = _roc_to_date(r.get('BIRTH', ''))

                if nat_id not in patient_info:
                    patient_info[nat_id] = {
                        'name':       name or '',
                        'birth':      birth,
                        'last_visit': v_date,
                        'first_visit': v_date,
                        'hep_type':   hep,
                    }
                else:
                    p = patient_info[nat_id]
                    if v_date > p['last_visit']:
                        p['last_visit'] = v_date
                        # Always use the most recent visit's name — handles family members
                        # sharing an IC card (被保險人) and name typo corrections over time.
                        if name:
                            p['name'] = name
                        if birth:
                            p['birth'] = birth
                    if v_date < p['first_visit']:
                        p['first_visit'] = v_date
                    if hep != p['hep_type'] and p['hep_type'] != 'BC':
                        p['hep_type'] = 'BC'
        except Exception:
            pass

    return patient_info


def _hep_disease_name(hep_type: str) -> str:
    return 'B型肝炎' if hep_type == 'B' else ('C型肝炎' if hep_type == 'C' else 'B/C型肝炎')


def _query_hep_followups(as_of: date, patient_info: dict[str, dict]) -> tuple[list[FollowupEntry], list[FollowupEntry]]:
    """Return (active_overdue, inactive) hepatitis B/C patients.

    active_overdue: patients 161–364 days since last hepatitis visit (overdue for 追蹤).
    inactive: patients 365+ days since last hepatitis visit (結案 or eligible for 再收案).

    patient_info comes from _scan_hep_patient_info(as_of) — shared with
    _query_hep_returned() since computing it is the most expensive part of a report.
    """
    results: list[FollowupEntry] = []
    inactive: list[FollowupEntry] = []

    for nat_id, info in patient_info.items():
        if not info['name'] or not info['birth']:
            continue

        last_visit = info['last_visit']
        days_since = (as_of - last_visit).days

        if days_since < HEP_FOLLOWUP_DAYS:
            continue  # not yet overdue

        disease = _hep_disease_name(info['hep_type'])

        due_date     = last_visit + timedelta(days=HEP_FOLLOWUP_DAYS)
        days_overdue = (as_of - due_date).days

        # Determine last_stage label: 收案 if patient has only ever had one hepatitis visit
        stage = '收案' if info['first_visit'] == info['last_visit'] else '追蹤'

        entry = FollowupEntry(
            patient=Patient(chart_number=nat_id, name=info['name'], birth_date=info['birth']),
            disease_name=disease,
            due_date=due_date,
            days_overdue=days_overdue,
            category='B肝',
            last_visit_date=last_visit,
            last_stage=stage,
            contact_reason='需抽血+超音波',
        )

        if days_since >= HEP_CLOSE_DAYS + HEP_REOPEN_DAYS:
            # 730+ days: eligible for 再收案
            inactive.append(entry.model_copy(update={
                'last_stage': '再收案',
                'contact_reason': '需重新收案+抽血+超音波',
            }))
        elif days_since >= HEP_CLOSE_DAYS:
            # 365–729 days: 結案, waiting period before re-enrollment
            inactive.append(entry.model_copy(update={'last_stage': '結案'}))
        else:
            results.append(entry)

    return (
        sorted(results, key=lambda e: e.days_overdue, reverse=True),
        sorted(inactive, key=lambda e: e.last_visit_date or date.min),
    )


def _query_hep_returned(as_of: date, patient_info: dict[str, dict]) -> list[FollowupEntry]:
    """Patients whose most recent hepatitis visit was within HEP_RETURN_WINDOW_DAYS.

    They've returned for B/C型肝炎追蹤 (same hep-ICD visit detection as
    _query_hep_followups) — blood results take ~3 working days, after which a
    VPN entry is still needed. Returns ALL qualifying patients regardless of
    contact history; filtering out ones already marked done (完成B肝) happens
    in main.py, same as other completion-tracking lists (e.g. mspt_completed).

    patient_info comes from _scan_hep_patient_info(as_of) — shared with
    _query_hep_followups() since computing it is the most expensive part of a report.
    """
    results: list[FollowupEntry] = []

    for nat_id, info in patient_info.items():
        if not info['name'] or not info['birth']:
            continue

        last_visit = info['last_visit']
        days_since = (as_of - last_visit).days
        if days_since > HEP_RETURN_WINDOW_DAYS:
            continue

        results.append(FollowupEntry(
            patient=Patient(chart_number=nat_id, name=info['name'], birth_date=info['birth']),
            disease_name=_hep_disease_name(info['hep_type']),
            due_date=last_visit,
            days_overdue=days_since,
            category='B肝',
            last_visit_date=last_visit,
            contact_reason='待輸入VPN',
        ))

    return sorted(results, key=lambda e: e.last_visit_date or date.min)


# ── Visit detection (has patient returned?) ───────────────────────────────────

def get_latest_visit_dates(chart_numbers: set[str], category: str) -> dict[str, date]:
    """Return {chart_number: latest visit date} for the given patients, looking back 30 days.
    Used to detect whether a contacted patient has since returned.

    For 慢簽: matches AE連續 or 01西醫 IC01 (M33='1', M26='3' in main IC file).
    For B肝: matches 01西醫/AE連續 visits that carry an actual hep B/C ICD code
    (same check _query_hep_followups uses) — a B肝 patient coming in for an
    unrelated reason should not count as a hep follow-up return.
    For 代謝症候群: matches any 01西醫 visit."""
    if not chart_numbers:
        return {}
    since  = date.today() - timedelta(days=30)
    result: dict[str, date] = {}

    for ic_path in _ic_files_since(since):
        p_path = ic_path[:-4] + 'P.DBF'
        panel_cfs = _p_file_drug_cfs(p_path, HEP_PANEL_DRUG_NO) if category == 'B肝' else None
        try:
            for r in _parse_dbf_cached(ic_path):
                h = r.get('H_TYPE', '')
                if category == '慢簽':
                    m33 = r.get('M33', '').strip()
                    m26 = r.get('M26', '').strip()
                    # See _query_chronic_prescriptions: some refills are filed under
                    # H_TYPE values other than AE連續 (e.g. AB療程, AI同日) but still
                    # carry the same cycle markers — trust the markers over H_TYPE.
                    is_ae = h == 'AE連續' or (h != '01西醫' and m26 == '3' and m33 in ('2', '3'))
                    if not is_ae:
                        if h != '01西醫':
                            continue
                        if not (m33 == '1' and m26 == '3'):
                            continue
                elif category == 'B肝':
                    if h not in ('01西醫', 'AE連續'):
                        continue
                    if not _hep_type(r):
                        continue
                    # Same panel-order requirement as _scan_hep_patient_info —
                    # the ICD code alone doesn't mean the visit was for hep follow-up.
                    if r.get('CODE_F', '').strip() not in panel_cfs:
                        continue
                else:
                    if h != '01西醫':
                        continue

                key = r.get('ID', '').strip()
                if not key or key not in chart_numbers:
                    continue
                v_date = _roc_to_date(r.get('DATE', ''))
                if v_date and (key not in result or v_date > result[key]):
                    result[key] = v_date
        except Exception:
            pass
    return result


# ── Doctor return-rate analytics ──────────────────────────────────────────────

def get_doctor_return_rates(month: str) -> list[dict]:
    """Compute per-doctor 90-day same-doctor return rates for a Gregorian YYYY-MM month.

    Only 01西醫 visits count — AE連續 (IC02/IC03 prescription pickups) are excluded
    from both the denominator and the return check, since the patient isn't there
    for a consultation with the doctor.

    For each unique (patient, doctor) pair with a 01西醫 visit in the month,
    checks whether the patient returned to the same doctor (01西醫 only) within 90 days.
    """
    year, m = int(month[:4]), int(month[5:])
    roc_month = f"{year - 1911:03d}{m:02d}"
    ic_file = os.path.join(IC_DATA_PATH, f"IC{roc_month}.DBF")
    if not os.path.isfile(ic_file):
        return []

    # (nat_id, doctor) → last 01西醫 consultation date this month
    target: dict[tuple[str, str], date] = {}
    try:
        for row in _parse_dbf(ic_file):
            if row.get('H_TYPE', '').strip() != '01西醫':
                continue
            nat_id = row.get('ID', '').strip()
            doctor = row.get('DOCTOR', '').strip()
            vis = _roc_to_date(row.get('DATE', ''))
            if not nat_id or not doctor or vis is None:
                continue
            key = (nat_id, doctor)
            if key not in target or vis > target[key]:
                target[key] = vis
    except Exception:
        return []

    if not target:
        return []

    # Check next 3 months for a 01西醫 return visit to the same doctor within 90 days
    returned: set[tuple[str, str]] = set()
    for lookahead in range(1, 4):
        next_m = (m - 1 + lookahead) % 12 + 1
        next_y = year + (m - 1 + lookahead) // 12
        roc_next = f"{next_y - 1911:03d}{next_m:02d}"
        next_file = os.path.join(IC_DATA_PATH, f"IC{roc_next}.DBF")
        if not os.path.isfile(next_file):
            continue
        try:
            for row in _parse_dbf(next_file):
                if row.get('H_TYPE', '').strip() != '01西醫':
                    continue
                nat_id = row.get('ID', '').strip()
                doctor = row.get('DOCTOR', '').strip()
                key = (nat_id, doctor)
                if key not in target or key in returned:
                    continue
                ret = _roc_to_date(row.get('DATE', ''))
                if ret is None:
                    continue
                if 0 < (ret - target[key]).days <= 90:
                    returned.add(key)
        except Exception:
            continue

    # Aggregate by doctor
    doctor_stats: dict[str, dict[str, int]] = {}
    for (nat_id, doctor) in target:
        s = doctor_stats.setdefault(doctor, {'total': 0, 'returned': 0})
        s['total'] += 1
        if (nat_id, doctor) in returned:
            s['returned'] += 1

    return sorted(
        [
            {
                'doctor': doctor,
                'total': s['total'],
                'returned': s['returned'],
                'rate': round(s['returned'] / s['total'] * 100, 1),
            }
            for doctor, s in doctor_stats.items()
        ],
        key=lambda x: -x['rate'],
    )


# ── Patient search (PATDB) ────────────────────────────────────────────────────

_patdb_cache: list[dict] | None = None

def _load_patdb() -> list[dict]:
    global _patdb_cache
    if _patdb_cache is not None:
        return _patdb_cache
    if not os.path.exists(PATDB_PATH):
        _patdb_cache = []
        return _patdb_cache
    _patdb_cache = _parse_dbf(PATDB_PATH)
    return _patdb_cache


def _parse_allergy(warn: str) -> list[str]:
    return [a.strip() for a in warn.split('.') if a.strip()]


_patdb_phone_index: dict[str, str] | None = None


def _get_patdb_phone_index() -> dict[str, str]:
    """National ID -> TEL, built once from PATDB and cached. PATDB has a
    single combined phone field (no separate mobile/landline), so this is
    whichever number the clinic has on file."""
    global _patdb_phone_index
    if _patdb_phone_index is None:
        _patdb_phone_index = {
            r.get('ID', '').strip(): r.get('TEL', '').strip()
            for r in _load_patdb()
            if r.get('ID', '').strip()
        }
    return _patdb_phone_index


def get_phone_by_chart_number(chart_number: str) -> str:
    """Look up a patient's TEL (landline) from PATDB by national ID."""
    return _get_patdb_phone_index().get(chart_number, '')


def _read_patdb_with_pos() -> list[tuple[int, dict]]:
    """Read PATDB returning (1-based record position, row) for each non-deleted record.
    Position counts all records including deleted ones, matching VFP6_P.CODE."""
    if not os.path.exists(PATDB_PATH):
        return []
    results = []
    with open(PATDB_PATH, 'rb') as f:
        hdr = f.read(32)
        num_records = struct.unpack_from('<I', hdr, 4)[0]
        header_size = struct.unpack_from('<H', hdr, 8)[0]
        record_size = struct.unpack_from('<H', hdr, 10)[0]
        fields: list[tuple[str, int]] = []
        f.seek(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            fields.append((name, fd[16]))
        f.seek(header_size)
        for pos in range(1, num_records + 1):
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
            results.append((pos, row))
    return results


def _scan_vfp6p_p1(path: str) -> dict[int, str]:
    """Fast scan of VFP6_P: returns {code_int: mobile} for TYPE=P1 only.
    Reads every record but only fully decodes the TYPE field first — non-P1
    records (the majority of the ~180K rows) skip CODE/DESC decoding entirely,
    making this ~4-5× faster than a full _parse_dbf call."""
    result: dict[int, str] = {}
    with open(path, 'rb') as f:
        hdr = f.read(32)
        num_records = struct.unpack_from('<I', hdr, 4)[0]
        header_size = struct.unpack_from('<H', hdr, 8)[0]
        record_size = struct.unpack_from('<H', hdr, 10)[0]

        fields: list[tuple[str, int, int]] = []  # (name, byte-offset-in-record, length)
        f.seek(32)
        off = 1  # byte 0 is the deletion flag
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            flen = fd[16]
            fields.append((name, off, flen))
            off += flen

        type_off = type_len = code_off = code_len = desc_off = desc_len = 0
        for name, foff, flen in fields:
            if name == 'TYPE': type_off, type_len = foff, flen
            elif name == 'CODE': code_off, code_len = foff, flen
            elif name == 'DESC': desc_off, desc_len = foff, flen

        if not (type_len and code_len and desc_len):
            return result

        f.seek(header_size)
        for _ in range(num_records):
            raw = f.read(record_size)
            if not raw or raw[0] == 0x2A:  # deleted
                continue
            if raw[type_off:type_off + type_len].rstrip(b' ') != b'P1':
                continue  # skip non-P1 records without decoding CODE/DESC
            try:
                code = int(raw[code_off:code_off + code_len].decode('ascii').strip())
                desc = raw[desc_off:desc_off + desc_len].decode('big5', errors='replace').strip()
                if code and desc:
                    result[code] = desc
            except Exception:
                pass
    return result


_vfp6p_mobile_index: dict[str, str] | None = None


def _get_vfp6p_mobile_index() -> dict[str, str]:
    """Returns dict: national ID → 手機 (mobile), joined via VFP6_P TYPE=P1."""
    global _vfp6p_mobile_index
    if _vfp6p_mobile_index is not None:
        return _vfp6p_mobile_index
    import config as _cfg
    vfp6p_path = getattr(_cfg, 'VFP6P_PATH', '')
    if not vfp6p_path or not os.path.exists(vfp6p_path):
        _vfp6p_mobile_index = {}
        return _vfp6p_mobile_index

    # Load VFP6_P P1 records: code_int → mobile (fast scan, skips non-P1 decoding)
    code_to_mobile = _scan_vfp6p_p1(vfp6p_path)

    # Join with PATDB by 1-based position → national ID
    _vfp6p_mobile_index = {}
    for pos, row in _read_patdb_with_pos():
        mobile = code_to_mobile.get(pos, '')
        nat_id = row.get('ID', '').strip()
        if nat_id and mobile:
            _vfp6p_mobile_index[nat_id] = mobile
    return _vfp6p_mobile_index


def get_mobile_by_chart_number(chart_number: str) -> str:
    """Look up a patient's 手機 (mobile) from VFP6_P by national ID."""
    return _get_vfp6p_mobile_index().get(chart_number, '')


def _allergy_by_name(name: str) -> list[str] | None:
    """Exact name match in PATDB → allergy list. None = not found."""
    for r in _load_patdb():
        if r.get('NAME', '').strip() == name:
            return _parse_allergy(r.get('WARN', ''))
    return None


def get_queue() -> list[dict]:
    """Read QLOOK1.DBF and return current waiting patients with allergy info."""
    if not os.path.exists(QUEUE_PATH):
        return []
    try:
        records = _parse_dbf(QUEUE_PATH)
    except Exception:
        return []
    result = []
    for r in records:
        name = r.get('NAME', '').strip()
        if not name:
            continue
        allergies = _allergy_by_name(name)
        result.append({
            'name':          name,
            'const':         r.get('CONST', '').strip(),
            'date':          r.get('DATE',  '').strip(),
            'allergies':     allergies if allergies is not None else [],
            'allergy_known': allergies is not None,
        })
    return result


def search_patients(q: str, limit: int = 20) -> list[dict]:
    """Search PATDB by name (contains) or exact national ID. Returns up to `limit` results."""
    q = q.strip()
    if not q:
        return []
    q_lower = q.lower()
    results = []
    for r in _load_patdb():
        name = r.get('NAME', '')
        nat_id = r.get('ID', '')
        if q_lower in name.lower() or q == nat_id:
            results.append({
                'name':      name,
                'nat_id':    nat_id,
                'birth':     r.get('BIRTH', ''),
                'allergies': _parse_allergy(r.get('WARN', '')),
            })
            if len(results) >= limit:
                break
    return results


# ── Mock data ─────────────────────────────────────────────────────────────────

def _p(chart: str, name: str, birth: date) -> Patient:
    return Patient(chart_number=chart, name=name, birth_date=birth)


def _chronic(as_of: date, chart: str, name: str, birth: date, disease: str, due: date) -> FollowupEntry:
    return FollowupEntry(
        patient=_p(chart, name, birth),
        disease_name=disease,
        due_date=due,
        days_overdue=max(0, (as_of - due).days),
        category="慢簽",
    )


def _mspt_followup(as_of: date, chart: str, name: str, birth: date, stage: str, reason: str, due: date) -> FollowupEntry:
    return FollowupEntry(
        patient=_p(chart, name, birth),
        disease_name="代謝症候群",
        due_date=due,
        days_overdue=max(0, (as_of - due).days),
        category="代謝症候群",
        mspt_stage=stage,
        contact_reason=reason,
    )


def _submittable(chart: str, name: str, birth: date, stage: str, report_date: date, days_since: int) -> MsptSubmittableEntry:
    return MsptSubmittableEntry(
        patient=_p(chart, name, birth),
        mspt_stage=stage,
        blood_report_date=report_date,
        days_since_last_stage=days_since,
    )


def _waiting(chart: str, name: str, birth: date, stage: str, draw_date: date) -> MsptWaitingEntry:
    return MsptWaitingEntry(
        patient=_p(chart, name, birth),
        mspt_stage=stage,
        blood_draw_date=draw_date,
    )


def _mock_report(as_of: date) -> DailyReport:
    return DailyReport(
        report_date=as_of,
        chronic_prescriptions=[
            # Extreme backlog
            _chronic(as_of, "10001", "王大明", date(1945,  6,  3), "高血壓",         date(2026,  2, 19)),
            _chronic(as_of, "10002", "陳美華", date(1952,  9, 18), "糖尿病",         date(2026,  3,  5)),
            _chronic(as_of, "10003", "李建國", date(1958,  3, 27), "高血脂",         date(2026,  3, 20)),
            # Mid-range overdue
            _chronic(as_of, "10004", "張淑芬", date(1948, 11,  4), "骨質疏鬆",       date(2026,  3, 29)),
            _chronic(as_of, "10005", "林志強", date(1963,  7, 15), "慢性腎臟病",     date(2026,  4,  5)),
            _chronic(as_of, "10006", "黃俊雄", date(1955,  1, 22), "心臟衰竭",       date(2026,  4,  9)),
            _chronic(as_of, "10007", "吳雅惠", date(1970,  4,  9), "甲狀腺功能低下", date(2026,  4, 12)),
            _chronic(as_of, "10008", "劉文凱", date(1967,  8, 30), "痛風",           date(2026,  4, 14)),
            # Short overdue
            _chronic(as_of, "10009", "蔡淑玲", date(1974, 12,  6), "高血壓",         date(2026,  4, 16)),
            _chronic(as_of, "10010", "許建志", date(1960,  2, 14), "糖尿病",         date(2026,  4, 17)),
            _chronic(as_of, "10011", "鄭美珍", date(1980,  5, 21), "高血脂",         date(2026,  4, 18)),
            # Due today
            _chronic(as_of, "10012", "林雅芳", date(1972, 10,  8), "骨質疏鬆",       date(2026,  4, 19)),
            _chronic(as_of, "10013", "謝志明", date(1956,  3, 31), "氣喘",           date(2026,  4, 19)),
            _chronic(as_of, "10014", "江淑娟", date(1968,  7, 17), "高血壓",         date(2026,  4, 19)),
        ],
        mspt_followups=[
            _mspt_followup(as_of, "20001", "馬建宏", date(1961,  2, 14), "收案",     "需初診+抽血", date(2026,  4,  4)),
            _mspt_followup(as_of, "20002", "潘文正", date(1957,  6, 22), "收案",     "需初診+抽血", date(2026,  4, 19)),
            _mspt_followup(as_of, "20003", "沈淑芬", date(1953,  8,  3), "追1",      "需抽血",      date(2026,  3, 28)),
            _mspt_followup(as_of, "20004", "朱雅婷", date(1965,  4, 19), "追1",      "需抽血",      date(2026,  4, 15)),
            _mspt_followup(as_of, "20005", "高建國", date(1971, 11,  1), "追1",      "需抽血",      date(2026,  4, 19)),
            _mspt_followup(as_of, "20006", "魏淑華", date(1959,  7,  7), "追2",      "需抽血",      date(2026,  4,  8)),
            _mspt_followup(as_of, "20007", "洪文彬", date(1975,  1, 25), "追2",      "需抽血",      date(2026,  4, 18)),
            _mspt_followup(as_of, "20008", "趙明山", date(1950,  9, 12), "追3",      "需抽血",      date(2026,  4,  1)),
            _mspt_followup(as_of, "20009", "葉淑貞", date(1966,  5, 30), "追3",      "需抽血",      date(2026,  4, 19)),
            _mspt_followup(as_of, "20010", "賴志偉", date(1954,  3, 16), "年度追蹤", "需回診+抽血", date(2026,  3, 20)),
            _mspt_followup(as_of, "20011", "蕭美玲", date(1962,  8,  5), "年度追蹤", "需回診+抽血", date(2026,  4, 11)),
            _mspt_followup(as_of, "20012", "邱建志", date(1969, 12, 20), "年度追蹤", "需回診+抽血", date(2026,  4, 16)),
            _mspt_followup(as_of, "20013", "楊淑惠", date(1978,  6,  2), "年度追蹤", "需回診+抽血", date(2026,  4, 19)),
        ],
        mspt_submittable=[
            _submittable("30001", "吳建國", date(1952, 11,  3), "追1", date(2026,  4, 17),  74),
            _submittable("30002", "鄭雅芳", date(1964,  4, 19), "追1", date(2026,  3, 30),  81),
            _submittable("30003", "陳志強", date(1970,  9, 28), "追1", date(2026,  2, 23),  88),
            _submittable("30004", "趙美珍", date(1958,  2, 11), "追2", date(2026,  4, 11),  72),
            _submittable("30005", "林文凱", date(1967,  7, 14), "追2", date(2026,  3, 15),  79),
            _submittable("30006", "黃淑娟", date(1975, 10, 30), "追2", date(2026,  2,  8),  85),
            _submittable("30007", "許建宏", date(1955,  5,  6), "追3", date(2026,  4, 15),  71),
            _submittable("30008", "劉雅惠", date(1963,  1, 22), "追3", date(2026,  3, 22),  77),
        ],
        mspt_waiting=[
            _waiting("40001", "江淑芬", date(1960,  4,  8), "收案",     date(2026,  4, 19)),
            _waiting("40002", "蔡文彬", date(1956, 10, 25), "追1",      date(2026,  4, 18)),
            _waiting("40003", "謝淑玲", date(1969,  3, 16), "追2",      date(2026,  4, 16)),
            _waiting("40004", "周美華", date(1953,  8, 21), "追3",      date(2026,  4, 14)),
            _waiting("40005", "楊志明", date(1948, 12,  9), "年度追蹤", date(2026,  4, 11)),
        ],
    )
