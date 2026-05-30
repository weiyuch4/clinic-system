import hashlib
import logging
import os
import secrets
import threading
from datetime import date, timedelta

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

import backup
import contacts
import database
import lab_results
from models import (
    ChartNumberRequest, ContactRequest, DailyReport, ExcludeRequest, FollowupEntry,
    ManualOnHoldRequest, ManualPickupRequest, MsptCompleteRequest, MsptManualRemoveRequest,
    MsptManualRequest, MsptSubmittableEntry,
    NurseEntryRequest, OnHoldRemoveRequest, OnHoldRequest, SubmitRequest, UnexcludeRequest,
)

# ── Edit this list to match your clinic's nurse names ──────────────────────────
NURSE_NAMES: list[str] = ["媛淩", "巧潔", "辰優", "惠茗"]
# ───────────────────────────────────────────────────────────────────────────────

# ── Admin stats page credentials ───────────────────────────────────────────────
# To change the password, run in terminal:
#   python -c "import hashlib; print(hashlib.sha256(b'your-new-password').hexdigest())"
# Then replace ADMIN_PASS_HASH with the output.
ADMIN_USER      = "admin"
ADMIN_PASS_HASH = "fbfdc9472dbe28e802c388914610c16634c383183836bcdf36b7aca819c80768"
# ───────────────────────────────────────────────────────────────────────────────

_security = HTTPBasic()

def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    input_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    ok = (
        secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode()) and
        secrets.compare_digest(input_hash, ADMIN_PASS_HASH)
    )
    if not ok:
        raise HTTPException(status_code=401, detail="認證失敗",
                            headers={"WWW-Authenticate": "Basic"})

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


@app.get("/admin/stats")
def admin_stats(month: str | None = None, _: None = Depends(_require_admin)) -> Response:
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        stats = contacts.get_activity_stats(month)
    except Exception:
        logger.exception("admin_stats failed for month=%s", month)
        raise HTTPException(status_code=500, detail="查詢失敗")

    nurses = sorted(stats.keys(), key=lambda n: (n == "（未選擇）", n))
    cols = [("contacted", "已通知"), ("called", "再次通知"), ("mspt", "完成MSPT"),
            ("excluded", "排除"), ("pickup", "手動取藥")]

    def td(val: int) -> str:
        colour = "#111" if val else "#ccc"
        return f'<td style="text-align:center;color:{colour}">{val}</td>'

    rows_html = ""
    totals = {k: 0 for k, _ in cols}
    for nurse in nurses:
        s = stats[nurse]
        total = sum(s[k] for k, _ in cols)
        for k, _ in cols:
            totals[k] += s[k]
        rows_html += (
            f'<tr><td style="font-weight:600">{nurse}</td>'
            + "".join(td(s[k]) for k, _ in cols)
            + f'<td style="text-align:center;font-weight:700">{total}</td></tr>'
        )

    grand = sum(totals.values())
    totals_html = (
        '<tr style="background:#f0f4f8;font-weight:700"><td>合計</td>'
        + "".join(f'<td style="text-align:center">{totals[k]}</td>' for k, _ in cols)
        + f'<td style="text-align:center">{grand}</td></tr>'
    )

    thead = "".join(f'<th style="padding:10px 14px;text-align:center">{label}</th>' for _, label in cols)
    prev_y, prev_m = (int(month[:4]), int(month[5:])-1) if int(month[5:]) > 1 else (int(month[:4])-1, 12)
    next_y, next_m = (int(month[:4]), int(month[5:])+1) if int(month[5:]) < 12 else (int(month[:4])+1, 1)
    prev_str = f"{prev_y}-{prev_m:02d}"
    next_str = f"{next_y}-{next_m:02d}"

    html = f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8">
