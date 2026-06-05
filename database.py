from datetime import date, timedelta
import glob
import os
import struct

from config import IC_DATA_PATH, METABOLIC_FOLLOWUP_DAYS, USE_MOCK_DATA
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

# ── DBF cache ─────────────────────────────────────────────────────────────────

# IC files are historical — once a month ends the file never changes — so caching is safe.
# The current month's file is always re-read to pick up intra-month updates.
_dbf_cache: dict[str, list[dict]] = {}


def _current_roc_month() -> str:
    d = date.today()
    return f"{d.year - 1911:03d}{d.month:02d}"


def _parse_dbf_cached(path: str) -> list[dict]:
    if _current_roc_month() in os.path.basename(path).upper():
        return _parse_dbf(path)
    if path not in _dbf_cache:
        _dbf_cache[path] = _parse_dbf(path)
    return _dbf_cache[path]


def warmup_cache() -> None:
    """Pre-load all IC (and P) files into the cache. Call in a background thread
    at server startup so the first user request doesn't pay the full parse cost."""
    for path in _ic_main_files():
        try:
            _parse_dbf_cached(path)
            p = path[:-4] + 'P.DBF'
            if os.path.exists(p):
                _parse_dbf_cached(p)
        except Exception:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def get_daily_report(as_of: date) -> DailyReport:
    if USE_MOCK_DATA:
        return _mock_report(as_of)
    mspt_followups, mspt_inactive = _query_mspt_followups(as_of)
    return DailyReport(
        report_date=as_of,
        chronic_prescriptions=_query_chronic_prescriptions(as_of),
        mspt_followups=mspt_followups,
        mspt_inactive=mspt_inactive,
        mspt_submittable=[],
        mspt_waiting=[],
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
    IC01 is identified by M33='1' AND M26='3' on the IC main record (NHI-mandated
    fields exclusive to 連續處方箋 initial prescriptions) plus LONG='1' in the P file.
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
            h_type   = r.get('H_TYPE', '')
            is_ae    = h_type == 'AE連續'
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
                # 連續處方箋 IC01: NHI mandates M33='1' (cycle 1 of 3) and M26='3'
                # (3-cycle series). Regular 慢性病 and offline visits lack these fields.
                if not (r.get('M33', '').strip() == '1' and r.get('M26', '').strip() == '3'):
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
                    entry['m33'] = r.get('M33', '').strip()
                target[nat_id] = entry
            elif is_ae and v_date == target[nat_id]['date'] and cf and cf not in target[nat_id]['code_fs']:
                target[nat_id]['code_fs'].append(cf)
                # Keep the highest M33 seen (e.g. IC02 + IC03 same day → m33='3')
                new_m33 = r.get('M33', '').strip()
                cur_m33 = target[nat_id].get('m33', '')
                if new_m33.isdigit() and (not cur_m33.isdigit() or int(new_m33) > int(cur_m33)):
                    target[nat_id]['m33'] = new_m33

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
                'contact_reason': '需重新收案+抽血',
            })
            if (as_of - info['latest_date']).days > LONG_INACTIVE_DAYS:
                inactive.append(entry)
            else:
                results.append(entry)
        else:
            results.append(entry.model_copy(update={'mspt_stage': next_stage}))

    return (
        sorted(results, key=lambda e: e.days_overdue, reverse=True),
        sorted(inactive, key=lambda e: e.last_visit_date or date.min),
    )


# ── Visit detection (has patient returned?) ───────────────────────────────────

def get_latest_visit_dates(chart_numbers: set[str], category: str) -> dict[str, date]:
    """Return {chart_number: latest visit date} for the given patients, looking back 30 days.
    Used to detect whether a contacted patient has since returned.

    For 慢簽: matches AE連續 or 01西醫 IC01 (M33='1', M26='3') records.
    For 代謝症候群: matches any 01西醫 visit."""
    if not chart_numbers:
        return {}
    since  = date.today() - timedelta(days=30)
    result: dict[str, date] = {}

    for ic_path in _ic_files_since(since):
        try:
            for r in _parse_dbf_cached(ic_path):
                h = r.get('H_TYPE', '')
                if category == '慢簽':
                    is_ae   = h == 'AE連續'
                    is_ic01 = (
                        h == '01西醫'
                        and r.get('M33', '').strip() == '1'
                        and r.get('M26', '').strip() == '3'
                    )
                    if not is_ae and not is_ic01:
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
