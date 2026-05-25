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

# In-memory cache for parsed DBF files.
# IC files are historical and never change once a month ends, so caching is safe.
_dbf_cache: dict[str, list[dict]] = {}


def _parse_dbf_cached(path: str) -> list[dict]:
    if path not in _dbf_cache:
        _dbf_cache[path] = _parse_dbf(path)
    return _dbf_cache[path]


def warmup_cache() -> None:
    """Pre-load all IC (and P) files into the cache. Call in a background thread
    at server startup so the first user request doesn't pay the full parse cost."""
    for path in _ic_main_files():
        if path not in _dbf_cache:
            try:
                _parse_dbf_cached(path)
                p = path[:-4] + 'P.DBF'
                if os.path.exists(p) and p not in _dbf_cache:
                    _parse_dbf_cached(p)
            except Exception:
                pass


def get_daily_report(as_of: date) -> DailyReport:
    if USE_MOCK_DATA:
        return _mock_report(as_of)
    return DailyReport(
        report_date=as_of,
        chronic_prescriptions=_query_chronic_prescriptions(as_of),
        mspt_followups=_query_mspt_followups(as_of),
        mspt_submittable=[],
        mspt_waiting=[],
    )


# --- DBF utilities ---

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
            if fd[0] == 0x0D:
                break
            name = fd[:11].rstrip(b'\x00').decode('ascii', errors='replace')
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


# --- ICD code → Chinese disease name ---

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


# --- Real DB queries ---

def _query_chronic_prescriptions(as_of: date) -> list[FollowupEntry]:
    """Return patients whose last 慢簽 visit + prescription days is past as_of."""
    since = as_of - timedelta(days=365)

    # nat_id → info about the patient's latest AE連續 visit
    best: dict[str, dict] = {}

    for ic_path in _ic_files_since(since):
        try:
            records = _parse_dbf_cached(ic_path)
        except Exception:
            continue
        for r in records:
            if r.get('H_TYPE') != 'AE連續':
                continue
            v_date = _roc_to_date(r.get('DATE', ''))
            if not v_date or v_date > as_of:
                continue
            nat_id = r.get('ID', '').strip()
            if not nat_id:
                continue
            if nat_id not in best or v_date > best[nat_id]['date']:
                icd = next(
                    (r.get(f, '') for f in ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')
                     if _icd_to_name(r.get(f, ''))),
                    '',
                )
                best[nat_id] = {
                    'date': v_date,
                    'code_f': r.get('CODE_F', '').strip(),
                    'name': r.get('NAME', '').strip(),
                    'birth': _roc_to_date(r.get('BIRTH', '')),
                    'icd': icd,
                    'ic_path': ic_path,
                }

    # Group patients by their P file path so each P file is parsed only once.
    by_p_path: dict[str, set[str]] = {}
    for v in best.values():
        p_path = v['ic_path'][:-4] + 'P.DBF'
        if os.path.exists(p_path):
            by_p_path.setdefault(p_path, set()).add(v['code_f'])

    ps_lookup: dict[str, int] = {}  # code_f → days supply
    for p_path, code_fs in by_p_path.items():
        try:
            for r in _parse_dbf_cached(p_path):
                cf = r.get('CODE_F', '').strip()
                if cf in code_fs and cf not in ps_lookup and r.get('LONG', '').strip() == '1':
                    ps = r.get('PS', '').strip()
                    if ps.isdigit() and int(ps) > 0:
                        ps_lookup[cf] = int(ps)
        except Exception:
            pass

    results = []
    for nat_id, v in best.items():
        if not v['name'] or not v['birth']:
            continue
        ps = ps_lookup.get(v['code_f'], 28)
        due_date = v['date'] + timedelta(days=ps)
        if due_date > as_of:
            continue
        results.append(FollowupEntry(
            patient=Patient(
                chart_number=nat_id,
                name=v['name'],
                birth_date=v['birth'],
            ),
            disease_name=_icd_to_name(v['icd']) or '慢簽',
            due_date=due_date,
            days_overdue=(as_of - due_date).days,
            last_visit_date=v['date'],
            category='慢簽',
        ))
    return sorted(results, key=lambda e: e.days_overdue, reverse=True)


# NHI procedure codes for 代謝症候群 tracking, as they appear in the P file DRUG_NO field.
# The clinic software displays these as "追蹤管理費 1 (>=70天)" etc., but the DBF stores codes.
_MSPT_CODE_MAP: dict[str, str] = {
    'P7501C':  '收案',
    'P7502C':  '追1',
    'P75022C': '追2',
    'P75023C': '追3',
    'P7503C':  '年度追蹤',
}


