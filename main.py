import logging
import os
import threading
import webbrowser
from datetime import date

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import contacts
import database
from models import ContactRequest, DailyReport, FollowupEntry, MsptSubmittableEntry, SubmitRequest

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="診所追蹤系統")
app.mount("/static", StaticFiles(directory="static"), name="static")

contacts.init()
threading.Thread(target=database.warmup_cache, daemon=True).start()


@app.get("/")
def index() -> Response:
    try:
        content = open("static/index.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入介面檔案")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/report")
def get_report(report_date: date | None = None) -> DailyReport:
    try:
        report = database.get_daily_report(report_date or date.today())
        hidden_keys = contacts.get_hidden_keys()
        call_required_keys = contacts.get_call_required_keys()
        submitted_keys = contacts.get_submitted_keys()

        def filter_followups(entries: list[FollowupEntry]) -> list[FollowupEntry]:
            result = []
            for e in entries:
                key = (e.patient.chart_number, e.category, e.due_date.isoformat())
                if key in hidden_keys:
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
        ]

        return DailyReport(
            report_date=report.report_date,
            chronic_prescriptions=filter_followups(report.chronic_prescriptions),
            mspt_followups=filter_followups(report.mspt_followups),
            mspt_submittable=[
                e for e in report.mspt_submittable
                if (e.patient.chart_number, e.mspt_stage) not in submitted_keys
            ],
            mspt_waiting=report.mspt_waiting,
            contacted=contacted,
            called=contacts.get_called_entries(),
            submitted=contacts.get_submitted_entries(),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_report failed for date=%s", report_date)
        raise HTTPException(status_code=503, detail="資料載入失敗，請確認資料夾是否可存取")


@app.post("/api/contacted")
def mark_contacted(entry: FollowupEntry) -> None:
    try:
        contacts.mark_contacted(entry)
    except Exception:
        logger.exception("mark_contacted failed for %s", entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="聯絡記錄儲存失敗，請稍後再試")


@app.post("/api/called")
def mark_called(entry: FollowupEntry) -> None:
    try:
        contacts.mark_called(entry)
    except Exception:
        logger.exception("mark_called failed for %s", entry.patient.chart_number)
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


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)