<title>護理師活動統計</title>
<style>
  body{{font-family:-apple-system,"Microsoft JhengHei",sans-serif;background:#f0f4f8;padding:40px 20px;color:#111}}
  .card{{max-width:700px;margin:0 auto;background:white;border-radius:12px;box-shadow:0 2px 16px rgba(0,0,0,.08);padding:40px 48px}}
  h1{{font-size:22px;font-weight:800;margin-bottom:4px}}
  .sub{{font-size:13px;color:#6b7280;margin-bottom:28px}}
  .nav{{display:flex;align-items:center;gap:16px;margin-bottom:20px}}
  .nav a{{color:#2563eb;text-decoration:none;font-size:14px}}
  .nav a:hover{{text-decoration:underline}}
  .month-label{{font-size:18px;font-weight:700;color:#1e3a5f}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th{{background:#f8fafc;padding:10px 14px;border:1px solid #e4e9f0;color:#374151;font-weight:700;text-align:left}}
  td{{padding:10px 14px;border:1px solid #e4e9f0}}
  tr:nth-child(even) td{{background:#fafbfc}}
  .empty{{color:#9ca3af;font-size:14px;padding:24px 0;text-align:center}}
</style></head>
<body><div class="card">
  <h1>護理師活動統計</h1>
  <div class="sub">僅限管理員查閱 — 此頁面不對外顯示</div>
  <div class="nav">
    <a href="/admin/stats?month={prev_str}">← {prev_str}</a>
    <span class="month-label">{month}</span>
    <a href="/admin/stats?month={next_str}">{next_str} →</a>
  </div>
  {"<table><thead><tr><th>護理師</th>" + thead + "<th style='text-align:center'>合計</th></tr></thead><tbody>" + rows_html + totals_html + "</tbody></table>" if nurses else '<div class="empty">本月尚無紀錄</div>'}
</div></body></html>"""

    return Response(content=html, media_type="text/html")


@app.get("/api/report")
def get_report(report_date: date | None = None) -> DailyReport:
    try:
        report = database.get_daily_report(report_date or date.today())
        hidden_keys = contacts.get_hidden_keys()
        call_required_keys = contacts.get_call_required_keys()
        submitted_keys = contacts.get_submitted_keys()
        excluded_keys = contacts.get_excluded_keys()          # (chart_number, category)
        mspt_completed_keys = contacts.get_mspt_completed_keys()  # (chart_number, mspt_stage, due_date)
        mspt_checkedin_keys = contacts.get_mspt_checkedin_keys()  # (chart_number, mspt_stage, due_date)
        on_hold_keys = contacts.get_on_hold_keys()            # (chart_number, category, due_date)
        manual_overrides = contacts.get_mspt_manual_overrides()
        as_of = report_date or date.today()

        _STAGE_NEXT_M = {'收案': '追1', '追1': '追2', '追2': '追3', '追3': '年度追蹤', '年度追蹤': '追1'}
        _MSPT_FOLLOWUP_DAYS = 70
        _MSPT_REOPEN_DAYS = 365

        def apply_mspt_overrides(entries: list[FollowupEntry]) -> list[FollowupEntry]:
            if not manual_overrides:
                return entries
            result = []
            for e in entries:
                ov = manual_overrides.get(e.patient.chart_number)
                if not ov:
                    result.append(e)
                    continue
                m_stage, m_date = ov['stage'], ov['date']
                # Skip override if IC data is already newer
                if e.last_visit_date and m_date <= e.last_visit_date:
                    result.append(e)
                    continue
                next_s = _STAGE_NEXT_M.get(m_stage)
                if not next_s:
                    result.append(e)
                    continue
                new_due = m_date + timedelta(days=_MSPT_FOLLOWUP_DAYS)
                new_ov = (as_of - new_due).days
                if new_ov < 0:
                    continue  # not yet due — drop from pending
                result.append(e.model_copy(update={
                    'mspt_stage': '收案' if new_ov > _MSPT_REOPEN_DAYS else next_s,
                    'last_stage': m_stage,
                    'last_visit_date': m_date,
                    'due_date': new_due,
                    'days_overdue': new_ov,
                    'contact_reason': '需重新收案+抽血' if new_ov > _MSPT_REOPEN_DAYS else None,
                }))
            return result

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
                if (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) in mspt_checkedin_keys:
                    continue
                if key in on_hold_keys:
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
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_checkedin_keys
        ]

        # Filter chronic patients suppressed by a manual pickup record
        _CHRONIC_GRACE = 5
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
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_checkedin_keys
        ]

        return DailyReport(
            report_date=report.report_date,
            chronic_prescriptions=filter_followups(chronic_prescriptions),
            mspt_followups=filter_followups(apply_mspt_overrides(report.mspt_followups)),
            mspt_inactive=filter_followups(apply_mspt_overrides(report.mspt_inactive)),
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
            mspt_checkedin=contacts.get_mspt_checkedin_entries(),
            chronic_manual_pickups=contacts.get_manual_pickup_entries(),
            on_hold=contacts.get_on_hold_entries(),
            mspt_manual=contacts.get_mspt_manual_entries(),
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
        raise HTTPException(status_code=500, detail="完成MSPT記錄儲存失敗，請稍後再試")


@app.delete("/api/mspt-completed")
def unmark_mspt_completed(req: MsptCompleteRequest) -> None:
    try:
        contacts.unmark_mspt_completed(req.chart_number, req.mspt_stage, req.due_date.isoformat())
    except Exception:
        logger.exception("unmark_mspt_completed failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷完成MSPT失敗，請稍後再試")



@app.post("/api/mspt-checkedin")
def mark_mspt_checkedin(req: NurseEntryRequest) -> None:
    try:
        contacts.mark_mspt_checkedin(req.entry, req.nurse)
    except Exception:
        logger.exception("mark_mspt_checkedin failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="待建檔記錄儲存失敗，請稍後再試")


@app.delete("/api/mspt-checkedin")
def unmark_mspt_checkedin(req: MsptCompleteRequest) -> None:
    try:
        contacts.unmark_mspt_checkedin(req.chart_number, req.mspt_stage, req.due_date.isoformat())
    except Exception:
        logger.exception("unmark_mspt_checkedin failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷待建檔失敗，請稍後再試")


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


@app.post("/api/on-hold")
def mark_on_hold(req: OnHoldRequest) -> dict:
    try:
        hold_id = contacts.mark_on_hold(req.entry, req.note, req.nurse)
        return {"hold_id": hold_id}
    except Exception:
        logger.exception("mark_on_hold failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="暫緩記錄儲存失敗，請稍後再試")


@app.post("/api/on-hold/manual")
def mark_on_hold_manual(req: ManualOnHoldRequest) -> dict:
    try:
        hold_id = contacts.mark_on_hold_manual(req.name, req.note, req.nurse, req.category)
        return {"hold_id": hold_id}
    except Exception:
        logger.exception("mark_on_hold_manual failed for %s", req.name)
        raise HTTPException(status_code=500, detail="暫緩記錄儲存失敗，請稍後再試")


@app.delete("/api/on-hold")
def remove_on_hold(req: OnHoldRemoveRequest) -> None:
    try:
        contacts.remove_on_hold(req.hold_id)
    except Exception:
        logger.exception("remove_on_hold failed for id=%s", req.hold_id)
        raise HTTPException(status_code=500, detail="撤銷暫緩失敗，請稍後再試")


@app.post("/api/mspt-manual")
def mark_mspt_manual(req: MsptManualRequest) -> None:
    try:
        contacts.mark_mspt_manual(
            req.entry.patient.chart_number,
            req.entry.patient.name,
            req.entry.patient.birth_date,
            req.mspt_stage,
            req.completed_date,
            req.nurse,
        )
    except Exception:
        logger.exception("mark_mspt_manual failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="手動標記儲存失敗，請稍後再試")


@app.delete("/api/mspt-manual")
def unmark_mspt_manual(req: MsptManualRemoveRequest) -> None:
    try:
        contacts.unmark_mspt_manual(req.chart_number)
    except Exception:
        logger.exception("unmark_mspt_manual failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷手動標記失敗，請稍後再試")


@app.get("/api/lab/{national_id}")
def get_lab_results(national_id: str) -> dict:
    """Return structured blood test results for a patient by national ID."""
    return lab_results.get_lab_results(national_id.strip().upper())


@app.get("/api/lab-debug")
def lab_debug() -> dict:
    """Diagnostic: inspect PAT_HIST.DBF field names and a few sample rows."""
    import os, struct
    zz = r"Z:\Z"
    path = os.path.join(zz, "PAT_HIST.DBF")
    result: dict = {"path": path, "exists": os.path.isfile(path), "fields": [], "sample_rows": []}
    if not result["exists"]:
        result["files_in_zz"] = os.listdir(zz) if os.path.isdir(zz) else "Z:\\Z not accessible"
        return result
    try:
        with open(path, "rb") as f:
            hdr = f.read(32)
            header_size = struct.unpack_from("<H", hdr, 8)[0]
            record_size = struct.unpack_from("<H", hdr, 10)[0]
            fields = []
            f.seek(32)
            while True:
                fd = f.read(32)
                if not fd or fd[0] == 0x0D:
                    break
                name = fd[:11].rstrip(b"\x00").decode("ascii", errors="replace").strip()
                flen = fd[16]
                if name:
                    fields.append((name, flen))
            result["fields"] = [f"{n}({l})" for n, l in fields]
            f.seek(header_size)
            col_offsets = []
            off = 1
            for n, l in fields:
                col_offsets.append((n, off, l))
                off += l
            count = 0
            while count < 3:
                raw = f.read(record_size)
                if not raw or len(raw) < record_size:
                    break
                if raw[0] == 0x2A:
                    continue
                row = {}
                for n, o, l in col_offsets:
                    try:
                        row[n] = raw[o:o+l].decode("big5").strip()
                    except Exception:
                        row[n] = raw[o:o+l].decode("latin-1").strip()
                result["sample_rows"].append(row)
                count += 1
    except Exception as e:
        result["error"] = str(e)
    return result


@app.get("/api/debug/mspt")
def debug_mspt(nat_id: str | None = None) -> dict:
    """Diagnostic: show MSPT stage detection across the full 2-year scan window.
    Pass ?nat_id=A123456789 to see a specific patient's full diagnosis."""
    import sqlite3 as _sqlite3
    from database import _ic_files_since, _parse_dbf_cached, _roc_to_date

    as_of = date.today()
    MAX_INACTIVE_DAYS = 2 * 365
    REOPEN_AFTER_DAYS = 365
    METABOLIC_FOLLOWUP_DAYS = 70
    _STAGE_NEXT = {'收案': '追1', '追1': '追2', '追2': '追3', '追3': '年度追蹤', '年度追蹤': '追1'}
    _STAGE_GAPS = {'收案': METABOLIC_FOLLOWUP_DAYS, '追1': METABOLIC_FOLLOWUP_DAYS,
                   '追2': METABOLIC_FOLLOWUP_DAYS, '追3': METABOLIC_FOLLOWUP_DAYS, '年度追蹤': METABOLIC_FOLLOWUP_DAYS}
    since = as_of - timedelta(days=MAX_INACTIVE_DAYS)
    ic_files = _ic_files_since(since)

    _MSPT_CODE_MAP = {
        'P7501C': '收案', 'P7502C': '追1', 'P75022C': '追2',
        'P75023C': '追3', 'P7503C': '年度追蹤',
    }

    all_mspt_drug_nos: set[str] = set()
    patient_stages: dict[str, list] = {}
    patient_info: dict[str, dict] = {}

    # Also collect raw P-file DRUG_NO values seen for this patient (diagnosis)
    patient_raw_drug_nos: dict[str, list] = {}

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
                    name  = r.get('NAME', '').strip()
                    birth = _roc_to_date(r.get('BIRTH', ''))
                    if name and birth:
                        prev = patient_info.get(nid)
                        if prev is None or v_date > prev['latest_date']:
                            patient_info[nid] = {'name': name, 'birth': birth.isoformat(),
                                                 'latest_date': v_date}
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
                if nid and nat_id and nid == nat_id and dn:
                    patient_raw_drug_nos.setdefault(nid, []).append(
                        {'drug_no': dn, 'cf': cf, 'file': os.path.basename(p_path)}
                    )
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
    db_status = None
    computed = None

    if nat_id:
        hist = patient_stages.get(nat_id)
        specific = sorted(hist, key=lambda x: x['date']) if hist else []

        # Compute what the system would show for this patient
        if specific:
            last_stage = specific[-1]['stage']
            last_date  = date.fromisoformat(specific[-1]['date'])
            days_inactive = (as_of - last_date).days
            next_stage = _STAGE_NEXT.get(last_stage)
            gap        = _STAGE_GAPS.get(last_stage)
            due_date   = last_date + timedelta(days=gap) if gap else None
            days_overdue = (as_of - due_date).days if due_date else None
            computed = {
                'last_stage': last_stage,
                'last_date': last_date.isoformat(),
                'days_inactive': days_inactive,
                'next_stage': next_stage,
                'gap_days': gap,
                'due_date': due_date.isoformat() if due_date else None,
                'days_overdue': days_overdue,
                'exceeds_MAX_INACTIVE': days_inactive > MAX_INACTIVE_DAYS,
                'exceeds_REOPEN_AFTER': days_overdue is not None and days_overdue > REOPEN_AFTER_DAYS,
                'verdict': (
                    'NOT_DUE_YET' if days_overdue is not None and days_overdue < 0
                    else 'NEEDS_REOPEN' if days_overdue is not None and days_overdue > REOPEN_AFTER_DAYS
                    else 'SHOULD_APPEAR' if days_overdue is not None and days_overdue >= 0
                    else 'UNKNOWN'
                ),
            }

        # Check contacts.db for this patient
        try:
            conn = _sqlite3.connect(contacts.DB_PATH)
            db_status = {
                'contacts': conn.execute(
                    "SELECT chart_number,category,due_date,mspt_stage,attempt,contacted_at FROM contacts WHERE chart_number=?",
                    (nat_id,)).fetchall(),
                'excluded': conn.execute(
                    "SELECT chart_number,category,reason,excluded_at FROM excluded WHERE chart_number=?",
                    (nat_id,)).fetchall(),
                'mspt_completed': conn.execute(
                    "SELECT chart_number,mspt_stage,due_date,completed_at FROM mspt_completed WHERE chart_number=?",
                    (nat_id,)).fetchall(),
                'mspt_checkedin': conn.execute(
                    "SELECT chart_number,mspt_stage,due_date,checkedin_at FROM mspt_checkedin WHERE chart_number=?",
                    (nat_id,)).fetchall(),
            }
            conn.close()
        except Exception as e:
            db_status = {'error': str(e)}

    return {
        'as_of': as_of.isoformat(),
        'scan_since': since.isoformat(),
        'ic_files_scanned': [os.path.basename(f) for f in ic_files],
        'mspt_drug_nos_found': sorted(all_mspt_drug_nos),
        'mspt_patients_detected': len(patient_stages),
        'last_stage_counts': last_stage_counts,
        'specific_patient_history': specific,
        'specific_patient_info': patient_info.get(nat_id) if nat_id else None,
        'specific_raw_drug_nos_in_p_files': patient_raw_drug_nos.get(nat_id, []) if nat_id else None,
        'computed_outcome': computed,
        'db_status': db_status,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