def _query_mspt_followups(as_of: date) -> list[FollowupEntry]:
    """Return MSPT patients whose next stage visit is overdue as of as_of.

    Stage detection uses NHI procedure codes in the P-file DRUG_NO field.
    History is grouped by national ID (ID field) because CODE_F is assigned
    per-visit and changes across visits for the same patient.
    The P file has no DATE field, so each patient's latest IC visit date for
    that month is used as the stage date."""
    MAX_INACTIVE_DAYS  = 2 * 365  # older than 2 years — ignore entirely
    REOPEN_AFTER_DAYS  = 365      # > 1 year inactive → case closed, needs 收案 restart
    _STAGE_NEXT = {'收案': '追1', '追1': '追2', '追2': '追3', '追3': '年度追蹤', '年度追蹤': '追1'}
    _STAGE_GAPS = {'收案': METABOLIC_FOLLOWUP_DAYS, '追1': METABOLIC_FOLLOWUP_DAYS,
                   '追2': METABOLIC_FOLLOWUP_DAYS, '追3': 365, '年度追蹤': METABOLIC_FOLLOWUP_DAYS}
    since = as_of - timedelta(days=MAX_INACTIVE_DAYS)

    # Keyed by national ID (身分證字號) for stable cross-visit identity
    patient_info: dict[str, dict] = {}        # nat_id → {name, birth, latest_cf, latest_date}
    stage_history: dict[str, list[dict]] = {} # nat_id → [{stage, date}, ...]

    for ic_path in _ic_files_since(since):
        month_cf_to_id: dict[str, str] = {}    # code_f → nat_id (built from IC file)
        month_cf_dates: dict[str, date] = {}   # code_f → visit date (for precise stage dating)

        try:
            for r in _parse_dbf_cached(ic_path):
                v_date = _roc_to_date(r.get('DATE', ''))
                if not v_date or v_date > as_of:
                    continue
                cf = r.get('CODE_F', '').strip()
                nat_id = r.get('ID', '').strip()
                if not cf or not nat_id:
                    continue

                month_cf_to_id[cf] = nat_id
                month_cf_dates[cf] = v_date

                name = r.get('NAME', '').strip()
                birth = _roc_to_date(r.get('BIRTH', ''))
                if name and birth:
                    prev = patient_info.get(nat_id)
                    if prev is None or v_date > prev['latest_date']:
                        patient_info[nat_id] = {
                            'name': name, 'birth': birth,
                            'latest_cf': cf, 'latest_date': v_date,
                        }

                # Enrollment from AC保健 is NOT used here to avoid false-positives from
                # 成人健檢 visits (same AC保健/KIND=10/FEE=300, ICD=Z0000).
                # 收案 is detected via P7501C in the P file below.
        except Exception:
            pass

        p_path = ic_path[:-4] + 'P.DBF'
        if not os.path.exists(p_path):
            continue
        try:
            for r in _parse_dbf_cached(p_path):
                cf = r.get('CODE_F', '').strip()
                nat_id = month_cf_to_id.get(cf)
                if not nat_id:
                    continue
                stage = _MSPT_CODE_MAP.get(r.get('DRUG_NO', '').strip())
                if stage is None:
                    continue
                # Use the specific CODE_F's visit date for precise stage dating
                v_date = month_cf_dates.get(cf)
                if not v_date or v_date > as_of:
                    continue
                stage_history.setdefault(nat_id, []).append({'stage': stage, 'date': v_date})
        except Exception:
            pass

    results = []
    for nat_id, history in stage_history.items():
        info = patient_info.get(nat_id)
        if not info:
            continue

        history.sort(key=lambda x: x['date'])

        last_stage    = history[-1]['stage']
        last_date     = history[-1]['date']
        days_inactive = (as_of - last_date).days

        # Ignore patients whose last MSPT activity is older than 2 years
        if days_inactive > MAX_INACTIVE_DAYS:
            continue

        # Case closed: > 1 year without any follow-up → needs 收案 restart + blood test
        if days_inactive > REOPEN_AFTER_DAYS:
            due_date = last_date + timedelta(days=REOPEN_AFTER_DAYS)
            results.append(FollowupEntry(
                patient=Patient(
                    chart_number=nat_id,
                    name=info['name'],
                    birth_date=info['birth'],
                ),
                disease_name='代謝症候群',
                due_date=due_date,
                days_overdue=(as_of - due_date).days,
                category='代謝症候群',
                mspt_stage='收案',
                last_stage=last_stage,
                contact_reason='需重新收案+抽血',
                last_visit_date=last_date,
            ))
            continue

        next_stage = _STAGE_NEXT.get(last_stage)
        gap        = _STAGE_GAPS.get(last_stage)
        if next_stage is None or gap is None:
            continue
        due_date = last_date + timedelta(days=gap)
        if due_date > as_of:
            continue

        results.append(FollowupEntry(
            patient=Patient(
                chart_number=nat_id,
                name=info['name'],
                birth_date=info['birth'],
            ),
            disease_name='代謝症候群',
            due_date=due_date,
            days_overdue=(as_of - due_date).days,
            category='代謝症候群',
            mspt_stage=next_stage,
            last_stage=last_stage,
            last_visit_date=last_date,
        ))
    return sorted(results, key=lambda e: e.days_overdue, reverse=True)


def get_latest_visit_dates(chart_numbers: set[str], category: str) -> dict[str, date]:
    """Return {chart_number: latest visit date} for the given patients, looking back 30 days.
    Used to detect whether a patient returned after being contacted.

    For 慢簽: chart_number is CODE_F, matched via CODE_F in AE連續 records.
    For 代謝症候群: chart_number is national ID, matched via ID field in any 01西醫 visit."""
    if not chart_numbers:
        return {}
    since = date.today() - timedelta(days=30)
    result: dict[str, date] = {}
    for ic_path in _ic_files_since(since):
        try:
            for r in _parse_dbf_cached(ic_path):
                if category == '慢簽':
                    if r.get('H_TYPE') != 'AE連續':
                        continue
                    key = r.get('ID', '').strip()
                else:
                    if r.get('H_TYPE') != '01西醫':
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


# --- Mock data (USE_MOCK_DATA = True) ---

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
