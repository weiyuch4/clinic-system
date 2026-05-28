import logging
import os
import threading
from datetime import date, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import backup
import contacts
import database
from models import (
    ChartNumberRequest, ContactRequest, DailyReport, ExcludeRequest, FollowupEntry,
    ManualPickupRequest, MsptCompleteRequest, MsptSubmittableEntry, NurseEntryRequest,
    SubmitRequest, UnexcludeRequest,
)

# ── Edit this list to match your clinic's nurse names ──────────────────────────
NURSE_NAMES: list[str] = ["媛淩", "巧潔", "辰優", "惠茗"]
# ───────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="診所追蹤系統")
app.mount("/static", StaticFiles(directory="static"), name="static")

contacts.init()
backup.run()
threading.Thread(target=database.warmup_cache, daemon=True).start()


@app.get("/")
def index() -> Response:
    try:
        content = open("static/index.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入介面檔案")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/nurses")
def get_nurses() -> list[str]:
    return NURSE_NAMES


@app.get("/api/report")
def get_report(report_date: date | None = None) -> DailyReport:
    try:
        report = database.get_daily_report(report_date or date.today())
        hidden_keys = contacts.get_hidden_keys()
        call_required_keys = contacts.get_call_required_keys()
        submitted_keys = contacts.get_submitted_keys()
        excluded_keys = contacts.get_excluded_keys()          # (chart_number, category)
        mspt_completed_keys = contacts.get_mspt_completed_keys()  # (chart_number, mspt_stage, due_date)

        def filter_followups(entries: list[FollowupEntry]) -> list[FollowupEntry]:
            result = []
            for e in entries:
                key = (e.patient.chart_number, e.category, e.due_date.isoformat())
                if key in hidden_keys:
                    continue
                if (e.patient.chart_number, e.category) in excluded_keys:
                    continue
                if (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) in mspt_completed_keys:
                    continue
                result.append(e.model_copy(update={"call_required": key in call_required_keys}))
            return result

        # Filter 已聯絡 entries: exclude patients who have already returned since being contacted
        contacted_with_dates = contacts.get_contacted_with_dates()
        chronic_charts = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '慢簽'}
        mspt_charts    = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '代謝症候群'}
        chronic_visits = database.get_latest_visit_dates(chronic_charts, '慢簽')
        mspt_visits    = database.get_latest_visit_dates(mspt_charts, '代謝症候群')

        def has_returned(entry: FollowupEntry, contacted_at: date) -> bool:
            visits = chronic_visits if entry.category == '慢簽' else mspt_visits
            latest = visits.get(entry.patient.chart_number)
            return latest is not None and latest > contacted_at

        contacted = [
            e.model_copy(update={"contacted_at": ca})
            for e, ca in contacted_with_dates
            if not has_returned(e, ca)
            and (e.patient.chart_number, e.category) not in excluded_keys
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_completed_keys
        ]

        # Filter chronic patients suppressed by a manual pickup record
        _CHRONIC_GRACE = 5
        as_of = report_date or date.today()
        manual_pickup_map = contacts.get_manual_pickup_map()

        def chronic_suppressed(entry: FollowupEntry) -> bool:
            mp = manual_pickup_map.get(entry.patient.chart_number)
            if not mp:
                return False
            pickup_date, ps_days = date.fromisoformat(mp[0]), mp[1]
            # If IC already has a newer visit, the manual record is superseded
            if entry.last_visit_date and pickup_date <= entry.last_visit_date:
                return False
            next_due = pickup_date + timedelta(days=ps_days)
            return (as_of - next_due).days < _CHRONIC_GRACE

        chronic_prescriptions = [e for e in report.chronic_prescriptions if not chronic_suppressed(e)]

        manual_excluded = contacts.get_excluded_entries()
        auto_excluded = contacts.get_auto_excluded_entries()
        all_excluded = manual_excluded + [
            e for e in auto_excluded
            if (e.patient.chart_number, e.category) not in {(x.patient.chart_number, x.category) for x in manual_excluded}
        ]

        called_entries = contacts.get_called_entries()
        called_filtered = [
            e for e in called_entries
            if (e.patient.chart_number, e.category) not in excluded_keys
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_completed_keys
        ]

        return DailyReport(
            report_date=report.report_date,
            chronic_prescriptions=filter_followups(chronic_prescriptions),
            mspt_followups=filter_followups(report.mspt_followups),
            mspt_inactive=filter_followups(report.mspt_inactive),
            mspt_submittable=[
                e for e in report.mspt_submittable
                if (e.patient.chart_number, e.mspt_stage) not in submitted_keys
            ],
            mspt_waiting=report.mspt_waiting,
            contacted=contacted,
            called=called_filtered,
            submitted=contacts.get_submitted_entries(),
            excluded=all_excluded,
            mspt_completed=contacts.get_mspt_completed_entries(),
            chronic_manual_pickups=contacts.get_manual_pickup_entries(),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_report failed for date=%s", report_date)
        raise HTTPException(status_code=503, detail="資料載入失敗，請確認資料夾是否可存取")


@app.post("/api/contacted")
def mark_contacted(req: NurseEntryRequest) -> None:
    try:
        contacts.mark_contacted(req.entry, req.nurse)
    except Exception:
        logger.exception("mark_contacted failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="聯絡記錄儲存失敗，請稍後再試")


@app.post("/api/called")
def mark_called(req: NurseEntryRequest) -> None:
    try:
        contacts.mark_called(req.entry, req.nurse)
    except Exception:
        logger.exception("mark_called failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="二次通知記錄儲存失敗，請稍後再試")


@app.delete("/api/contacted")
def unmark_contacted(req: ContactRequest) -> None:
    try:
        contacts.unmark(req.chart_number, req.category, req.due_date)
    except Exception:
        logger.exception("unmark_contacted failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.post("/api/submitted")
def mark_submitted(entry: MsptSubmittableEntry) -> None:
    try:
        contacts.mark_submitted(entry)
    except Exception:
        logger.exception("mark_submitted failed for %s", entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="申報記錄儲存失敗，請稍後再試")


@app.delete("/api/submitted")
def unmark_submitted(req: SubmitRequest) -> None:
    try:
        contacts.unmark_submitted(req.chart_number, req.mspt_stage)
    except Exception:
        logger.exception("unmark_submitted failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷申報失敗，請稍後再試")


@app.post("/api/excluded")
def mark_excluded(req: ExcludeRequest) -> None:
    try:
        contacts.mark_excluded(req.entry, req.reason, req.note, req.nurse)
    except Exception:
        logger.exception("mark_excluded failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="排除記錄儲存失敗，請稍後再試")


@app.delete("/api/excluded")
def unmark_excluded(req: UnexcludeRequest) -> None:
    try:
        contacts.unmark_excluded(req.chart_number, req.category)
    except Exception:
        logger.exception("unmark_excluded failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷排除失敗，請稍後再試")


@app.post("/api/mspt-completed")
def mark_mspt_completed(req: NurseEntryRequest) -> None:
    try:
        contacts.mark_mspt_completed(req.entry, req.nurse)
    except Exception:
        logger.exception("mark_mspt_completed failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="掛MSPT完成記錄儲存失敗，請稍後再試")


@app.delete("/api/mspt-completed")
def unmark_mspt_completed(req: MsptCompleteRequest) -> None:
    try:
        contacts.unmark_mspt_completed(req.chart_number, req.mspt_stage, req.due_date.isoformat())
    except Exception:
        logger.exception("unmark_mspt_completed failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷掛MSPT完成失敗，請稍後再試")



@app.post("/api/manual-pickup")
def mark_manual_pickup(req: ManualPickupRequest) -> None:
    try:
        contacts.mark_manual_pickup(req.entry, req.pickup_date, req.ps_days, req.nurse)
    except Exception:
        logger.exception("mark_manual_pickup failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="手動取藥記錄儲存失敗，請稍後再試")


@app.delete("/api/manual-pickup")
def unmark_manual_pickup(req: ChartNumberRequest) -> None:
    try:
        contacts.unmark_manual_pickup(req.chart_number)
    except Exception:
        logger.exception("unmark_manual_pickup failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.get("/api/notice")
def get_notice() -> dict:
    try:
        text = open("notice.txt", encoding="utf-8").read().strip()
    except OSError:
        text = ""
    return {"text": text}


@app.get("/api/contacts/history")
def get_contacts_history(target_date: str | None = None) -> dict:
    target = target_date or date.today().isoformat()
    try:
        history = contacts.get_print_history(target)
        return {
            "contacted": [e.model_dump(mode="json") for e in history["contacted"]],
            "called": [e.model_dump(mode="json") for e in history["called"]],
            "mspt_completed": [e.model_dump(mode="json") for e in history["mspt_completed"]],
            "excluded": [e.model_dump(mode="json") for e in history["excluded"]],
            "manual_pickups": [e.model_dump(mode="json") for e in history["manual_pickups"]],
        }
    except Exception:
        logger.exception("get_contacts_history failed for date=%s", target_date)
        raise HTTPException(status_code=500, detail="聯絡紀錄載入失敗")


@app.get("/api/debug/p-sample")
def debug_p_sample(n: int = 3) -> dict:
    """Diagnostic: sample the most recent IC, P, and H files to inspect their structure.
    Remove or protect this endpoint before exposing outside the clinic LAN."""
    import glob as _glob
    from config import IC_DATA_PATH

    all_dbf = sorted(_glob.glob(os.path.join(IC_DATA_PATH, '*.DBF')))
    all_dbf += sorted(_glob.glob(os.path.join(IC_DATA_PATH, '*.dbf')))

    def _monthly_stem(fname: str) -> str:
        """Return the 5-char stem between 'IC' and the type suffix, e.g. '11411'."""
        upper = fname.upper()
        if not upper.startswith('IC'):
            return ''
        rest = upper[2:]  # strip 'IC'
        for suffix in ('PX.DBF', 'H.DBF', 'N.DBF', 'P.DBF', 'X.DBF', '.DBF'):
            if rest.endswith(suffix):
                return rest[:-len(suffix)]
        return ''

    _TYPED_SUFFIXES = ('PX.DBF', 'H.DBF', 'N.DBF', 'P.DBF', 'X.DBF')

    def _latest_nonempty(suffix: str) -> dict | None:
        """Return fields + sample from the most recent non-empty file ending with suffix.
        For the plain '.DBF' case, exclude files that are actually P/H/N/X typed files."""
        upper_suffix = suffix.upper()
        def _matches(fname: str) -> bool:
            u = fname.upper()
            if not u.endswith(upper_suffix):
                return False
            # When looking for the main IC file (.DBF), skip typed variants
            if upper_suffix == '.DBF':
                for ts in _TYPED_SUFFIXES:
                    if u.endswith(ts):
                        return False
            stem = _monthly_stem(fname)
            return len(stem) == 5 and stem.isdigit()
        candidates = [f for f in reversed(all_dbf) if _matches(os.path.basename(f))]
        for path in candidates:
            try:
                records = database._parse_dbf(path)
                if records:
                    return {
                        "file": os.path.basename(path),
                        "total_records": len(records),
                        "fields": list(records[0].keys()),
                        "sample": records[:n],
                    }
            except Exception:
                pass
        return None

    ic = _latest_nonempty('.DBF')
    p  = _latest_nonempty('P.DBF')
    h  = _latest_nonempty('H.DBF')

    # Collect distinct H_TYPE and KIND values from the actual IC main file
    h_types, kinds = set(), set()
    if ic:
        try:
            for r in database._parse_dbf(os.path.join(IC_DATA_PATH, ic["file"])):
                h_types.add(r.get('H_TYPE', ''))
                kinds.add(r.get('KIND', ''))
        except Exception:
            pass

    # Collect all distinct DRUG_NO values from the most recent 3 P files
    # (MSPT management fee NHI procedure codes will appear here alongside drug codes)
    p_stems_seen = 0
    distinct_drug_nos: set[str] = set()
    for f in reversed(all_dbf):
        bname = os.path.basename(f).upper()
        if not bname.endswith('P.DBF'):
            continue
        stem = _monthly_stem(bname)
        if len(stem) != 5 or not stem.isdigit():
            continue
        try:
            for r in database._parse_dbf(f):
                dn = r.get('DRUG_NO', '').strip()
                if dn:
                    distinct_drug_nos.add(dn)
        except Exception:
            pass
        p_stems_seen += 1
        if p_stems_seen >= 3:
            break

    return {
        "ic_data_path": IC_DATA_PATH,
        "recent_ic_file": ic,
        "recent_p_file":  p,
        "recent_h_file":  h,
        "distinct_h_type_in_ic": sorted(h_types),
        "distinct_kind_in_ic":   sorted(kinds),
        "distinct_drug_nos_recent_3_p_files": sorted(distinct_drug_nos),
    }


@app.get("/api/debug/mspt")
def debug_mspt(nat_id: str | None = None) -> dict:
    """Diagnostic: show MSPT stage detection across the full 2-year scan window.
    Pass ?nat_id=A123456789 to see a specific patient's stage history."""
    from datetime import timedelta
    from database import _ic_files_since, _parse_dbf_cached, _roc_to_date

    as_of = date.today()
    MAX_INACTIVE_DAYS = 2 * 365
    since = as_of - timedelta(days=MAX_INACTIVE_DAYS)
    ic_files = _ic_files_since(since)

    _MSPT_CODE_MAP = {
        'P7501C': '收案', 'P7502C': '追1', 'P75022C': '追2',
        'P75023C': '追3', 'P7503C': '年度追蹤',
    }

    all_mspt_drug_nos: set[str] = set()
    patient_stages: dict[str, list] = {}

    for ic_path in ic_files:
        month_cf_to_id: dict[str, str] = {}
        month_cf_dates: dict[str, object] = {}
        try:
            for r in _parse_dbf_cached(ic_path):
                v_date = _roc_to_date(r.get('DATE', ''))
                if not v_date or v_date > as_of:
                    continue
                cf  = r.get('CODE_F', '').strip()
                nid = r.get('ID', '').strip()
                if cf and nid:
                    month_cf_to_id[cf] = nid
                    month_cf_dates[cf] = v_date
        except Exception:
            pass

        p_path = ic_path[:-4] + 'P.DBF'
        if not os.path.exists(p_path):
            continue
        try:
            for r in _parse_dbf_cached(p_path):
                dn  = r.get('DRUG_NO', '').strip()
                cf  = r.get('CODE_F', '').strip()
                nid = month_cf_to_id.get(cf)
                stage = _MSPT_CODE_MAP.get(dn)
                if stage:
                    all_mspt_drug_nos.add(dn)
                if not nid or not stage:
                    continue
                v_date = month_cf_dates.get(cf)
                if v_date:
                    patient_stages.setdefault(nid, []).append(
                        {'stage': stage, 'date': v_date.isoformat(), 'file': os.path.basename(ic_path)}
                    )
        except Exception:
            pass

    # Summarise last stage across all detected patients
    last_stage_counts: dict[str, int] = {}
    for hist in patient_stages.values():
        if hist:
            ls = sorted(hist, key=lambda x: x['date'])[-1]['stage']
            last_stage_counts[ls] = last_stage_counts.get(ls, 0) + 1

    specific = None
    if nat_id:
        hist = patient_stages.get(nat_id)
        specific = sorted(hist, key=lambda x: x['date']) if hist else []

    return {
        'as_of': as_of.isoformat(),
        'scan_since': since.isoformat(),
        'ic_files_scanned': [os.path.basename(f) for f in ic_files],
        'mspt_drug_nos_found': sorted(all_mspt_drug_nos),
        'mspt_patients_detected': len(patient_stages),
        'last_stage_counts': last_stage_counts,
        'specific_patient_history': specific,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
