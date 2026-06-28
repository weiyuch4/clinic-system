import asyncio
import hashlib
import logging
import os
import secrets
import threading
from datetime import date, timedelta

import tempfile

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

import backup
import config
import contacts
import database
import directory
import lab_report
import lab_results
from models import (
    ChartNumberRequest, ClinicContactRequest, ContactRequest, DailyReport, ExcludeRequest, FollowupEntry,
    HepReturnedCompleteRequest, ManualOnHoldRequest, ManualPickupRequest, MsptCompleteRequest,
    MsptManualRemoveRequest, MsptManualRequest, MsptSubmittableEntry,
    NurseEntryRequest, OnHoldRemoveRequest, OnHoldRequest, SendLineNotificationsRequest,
    SubmitRequest, UnexcludeRequest, UndoLineNotificationRequest,
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
directory.init()
lab_report.init()
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


@app.get("/doctor")
def doctor_page() -> Response:
    try:
        content = open("static/doctor.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入介面檔案")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/queue")
def get_queue() -> list[dict]:
    return database.get_queue()


@app.get("/api/patient/search")
def patient_search(q: str = "") -> list[dict]:
    return database.search_patients(q)


@app.get("/api/nurses")
def get_nurses() -> list[str]:
    return NURSE_NAMES


@app.get("/admin")
def admin_page(_: None = Depends(_require_admin)) -> Response:
    try:
        content = open("static/admin.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入後台介面")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/admin/stats")
def admin_stats_redirect() -> RedirectResponse:  # kept for old bookmarks
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/api/admin/stats")
def admin_stats_json(month: str | None = None, _: None = Depends(_require_admin)) -> dict:
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        return {"month": month, "stats": contacts.get_activity_stats(month)}
    except Exception:
        logger.exception("admin_stats_json failed for month=%s", month)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/admin/doctors")
def admin_doctors_json(month: str | None = None, _: None = Depends(_require_admin)) -> dict:
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        return {"month": month, "doctors": database.get_doctor_return_rates(month)}
    except Exception:
        logger.exception("admin_doctors failed for month=%s", month)
        raise HTTPException(status_code=500, detail="查詢失敗")


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
        line_unlinked_charts = contacts.get_line_unlinked_chart_numbers()
        alleypin_not_found_charts = contacts.get_alleypin_not_found_chart_numbers()
        line_recently_sent_map = contacts.get_line_recently_sent_map()  # (chart_number, template) -> last_sent_at iso date
        hep_returned_completed_keys = contacts.get_hep_returned_completed_keys()  # (chart_number, last_visit_date)
        manual_overrides = contacts.get_mspt_manual_overrides()
        as_of = report_date or date.today()

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
                next_s = database.MSPT_STAGE_NEXT.get(m_stage)
                if not next_s:
                    result.append(e)
                    continue
                new_due = m_date + timedelta(days=config.METABOLIC_FOLLOWUP_DAYS)
                new_ov = (as_of - new_due).days
                if new_ov < 0:
                    continue  # not yet due — drop from pending
                final_stage = '收案' if new_ov > database.MSPT_REOPEN_DAYS else next_s
                result.append(e.model_copy(update={
                    'mspt_stage': final_stage,
                    'needs_blood_test': database.mspt_needs_blood_test(final_stage, e.patient.chart_number, as_of),
                    'last_stage': m_stage,
                    'last_visit_date': m_date,
                    'due_date': new_due,
                    'days_overdue': new_ov,
                    'contact_reason': '需重新收案+抽血' if new_ov > database.MSPT_REOPEN_DAYS else None,
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
                # call_required must be set before picking the template (慢簽's
                # template depends on it) — compute the copy first, then derive
                # the template from it rather than from the stale original `e`.
                updated = e.model_copy(update={
                    "call_required": key in call_required_keys,
                    "line_unlinked": e.patient.chart_number in line_unlinked_charts,
                    "alleypin_not_found": e.patient.chart_number in alleypin_not_found_charts,
                    "phone": database.get_phone_by_chart_number(e.patient.chart_number),
                })
                template = _pick_line_template(updated)
                sent_at = line_recently_sent_map.get((e.patient.chart_number, template)) if template else None
                if sent_at:
                    days_ago = (as_of - date.fromisoformat(sent_at)).days
                    if 0 <= days_ago < config.RECENT_SEND_THRESHOLD_DAYS:
                        updated = updated.model_copy(update={"recently_sent_days_ago": days_ago})
                result.append(updated)
            return result

        # Filter 已聯絡 entries: exclude patients who have already returned since being contacted
        contacted_with_dates = contacts.get_contacted_with_dates()
        chronic_charts = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '慢簽'}
        mspt_charts    = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '代謝症候群'}
        hep_charts     = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == 'B肝'}
        chronic_visits = database.get_latest_visit_dates(chronic_charts, '慢簽')
        mspt_visits    = database.get_latest_visit_dates(mspt_charts, '代謝症候群')
        hep_visits     = database.get_latest_visit_dates(hep_charts, 'B肝')

        def has_returned(entry: FollowupEntry, contacted_at: date) -> bool:
            if entry.category == '慢簽':
                visits = chronic_visits
            elif entry.category == '代謝症候群':
                visits = mspt_visits
            else:
                visits = hep_visits
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
        manual_pickup_map = contacts.get_manual_pickup_map()

        def chronic_suppressed(entry: FollowupEntry) -> bool:
            mp = manual_pickup_map.get(entry.patient.chart_number)
            if not mp:
                return False
            pickup_date = date.fromisoformat(mp[0])
            # If IC already has a newer visit, the manual record is superseded
            if entry.last_visit_date and pickup_date <= entry.last_visit_date:
                return False
            # Manual pickup is more recent than IC — suppress until IC captures a newer visit.
            # No time-based expiry: the clinic uses this to record pickups missed by the IC
            # system (e.g. missing files), so the date may be weeks in the past.
            return True

        chronic_prescriptions = [e for e in report.chronic_prescriptions if not chronic_suppressed(e)]

        # Same pattern for B/C肝: a nurse can manually mark 完成B肝 from the
        # pending list (e.g. the IC visit/order wasn't captured), which should
        # suppress the entry until IC data itself shows a newer confirmed visit.
        hep_completed_latest = contacts.get_hep_completed_latest_map()

        def hep_suppressed(entry: FollowupEntry) -> bool:
            completed_str = hep_completed_latest.get(entry.patient.chart_number)
            if not completed_str:
                return False
            completed_date = date.fromisoformat(completed_str)
            if entry.last_visit_date and completed_date <= entry.last_visit_date:
                return False
            return True

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
            # 長期未回診 (結案/再收案) is merged into the same list rather than a
            # separate section — we want to keep notifying these patients too,
            # and a separate collapsed section was too easy to forget to check.
            # Sorted ascending so mildly-overdue patients surface before the
            # open-ended 結案/再收案 backlog, which can accumulate indefinitely.
            hep_followups=sorted(
                [
                    e for e in filter_followups(report.hep_followups) + filter_followups(report.hep_inactive)
                    if not hep_suppressed(e)
                ],
                key=lambda e: e.days_overdue,
            ),
            hep_returned=[
                e for e in report.hep_returned
                if (e.patient.chart_number, e.last_visit_date.isoformat()) not in hep_returned_completed_keys
            ],
            hep_returned_completed=contacts.get_hep_returned_completed_entries(),
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


@app.post("/api/hep-returned-completed")
def mark_hep_returned_completed(req: NurseEntryRequest) -> None:
    try:
        contacts.mark_hep_returned_completed(req.entry, req.nurse)
    except Exception:
        logger.exception("mark_hep_returned_completed failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="完成B肝記錄儲存失敗，請稍後再試")


@app.delete("/api/hep-returned-completed")
def unmark_hep_returned_completed(req: HepReturnedCompleteRequest) -> None:
    try:
        contacts.unmark_hep_returned_completed(req.chart_number, req.last_visit_date.isoformat())
    except Exception:
        logger.exception("unmark_hep_returned_completed failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


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


_line_batch_state: dict = {
    "running": False, "category": None, "dry_run": False,
    "total": 0, "results": [], "error": None,
}
_line_batch_task: asyncio.Task | None = None  # kept separate from _line_batch_state — not JSON-serializable


def _pick_line_template(entry: FollowupEntry) -> str | None:
    if entry.category == "慢簽":
        return "立即二次通知拿藥" if entry.call_required else "立即拿藥提醒"
    if entry.category == "代謝症候群":
        return "立即MSPT回診抽血" if entry.needs_blood_test else "立即MSPT定期追蹤"
    if entry.category == "B肝":
        return "立即B型肝炎追蹤"
    return None


async def _run_line_batch_task(targets: list[dict], dry_run: bool, nurse: str) -> None:
    import line_notify  # deferred — depends on playwright, which is optional for the rest of the app

    def on_result(result: dict) -> None:
        _line_batch_state["results"].append(result)
        target = next((t for t in targets if t["chart_number"] == result["chart_number"]), None)
        if not target:
            return

        try:
            contacts.log_line_notification(
                chart_number=target["chart_number"],
                name=target["entry"].patient.name,
                birth_date=target["entry"].patient.birth_date.isoformat(),
                category=target["entry"].category,
                template=target["template"],
                status=result["status"],
                detail=result.get("detail", ""),
                dry_run=dry_run,
                nurse=nurse,
            )
        except Exception:
            logger.exception("failed to log LINE notification result for %s", target["chart_number"])

        if result["status"] == "sent" and not dry_run:
            try:
                if target["call_required"]:
                    contacts.mark_called(target["entry"], nurse)
                else:
                    contacts.mark_contacted(target["entry"], nurse)
            except Exception:
                logger.exception("failed to mark %s as contacted after LINE send", target["chart_number"])
            try:
                contacts.clear_line_unlinked(target["chart_number"])
            except Exception:
                logger.exception("failed to clear line_unlinked flag for %s", target["chart_number"])
            try:
                contacts.record_line_sent(
                    target["chart_number"], target["template"], target["entry"].patient.name,
                    date.today().isoformat(), nurse,
                )
            except Exception:
                logger.exception("failed to record send date for %s", target["chart_number"])

        if result["status"] == "line_not_linked":
            try:
                contacts.flag_line_unlinked(target["chart_number"], target["entry"].patient.name, nurse)
            except Exception:
                logger.exception("failed to flag %s as line_unlinked", target["chart_number"])

        if result["status"] == "not_found":
            try:
                contacts.flag_alleypin_not_found(target["chart_number"], target["entry"].patient.name, nurse)
            except Exception:
                logger.exception("failed to flag %s as alleypin_not_found", target["chart_number"])
        elif result["status"] != "error":
            # Any other status means _find_patient_row succeeded this time
            # ("error" is ambiguous — it can happen during the search itself,
            # so it's left alone rather than assumed to mean "found").
            try:
                contacts.clear_alleypin_not_found(target["chart_number"])
            except Exception:
                logger.exception("failed to clear alleypin_not_found flag for %s", target["chart_number"])

        if result["status"] == "recently_sent":
            try:
                contacts.record_line_sent(
                    target["chart_number"], target["template"], target["entry"].patient.name,
                    result["last_sent_at"], nurse,
                )
            except Exception:
                logger.exception("failed to record send date for %s", target["chart_number"])

    try:
        await line_notify.run_batch(
            [
                {
                    "chart_number": t["chart_number"],
                    "dob": t["entry"].patient.birth_date,
                    "name": t["entry"].patient.name,
                    "template": t["template"],
                }
                for t in targets
            ],
            dry_run=dry_run,
            on_result=on_result,
        )
    except Exception as e:
        logger.exception("LINE batch send failed")
        _line_batch_state["error"] = str(e)
    finally:
        _line_batch_state["running"] = False


@app.post("/api/send-line-notifications")
async def send_line_notifications(req: SendLineNotificationsRequest) -> dict:
    try:
        import line_notify  # noqa: F401 — just checking it (and playwright) is installed
    except ImportError:
        raise HTTPException(status_code=500, detail="尚未安裝 playwright，請執行 pip install playwright 並 playwright install chromium")

    if _line_batch_state["running"]:
        raise HTTPException(status_code=409, detail="已有一個批次發送正在進行中，請稍候")

    report_data = get_report(report_date=None)
    source = {
        "慢簽": report_data.chronic_prescriptions,
        "代謝症候群": report_data.mspt_followups,
        "B肝": report_data.hep_followups,
    }[req.category]

    if req.chart_numbers:
        wanted = set(req.chart_numbers)
        source = [e for e in source if e.patient.chart_number in wanted]

    targets = []
    for e in source:
        template = _pick_line_template(e)
        if not template:
            continue
        targets.append({
            "chart_number": e.patient.chart_number,
            "entry": e,
            "template": template,
            "call_required": e.call_required,
        })

    if req.limit is not None:
        targets = targets[:req.limit]

    if not targets:
        return {"started": False, "total": 0, "detail": "沒有符合條件的病患"}

    _line_batch_state.update({
        "running": True, "category": req.category, "dry_run": req.dry_run,
        "total": len(targets), "results": [], "error": None,
    })
    global _line_batch_task
    _line_batch_task = asyncio.create_task(_run_line_batch_task(targets, req.dry_run, req.nurse))
    return {"started": True, "total": len(targets)}


@app.get("/api/send-line-notifications/status")
def get_line_notifications_status() -> dict:
    return _line_batch_state


@app.post("/api/send-line-notifications/cancel")
async def cancel_line_notifications() -> dict:
    """Cancel any in-progress batch and force-close the automation browser —
    covers both "it's stuck mid-batch" and "the browser itself is stuck for
    some unrelated reason" in one action. Always attempts the browser stop,
    even if nothing was running, so the CDP port is reliably freed either way."""
    cancelled = False
    if _line_batch_task is not None and not _line_batch_task.done():
        _line_batch_task.cancel()
        cancelled = True

    browser_stopped = False
    try:
        import line_notify
        browser_stopped = await line_notify.stop_browser()
    except ImportError:
        pass
    except Exception:
        logger.exception("stop_browser failed during cancel")

    _line_batch_state["running"] = False
    if cancelled:
        _line_batch_state["error"] = "已手動取消"
    return {"cancelled": cancelled, "browser_stopped": browser_stopped}


@app.get("/api/admin/line-notification-log")
def get_line_notification_log(_: None = Depends(_require_admin)) -> list:
    return contacts.get_line_notification_log()


@app.post("/api/admin/line-notification-log/{log_id}/undo")
async def undo_line_notification(log_id: int, req: UndoLineNotificationRequest, _: None = Depends(_require_admin)) -> dict:
    entry = contacts.get_line_notification_log_entry(log_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="找不到此記錄")
    if entry["status"] != "sent":
        raise HTTPException(status_code=400, detail="此記錄並未成功發送，無需復原")
    if entry["undone_at"]:
        raise HTTPException(status_code=400, detail="此記錄已經復原過了")

    try:
        import line_notify
    except ImportError:
        raise HTTPException(status_code=500, detail="尚未安裝 playwright，請執行 pip install playwright 並 playwright install chromium")

    target = {
        "chart_number": entry["chart_number"],
        "dob_roc": line_notify.to_roc_slash_date(date.fromisoformat(entry["birth_date"])),
        "name": entry["name"],
        "template": entry["template"],
    }
    try:
        result = await line_notify.run_undo(target, req.dry_run)
    except Exception as e:
        logger.exception("undo_line_notification failed for log_id=%s", log_id)
        raise HTTPException(status_code=500, detail=f"復原失敗：{e}")

    if result["status"] == "sent":
        contacts.mark_line_notification_undone(log_id, req.nurse)
    return result


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



@app.post("/api/admin/lab-report")
async def upload_lab_report(
    file: UploadFile = File(...),
    _: None = Depends(_require_admin),
) -> dict:
    if not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="請上傳 .xlsx 檔案")
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        report_id = lab_report.save_report(tmp_path, file.filename)
        return {"id": report_id}
    except Exception:
        logger.exception("upload_lab_report failed for %s", file.filename)
        raise HTTPException(status_code=500, detail="檔案解析失敗，請確認格式正確")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@app.get("/api/admin/lab-reports")
def list_lab_reports(_: None = Depends(_require_admin)) -> list:
    try:
        return lab_report.list_reports()
    except Exception:
        logger.exception("list_lab_reports failed")
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/admin/lab-report/{report_id}")
def get_lab_report(report_id: int, _: None = Depends(_require_admin)) -> dict:
    try:
        data = lab_report.get_report(report_id)
        if data is None:
            raise HTTPException(status_code=404, detail="找不到此報告")
        return data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_lab_report failed for id=%s", report_id)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.delete("/api/admin/lab-report/{report_id}")
def delete_lab_report(report_id: int, _: None = Depends(_require_admin)) -> None:
    try:
        if not lab_report.delete_report(report_id):
            raise HTTPException(status_code=404, detail="找不到此報告")
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_lab_report failed for id=%s", report_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


@app.get("/api/directory")
def list_clinic_contacts() -> list:
    try:
        return directory.list_contacts()
    except Exception:
        logger.exception("list_clinic_contacts failed")
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.post("/api/directory")
def add_clinic_contact(req: ClinicContactRequest) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="名稱不可空白")
    try:
        new_id = directory.add_contact(req.name.strip(), req.category.strip(), req.phone.strip(), req.note.strip(), req.nurse)
        return {"id": new_id}
    except Exception:
        logger.exception("add_clinic_contact failed")
        raise HTTPException(status_code=500, detail="新增失敗")


@app.delete("/api/directory/{contact_id}")
def delete_clinic_contact(contact_id: int) -> None:
    try:
        if not directory.delete_contact(contact_id):
            raise HTTPException(status_code=404, detail="找不到此聯絡人")
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_clinic_contact failed for id=%s", contact_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
