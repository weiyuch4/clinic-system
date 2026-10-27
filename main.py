import asyncio
import logging
import os
import re as _re
import requests
import secrets
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import tempfile

from dotenv import load_dotenv
_env_file = ".env.dev" if os.path.exists(".env.dev") else ".env"
load_dotenv(_env_file, override=True)

import uvicorn
from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import auth
import backup
import config
import contacts
import database
import db
import directory
import inventory
import lab_report
import lab_results
import line_service
import broadcast_service
import ai_agent_service
import review_service
import scheduler
import settings as _settings
from models import (
    BloodDismissRequest, BloodNotifiedRequest, BloodPhysicalRequest, BulletinNoteRequest, ChartNumberRequest, ChangePasswordRequest, ClinicContactRequest, ContactRequest, CopyWeekRequest,
    StickyNoteRequest, DoctorNoteRequest,
    CreateUserRequest, DailyReport,
    CkdManualInactiveRequest, ExcludeRequest, FollowupEntry, HepManualReturnedRequest, HepReintakeRequest, HepReturnedCompleteRequest, LineUnlinkedRequest, LoginRequest, LoginResponse,
    ManualOnHoldRequest, ManualPickupRequest,
    MsptCompleteRequest, MsptManualRemoveRequest, MsptManualRequest, MsptSubmittableEntry,
    NurseEntryRequest, NurseNameRequest, OnHoldRemoveRequest, OnHoldRequest, PublishWeekRequest,
    RenameUserRequest, ResetPasswordRequest, SalaryRecordRequest, SendLineNotificationsRequest, ShiftEntry, SubmitRequest,
    UnexcludeRequest, UndoLineNotificationRequest, UpdateExclusionReasonRequest,
    BroadcastCreateRequest,
    AiAgentSettingsRequest,
    AiKbUpsertRequest,
    ReviewSettingsRequest,
    ReviewSendRequest,
)

# ── Edit this for your clinic's name ───────────────────────────────────────────
CLINIC_NAME = "魏宏杰診所"
# ───────────────────────────────────────────────────────────────────────────────

# ── Edit this list to match your clinic's nurse names ──────────────────────────
NURSE_NAMES: list[str] = ["媛淩", "巧潔", "巧菱", "惠茗"]
# ───────────────────────────────────────────────────────────────────────────────

CLOUD_MODE = os.environ.get("CLOUD_MODE", "").lower() in ("1", "true", "yes")
_SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")

# Clinic-specific: hide prescriptions due before this date (set when adopting the feature mid-cycle).
# Leave unset for new clinics to show all prescriptions within PRESCRIPTION_GRACE_DAYS.
_PRESCRIPTION_START_DATE: date | None = None
_psd_env = os.environ.get("PRESCRIPTION_START_DATE", "")
if _psd_env:
    try:
        _PRESCRIPTION_START_DATE = date.fromisoformat(_psd_env)
    except ValueError:
        pass

# Per-clinic server-side caches. No TTL — invalidated only by writes and at midnight
# (date mismatch). Write endpoints call the invalidate helpers immediately, so cached
# data is always consistent with the DB during active use. The only "cold start" is
# after a Railway deploy (process restart clears the dict).
_report_cache: dict[int, tuple[date, "DailyReport"]] = {}
_blood_pending_cache: dict[int, list] = {}
_blood_physical_cache: dict[int, list] = {}
_bind_rate: dict = {}  # ip -> [timestamps]
_pin_failures: dict = {}  # (clinic_id, nurse_name) -> [timestamps]
_PIN_MAX_ATTEMPTS = 5
_PIN_LOCKOUT_SECONDS = 900  # 15 minutes


def _invalidate_report_cache(clinic_id: int) -> None:
    _report_cache.pop(clinic_id, None)


def _invalidate_blood_pending_cache(clinic_id: int) -> None:
    _blood_pending_cache.pop(clinic_id, None)


def _invalidate_blood_physical_cache(clinic_id: int) -> None:
    _blood_physical_cache.pop(clinic_id, None)


logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=CLINIC_NAME)
app.mount("/static", StaticFiles(directory="static"), name="static")

try:
    db.init_pool(minconn=2, maxconn=18)
except RuntimeError as e:
    logger.warning(f"PostgreSQL pool not initialized: {e}. Set DATABASE_URL to enable database access.")

auth.init()
contacts.init()
directory.init()
inventory.init()
lab_report.init()
line_service.init()
broadcast_service.init()
ai_agent_service.init()
review_service.init()

# ── Scheduler ──────────────────────────────────────────────────────────────────
import atexit
from apscheduler.triggers.interval import IntervalTrigger as _IntervalTrigger
scheduler.start()
scheduler.get().add_job(
    broadcast_service.tick_scheduled,
    _IntervalTrigger(minutes=1),
    id="broadcast_tick",
    replace_existing=True,
)
atexit.register(scheduler.shutdown)

backup.run()
if CLOUD_MODE:
    database._blood_status_ready.set()  # no BIO files on cloud — skip warmup
else:
    threading.Thread(target=database.warmup_cache, daemon=True).start()



if not auth.has_any_users():
    _default_pass = os.environ.get("BOOTSTRAP_ADMIN_PASS", "")
    if not _default_pass:
        raise RuntimeError(
            "BOOTSTRAP_ADMIN_PASS environment variable must be set before first run. "
            "Set it to a strong password and restart."
        )
    auth.bootstrap_clinic(
        clinic_slug="clinic1",
        clinic_name="診所",
        admin_username="clinic",
        admin_password=_default_pass,
        nurse_names=[],
        nurse_password="",
        must_change_password=True,
    )
    logger.warning(
        "No users found — bootstrapped admin account (username: clinic). "
        "Password was set from BOOTSTRAP_ADMIN_PASS. Change it after first login."
    )

if not contacts.get_nurses():  # first run on this DB — seed from the hardcoded defaults above
    for _name in NURSE_NAMES:
        contacts.add_nurse(_name)


# ── API auth middleware ─────────────────────────────────────────────────────────
# All /api/* routes require a valid JWT.  Static files, page routes, and the
# /auth/* endpoints themselves are public.  Nurse identity inside the session
# still comes from request body fields (Option B shared-session model).
@app.middleware("http")
async def require_auth_for_api(request: Request, call_next):
    _sync_exempt = {"/api/admin/login", "/api/sync/push", "/api/sync/push-lab", "/api/sync/push-blood-pending", "/api/sync/push-prescriptions", "/api/sync/push-doctor-rates", "/api/sync/status", "/api/sync/push-blood-recall", "/api/sync/blood-recall-settings", "/api/sync/clinic-settings", "/api/sync/open-episodes", "/api/sync/push-returns"}
    if request.url.path.startswith("/api/") and request.url.path not in _sync_exempt:
        token = request.headers.get("Authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        if not token:
            return JSONResponse({"detail": "請先登入"}, status_code=401)
        try:
            auth.decode_access_token(token)
        except Exception:
            return JSONResponse({"detail": "憑證無效或已過期，請重新登入"}, status_code=401)
    return await call_next(request)


_REFRESH_COOKIE = "refresh_token"
_COOKIE_MAX_AGE = auth.REFRESH_TOKEN_DAYS * 86400


@app.post("/api/admin/login")
def admin_login(body: LoginRequest) -> dict:
    """Admin portal login — returns an access token only, NO refresh cookie.
    Desktop: stored in sessionStorage (cleared on tab close).
    Mobile (remember=True): stored in localStorage with 30-day expiry."""
    CLINIC_ID = 1
    user = auth.get_user_by_username(CLINIC_ID, body.username)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="此帳號無管理員權限")
    minutes = auth.REFRESH_TOKEN_DAYS * 24 * 60 if body.remember else None
    token = auth.create_access_token(
        user_id=user["id"], clinic_id=user["clinic_id"],
        role=user["role"], display_name=user["display_name"],
        minutes=minutes,
    )
    return {"access_token": token, "display_name": user["display_name"]}


@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest) -> JSONResponse:
    # Single-tenant: clinic_id is always 1 for now.
    # When multi-tenant, resolve clinic_id from body.clinic_slug here.
    CLINIC_ID = 1
    user = auth.get_user_by_username(CLINIC_ID, body.username)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    access_token  = auth.create_access_token(
        user_id=user["id"], clinic_id=user["clinic_id"],
        role=user["role"], display_name=user["display_name"],
    )
    refresh_token = auth.create_refresh_token(user["id"])
    response = JSONResponse(LoginResponse(
        access_token=access_token,
        display_name=user["display_name"],
        role=user["role"],
        must_change_password=bool(user["must_change_password"]),
    ).model_dump())
    response.set_cookie(
        key=_REFRESH_COOKIE, value=refresh_token,
        max_age=_COOKIE_MAX_AGE, httponly=True,
        samesite="strict", secure=True,
    )
    return response


@app.post("/auth/refresh")
def refresh_token(request: Request) -> JSONResponse:
    old_raw = request.cookies.get(_REFRESH_COOKIE)
    if not old_raw:
        raise HTTPException(status_code=401, detail="Session 已過期，請重新登入")
    new_raw, user_id = auth.rotate_refresh_token(old_raw)
    user = auth.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="帳號不存在")
    access_token = auth.create_access_token(
        user_id=user["id"], clinic_id=user["clinic_id"],
        role=user["role"], display_name=user["display_name"],
    )
    response = JSONResponse({"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key=_REFRESH_COOKIE, value=new_raw,
        max_age=_COOKIE_MAX_AGE, httponly=True,
        samesite="strict", secure=True,
    )
    return response


@app.post("/auth/logout")
def logout(request: Request) -> JSONResponse:
    raw = request.cookies.get(_REFRESH_COOKIE)
    if raw:
        auth.delete_refresh_token(raw)
    response = JSONResponse({"ok": True})
    response.delete_cookie(_REFRESH_COOKIE)
    return response


@app.patch("/api/auth/change-password")
def change_password(body: ChangePasswordRequest,
                    user: auth.CurrentUser = Depends(auth.get_current_user)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")
    try:
        auth.change_own_password(user.user_id, user.clinic_id, body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"ok": True}


@app.get("/change-password")
def change_password_page() -> Response:
    try:
        content = open("static/change-password.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入頁面")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/nurse-mgmt")
def nurse_mgmt_page() -> Response:
    try:
        content = open("static/nurse-mgmt.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入頁面")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/admin/users")
def admin_list_users(admin: auth.CurrentUser = Depends(auth.require_admin)):
    rows = auth.get_all_users_including_inactive(admin.clinic_id)
    return [dict(r) for r in rows]


@app.post("/api/admin/users", status_code=201)
def admin_create_user(body: CreateUserRequest,
                      admin: auth.CurrentUser = Depends(auth.require_admin)):
    if body.role not in ("admin", "nurse"):
        raise HTTPException(status_code=400, detail="role 必須是 admin 或 nurse")
    if len(body.initial_password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少需要 6 個字元")
    existing = auth.get_user_by_username(admin.clinic_id, body.username)
    if existing:
        raise HTTPException(status_code=409, detail="此帳號名稱已存在")
    user_id = auth.create_user(
        clinic_id=admin.clinic_id,
        username=body.username,
        display_name=body.display_name,
        role=body.role,
        password=body.initial_password,
        created_by=admin.user_id,
    )
    return {"id": user_id, "username": body.username, "display_name": body.display_name}


@app.patch("/api/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, body: ResetPasswordRequest,
                         admin: auth.CurrentUser = Depends(auth.require_admin)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少需要 6 個字元")
    auth.update_password(user_id, admin.clinic_id, body.new_password)
    return {"ok": True}


@app.patch("/api/admin/users/{user_id}/username")
def admin_rename_user(user_id: int, body: RenameUserRequest,
                      admin: auth.CurrentUser = Depends(auth.require_admin)):
    new_username = body.new_username.strip()
    if not new_username:
        raise HTTPException(status_code=400, detail="帳號不能為空")
    try:
        auth.update_username(user_id, admin.clinic_id, new_username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def admin_deactivate_user(user_id: int,
                          admin: auth.CurrentUser = Depends(auth.require_admin)):
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="無法停用自己的帳號")
    auth.deactivate_user(user_id, admin.clinic_id)
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_get_settings(admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    return contacts.get_clinic_settings(admin.clinic_id)


@app.patch("/api/admin/settings")
def admin_update_settings(body: dict, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    allowed = set(contacts.CLINIC_SETTINGS_DEFAULTS.keys())
    unknown = set(body.keys()) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支援的設定項目: {', '.join(unknown)}")
    _date_keys = {"prescription_cutover_date"}
    for k, v in body.items():
        if k in _date_keys:
            if v is not None:
                try:
                    date.fromisoformat(str(v))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"{k} 必須為 YYYY-MM-DD 格式或 null")
        elif k in contacts.CLINIC_SETTINGS_ZERO_OK:
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise HTTPException(status_code=400, detail=f"{k} 必須為 0 或正整數")
        elif not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise HTTPException(status_code=400, detail=f"{k} 必須為正整數")
    try:
        return contacts.update_clinic_settings(body, admin.clinic_id)
    except Exception as exc:
        logger.exception("update_clinic_settings failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"設定儲存失敗：{exc}")


@app.post("/api/admin/users/{user_id}/reactivate")
def admin_reactivate_user(user_id: int,
                          admin: auth.CurrentUser = Depends(auth.require_admin)):
    auth.reactivate_user(user_id, admin.clinic_id)
    return {"ok": True}


# ── Announcements ────────────────────────────────────────────────────────────

@app.get("/api/announcements")
def list_announcements(user: auth.CurrentUser = Depends(auth.get_current_user),
                       nurse: str = ""):
    from db import _conn as _db
    nurse_name = nurse.strip() or user.display_name
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT a.id, a.title, a.body, a.created_by, a.created_at,
                          EXISTS(
                              SELECT 1 FROM announcement_reads r
                              WHERE r.announcement_id = a.id
                                AND r.clinic_id = a.clinic_id
                                AND r.nurse_name = %s
                          ) AS is_read
                   FROM announcements a
                   WHERE a.clinic_id = %s AND a.is_active = TRUE
                   ORDER BY a.created_at DESC""",
                (nurse_name, user.clinic_id),
            )
            return cur.fetchall()


@app.post("/api/announcements", status_code=201)
def create_announcement(body: dict,
                        admin: auth.CurrentUser = Depends(auth.require_admin)):
    title = (body.get("title") or "").strip()
    text  = (body.get("body")  or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="標題不能為空")
    from db import _conn as _db
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO announcements (clinic_id, title, body, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (admin.clinic_id, title, text, admin.display_name, now),
            )
            row = cur.fetchone()
    return {"id": row["id"], "ok": True}


@app.post("/api/announcements/{ann_id}/read")
def mark_announcement_read(ann_id: int,
                           user: auth.CurrentUser = Depends(auth.get_current_user),
                           body: dict = Body(default={})):
    from db import _conn as _db
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    nurse = (body.get("nurse") or "").strip() or user.display_name
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO announcement_reads (announcement_id, clinic_id, nurse_name, read_at)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (announcement_id, clinic_id, nurse_name) DO NOTHING""",
                (ann_id, user.clinic_id, nurse, now),
            )
    return {"ok": True}


@app.delete("/api/admin/announcements/{ann_id}", status_code=204)
def close_announcement(ann_id: int,
                       admin: auth.CurrentUser = Depends(auth.require_admin)):
    from db import _conn as _db
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE announcements SET is_active = FALSE WHERE id = %s AND clinic_id = %s",
                (ann_id, admin.clinic_id),
            )
    return Response(status_code=204)


@app.get("/api/admin/announcements/{ann_id}/reads")
def get_announcement_reads(ann_id: int,
                           admin: auth.CurrentUser = Depends(auth.require_admin)):
    from db import _conn as _db
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT nurse_name, read_at FROM announcement_reads
                   WHERE announcement_id = %s AND clinic_id = %s
                   ORDER BY read_at""",
                (ann_id, admin.clinic_id),
            )
            return cur.fetchall()


@app.get("/login")
def login_page() -> Response:
    try:
        content = open("static/login.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入登入頁面")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/doctor")
def doctor_page() -> Response:
    try:
        content = open("static/doctor.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入介面檔案")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/dashboard")
def dashboard_page() -> Response:
    try:
        content = open("static/dashboard.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入介面檔案")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse("static/sw.js", headers={
        "Content-Type": "application/javascript",
        "Service-Worker-Allowed": "/",
        "Cache-Control": "no-cache",
    })


@app.get("/{page}")
def app_page(page: str) -> Response:
    if not _re.fullmatch(r"[a-z0-9_-]{1,40}", page):
        raise HTTPException(status_code=404, detail="頁面不存在")
    try:
        content = open(f"static/{page}.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=404, detail="頁面不存在")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


# Legacy /new/* redirects — keeps old bookmarks working
@app.get("/new")
def legacy_new_dashboard():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=301)


@app.get("/new/{page}")
def legacy_new_page(page: str):
    from fastapi.responses import RedirectResponse
    if not _re.fullmatch(r"[a-z0-9_-]{1,40}", page):
        raise HTTPException(status_code=404, detail="頁面不存在")
    return RedirectResponse(url=f"/{page}", status_code=301)


@app.get("/warmup-status")
def get_warmup_status():
    return {"blood_status_ready": database._blood_status_ready.is_set()}


@app.get("/api/queue")
def get_queue() -> list[dict]:
    return database.get_queue()


@app.get("/api/patient/search")
def patient_search(q: str = "") -> list[dict]:
    return database.search_patients(q)


@app.get("/api/patients/search")
def search_patients_api(q: str = Query("", min_length=1), user: auth.CurrentUser = Depends(auth.get_current_user)):
    try:
        return {"patients": contacts.search_patients_cloud(q.strip(), user.clinic_id)}
    except Exception:
        logger.exception("search_patients_api failed")
        raise HTTPException(status_code=500, detail="搜尋失敗")


@app.get("/api/patient-profile/{chart_number}")
def get_patient_profile_api(chart_number: str, user: auth.CurrentUser = Depends(auth.get_current_user)):
    try:
        profile = contacts.get_patient_profile(chart_number, user.clinic_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到病患資料")
        return profile
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_patient_profile_api failed")
        raise HTTPException(status_code=500, detail="載入失敗")


@app.get("/api/nurses")
def get_nurses(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[str]:
    return contacts.get_nurses(user.clinic_id)


@app.get("/api/nurses/with-pin-status")
def get_nurses_with_pin_status(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    return contacts.get_nurses_with_pin_status(user.clinic_id)


@app.get("/api/history")
def get_history(q: str = Query(..., min_length=1), user: auth.CurrentUser = Depends(auth.get_current_user)):
    if not q.strip():
        raise HTTPException(status_code=422, detail="請輸入搜尋字詞")
    try:
        events = contacts.get_contact_history(q.strip(), user.clinic_id)
        return {"events": events}
    except Exception:
        logger.exception("get_history failed")
        raise HTTPException(status_code=500, detail="查詢失敗，請稍後再試")


@app.get("/api/bulletin")
def get_bulletin(limit: int = 100, user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    try:
        return contacts.get_bulletin_notes(limit, user.clinic_id)
    except Exception:
        logger.exception("get_bulletin failed")
        raise HTTPException(status_code=500, detail="載入留言失敗")


@app.post("/api/bulletin")
def add_bulletin(req: BulletinNoteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="內容不可空白")
    try:
        return contacts.add_bulletin_note(req.nurse or "（未選擇）", content, user.clinic_id)
    except Exception:
        logger.exception("add_bulletin failed")
        raise HTTPException(status_code=500, detail="發布失敗")


@app.delete("/api/bulletin/{note_id}")
def delete_bulletin(note_id: int, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        note = contacts.get_bulletin_note(note_id, user.clinic_id)
        if note and note["nurse"] != user.display_name and user.role != "admin":
            raise HTTPException(status_code=403, detail="只能刪除自己的留言")
        contacts.delete_bulletin_note(note_id, user.clinic_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_bulletin failed for id=%s", note_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


@app.get("/api/notes")
def get_notes(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    try:
        return contacts.get_sticky_notes(user.clinic_id)
    except Exception:
        logger.exception("get_notes failed")
        raise HTTPException(status_code=500, detail="載入便利貼失敗")


@app.post("/api/notes")
def add_note(req: StickyNoteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="內容不可空白")
    color = req.color if req.color in {"yellow", "blue", "green", "pink"} else "yellow"
    try:
        return contacts.add_sticky_note(content, color, req.nurse, user.clinic_id)
    except Exception:
        logger.exception("add_note failed")
        raise HTTPException(status_code=500, detail="新增便利貼失敗")


@app.patch("/api/notes/{note_id}")
def update_note(note_id: int, req: StickyNoteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="內容不可空白")
    try:
        return contacts.update_sticky_note(note_id, content, req.color, user.clinic_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="找不到便利貼")
    except Exception:
        logger.exception("update_note failed for id=%s", note_id)
        raise HTTPException(status_code=500, detail="更新便利貼失敗")


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        note = next((n for n in contacts.get_sticky_notes(user.clinic_id) if n["id"] == note_id), None)
        if note and note.get("nurse") and note["nurse"] != user.display_name and user.role != "admin":
            raise HTTPException(status_code=403, detail="只能刪除自己的便利貼")
        contacts.delete_sticky_note(note_id, user.clinic_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_note failed for id=%s", note_id)
        raise HTTPException(status_code=500, detail="刪除便利貼失敗")


@app.get("/api/doctor-notes")
def get_doctor_notes(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    try:
        return contacts.get_doctor_notes(user.clinic_id)
    except Exception:
        logger.exception("get_doctor_notes failed")
        raise HTTPException(status_code=500, detail="載入醫師留言失敗")


@app.post("/api/doctor-notes")
def add_doctor_note(req: DoctorNoteRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    title = req.title.strip()
    content = req.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="標題與內容不可空白")
    try:
        return contacts.add_doctor_note(title, content, admin.display_name, admin.clinic_id)
    except Exception:
        logger.exception("add_doctor_note failed")
        raise HTTPException(status_code=500, detail="新增醫師留言失敗")


@app.delete("/api/doctor-notes/{note_id}")
def delete_doctor_note(note_id: int, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.delete_doctor_note(note_id, admin.clinic_id)
    except Exception:
        logger.exception("delete_doctor_note failed for id=%s", note_id)
        raise HTTPException(status_code=500, detail="刪除醫師留言失敗")


@app.get("/api/admin/salary")
def get_salary_records(nurse: str, month: str, admin: auth.CurrentUser = Depends(auth.require_admin)) -> list[dict]:
    try:
        return contacts.get_salary_records(nurse, month, admin.clinic_id)
    except Exception:
        logger.exception("get_salary_records failed")
        raise HTTPException(status_code=500, detail="載入失敗")


@app.post("/api/admin/salary")
def save_salary_record(req: SalaryRecordRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    try:
        return contacts.save_salary_record(
            req.nurse, req.month, req.attendance, req.performance,
            req.sat_pay, req.float_bonus, req.ot_pay, req.total, req.ot_entries,
            admin.clinic_id, req.sick_days,
        )
    except Exception:
        logger.exception("save_salary_record failed")
        raise HTTPException(status_code=500, detail="儲存失敗")


@app.put("/api/admin/salary/{record_id}")
def update_salary_record(record_id: int, req: SalaryRecordRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.update_salary_record(
            record_id, req.attendance, req.performance,
            req.sat_pay, req.float_bonus, req.ot_pay, req.total, req.ot_entries,
            admin.clinic_id, req.sick_days,
        )
    except Exception:
        logger.exception("update_salary_record failed for id=%s", record_id)
        raise HTTPException(status_code=500, detail="更新失敗")


@app.get("/api/admin/salary/sick-days")
def get_yearly_sick_days(nurse: str, year: int, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    try:
        total = contacts.get_yearly_sick_days(nurse, year, admin.clinic_id)
        return {"total": total}
    except Exception:
        logger.exception("get_yearly_sick_days failed")
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.delete("/api/admin/salary/{record_id}")
def delete_salary_record(record_id: int, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.delete_salary_record(record_id, admin.clinic_id)
    except Exception:
        logger.exception("delete_salary_record failed for id=%s", record_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


# ── Nurse self-reported overtime ──────────────────────────────────────────────

@app.get("/api/me")
def get_me(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return {"display_name": user.display_name, "role": user.role}


@app.get("/api/nurse/ot-logs")
def get_my_ot_logs(month: str = "", nurse: str = "", user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    # Shared-session model: nurse identity comes from PIN selection on the frontend
    effective_nurse = nurse.strip() or user.display_name
    return contacts.get_nurse_ot_logs(effective_nurse, user.clinic_id, month or None, legacy_nurse=user.display_name)


@app.post("/api/nurse/ot-logs")
def add_my_ot_log(body: dict, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    date       = str(body.get("date", "")).strip()
    start_time = str(body.get("start_time", "")).strip()
    end_time   = str(body.get("end_time", "")).strip()
    note       = str(body.get("note", "")).strip()
    # Shared-session model: nurse name comes from PIN selection passed by the frontend
    nurse      = str(body.get("nurse", "")).strip() or user.display_name
    if not date or not start_time or not end_time:
        raise HTTPException(status_code=422, detail="日期與時間不可空白")
    new_id = contacts.add_nurse_ot_log(nurse, user.clinic_id, date, start_time, end_time, note)
    return {"id": new_id}


@app.delete("/api/nurse/ot-logs/{log_id}")
def delete_my_ot_log(log_id: int, nurse: str = "", user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    # nurse param comes from PIN-selected identity on the frontend; admins bypass the check
    if not contacts.delete_nurse_ot_log(log_id, user.clinic_id, nurse.strip(), is_admin=user.role == "admin"):
        raise HTTPException(status_code=404, detail="記錄不存在")


@app.put("/api/nurse/ot-logs/{log_id}")
def update_my_ot_log(log_id: int, body: dict, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    date       = str(body.get("date", "")).strip()
    start_time = str(body.get("start_time", "")).strip()
    end_time   = str(body.get("end_time", "")).strip()
    note       = str(body.get("note", "")).strip()
    nurse      = str(body.get("nurse", "")).strip() or user.display_name
    if not date or not start_time or not end_time:
        raise HTTPException(status_code=422, detail="日期與時間不可空白")
    if not contacts.update_nurse_ot_log(log_id, user.clinic_id, date, start_time, end_time, note, nurse=nurse, is_admin=user.role == "admin"):
        raise HTTPException(status_code=404, detail="記錄不存在")
    return {"ok": True}


@app.get("/api/admin/nurse-ot-logs")
def get_nurse_ot_logs_admin(
    nurse: str, month: str = "",
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> list[dict]:
    return contacts.get_nurse_ot_logs(nurse, admin.clinic_id, month or None)


@app.post("/api/admin/nurses")
def add_nurse(req: NurseNameRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不可空白")
    try:
        if not contacts.add_nurse(name, admin.clinic_id):
            raise HTTPException(status_code=400, detail="此姓名已存在")
    except HTTPException:
        raise
    except Exception:
        logger.exception("add_nurse failed for name=%s", name)
        raise HTTPException(status_code=500, detail="新增失敗")


@app.put("/api/admin/nurses/{name}")
def rename_nurse(name: str, req: NurseNameRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="姓名不可空白")
    try:
        if not contacts.rename_nurse(name, new_name, admin.clinic_id):
            raise HTTPException(status_code=400, detail="此姓名已存在")
    except HTTPException:
        raise
    except Exception:
        logger.exception("rename_nurse failed from=%s to=%s", name, new_name)
        raise HTTPException(status_code=500, detail="更新失敗")


@app.delete("/api/admin/nurses/{name}")
def remove_nurse(name: str, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.remove_nurse(name, admin.clinic_id)
    except Exception:
        logger.exception("remove_nurse failed for name=%s", name)
        raise HTTPException(status_code=500, detail="移除失敗")


# ── Pharmacists ───────────────────────────────────────────────────────────────

@app.get("/api/pharmacists")
def get_pharmacists(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[str]:
    return contacts.get_pharmacists(user.clinic_id)


@app.post("/api/admin/pharmacists", status_code=201)
def add_pharmacist(req: NurseNameRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不可空白")
    try:
        if not contacts.add_pharmacist(name, admin.clinic_id):
            raise HTTPException(status_code=400, detail="此姓名已存在")
    except HTTPException:
        raise
    except Exception:
        logger.exception("add_pharmacist failed for name=%s", name)
        raise HTTPException(status_code=500, detail="新增失敗")


@app.put("/api/admin/pharmacists/{name}")
def rename_pharmacist(name: str, req: NurseNameRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="姓名不可空白")
    try:
        if not contacts.rename_pharmacist(name, new_name, admin.clinic_id):
            raise HTTPException(status_code=400, detail="此姓名已存在")
    except HTTPException:
        raise
    except Exception:
        logger.exception("rename_pharmacist failed from=%s to=%s", name, new_name)
        raise HTTPException(status_code=500, detail="更新失敗")


@app.delete("/api/admin/pharmacists/{name}")
def remove_pharmacist(name: str, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.remove_pharmacist(name, admin.clinic_id)
    except Exception:
        logger.exception("remove_pharmacist failed for name=%s", name)
        raise HTTPException(status_code=500, detail="移除失敗")


@app.put("/api/admin/nurses/{name}/pin")
def set_nurse_pin(name: str, body: dict, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    pin = str(body.get("pin", "")).strip()
    try:
        contacts.set_nurse_pin(name, pin, admin.clinic_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("set_nurse_pin failed for name=%s", name)
        raise HTTPException(status_code=500, detail="設定失敗")


@app.delete("/api/admin/nurses/{name}/pin")
def clear_nurse_pin(name: str, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.clear_nurse_pin(name, admin.clinic_id)
    except Exception:
        logger.exception("clear_nurse_pin failed for name=%s", name)
        raise HTTPException(status_code=500, detail="清除失敗")


@app.post("/api/auth/nurse-pin")
def verify_nurse_pin(body: dict, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    name = str(body.get("name", "")).strip()
    pin  = str(body.get("pin",  "")).strip()
    if not name or not pin:
        raise HTTPException(status_code=422, detail="請輸入護理師名稱與 PIN")
    key = (user.clinic_id, name)
    now_ts = _time.time()
    recent = [t for t in _pin_failures.get(key, []) if now_ts - t < _PIN_LOCKOUT_SECONDS]
    if len(recent) >= _PIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="嘗試次數過多，請 15 分鐘後再試")
    if not contacts.verify_nurse_pin(name, pin, user.clinic_id):
        _pin_failures[key] = recent + [now_ts]
        raise HTTPException(status_code=401, detail="PIN 不正確")
    _pin_failures.pop(key, None)
    return {"ok": True, "name": name}


@app.post("/api/auth/nurse-pin/change")
def change_nurse_pin(body: dict, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    name    = str(body.get("name",    "")).strip()
    old_pin = str(body.get("old_pin", "")).strip()
    new_pin = str(body.get("new_pin", "")).strip()
    if not name or not old_pin or not new_pin:
        raise HTTPException(status_code=422, detail="請填寫所有欄位")
    key = (user.clinic_id, name)
    now_ts = _time.time()
    recent = [t for t in _pin_failures.get(key, []) if now_ts - t < _PIN_LOCKOUT_SECONDS]
    if len(recent) >= _PIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="嘗試次數過多，請 15 分鐘後再試")
    if not contacts.verify_nurse_pin(name, old_pin, user.clinic_id):
        _pin_failures[key] = recent + [now_ts]
        raise HTTPException(status_code=401, detail="目前 PIN 不正確")
    _pin_failures.pop(key, None)
    try:
        contacts.set_nurse_pin(name, new_pin, user.clinic_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}


@app.get("/admin")
def admin_page() -> Response:
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
def admin_stats_json(month: str | None = None, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        return {"month": month, "stats": contacts.get_activity_stats(month, admin.clinic_id)}
    except Exception:
        logger.exception("admin_stats_json failed for month=%s", month)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/admin/doctors")
def admin_doctors_json(month: str | None = None, user: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        if CLOUD_MODE:
            doctors = contacts.get_synced_doctor_rates(month, user.clinic_id)
        else:
            doctors = database.get_doctor_return_rates(month)
        return {"month": month, "doctors": doctors}
    except Exception:
        logger.exception("admin_doctors failed for month=%s", month)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/admin/shifts")
def get_shifts(week_start: date, admin: auth.CurrentUser = Depends(auth.require_admin)) -> list[ShiftEntry]:
    try:
        return contacts.get_shifts_for_week(week_start.isoformat(), admin.clinic_id)
    except Exception:
        logger.exception("get_shifts failed for week_start=%s", week_start)
        raise HTTPException(status_code=500, detail="查詢排班失敗")


@app.post("/api/admin/shifts")
def set_shift(req: ShiftEntry, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.set_shift(
            req.nurse, req.shift_date.isoformat(), req.slot, req.start_time, req.end_time,
            req.clean_start, req.clean_end, admin.clinic_id,
        )
    except Exception:
        logger.exception("set_shift failed for nurse=%s date=%s slot=%s", req.nurse, req.shift_date, req.slot)
        raise HTTPException(status_code=500, detail="儲存排班失敗")


@app.post("/api/admin/shifts/copy-week")
def copy_week(req: CopyWeekRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.copy_week(req.from_week_start.isoformat(), req.to_week_start.isoformat(), admin.clinic_id)
    except Exception:
        logger.exception("copy_week failed from=%s to=%s", req.from_week_start, req.to_week_start)
        raise HTTPException(status_code=500, detail="複製排班失敗")


@app.get("/api/admin/shifts/publish-status")
def get_publish_status(week_start: date, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    return {"published": contacts.is_week_published(week_start.isoformat(), admin.clinic_id)}


@app.post("/api/admin/shifts/publish")
def publish_week(req: PublishWeekRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.publish_week(req.week_start.isoformat(), admin.clinic_id)
    except Exception:
        logger.exception("publish_week failed for week_start=%s", req.week_start)
        raise HTTPException(status_code=500, detail="發布失敗")


@app.post("/api/admin/shifts/unpublish")
def unpublish_week(req: PublishWeekRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        contacts.unpublish_week(req.week_start.isoformat(), admin.clinic_id)
    except Exception:
        logger.exception("unpublish_week failed for week_start=%s", req.week_start)
        raise HTTPException(status_code=500, detail="取消發布失敗")


@app.get("/api/schedule")
def get_public_schedule(week_start: date, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Nurses view their published schedule. Only returns shift data once the admin
    has published that week; otherwise reports unpublished without leaking draft data."""
    ws = week_start.isoformat()
    if not contacts.is_week_published(ws, user.clinic_id):
        return {"published": False, "nurses": [], "shifts": []}
    try:
        return {"published": True, "nurses": contacts.get_nurses(user.clinic_id), "shifts": contacts.get_shifts_for_week(ws, user.clinic_id)}
    except Exception:
        logger.exception("get_public_schedule failed for week_start=%s", week_start)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/schedule/month")
def get_month_schedule(month: str, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Return all shifts for an entire calendar month (YYYY-MM) for print purposes.
    All authenticated users see all entered shifts regardless of publish status."""
    import re
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(status_code=422, detail="month 格式應為 YYYY-MM")
    try:
        return contacts.get_month_schedule(month, user.clinic_id)
    except Exception as exc:
        logger.exception("get_month_schedule failed: %s", exc)
        raise HTTPException(status_code=500, detail="查詢失敗")


def _build_cloud_report(synced: list[dict], as_of: date) -> DailyReport:
    from models import Patient
    chronic, mspt, mspt_inactive, mspt_upcoming = [], [], [], []
    hep, hep_inactive, hep_upcoming = [], [], []
    ckd, ckd_inactive, ckd_upcoming = [], [], []
    for c in synced:
        cat = c["category"]
        base_cat = cat.removesuffix("_inactive").removesuffix("_upcoming")
        e = FollowupEntry(
            patient=Patient(
                chart_number=c["chart_number"],
                name=c["name"],
                birth_date=date.fromisoformat(c["birth_date"]),
            ),
            disease_name=c["disease_name"],
            category=base_cat,
            due_date=date.fromisoformat(c["due_date"]),
            days_overdue=c["days_overdue"],
            mspt_stage=c.get("mspt_stage"),
            contact_reason=c.get("contact_reason"),
            last_visit_date=date.fromisoformat(c["last_visit_date"]) if c.get("last_visit_date") else None,
            phone=c.get("phone", ""),
            mobile=c.get("mobile", ""),
        )
        if cat == '慢簽':
            chronic.append(e)
        elif cat == '代謝症候群':
            mspt.append(e)
        elif cat == '代謝症候群_inactive':
            mspt_inactive.append(e)
        elif cat == '代謝症候群_upcoming':
            mspt_upcoming.append(e)
        elif cat == 'B肝':
            hep.append(e)
        elif cat == 'B肝_inactive':
            hep_inactive.append(e)
        elif cat == 'B肝_upcoming':
            hep_upcoming.append(e)
        elif cat == '慢性腎臟病':
            ckd.append(e)
        elif cat == '慢性腎臟病_inactive':
            ckd_inactive.append(e)
        elif cat == '慢性腎臟病_upcoming':
            ckd_upcoming.append(e)
        else:
            logger.warning("_build_cloud_report: unknown category %r — dropped for %s", cat, c.get("chart_number"))
    return DailyReport(
        report_date=as_of,
        chronic_prescriptions=chronic,
        mspt_followups=mspt,
        mspt_inactive=mspt_inactive,
        mspt_upcoming=mspt_upcoming,
        mspt_submittable=[],
        mspt_waiting=[],
        hep_followups=hep,
        hep_inactive=hep_inactive,
        hep_upcoming=hep_upcoming,
        hep_returned=[],
        ckd_followups=ckd,
        ckd_inactive=ckd_inactive,
        ckd_upcoming=ckd_upcoming,
    )


@app.post("/api/sync/push")
async def sync_push(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    db.set_clinic_id(clinic_id)
    candidates = body.get("candidates", [])
    contacts.upsert_synced_candidates(candidates, clinic_id)
    try:
        contacts.record_followup_episodes(candidates, clinic_id)
    except Exception as exc:  # stats history must never block the follow-up lists
        logger.warning("record_followup_episodes failed: %s", exc)
    _invalidate_report_cache(clinic_id)
    return {"ok": True, "count": len(candidates)}


@app.get("/api/sync/open-episodes")
def sync_open_episodes(request: Request) -> dict:
    """Overdue episodes the sync agent should check for a return visit."""
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    db.set_clinic_id(1)
    return {"episodes": contacts.get_open_episodes(1)}


@app.post("/api/sync/push-returns")
async def sync_push_returns(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    db.set_clinic_id(clinic_id)
    rows = body.get("returns", [])
    for r in rows:
        try:
            date.fromisoformat(str(r["returned_on"]))
            date.fromisoformat(str(r["due_date"]))
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="each return needs chart_number, category, due_date, returned_on (YYYY-MM-DD)")
    return {"ok": True, "updated": contacts.record_episode_returns(rows, clinic_id)}


@app.post("/api/sync/push-prescriptions")
async def sync_push_prescriptions(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    rows = body.get("prescriptions", [])
    contacts.upsert_synced_prescriptions(rows, clinic_id)
    return {"ok": True, "count": len(rows)}


@app.post("/api/sync/push-doctor-rates")
async def sync_push_doctor_rates(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    month = body.get("month", "")
    rows = body.get("rates", [])
    if month:
        contacts.upsert_synced_doctor_rates(month, rows, clinic_id)
    return {"ok": True, "month": month, "count": len(rows)}


@app.post("/api/sync/push-lab")
async def sync_push_lab(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    lab_data = body.get("lab_data", {})
    contacts.upsert_lab_cache(lab_data, clinic_id)
    _invalidate_blood_pending_cache(clinic_id)
    return {"ok": True, "count": len(lab_data)}


@app.post("/api/sync/push-blood-pending")
async def sync_push_blood_pending(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    days = body.get("days", [])
    contacts.upsert_synced_blood_pending(days, clinic_id)
    _invalidate_blood_pending_cache(clinic_id)
    return {"ok": True, "days": len(days)}


@app.get("/api/sync/blood-recall-settings")
def sync_blood_recall_settings(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    db.set_clinic_id(1)
    return contacts.get_blood_recall_settings(1)


@app.get("/api/sync/clinic-settings")
def sync_clinic_settings(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    db.set_clinic_id(1)
    return contacts.get_clinic_settings(1)


@app.post("/api/sync/push-blood-recall")
async def sync_push_blood_recall(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    body = await request.json()
    clinic_id = int(body.get("clinic_id", 1))
    patients = body.get("patients", [])
    db.set_clinic_id(clinic_id)
    for p in patients:
        nat_id = p.get("nat_id", "").strip()
        name = p.get("name", "")
        last_draw_date = p.get("last_draw_date", "")
        has_abnormal = bool(p.get("has_abnormal", False))
        abnormal_items = p.get("abnormal_items", [])
        if not nat_id or not last_draw_date:
            continue
        # Only upsert patients with abnormal items; skip if all-normal and not on list
        if has_abnormal:
            contacts.upsert_blood_recall_patient(clinic_id, nat_id, name, last_draw_date, abnormal_items, True)
        else:
            # Patient had watched items but all-normal on latest draw — update to 'normal' if currently active
            contacts.upsert_blood_recall_patient(clinic_id, nat_id, name, last_draw_date, abnormal_items, False)
    return {"ok": True, "processed": len(patients)}


@app.get("/api/blood-recall")
def get_blood_recall(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list:
    return contacts.get_blood_recall_patients(user.clinic_id)


@app.patch("/api/blood-recall/{patient_id}")
def update_blood_recall(patient_id: int, body: dict = Body(...),
                         user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    status = body.get("status", "")
    if status not in ("done", "active", "contacted"):
        raise HTTPException(status_code=400, detail="status must be 'done', 'active', or 'contacted'")
    contacts.update_blood_recall_status(user.clinic_id, patient_id, status)
    return {"ok": True}


@app.get("/api/blood-recall/settings")
def get_blood_recall_settings(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return contacts.get_blood_recall_settings(user.clinic_id)


@app.post("/api/blood-recall/settings")
def save_blood_recall_settings(body: dict = Body(...),
                                 user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理員權限")
    watched_items = body.get("watched_items", [])
    date_window_days = int(body.get("date_window_days", 365))
    if not isinstance(watched_items, list):
        raise HTTPException(status_code=400, detail="watched_items must be a list")
    if not (30 <= date_window_days <= 730):
        raise HTTPException(status_code=400, detail="date_window_days must be 30–730")
    contacts.save_blood_recall_settings(user.clinic_id, watched_items, date_window_days)
    return {"ok": True}


@app.get("/api/sync/status")
def sync_status(request: Request) -> dict:
    token = request.headers.get("X-Sync-Token", "")
    if not _SYNC_TOKEN or not secrets.compare_digest(token, _SYNC_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    db.set_clinic_id(1)
    rows = contacts.get_synced_candidates(1)
    synced_at = max((r["synced_at"] for r in rows), default=None)
    return {"synced_at": synced_at, "count": len(rows)}


@app.get("/api/report/prescriptions")
def get_prescriptions(report_date: date | None = None, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    as_of = report_date or date.today()
    try:
        if CLOUD_MODE:
            settings = contacts.get_clinic_settings(user.clinic_id)
            grace = settings["prescription_grace_days"]
            min_ps = settings["prescription_min_ps_days"]
            cutover_str = settings.get("prescription_cutover_date")
            cutover = date.fromisoformat(cutover_str) if cutover_str else None
            rows = contacts.get_synced_prescriptions(user.clinic_id)
            phone_map = contacts.get_candidate_phone_map(user.clinic_id)
            results = []
            for r in rows:
                due = date.fromisoformat(r['due_date'])
                days_until_due = (due - as_of).days
                if days_until_due < -grace:
                    continue  # past grace period
                if (r.get('ps') or 0) < min_ps:
                    continue  # shorter than the clinic's minimum prescription length
                if _PRESCRIPTION_START_DATE and due < _PRESCRIPTION_START_DATE:
                    continue  # pre-adoption prescriptions hidden for this clinic
                if cutover and r.get('visit_date'):
                    visit = date.fromisoformat(r['visit_date'])
                    if visit >= cutover:
                        continue  # handled by old method; excluded from catch-up list
                ph, mob = phone_map.get(r['nat_id'], ('', ''))
                results.append({
                    **r,
                    'days_until_due': days_until_due,
                    'phone': ph,
                    'mobile': mob,
                })
            return {
                "rows": sorted(results, key=lambda e: e['days_until_due']),
                "cutover_date": cutover_str,
            }
        phone_idx = database._get_patdb_phone_index()
        min_ps = contacts.get_clinic_settings(user.clinic_id)["prescription_min_ps_days"]
        rows = [{**r, 'phone': phone_idx.get(r['nat_id'], ''), 'mobile': ''}
                for r in database._query_all_prescriptions(as_of, min_ps)]
        return {"rows": rows, "cutover_date": None}
    except Exception as exc:
        logger.exception("get_prescriptions failed: %s", exc)
        raise HTTPException(status_code=500, detail="資料載入失敗，請稍後再試")


@app.get("/api/report")
def get_report(report_date: date | None = None, user: auth.CurrentUser = Depends(auth.get_current_user)) -> DailyReport:
    cid = user.clinic_id
    if report_date is None:
        _cached = _report_cache.get(cid)
        if _cached and _cached[0] == date.today():
            return _cached[1]
    try:
        as_of = report_date or date.today()
        cid = user.clinic_id
        # All DB queries run in parallel with the IC file report to avoid
        # sequential 130ms round trips to Supabase Tokyo on every tab load.
        with ThreadPoolExecutor(max_workers=12) as exe:
            f_report               = exe.submit(contacts.get_synced_candidates, cid) if CLOUD_MODE else exe.submit(database.get_daily_report, as_of)
            f_hidden               = exe.submit(contacts.get_hidden_keys, cid)
            f_call_required        = exe.submit(contacts.get_call_required_keys, cid)
            f_submitted            = exe.submit(contacts.get_submitted_keys, cid)
            f_excluded_keys        = exe.submit(contacts.get_excluded_keys, cid)
            f_mspt_completed_keys  = exe.submit(contacts.get_mspt_completed_keys, cid)
            f_mspt_checkedin_keys  = exe.submit(contacts.get_mspt_checkedin_keys, cid)
            f_mspt_phone_keys      = exe.submit(contacts.get_mspt_phone_completed_keys, cid)
            f_phone_submittable    = exe.submit(contacts.get_mspt_phone_completed_submittable, cid)
            f_on_hold_keys         = exe.submit(contacts.get_on_hold_keys, cid)
            f_line_unlinked        = exe.submit(contacts.get_line_unlinked_chart_numbers, cid)
            f_alleypin             = exe.submit(contacts.get_alleypin_not_found_chart_numbers, cid)
            f_line_recently_sent   = exe.submit(contacts.get_line_recently_sent_map, cid)
            f_hep_returned_keys    = exe.submit(contacts.get_hep_returned_completed_keys, cid)
            f_hep_reintake_charts  = exe.submit(contacts.get_hep_reintake_chart_numbers, cid)
            f_hep_manual_returned  = exe.submit(contacts.get_hep_manual_returned_charts, cid)
            f_ckd_manual_inactive  = exe.submit(contacts.get_ckd_manual_inactive_charts, cid)
            f_ckd_reintake_charts  = exe.submit(contacts.get_ckd_reintake_chart_numbers, cid)
            f_manual_overrides     = exe.submit(contacts.get_mspt_manual_overrides, cid)
            f_contacted            = exe.submit(contacts.get_contacted_with_dates, cid)
            f_manual_pickup_map    = exe.submit(contacts.get_manual_pickup_map, cid)
            f_hep_completed_latest = exe.submit(contacts.get_hep_completed_latest_map, cid)
            f_excluded_entries     = exe.submit(contacts.get_excluded_entries, cid)
            f_auto_excluded        = exe.submit(contacts.get_auto_excluded_entries, cid)
            f_called_entries       = exe.submit(contacts.get_called_entries, cid)
            f_all_blood_used       = exe.submit(contacts.get_all_mspt_blood_used, cid)
            f_all_lab_cache        = exe.submit(contacts.get_all_lab_cache, cid) if CLOUD_MODE else None

        _raw_candidates             = f_report.result()
        report                      = _build_cloud_report(_raw_candidates, as_of) if CLOUD_MODE else _raw_candidates  # type: ignore[arg-type]

        # Build phone lookup from synced_candidates (cloud) or report entries (local)
        # so that 已聯繫 / 暫緩中 entries — stored without phone — can show numbers.
        if CLOUD_MODE:
            _phone_lookup: dict[str, tuple[str, str]] = {
                c['chart_number']: (c.get('phone', ''), c.get('mobile', ''))
                for c in _raw_candidates if isinstance(c, dict)
            }
        else:
            _phone_lookup = {
                e.patient.chart_number: (e.phone, e.mobile)
                for e in (report.mspt_followups + report.chronic_prescriptions
                          + report.hep_followups + report.ckd_followups)
                if e.phone or e.mobile
            }

        def _enrich_phones(entries: list) -> list:
            if not _phone_lookup:
                return entries
            out = []
            for e in entries:
                chart = (e.patient.chart_number if e.patient else '') if hasattr(e, 'patient') else ''
                if chart and chart in _phone_lookup and not getattr(e, 'phone', '') and not getattr(e, 'mobile', ''):
                    ph, mob = _phone_lookup[chart]
                    e = e.model_copy(update={'phone': ph, 'mobile': mob})
                out.append(e)
            return out
        hidden_keys                 = f_hidden.result()
        call_required_keys          = f_call_required.result()
        submitted_keys              = f_submitted.result()
        excluded_keys               = f_excluded_keys.result()
        mspt_completed_keys         = f_mspt_completed_keys.result()
        mspt_checkedin_keys         = f_mspt_checkedin_keys.result()
        mspt_phone_completed_keys   = f_mspt_phone_keys.result()
        phone_submittable           = f_phone_submittable.result()
        on_hold_keys                = f_on_hold_keys.result()
        line_unlinked_charts        = f_line_unlinked.result()
        alleypin_not_found_charts   = f_alleypin.result()
        line_recently_sent_map      = f_line_recently_sent.result()
        hep_returned_completed_keys = f_hep_returned_keys.result()
        hep_reintake_charts         = f_hep_reintake_charts.result()
        hep_manual_returned_charts  = f_hep_manual_returned.result()
        ckd_manual_inactive_charts  = f_ckd_manual_inactive.result()
        ckd_reintake_charts         = f_ckd_reintake_charts.result()
        manual_overrides            = f_manual_overrides.result()
        contacted_with_dates        = f_contacted.result()
        manual_pickup_map           = f_manual_pickup_map.result()
        hep_completed_latest        = f_hep_completed_latest.result()
        manual_excluded             = f_excluded_entries.result()
        auto_excluded_raw           = f_auto_excluded.result()
        called_entries              = f_called_entries.result()
        all_blood_used              = f_all_blood_used.result()
        all_lab_cache               = f_all_lab_cache.result() if f_all_lab_cache else {}

        def apply_blood_status(entries: list[FollowupEntry]) -> list[FollowupEntry]:
            """Fill needs_blood_test and blood_draw_date.

            Uses the BIO-based blood status cache once warmup has finished reading the
            lab files into memory. Falls back to DB-only (no BIO reads) until then so
            the first API response after a restart is instant rather than blocking for
            several minutes on the network drive."""
            out = []
            cache_ready = database._blood_status_ready.is_set()
            for e in entries:
                if e.category != '代謝症候群' or not e.mspt_stage:
                    out.append(e)
                    continue
                nat_id = e.patient.chart_number
                used = all_blood_used.get(nat_id, {})
                cache_key = f"{nat_id}:{e.mspt_stage}"
                if cache_ready and cache_key in database._blood_status_cache:
                    bt_needed, bt_date = database._blood_status_cache[cache_key]
                else:
                    bt_needed, bt_date = database.mspt_blood_status(
                        e.mspt_stage, nat_id, as_of, _used=used, skip_lab=True
                    )
                    # On cloud, skip_lab=True means BIO files weren't checked.
                    # Fall back to lab_cache (synced from PC1) to catch available draws.
                    if bt_needed and all_lab_cache:
                        used_dates = set(used.values())
                        cache_date = lab_results.check_metabolic_panel_in_cache(
                            nat_id, all_lab_cache, as_of,
                            window_days=database.MSPT_BLOOD_TEST_WINDOW_DAYS,
                            exclude_iso_dates=used_dates,
                        )
                        if cache_date:
                            bt_needed, bt_date = False, cache_date
                updates: dict = {'needs_blood_test': bt_needed, 'blood_draw_date': bt_date}
                if e.mspt_stage == '收案' and e.last_stage is not None:
                    updates['contact_reason'] = '需重新收案+抽血' if bt_needed else '需重新收案'
                out.append(e.model_copy(update=updates))
            return out

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
                if (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) in mspt_phone_completed_keys:
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
        chronic_charts = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '慢簽'}
        mspt_charts    = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == '代謝症候群'}
        hep_charts     = {e.patient.chart_number for e, _ in contacted_with_dates if e.category == 'B肝'}
        if CLOUD_MODE:
            def _cloud_latest_visits(charts: set, category: str) -> dict:
                if not charts:
                    return {}
                import db as _db_mod
                with _db_mod._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT chart_number, last_visit_date FROM synced_candidates "
                            "WHERE clinic_id = %s AND category = %s AND chart_number = ANY(%s) "
                            "AND last_visit_date IS NOT NULL",
                            (cid, category, list(charts)),
                        )
                        return {r["chart_number"]: date.fromisoformat(r["last_visit_date"]) for r in cur.fetchall()}
            with ThreadPoolExecutor(max_workers=3) as _vexe:
                f_cv = _vexe.submit(_cloud_latest_visits, chronic_charts, '慢簽')
                f_mv = _vexe.submit(_cloud_latest_visits, mspt_charts, '代謝症候群')
                f_hv = _vexe.submit(_cloud_latest_visits, hep_charts, 'B肝')
            chronic_visits = f_cv.result()
            mspt_visits    = f_mv.result()
            hep_visits     = f_hv.result()
        else:
            with ThreadPoolExecutor(max_workers=3) as _vexe:
                f_cv = _vexe.submit(database.get_latest_visit_dates, chronic_charts, '慢簽')
                f_mv = _vexe.submit(database.get_latest_visit_dates, mspt_charts, '代謝症候群')
                f_hv = _vexe.submit(database.get_latest_visit_dates, hep_charts, 'B肝')
            chronic_visits = f_cv.result()
            mspt_visits    = f_mv.result()
            hep_visits     = f_hv.result()

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
            and not (e.category == '處方' and _PRESCRIPTION_START_DATE and e.due_date < _PRESCRIPTION_START_DATE)
        ]

        # Filter chronic patients suppressed by a manual pickup record
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
        def apply_hep_reintake(entries: list[FollowupEntry]) -> list[FollowupEntry]:
            if not hep_reintake_charts:
                return entries
            return [
                e.model_copy(update={'last_stage': '收案'}) if e.patient.chart_number in hep_reintake_charts else e
                for e in entries
            ]

        def hep_suppressed(entry: FollowupEntry) -> bool:
            completed_str = hep_completed_latest.get(entry.patient.chart_number)
            if not completed_str:
                return False
            completed_date = date.fromisoformat(completed_str)
            if entry.last_visit_date and completed_date <= entry.last_visit_date:
                return False
            return True

        all_excluded = manual_excluded + [
            e for e in auto_excluded_raw
            if (e.patient.chart_number, e.category) not in {(x.patient.chart_number, x.category) for x in manual_excluded}
        ]

        called_filtered = [
            e for e in called_entries
            if (e.patient.chart_number, e.category) not in excluded_keys
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_completed_keys
            and (e.patient.chart_number, e.mspt_stage, e.due_date.isoformat()) not in mspt_checkedin_keys
            and not (e.category == '處方' and _PRESCRIPTION_START_DATE and e.due_date < _PRESCRIPTION_START_DATE)
        ]

        _result = DailyReport(
            report_date=report.report_date,
            chronic_prescriptions=filter_followups(chronic_prescriptions),
            mspt_followups=filter_followups(apply_mspt_overrides(apply_blood_status(report.mspt_followups))),
            mspt_inactive=filter_followups(apply_mspt_overrides(apply_blood_status(report.mspt_inactive))),
            mspt_submittable=[
                e for e in (report.mspt_submittable + phone_submittable)
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
                    e for e in filter_followups(apply_hep_reintake(report.hep_followups)) + filter_followups(apply_hep_reintake(report.hep_inactive))
                    if not hep_suppressed(e)
                    and (e.patient.chart_number, e.category) not in hep_manual_returned_charts
                ],
                key=lambda e: e.days_overdue,
            ),
            hep_returned=[
                e for e in report.hep_returned
                if (e.patient.chart_number, e.last_visit_date.isoformat()) not in hep_returned_completed_keys
            ] + [
                e.model_copy(update={"last_visit_date": as_of or date.today(), "manual": True})
                for e in filter_followups(apply_hep_reintake(report.hep_followups)) + filter_followups(apply_hep_reintake(report.hep_inactive))
                if (e.patient.chart_number, e.category) in hep_manual_returned_charts
                and (e.patient.chart_number, (as_of or date.today()).isoformat()) not in hep_returned_completed_keys
            ],
            hep_returned_completed=contacts.get_hep_returned_completed_entries(cid),
            contacted=_enrich_phones(contacted),
            called=_enrich_phones(called_filtered),
            submitted=contacts.get_submitted_entries(cid),
            excluded=all_excluded,
            mspt_completed=contacts.get_mspt_completed_entries(cid),
            mspt_checkedin=contacts.get_mspt_checkedin_entries(cid),
            chronic_manual_pickups=contacts.get_manual_pickup_entries(cid),
            on_hold=_enrich_phones(contacts.get_on_hold_entries(cid)),
            mspt_manual=contacts.get_mspt_manual_entries(cid),
            ckd_followups=filter_followups(
                [e for e in report.ckd_followups if e.patient.chart_number not in ckd_manual_inactive_charts] +
                [e for e in report.ckd_inactive if e.patient.chart_number in ckd_reintake_charts]
            ),
            ckd_inactive=filter_followups(
                [e for e in report.ckd_inactive if e.patient.chart_number not in ckd_reintake_charts] +
                [e.model_copy(update={"manual": True}) for e in report.ckd_followups
                 if e.patient.chart_number in ckd_manual_inactive_charts]
            ),
            mspt_upcoming=report.mspt_upcoming,
            hep_upcoming=report.hep_upcoming,
            ckd_upcoming=report.ckd_upcoming,
        )
        if report_date is None:
            _report_cache[cid] = (date.today(), _result)
        return _result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_report failed for date=%s: %s", report_date, exc)
        raise HTTPException(status_code=500, detail="資料載入失敗，請稍後再試")


@app.post("/api/contacted")
def mark_contacted(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_contacted(req.entry, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_contacted failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="聯絡記錄儲存失敗，請稍後再試")


@app.post("/api/called")
def mark_called(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_called(req.entry, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_called failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="二次通知記錄儲存失敗，請稍後再試")


@app.delete("/api/contacted")
def unmark_contacted(req: ContactRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark(req.chart_number, req.category, req.due_date, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_contacted failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.post("/api/submitted")
def mark_submitted(entry: MsptSubmittableEntry, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_submitted(entry, user.clinic_id)
        if entry.used_blood:
            contacts.record_mspt_blood_used(
                entry.patient.chart_number,
                entry.mspt_stage,
                entry.blood_report_date.isoformat(),
                user.clinic_id,
            )
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_submitted failed for %s", entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="待登VPN記錄儲存失敗，請稍後再試")


@app.delete("/api/submitted")
def unmark_submitted(req: SubmitRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_submitted(req.chart_number, req.mspt_stage, user.clinic_id)
        contacts.clear_mspt_blood_used(req.chart_number, req.mspt_stage, user.clinic_id)
        contacts.unmark_mspt_phone_completed(req.chart_number, req.mspt_stage, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_submitted failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷申報失敗，請稍後再試")


@app.post("/api/mspt-phone-complete")
def mspt_phone_complete(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    """Mark a phone-contact-only MSPT stage as complete: records contact + queues for NHI submission."""
    try:
        blood_draw_date = req.entry.blood_draw_date
        contacts.mark_mspt_phone_completed(req.entry, req.nurse, blood_draw_date, user.clinic_id)
        if blood_draw_date:
            contacts.record_mspt_blood_used(
                req.entry.patient.chart_number,
                req.entry.mspt_stage,
                blood_draw_date,
                user.clinic_id,
            )
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mspt_phone_complete failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="完成記錄失敗，請稍後再試")


@app.post("/api/mspt-blood-invalid")
def mspt_blood_invalid(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    """Mark a blood draw as invalid so the patient returns to 需回診.

    Two cases:
    - Manual blood_used entry only: clear it so the date is no longer recorded.
    - BIO-file draw (blood_draw_date set on entry): insert that date into mspt_blood_used
      so it appears in used_dates and is excluded from future blood searches, making
      needs_blood_test=True again for stages that require a fresh draw.
    Also evicts the entry from _blood_status_cache so the next API call recomputes
    rather than returning the stale cached result.
    """
    try:
        nat_id = req.entry.patient.chart_number
        stage  = req.entry.mspt_stage
        if req.entry.blood_draw_date:
            # Mark the BIO draw date as excluded by recording it as "used"
            contacts.record_mspt_blood_used(nat_id, stage, req.entry.blood_draw_date, user.clinic_id)
        else:
            contacts.clear_mspt_blood_used(nat_id, stage, user.clinic_id)
        # Evict the cached blood status so the next request recomputes from DB
        database._blood_status_cache.pop(f"{nat_id}:{stage}", None)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mspt_blood_invalid failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="操作失敗，請稍後再試")


@app.post("/api/mspt-waive-blood")
def mspt_waive_blood(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    """Nurse manually overrides: patient does not need a new blood draw.
    Stores 'waived' sentinel in mspt_blood_used so needs_blood_test returns False,
    moving them from 需回診 to 可電話完成."""
    try:
        nat_id = req.entry.patient.chart_number
        stage  = req.entry.mspt_stage
        contacts.record_mspt_blood_used(nat_id, stage, 'waived', user.clinic_id)
        database._blood_status_cache.pop(f"{nat_id}:{stage}", None)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mspt_waive_blood failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="操作失敗，請稍後再試")


@app.post("/api/excluded")
def mark_excluded(req: ExcludeRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_excluded(req.entry, req.reason, req.note, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception as exc:
        logger.exception("mark_excluded failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail=f"排除記錄儲存失敗 [{type(exc).__name__}]，請稍後再試")


@app.patch("/api/excluded")
def patch_excluded_reason(req: UpdateExclusionReasonRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.update_excluded_reason(
            req.chart_number, req.category, req.reason, req.note, req.nurse,
            req.name, req.birth_date.isoformat() if req.birth_date else '', user.clinic_id,
        )
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("patch_excluded_reason failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="更新失敗，請稍後再試")


@app.delete("/api/excluded")
def unmark_excluded(req: UnexcludeRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_excluded(req.chart_number, req.category, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_excluded failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷排除失敗，請稍後再試")


@app.delete("/api/auto-excluded")
def undo_auto_excluded(req: UnexcludeRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.undo_auto_excluded(req.chart_number, req.category, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("undo_auto_excluded failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.post("/api/mspt-completed")
def mark_mspt_completed(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_mspt_completed(req.entry, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_mspt_completed failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="完成MSPT記錄儲存失敗，請稍後再試")


@app.delete("/api/mspt-completed")
def unmark_mspt_completed(req: MsptCompleteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_mspt_completed(req.chart_number, req.mspt_stage, req.due_date.isoformat(), user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_mspt_completed failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷完成MSPT失敗，請稍後再試")


@app.post("/api/mspt-checkedin")
def mark_mspt_checkedin(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_mspt_checkedin(req.entry, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_mspt_checkedin failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="待建檔記錄儲存失敗，請稍後再試")


@app.delete("/api/mspt-checkedin")
def unmark_mspt_checkedin(req: MsptCompleteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_mspt_checkedin(req.chart_number, req.mspt_stage, req.due_date.isoformat(), user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_mspt_checkedin failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷待建檔失敗，請稍後再試")


@app.post("/api/hep-returned-completed")
def mark_hep_returned_completed(req: NurseEntryRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_hep_returned_completed(req.entry, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_hep_returned_completed failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="完成B肝記錄儲存失敗，請稍後再試")


@app.delete("/api/hep-returned-completed")
def unmark_hep_returned_completed(req: HepReturnedCompleteRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_hep_returned_completed(req.chart_number, req.last_visit_date.isoformat(), user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_hep_returned_completed failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.post("/api/hep-reintake")
def add_hep_reintake(req: HepReintakeRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.add_hep_reintake(req.chart_number, req.category, req.name, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("add_hep_reintake failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="再收案記錄儲存失敗，請稍後再試")


@app.delete("/api/hep-reintake")
def remove_hep_reintake(req: HepReintakeRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.remove_hep_reintake(req.chart_number, req.category, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("remove_hep_reintake failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷再收案失敗，請稍後再試")


@app.post("/api/hep-manual-returned")
def add_hep_manual_returned(req: HepManualReturnedRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.add_hep_manual_returned(req.chart_number, req.category, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("add_hep_manual_returned failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="移至待登VPN失敗，請稍後再試")


@app.delete("/api/hep-manual-returned")
def remove_hep_manual_returned(req: HepManualReturnedRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.remove_hep_manual_returned(req.chart_number, req.category, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("remove_hep_manual_returned failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="移回待聯絡失敗，請稍後再試")


@app.post("/api/ckd-manual-inactive")
def add_ckd_manual_inactive(req: CkdManualInactiveRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.add_ckd_manual_inactive(req.chart_number, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("add_ckd_manual_inactive failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="移至未複診失敗，請稍後再試")


@app.delete("/api/ckd-manual-inactive")
def remove_ckd_manual_inactive(req: CkdManualInactiveRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.remove_ckd_manual_inactive(req.chart_number, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("remove_ckd_manual_inactive failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="移回待聯絡失敗，請稍後再試")


@app.post("/api/manual-pickup")
def mark_manual_pickup(req: ManualPickupRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_manual_pickup(req.entry, req.pickup_date, req.ps_days, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_manual_pickup failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="手動取藥記錄儲存失敗，請稍後再試")


@app.delete("/api/manual-pickup")
def unmark_manual_pickup(req: ChartNumberRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_manual_pickup(req.chart_number, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_manual_pickup failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


@app.post("/api/line-unlinked")
def mark_line_unlinked(req: LineUnlinkedRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.flag_line_unlinked(req.chart_number, req.name, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("flag_line_unlinked failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="標記失敗，請稍後再試")

@app.delete("/api/line-unlinked/{chart_number}")
def clear_line_unlinked(chart_number: str, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.clear_line_unlinked(chart_number, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("clear_line_unlinked failed for %s", chart_number)
        raise HTTPException(status_code=500, detail="撤銷失敗，請稍後再試")


_line_batch_state: dict = {
    "running": False, "category": None, "dry_run": False,
    "total": 0, "results": [], "error": None,
    "direct": 0,  # patients sent via direct LINE API this batch
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


async def _run_line_batch_task(targets: list[dict], dry_run: bool, nurse: str, clinic_id: int = 1) -> None:
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
                clinic_id=clinic_id,
            )
        except Exception:
            logger.exception("failed to log LINE notification result for %s", target["chart_number"])

        if result["status"] == "sent" and not dry_run:
            try:
                if target["call_required"]:
                    contacts.mark_called(target["entry"], nurse, clinic_id)
                else:
                    contacts.mark_contacted(target["entry"], nurse, clinic_id)
            except Exception:
                logger.exception("failed to mark %s as contacted after LINE send", target["chart_number"])
            try:
                contacts.clear_line_unlinked(target["chart_number"], clinic_id)
            except Exception:
                logger.exception("failed to clear line_unlinked flag for %s", target["chart_number"])
            try:
                contacts.record_line_sent(
                    target["chart_number"], target["template"], target["entry"].patient.name,
                    date.today().isoformat(), nurse, clinic_id,
                )
            except Exception:
                logger.exception("failed to record send date for %s", target["chart_number"])

        if result["status"] == "line_not_linked":
            try:
                contacts.flag_line_unlinked(target["chart_number"], target["entry"].patient.name, nurse, clinic_id)
            except Exception:
                logger.exception("failed to flag %s as line_unlinked", target["chart_number"])

        if result["status"] == "not_found":
            try:
                contacts.flag_alleypin_not_found(target["chart_number"], target["entry"].patient.name, nurse, clinic_id)
            except Exception:
                logger.exception("failed to flag %s as alleypin_not_found", target["chart_number"])
        elif result["status"] != "error":
            # Any other status means _find_patient_row succeeded this time
            # ("error" is ambiguous — it can happen during the search itself,
            # so it's left alone rather than assumed to mean "found").
            try:
                contacts.clear_alleypin_not_found(target["chart_number"], clinic_id)
            except Exception:
                logger.exception("failed to clear alleypin_not_found flag for %s", target["chart_number"])

        if result["status"] == "recently_sent":
            try:
                contacts.record_line_sent(
                    target["chart_number"], target["template"], target["entry"].patient.name,
                    result["last_sent_at"], nurse, clinic_id,
                )
            except Exception:
                logger.exception("failed to record send date for %s", target["chart_number"])

    try:
        # ── Phase 2: direct LINE API for bound patients ──────────────────────
        settings = line_service.get_settings(clinic_id)
        line_active = (
            bool(settings.get("is_active"))
            and bool((settings.get("channel_access_token") or "").strip())
        )

        direct_targets: list[dict] = []
        alleypin_targets: list[dict] = []

        if line_active:
            bound_set = {b["chart_number"] for b in line_service.get_all_bindings(clinic_id)}
            for t in targets:
                (direct_targets if t["chart_number"] in bound_set else alleypin_targets).append(t)
        else:
            alleypin_targets = list(targets)

        _line_batch_state["direct"] = 0

        for t in direct_targets:
            t["template"] = "直接推播"  # override template label in the activity log
            if dry_run:
                result: dict = {"chart_number": t["chart_number"], "status": "sent", "detail": "[測試] 直接推播"}
            else:
                push_r = line_service.push_category_message(
                    t["chart_number"], t["entry"].category, clinic_id, actor=nurse
                )
                if push_r.get("status") == 200:
                    result = {"chart_number": t["chart_number"], "status": "sent", "detail": "直接推播"}
                    _line_batch_state["direct"] += 1
                elif push_r.get("status") in (400, 403):
                    # 400/403 from LINE usually means user blocked the bot or invalid binding
                    result = {
                        "chart_number": t["chart_number"],
                        "status": "line_not_linked",
                        "detail": "LINE 已封鎖或綁定失效",
                    }
                else:
                    result = {
                        "chart_number": t["chart_number"],
                        "status": "error",
                        "detail": "LINE 傳送失敗（請稍後再試）",
                    }
            on_result(result)

        # ── Existing: AlleyPin automation for patients without bindings ──────
        if alleypin_targets:
            await line_notify.run_batch(
                [
                    {
                        "chart_number": t["chart_number"],
                        "dob": t["entry"].patient.birth_date,
                        "name": t["entry"].patient.name,
                        "template": t["template"],
                    }
                    for t in alleypin_targets
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
async def send_line_notifications(req: SendLineNotificationsRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    try:
        import line_notify  # noqa: F401 — just checking it (and playwright) is installed
    except ImportError:
        raise HTTPException(status_code=500, detail="尚未安裝 playwright，請執行 pip install playwright 並 playwright install chromium")

    if _line_batch_state["running"]:
        raise HTTPException(status_code=409, detail="已有一個批次發送正在進行中，請稍候")

    report_data = get_report(report_date=None, user=user)
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
        "total": len(targets), "results": [], "error": None, "direct": 0,
    })
    global _line_batch_task
    _line_batch_task = asyncio.create_task(_run_line_batch_task(targets, req.dry_run, req.nurse, user.clinic_id))
    return {"started": True, "total": len(targets)}


@app.get("/api/send-line-notifications/status")
def get_line_notifications_status(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return _line_batch_state


@app.post("/api/send-line-notifications/cancel")
async def cancel_line_notifications(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
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
def get_line_notification_log(admin: auth.CurrentUser = Depends(auth.require_admin)) -> list:
    return contacts.get_line_notification_log(clinic_id=admin.clinic_id)


@app.post("/api/admin/line-notification-log/{log_id}/undo")
async def undo_line_notification(log_id: int, req: UndoLineNotificationRequest, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    entry = contacts.get_line_notification_log_entry(log_id, admin.clinic_id)
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
        contacts.mark_line_notification_undone(log_id, req.nurse, admin.clinic_id)
    return result


@app.get("/api/blood-pending")
def get_blood_pending(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    """Patients with external lab orders (last 5 days + overdue), with result and notified status.
    Returns [{date, patients: [{name, nat_id, draw_codes, is_allergy,
    results_back, results_date, notified, overdue}]}], most recent day first."""
    cid = user.clinic_id
    _cached = _blood_pending_cache.get(cid)
    if _cached is not None:
        return _cached
    try:
        notified_keys  = contacts.get_blood_notified_keys(user.clinic_id)
        physical_keys  = contacts.get_blood_physical_keys(user.clinic_id)
        if CLOUD_MODE:
            days = contacts.get_synced_blood_pending(user.clinic_id)
        else:
            days = database.get_blood_draw_patients(date.today())
            for day in days:
                draw_date = date.fromisoformat(day['date'])
                for p in day['patients']:
                    found, result_date = lab_results.has_results_since(p['nat_id'], draw_date)
                    p['results_back'] = found
                    p['results_date'] = result_date
        today = date.today()
        for day in days:
            # Remove patients sent to external physical labs
            day['patients'] = [
                p for p in day['patients']
                if (p.get('nat_id', ''), day['date']) not in physical_keys
            ]
            for p in day['patients']:
                p['notified'] = (p.get('nat_id', ''), day['date']) in notified_keys
                draw_age = (today - date.fromisoformat(day['date'])).days
                p['overdue'] = draw_age > 5 and not p.get('results_back', False)
        # Drop empty day groups
        days = [d for d in days if d['patients']]
        # Enrich with phone/mobile
        if CLOUD_MODE:
            phone_map = contacts.get_candidate_phone_map(cid)
        else:
            _pidx = database._get_patdb_phone_index()
            phone_map = {k: (v, '') for k, v in _pidx.items()}
        for day in days:
            for p in day['patients']:
                ph, mob = phone_map.get(p.get('nat_id', ''), ('', ''))
                p['phone'] = ph
                p['mobile'] = mob
        _blood_pending_cache[cid] = days
        return days
    except Exception:
        logger.exception("get_blood_pending failed")
        raise HTTPException(status_code=500, detail="檢驗追蹤載入失敗")



@app.post("/api/blood-dismiss")
def post_blood_dismiss(req: BloodDismissRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Manually remove a patient from the 檢驗追蹤 list for a specific draw date."""
    try:
        database.dismiss_blood_patient(req.nat_id, req.draw_date, req.name, req.reason, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-dismiss failed")
        raise HTTPException(status_code=500, detail="移除失敗")


@app.post("/api/blood-notified")
def post_blood_notified(req: BloodNotifiedRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Mark a patient as notified after their lab results came back."""
    try:
        contacts.add_blood_notified(req.nat_id, req.draw_date, req.nurse, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-notified POST failed")
        raise HTTPException(status_code=500, detail="標記失敗")


@app.delete("/api/blood-notified")
def delete_blood_notified(req: BloodNotifiedRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Undo a blood-notified mark."""
    try:
        contacts.remove_blood_notified(req.nat_id, req.draw_date, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-notified DELETE failed")
        raise HTTPException(status_code=500, detail="撤銷失敗")


@app.get("/api/blood-physical")
def get_blood_physical(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    """Patients moved to external-lab physical report tracking."""
    cid = user.clinic_id
    _cached = _blood_physical_cache.get(cid)
    if _cached is not None:
        return _cached
    try:
        result = contacts.get_blood_physical(user.clinic_id)
        _blood_physical_cache[cid] = result
        return result
    except Exception:
        logger.exception("blood-physical GET failed")
        raise HTTPException(status_code=500, detail="實體報告清單載入失敗")


@app.post("/api/blood-physical")
def post_blood_physical(req: BloodPhysicalRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Move a patient to external-lab physical report tracking."""
    try:
        contacts.add_blood_physical(req.nat_id, req.draw_date, req.name, req.nurse,
                                    req.draw_codes, req.draw_code_names, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        _invalidate_blood_physical_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-physical POST failed")
        raise HTTPException(status_code=500, detail="移至實體報告失敗")


@app.delete("/api/blood-physical")
def delete_blood_physical(req: BloodPhysicalRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Move a patient back from physical tracking to the digital list."""
    try:
        contacts.remove_blood_physical(req.nat_id, req.draw_date, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        _invalidate_blood_physical_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-physical DELETE failed")
        raise HTTPException(status_code=500, detail="撤銷失敗")


@app.post("/api/blood-physical/done")
def blood_physical_done(req: BloodPhysicalRequest, user: auth.CurrentUser = Depends(auth.get_current_user)):
    """Mark physical-report patient as notified and remove from physical tracking."""
    try:
        contacts.add_blood_notified(req.nat_id, req.draw_date, req.nurse, user.clinic_id)
        contacts.remove_blood_physical(req.nat_id, req.draw_date, user.clinic_id)
        _invalidate_blood_pending_cache(user.clinic_id)
        _invalidate_blood_physical_cache(user.clinic_id)
        return {"ok": True}
    except Exception:
        logger.exception("blood-physical/done POST failed")
        raise HTTPException(status_code=500, detail="標記完成失敗")


@app.get("/api/notice")
def get_notice() -> dict:
    try:
        text = open("notice.txt", encoding="utf-8").read().strip()
    except OSError:
        text = ""
    return {"text": text}


@app.get("/api/contacts/history")
def get_contacts_history(target_date: str | None = None, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    target = target_date or date.today().isoformat()
    try:
        history = contacts.get_print_history(target, user.clinic_id)
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
def mark_on_hold(req: OnHoldRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    try:
        hold_id = contacts.mark_on_hold(req.entry, req.note, req.nurse, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
        return {"hold_id": hold_id}
    except Exception:
        logger.exception("mark_on_hold failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="暫緩記錄儲存失敗，請稍後再試")


@app.post("/api/on-hold/manual")
def mark_on_hold_manual(req: ManualOnHoldRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    try:
        hold_id = contacts.mark_on_hold_manual(req.name, req.note, req.nurse, req.category, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
        return {"hold_id": hold_id}
    except Exception:
        logger.exception("mark_on_hold_manual failed for %s", req.name)
        raise HTTPException(status_code=500, detail="暫緩記錄儲存失敗，請稍後再試")


@app.delete("/api/on-hold")
def remove_on_hold(req: OnHoldRemoveRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.remove_on_hold(req.hold_id, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("remove_on_hold failed for id=%s", req.hold_id)
        raise HTTPException(status_code=500, detail="撤銷暫緩失敗，請稍後再試")


@app.post("/api/mspt-manual")
def mark_mspt_manual(req: MsptManualRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.mark_mspt_manual(
            req.entry.patient.chart_number,
            req.entry.patient.name,
            req.entry.patient.birth_date,
            req.mspt_stage,
            req.completed_date,
            req.nurse,
            user.clinic_id,
        )
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("mark_mspt_manual failed for %s", req.entry.patient.chart_number)
        raise HTTPException(status_code=500, detail="手動標記儲存失敗，請稍後再試")


@app.delete("/api/mspt-manual")
def unmark_mspt_manual(req: MsptManualRemoveRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        contacts.unmark_mspt_manual(req.chart_number, user.clinic_id)
        _invalidate_report_cache(user.clinic_id)
    except Exception:
        logger.exception("unmark_mspt_manual failed for %s", req.chart_number)
        raise HTTPException(status_code=500, detail="撤銷手動標記失敗，請稍後再試")


@app.get("/api/lab")
def get_lab_results(q: str = "", user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Return structured blood test results. Tries local DBF files first; falls back to DB cache."""
    nat_id = q.strip().upper()
    result = lab_results.get_lab_results(nat_id)
    if not result.get('bio') and not result.get('cbc'):
        cached = contacts.get_lab_cache(nat_id, user.clinic_id)
        if cached.get('bio') or cached.get('cbc'):
            return cached
    return result



@app.post("/api/admin/lab-report")
async def upload_lab_report(
    file: UploadFile = File(...),
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    if not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="請上傳 .xlsx 檔案")
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        report_id = lab_report.save_report(tmp_path, file.filename, admin.clinic_id)
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
def list_lab_reports(admin: auth.CurrentUser = Depends(auth.require_admin)) -> list:
    try:
        return lab_report.list_reports(admin.clinic_id)
    except Exception:
        logger.exception("list_lab_reports failed")
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.get("/api/admin/lab-report/{report_id}")
def get_lab_report(report_id: int, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    try:
        data = lab_report.get_report(report_id, admin.clinic_id)
        if data is None:
            raise HTTPException(status_code=404, detail="找不到此報告")
        return data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_lab_report failed for id=%s", report_id)
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.delete("/api/admin/lab-report/{report_id}")
def delete_lab_report(report_id: int, admin: auth.CurrentUser = Depends(auth.require_admin)) -> None:
    try:
        if not lab_report.delete_report(report_id, admin.clinic_id):
            raise HTTPException(status_code=404, detail="找不到此報告")
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_lab_report failed for id=%s", report_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


@app.get("/api/admin/settings/lab-codes")
def get_lab_code_settings(admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    try:
        return {"prefixes": _settings.get_lab_prefixes(admin.clinic_id)}
    except Exception:
        logger.exception("get_lab_code_settings failed")
        raise HTTPException(status_code=500, detail="讀取失敗")


@app.put("/api/admin/settings/lab-codes")
def save_lab_code_settings(body: dict, admin: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    try:
        prefixes = body.get("prefixes", [])
        if not isinstance(prefixes, list):
            raise HTTPException(status_code=422, detail="prefixes 必須是清單")
        _settings.save_lab_prefixes(prefixes, admin.clinic_id)
        return {"prefixes": _settings.get_lab_prefixes(admin.clinic_id)}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("save_lab_code_settings failed")
        raise HTTPException(status_code=500, detail="儲存失敗")


@app.get("/api/admin/settings/lab-code-catalog")
def get_lab_code_catalog(_: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    """Return all NHI blood-test codes grouped by chapter, with Chinese names."""
    import nhi_blood_codes as _nhi_mod
    _LABELS = {
        "08": "血液常規", "09": "血液生化", "12": "血清免疫學",
        "14": "病毒學", "27": "放射免疫分析", "30": "過敏原",
    }
    chapters = {
        ch: {"label": _LABELS.get(ch, f"章別 {ch}"), "codes": sorted(_nhi_mod.CHAPTER_CODES[ch])}
        for ch in _nhi_mod.DEFAULT_CHAPTERS
    }
    return {"chapters": chapters, "names": _nhi_mod.CODE_NAMES}


@app.get("/api/directory")
def list_clinic_contacts(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list:
    try:
        return directory.list_contacts(user.clinic_id)
    except Exception:
        logger.exception("list_clinic_contacts failed")
        raise HTTPException(status_code=500, detail="查詢失敗")


@app.post("/api/directory")
def add_clinic_contact(req: ClinicContactRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="名稱不可空白")
    try:
        new_id = directory.add_contact(req.name.strip(), req.category.strip(), req.phone.strip(), req.note.strip(), req.nurse, user.clinic_id)
        return {"id": new_id}
    except Exception:
        logger.exception("add_clinic_contact failed")
        raise HTTPException(status_code=500, detail="新增失敗")


@app.put("/api/directory/{contact_id}")
def update_clinic_contact(contact_id: int, req: ClinicContactRequest, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="名稱不可空白")
    try:
        if not directory.update_contact(contact_id, req.name.strip(), req.category.strip(), req.phone.strip(), req.note.strip(), user.clinic_id):
            raise HTTPException(status_code=404, detail="找不到此聯絡人")
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_clinic_contact failed for id=%s", contact_id)
        raise HTTPException(status_code=500, detail="更新失敗")


@app.delete("/api/directory/{contact_id}")
def delete_clinic_contact(contact_id: int, user: auth.CurrentUser = Depends(auth.get_current_user)) -> None:
    try:
        if not directory.delete_contact(contact_id, user.clinic_id):
            raise HTTPException(status_code=404, detail="找不到此聯絡人")
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_clinic_contact failed for id=%s", contact_id)
        raise HTTPException(status_code=500, detail="刪除失敗")


# ── Inventory (monthly 點貨 + ordering) ────────────────────────────────────────

def _inv_nurse(body: dict, user: auth.CurrentUser) -> str:
    # Shared-session model: nurse name comes from PIN selection passed by the frontend
    return str(body.get("nurse") or "").strip() or user.display_name


def _inv_qty(value, allow_none: bool = False) -> float | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise HTTPException(status_code=422, detail="請輸入數量")
    try:
        q = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="數量格式不正確")
    if q < 0 or q > 1_000_000:
        raise HTTPException(status_code=422, detail="數量格式不正確")
    return q


@app.get("/api/inventory/items")
def inv_list_items(archived: bool = False, user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    return inventory.list_items(user.clinic_id, include_archived=archived)


@app.post("/api/inventory/items")
def inv_add_item(body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not str(body.get("name") or "").strip():
        raise HTTPException(status_code=422, detail="品名不可空白")
    return {"id": inventory.add_item(user.clinic_id, body)}


@app.post("/api/inventory/items/bulk")
def inv_bulk_add(body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Add many items at once from pasted lines: 品名, 單位, 位置 (unit and location optional)."""
    added = 0
    for line in str(body.get("text") or "").splitlines():
        parts = [p.strip() for p in _re.split(r"[,，\t]", line)]
        if not parts or not parts[0]:
            continue
        inventory.add_item(user.clinic_id, {
            "name": parts[0],
            "unit": parts[1] if len(parts) > 1 else "",
            "location": parts[2] if len(parts) > 2 else str(body.get("location") or ""),
        })
        added += 1
    return {"added": added}


@app.put("/api/inventory/items/{item_id}")
def inv_update_item(item_id: int, body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not str(body.get("name") or "").strip():
        raise HTTPException(status_code=422, detail="品名不可空白")
    if not inventory.update_item(user.clinic_id, item_id, body):
        raise HTTPException(status_code=404, detail="找不到此品項")
    return {"ok": True}


@app.post("/api/inventory/items/{item_id}/archive")
def inv_archive_item(item_id: int, body: dict = Body(default={}), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not inventory.set_item_active(user.clinic_id, item_id, bool(body.get("restore"))):
        raise HTTPException(status_code=404, detail="找不到此品項")
    return {"ok": True}


@app.put("/api/inventory/items-order")
def inv_reorder(body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    ids = body.get("ids")
    if not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="ids 須為陣列")
    inventory.reorder_items(user.clinic_id, [int(i) for i in ids])
    return {"ok": True}


@app.get("/api/inventory/count")
def inv_current_count(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return inventory.get_current_count(user.clinic_id)


@app.post("/api/inventory/count")
def inv_start_count(body: dict = Body(default={}), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return inventory.start_count(user.clinic_id, _inv_nurse(body, user))


@app.put("/api/inventory/count/{count_id}/lines/{item_id}")
def inv_set_line(count_id: int, item_id: int, body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    qty = _inv_qty(body.get("qty"), allow_none=True)
    if not inventory.set_line(user.clinic_id, count_id, item_id, qty, _inv_nurse(body, user)):
        raise HTTPException(status_code=409, detail="這次點貨已完成，請先重新開啟才能修改")
    return {"ok": True}


@app.post("/api/inventory/count/{count_id}/complete")
def inv_complete_count(count_id: int, body: dict = Body(default={}), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not inventory.complete_count(user.clinic_id, count_id, _inv_nurse(body, user)):
        raise HTTPException(status_code=409, detail="這次點貨已經完成")
    return {"ok": True}


@app.post("/api/inventory/count/{count_id}/reopen")
def inv_reopen_count(count_id: int, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not inventory.reopen_count(user.clinic_id, count_id):
        raise HTTPException(status_code=404, detail="找不到這次點貨")
    return {"ok": True}


@app.get("/api/inventory/suggestions")
def inv_suggestions(user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return inventory.get_suggestions(user.clinic_id)


@app.get("/api/inventory/orders")
def inv_open_orders(user: auth.CurrentUser = Depends(auth.get_current_user)) -> list[dict]:
    return inventory.list_open_orders(user.clinic_id)


@app.post("/api/inventory/orders")
def inv_place_orders(body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise HTTPException(status_code=422, detail="請選擇要訂購的品項")
    count_id = body.get("count_id")
    placed = inventory.place_orders(user.clinic_id, lines, _inv_nurse(body, user),
                                    int(count_id) if count_id else None)
    return {"placed": placed}


@app.post("/api/inventory/orders/{order_id}/receive")
def inv_receive_order(order_id: int, body: dict = Body(...), user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    qty = _inv_qty(body.get("qty"))
    if not inventory.receive_order(user.clinic_id, order_id, qty, _inv_nurse(body, user)):
        raise HTTPException(status_code=404, detail="找不到此訂單，或已經標記到貨")
    return {"ok": True}


@app.post("/api/inventory/orders/{order_id}/cancel")
def inv_cancel_order(order_id: int, user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    if not inventory.cancel_order(user.clinic_id, order_id):
        raise HTTPException(status_code=404, detail="找不到此訂單")
    return {"ok": True}


# ── LINE integration ────────────────────────────────────────────────────────────

def _clinic_from_slug(slug: str) -> int:
    cid = line_service.clinic_id_for_slug(slug)
    if cid is None:
        raise HTTPException(status_code=404, detail="找不到此診所")
    return cid


def _rate_limited(store: dict, key: str, limit: int, window: int = 3600) -> bool:
    """Record one attempt for key; True if the key already hit the limit within the window."""
    now_ts = _time.time()
    recent = [t for t in store.get(key, []) if t > now_ts - window]
    if len(recent) >= limit:
        store[key] = recent
        return True
    recent.append(now_ts)
    store[key] = recent
    return False


@app.get("/line/{slug}/bind")
def line_bind_page(slug: str):
    """Patient-facing LINE binding page (public). Each clinic's LIFF app points here."""
    _clinic_from_slug(slug)
    return FileResponse("static/line-bind.html")


@app.get("/line/{slug}/config")
def line_public_config(slug: str):
    """Public LINE config (LIFF ID + the account's add-friend ID) — no secrets exposed."""
    s = line_service.get_settings(_clinic_from_slug(slug))
    return {
        "liff_id": s.get("liff_id", ""),
        "is_active": bool(s.get("is_active")),
        "basic_id": line_service.get_basic_id(s.get("channel_access_token") or ""),
    }


@app.post("/line/{slug}/webhook")
async def line_webhook(slug: str, request: Request, background: BackgroundTasks):
    """LINE platform webhook (public). Verify, answer 200 at once, process in the background."""
    clinic_id = _clinic_from_slug(slug)
    body_bytes = await request.body()
    sig = request.headers.get("X-Line-Signature", "")
    secret = line_service.get_settings(clinic_id).get("channel_secret", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if not line_service.verify_signature(body_bytes, sig, secret):
        raise HTTPException(status_code=400, detail="Invalid signature")
    import json as _json
    background.add_task(line_service.process_webhook, _json.loads(body_bytes), clinic_id)
    return {"status": "ok"}


@app.post("/line/{slug}/bind")
async def line_bind_submit(slug: str, request: Request):
    """Bind a patient from the LIFF page (public). Identity comes only from the verified
    LIFF token. Any patient may bind; an ID already bound to another LINE account is refused.
    The birth date is stored unchecked so bindings can be verified later."""
    clinic_id = _clinic_from_slug(slug)
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if _rate_limited(_bind_rate, client_ip, 10):
        raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試")

    data = await request.json()
    chart_number = (data.get("chart_number") or "").strip().upper()
    birth_date = (data.get("birth_date") or "").strip()
    liff_access_token = (data.get("liff_access_token") or "").strip()

    if not _re.fullmatch(r"[A-Z]\d{9}", chart_number):
        raise HTTPException(status_code=400, detail="身分證字號格式不正確")
    try:
        bd = date.fromisoformat(birth_date)
    except ValueError:
        bd = None
    if not bd or bd.year < 1900 or bd > date.today():
        raise HTTPException(status_code=400, detail="請輸入正確的生日")
    if not liff_access_token:
        raise HTTPException(status_code=400, detail="請透過 LINE 應用程式開啟綁定頁面")

    settings = line_service.get_settings(clinic_id)
    try:
        profile = line_service.verify_liff_token(liff_access_token, settings.get("login_channel_id", ""))
    except (requests.RequestException, ValueError):
        raise HTTPException(status_code=503, detail="LINE 服務暫時無法連線，請稍後再試")
    if not profile:
        raise HTTPException(status_code=403, detail="LINE 身份驗證失敗，請關閉頁面後重新開啟")

    # Without an identity check, never let someone silently take over another person's binding
    existing = line_service.get_binding(chart_number, clinic_id)
    if existing and existing["line_user_id"] != profile["userId"]:
        raise HTTPException(status_code=409, detail="此身分證字號已由其他 LINE 帳號綁定，如需更換請洽診所櫃台")

    line_service.bind_patient(chart_number, profile["userId"], profile["displayName"], clinic_id,
                              actor="patient", birth_date=birth_date)
    token = settings.get("channel_access_token", "")
    if token:
        line_service._push(token, profile["userId"], [{"type": "text", "text": "✅ 綁定成功！您將收到診所的回診與健康提醒訊息。"}])
    return {"status": "ok"}


# Clinic 1's LINE console may still point at the original un-scoped URLs
@app.get("/line/bind")
def line_bind_page_legacy():
    return FileResponse("static/line-bind.html")


@app.get("/line/config")
def line_public_config_legacy():
    return line_public_config(line_service.slug_for_clinic(1))


@app.post("/line/webhook")
async def line_webhook_legacy(request: Request, background: BackgroundTasks):
    return await line_webhook(line_service.slug_for_clinic(1), request, background)


@app.post("/line/bind")
async def line_bind_submit_legacy(request: Request):
    return await line_bind_submit(line_service.slug_for_clinic(1), request)


def _public_base(request: Request) -> str:
    """Public origin as the browser sees it (Railway terminates TLS in front of uvicorn)."""
    proto = request.headers.get("X-Forwarded-Proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or request.url.netloc
    return f"{proto}://{host}"


def _line_urls(request: Request, clinic_id: int) -> dict:
    base = f"{_public_base(request)}/line/{line_service.slug_for_clinic(clinic_id)}"
    return {"webhook_url": f"{base}/webhook", "bind_endpoint_url": f"{base}/bind"}


@app.get("/api/line/settings")
def get_line_settings(request: Request, user: auth.CurrentUser = Depends(auth.get_current_user)):
    s = line_service.get_settings(user.clinic_id)
    return {
        "has_token": bool((s.get("channel_access_token") or "").strip()),
        "has_secret": bool((s.get("channel_secret") or "").strip()),
        "liff_id": s.get("liff_id", ""),
        "login_channel_id": s.get("login_channel_id", ""),
        "line_mode": s.get("line_mode", ""),
        "is_active": bool(s.get("is_active", 0)),
        "message_templates": line_service.get_message_templates(user.clinic_id),
        **_line_urls(request, user.clinic_id),
    }


@app.post("/api/line/settings")
def save_line_settings(body: dict = Body(...), admin: auth.CurrentUser = Depends(auth.require_admin)):
    mode = (body.get("line_mode") or "").strip()
    if mode not in ("", "new", "own", "vendor"):
        raise HTTPException(status_code=400, detail="line_mode 不正確")
    line_service.save_settings(
        admin.clinic_id,
        token=(body.get("channel_access_token") or "").strip(),
        secret=(body.get("channel_secret") or "").strip(),
        liff_id=(body.get("liff_id") or "").strip(),
        is_active=bool(body.get("is_active", False)),
        login_channel_id=str(body.get("login_channel_id") or "").strip(),
        line_mode=mode,
        actor=admin.display_name,
    )
    return {"status": "ok"}


# ── LINE setup wizard ─────────────────────────────────────────────────────────

@app.post("/api/line/setup/messaging")
def line_setup_messaging(request: Request, body: dict = Body(...), admin: auth.CurrentUser = Depends(auth.require_admin)):
    """Check the Messaging API token, save token + secret, point the webhook at this clinic
    and send LINE's test event. A passing test also proves the channel secret is right,
    because our webhook rejects events whose signature doesn't match it."""
    token = (body.get("channel_access_token") or "").strip()
    secret = (body.get("channel_secret") or "").strip()
    if not token or not secret:
        raise HTTPException(status_code=400, detail="請貼上 Channel access token 與 Channel secret")
    info = line_service.get_bot_info(token)
    if info is None:
        raise HTTPException(status_code=400, detail="Channel access token 無效，請重新複製（注意不要多複製空白）")
    s = line_service.get_settings(admin.clinic_id)
    line_service.save_settings(
        admin.clinic_id, token=token, secret=secret, liff_id=s.get("liff_id", ""),
        is_active=bool(s.get("is_active")), actor=admin.display_name,
    )
    webhook_url = _line_urls(request, admin.clinic_id)["webhook_url"]
    hook = line_service.setup_webhook(token, webhook_url)
    return {"bot": info, "webhook_url": webhook_url, **hook}


@app.post("/api/line/setup/liff")
def line_setup_liff(request: Request, body: dict = Body(...), admin: auth.CurrentUser = Depends(auth.require_admin)):
    """Create the patient binding page (LIFF app) in the clinic's LINE Login channel.
    The channel secret is used once to get a short-lived token and is not stored."""
    channel_id = str(body.get("login_channel_id") or "").strip()
    channel_secret = (body.get("login_channel_secret") or "").strip()
    if not channel_id.isdigit() or not channel_secret:
        raise HTTPException(status_code=400, detail="請貼上 LINE Login 的 Channel ID（數字）與 Channel secret")
    endpoint = _line_urls(request, admin.clinic_id)["bind_endpoint_url"]
    result = line_service.create_liff_app(channel_id, channel_secret, endpoint)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    s = line_service.get_settings(admin.clinic_id)
    line_service.save_settings(
        admin.clinic_id, token="", secret="", liff_id=result["liff_id"],
        is_active=bool(s.get("is_active")), login_channel_id=channel_id, actor=admin.display_name,
    )
    return {"liff_id": result["liff_id"], "liff_url": f"https://liff.line.me/{result['liff_id']}"}


@app.post("/api/line/setup/liff-manual")
def line_setup_liff_manual(body: dict = Body(...), admin: auth.CurrentUser = Depends(auth.require_admin)):
    liff_id = (body.get("liff_id") or "").strip()
    channel_id = str(body.get("login_channel_id") or "").strip()
    if not _re.fullmatch(r"\d+-[A-Za-z0-9]+", liff_id) or not channel_id.isdigit():
        raise HTTPException(status_code=400, detail="LIFF ID 或 Channel ID 格式不正確")
    if not liff_id.startswith(channel_id + "-"):
        raise HTTPException(status_code=400, detail="這個 LIFF ID 不屬於此 LINE Login channel，請確認兩者來自同一個 channel")
    s = line_service.get_settings(admin.clinic_id)
    line_service.save_settings(
        admin.clinic_id, token="", secret="", liff_id=liff_id,
        is_active=bool(s.get("is_active")), login_channel_id=channel_id, actor=admin.display_name,
    )
    return {"liff_id": liff_id, "liff_url": f"https://liff.line.me/{liff_id}"}


@app.post("/api/line/setup/mode")
def line_setup_mode(body: dict = Body(...), admin: auth.CurrentUser = Depends(auth.require_admin)):
    mode = (body.get("line_mode") or "").strip()
    if mode not in ("new", "own", "vendor"):
        raise HTTPException(status_code=400, detail="line_mode 不正確")
    line_service.set_line_mode(admin.clinic_id, mode, actor=admin.display_name)
    return {"status": "ok"}


@app.post("/api/line/setup/activate")
def line_setup_activate(admin: auth.CurrentUser = Depends(auth.require_admin)):
    s = line_service.get_settings(admin.clinic_id)
    if not (s.get("channel_access_token") and s.get("channel_secret") and s.get("liff_id") and s.get("login_channel_id")):
        raise HTTPException(status_code=400, detail="設定尚未完成")
    line_service.save_settings(
        admin.clinic_id, token="", secret="", liff_id=s["liff_id"], is_active=True, actor=admin.display_name,
    )
    return {"status": "ok"}


@app.get("/api/line/setup/status")
def line_setup_status(request: Request, admin: auth.CurrentUser = Depends(auth.require_admin)):
    """Live check of every setup piece, so the wizard can resume and show what's missing."""
    s = line_service.get_settings(admin.clinic_id)
    token = (s.get("channel_access_token") or "").strip()
    bot = line_service.get_bot_info(token) if token else None
    hook = line_service.get_webhook_info(token) if token else None
    urls = _line_urls(request, admin.clinic_id)
    return {
        "line_mode": s.get("line_mode", ""),
        "bot": bot,
        "webhook_ok": bool(hook and hook.get("active") and hook.get("endpoint") == urls["webhook_url"]),
        "webhook_active": bool(hook and hook.get("active")),
        "liff_id": s.get("liff_id", ""),
        "login_channel_id": s.get("login_channel_id", ""),
        "is_active": bool(s.get("is_active")),
        "friend_count": line_service.get_friend_count(admin.clinic_id) if token else None,
        "bound_count": line_service.get_binding_count(admin.clinic_id),
        **urls,
    }


@app.get("/api/line/stats")
def get_line_stats(user: auth.CurrentUser = Depends(auth.get_current_user)):
    count = line_service.get_binding_count(user.clinic_id)
    return {"bound": count}


@app.get("/api/line/bindings")
def get_line_bindings(user: auth.CurrentUser = Depends(auth.get_current_user)):
    return line_service.get_all_bindings(user.clinic_id)


@app.delete("/api/line/binding/{chart_number}")
def delete_line_binding(chart_number: str, admin: auth.CurrentUser = Depends(auth.require_admin)):
    removed = line_service.unbind_patient(chart_number, admin.clinic_id, actor=admin.display_name)
    if not removed:
        raise HTTPException(status_code=404, detail="找不到此綁定")
    return {"status": "ok"}


@app.post("/api/line/import")
async def import_line_bindings(request: Request, admin: auth.CurrentUser = Depends(auth.require_admin)):
    """Bulk import bindings from a JSON list [{chart_number, line_user_id, display_name}]."""
    rows = await request.json()
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="須為陣列格式")
    result = line_service.bulk_import_bindings(rows, admin.clinic_id, actor=admin.display_name)
    return result


@app.post("/api/line/broadcast-invite")
def broadcast_bind_invite(admin: auth.CurrentUser = Depends(auth.require_admin)):
    """Broadcast the binding invitation to every friend of the clinic's account."""
    result = line_service.broadcast_bind_invite(admin.clinic_id)
    return result


@app.get("/api/line/coverage")
def get_line_coverage(
    category: str = Query("慢簽"),
    user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """How many of the pending patients for a category have a direct LINE binding."""
    report_data = get_report(report_date=None, user=user)
    source = {
        "慢簽": report_data.chronic_prescriptions,
        "代謝症候群": report_data.mspt_followups,
        "B肝": report_data.hep_followups,
    }.get(category, [])
    pending_chart_numbers = {e.patient.chart_number for e in source if _pick_line_template(e)}
    total = len(pending_chart_numbers)
    if not total:
        return {"total": 0, "bound": 0, "pct": 0}
    bound_set = {b["chart_number"] for b in line_service.get_all_bindings(user.clinic_id)}
    bound = len(pending_chart_numbers & bound_set)
    return {"total": total, "bound": bound, "pct": round(bound / total * 100) if total else 0}


@app.get("/api/line/templates")
def get_line_templates(user: auth.CurrentUser = Depends(auth.get_current_user)):
    return line_service.get_message_templates(user.clinic_id)


@app.post("/api/line/templates")
async def save_line_templates(
    request: Request,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    templates = await request.json()
    if not isinstance(templates, dict):
        raise HTTPException(status_code=400, detail="須為 JSON 物件")
    line_service.save_message_templates(admin.clinic_id, templates)
    return {"status": "ok"}


@app.post("/api/line/bound-status")
def get_line_bound_status(
    body: dict = Body(...),
    user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Batch-check which chart numbers have a LINE binding.
    Returns {chart_number: bool} for every number in the request list."""
    chart_numbers = body.get("chart_numbers", [])
    if not isinstance(chart_numbers, list):
        raise HTTPException(status_code=400, detail="chart_numbers 須為陣列")
    bound_set = {b["chart_number"] for b in line_service.get_all_bindings(user.clinic_id)}
    return {cn: (cn in bound_set) for cn in chart_numbers if cn}


@app.post("/api/line/push-one")
def line_push_one(
    body: dict = Body(...),
    user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Push the configured category message to a single bound patient."""
    chart_number = (body.get("chart_number") or "").strip().upper()
    category = (body.get("category") or "慢簽").strip()
    if not chart_number:
        raise HTTPException(status_code=400, detail="chart_number 為必填")
    settings = line_service.get_settings(user.clinic_id)
    if not settings.get("is_active"):
        raise HTTPException(status_code=400, detail="LINE 功能尚未啟用")
    if not (settings.get("channel_access_token") or "").strip():
        raise HTTPException(status_code=400, detail="LINE 憑證尚未設定")
    result = line_service.push_category_message(chart_number, category, user.clinic_id, actor=user.display_name)
    if result.get("status") == 200:
        return {"status": "sent"}
    raw_body = (result.get("body") or "")[:300]
    logger.warning("LINE push-one failed for %s: status=%s body=%s", chart_number, result.get("status"), raw_body)
    raise HTTPException(status_code=502, detail="LINE 傳送失敗，請確認綁定是否有效")


@app.post("/api/line/test-send")
def line_test_send(
    body: dict = Body(...),
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    """Send one category message to a chosen bound patient so the admin can check wording and
    delivery. Works before LINE is switched on and never marks anyone as contacted."""
    chart_number = (body.get("chart_number") or "").strip().upper()
    category = (body.get("category") or "").strip()
    if not chart_number or not category:
        raise HTTPException(status_code=400, detail="請選擇病患與訊息類型")
    result = line_service.push_category_message(
        chart_number, category, admin.clinic_id, actor=f"{admin.display_name}（測試）"
    )
    if result.get("status") == 200:
        return {"status": "sent"}
    reason = {
        "no_token": "尚未完成 LINE 設定",
        "not_bound": "此病患尚未綁定 LINE",
        "no_template": "此類型沒有訊息內容",
    }.get(result.get("body"))
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    if result.get("status") == 429:
        raise HTTPException(status_code=502, detail="本月訊息額度已用完")
    logger.warning("LINE test-send failed for %s: status=%s body=%s",
                   chart_number, result.get("status"), (result.get("body") or "")[:300])
    raise HTTPException(status_code=502, detail="LINE 傳送失敗，對方可能已封鎖官方帳號")


@app.get("/api/line/audit")
def get_line_audit_log(
    limit: int = Query(200, ge=1, le=1000),
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> list[dict]:
    """Return the LINE audit log for this clinic (newest first)."""
    return line_service.get_audit_log(admin.clinic_id, limit)


@app.get("/api/line/bound-chart-numbers")
def get_bound_chart_numbers(user: auth.CurrentUser = Depends(auth.get_current_user)):
    bindings = line_service.get_all_bindings(user.clinic_id)
    return {"chart_numbers": [b["chart_number"] for b in bindings]}


# ── Broadcast page ─────────────────────────────────────────────────────────────

@app.get("/broadcasts")
def broadcasts_page() -> Response:
    try:
        content = open("static/broadcasts.html", "rb").read()
    except OSError:
        raise HTTPException(status_code=503, detail="無法載入頁面")
    return Response(content=content, media_type="text/html",
                    headers={"Cache-Control": "no-store"})


# ── Broadcast API ───────────────────────────────────────────────────────────────

@app.get("/api/broadcasts")
def api_list_broadcasts(
    limit: int = Query(100, ge=1, le=500),
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> list[dict]:
    return broadcast_service.list_broadcasts(admin.clinic_id, limit)


@app.post("/api/broadcasts", status_code=201)
def api_create_broadcast(
    body: BroadcastCreateRequest,
    background_tasks: BackgroundTasks,
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    name = body.name.strip()
    content = body.content.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名稱不可空白")
    if not content:
        raise HTTPException(status_code=400, detail="訊息內容不可空白")
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="訊息內容不可超過 5000 字")
    scheduled_at = body.scheduled_at.strip()
    broadcast_id = broadcast_service.create_broadcast(
        clinic_id=admin.clinic_id,
        name=name,
        content=content,
        audience_filter=body.audience_filter,
        scheduled_at=scheduled_at,
        created_by=admin.display_name,
    )
    if not scheduled_at:
        # Send now in background
        background_tasks.add_task(
            broadcast_service.execute_broadcast, broadcast_id, admin.clinic_id
        )
    return {"id": broadcast_id, "scheduled": bool(scheduled_at)}


@app.get("/api/broadcasts/{broadcast_id}")
def api_get_broadcast(
    broadcast_id: int,
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    bc = broadcast_service.get_broadcast(broadcast_id, admin.clinic_id)
    if not bc:
        raise HTTPException(status_code=404, detail="找不到此廣播")
    return bc


@app.post("/api/broadcasts/{broadcast_id}/send")
def api_send_broadcast(
    broadcast_id: int,
    background_tasks: BackgroundTasks,
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    bc = broadcast_service.get_broadcast(broadcast_id, admin.clinic_id)
    if not bc:
        raise HTTPException(status_code=404, detail="找不到此廣播")
    if bc["status"] not in ("draft", "scheduled"):
        raise HTTPException(status_code=400, detail="此廣播狀態無法重新發送")
    background_tasks.add_task(
        broadcast_service.execute_broadcast, broadcast_id, admin.clinic_id
    )
    return {"ok": True}


@app.delete("/api/broadcasts/{broadcast_id}")
def api_cancel_broadcast(
    broadcast_id: int,
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    cancelled = broadcast_service.cancel_broadcast(broadcast_id, admin.clinic_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="此廣播無法取消（已發送或不存在）")
    return {"ok": True}


@app.get("/api/broadcasts/{broadcast_id}/recipients")
def api_get_recipients(
    broadcast_id: int,
    admin: auth.CurrentUser = Depends(auth.require_admin),
) -> list[dict]:
    bc = broadcast_service.get_broadcast(broadcast_id, admin.clinic_id)
    if not bc:
        raise HTTPException(status_code=404, detail="找不到此廣播")
    return broadcast_service.get_recipients(broadcast_id, admin.clinic_id)


# ── AI Agent routes ────────────────────────────────────────────────────────────

@app.get("/ai-agent")
def ai_agent_page():
    return FileResponse("static/ai-agent.html")


@app.get("/api/ai-agent/settings")
def ai_get_settings(admin: auth.CurrentUser = Depends(auth.require_admin)):
    return ai_agent_service.get_settings(admin.clinic_id)


@app.post("/api/ai-agent/settings")
def ai_save_settings(
    req: AiAgentSettingsRequest,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    ai_agent_service.save_settings(
        admin.clinic_id,
        enabled=req.enabled,
        provider=req.provider,
        gemini_api_key=req.gemini_api_key,
        claude_api_key=req.claude_api_key,
        model_name=req.model_name,
        system_prompt=req.system_prompt,
        schedule_json=req.schedule_json,
    )
    return {"status": "ok"}


@app.get("/api/ai-agent/kb")
def ai_list_kb(admin: auth.CurrentUser = Depends(auth.require_admin)):
    return ai_agent_service.list_kb(admin.clinic_id)


@app.post("/api/ai-agent/kb")
def ai_upsert_kb(
    req: AiKbUpsertRequest,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    new_id = ai_agent_service.upsert_kb(
        admin.clinic_id,
        title=req.title,
        content=req.content,
        category=req.category,
        is_active=req.is_active,
        sort_order=req.sort_order,
        kb_id=req.id,
    )
    return {"id": new_id}


@app.delete("/api/ai-agent/kb/{kb_id}")
def ai_delete_kb(
    kb_id: int,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    ok = ai_agent_service.delete_kb(kb_id, admin.clinic_id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到此知識庫條目")
    return {"status": "ok"}


@app.get("/api/ai-agent/conversations")
def ai_list_conversations(
    limit: int = Query(50, ge=1, le=200),
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    return ai_agent_service.list_conversations(admin.clinic_id, limit)


# ── Review Automation routes ───────────────────────────────────────────────────

@app.get("/reviews")
def reviews_page():
    return FileResponse("static/reviews.html")


@app.get("/api/reviews/settings")
def reviews_get_settings(admin: auth.CurrentUser = Depends(auth.require_admin)):
    return review_service.get_settings(admin.clinic_id)


@app.post("/api/reviews/settings")
def reviews_save_settings(
    req: ReviewSettingsRequest,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    review_service.save_settings(
        admin.clinic_id,
        enabled=req.enabled,
        google_maps_url=req.google_maps_url,
        threshold=req.threshold,
        message_template=req.message_template,
        base_url=req.base_url,
    )
    return {"status": "ok"}


@app.post("/api/reviews/send")
def reviews_send(
    req: ReviewSendRequest,
    background_tasks: BackgroundTasks,
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    """Send review invites to a list of bound patients."""
    s = review_service.get_settings(admin.clinic_id)
    if not s.get("enabled"):
        raise HTTPException(status_code=400, detail="評論自動化尚未啟用")
    access_token = (line_service.get_settings(admin.clinic_id).get("channel_access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="LINE 憑證尚未設定")
    base_url = s.get("base_url", "").strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="請先設定診所網址 (base_url)")

    results = []
    for chart in req.chart_numbers[:50]:  # cap at 50 per call
        with db._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT line_user_id FROM line_bindings WHERE chart_number=%s AND clinic_id=%s",
                    (chart, admin.clinic_id),
                )
                binding = cur.fetchone()
        if not binding:
            results.append({"chart_number": chart, "ok": False, "detail": "未綁定 LINE"})
            continue
        result = review_service.send_review_invite(
            clinic_id=admin.clinic_id,
            chart_number=chart,
            line_user_id=binding["line_user_id"],
            patient_name=chart,
            access_token=access_token,
            base_url=base_url,
            message_template=s.get("message_template", ""),
        )
        results.append({"chart_number": chart, **result})
    return results


@app.get("/api/reviews/requests")
def reviews_list_requests(
    limit: int = Query(100, ge=1, le=500),
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    return review_service.list_requests(admin.clinic_id, limit)


@app.get("/api/reviews/feedback")
def reviews_list_feedback(
    limit: int = Query(100, ge=1, le=500),
    admin: auth.CurrentUser = Depends(auth.require_admin),
):
    return review_service.list_feedback(admin.clinic_id, limit)


@app.get("/api/reviews/stats")
def reviews_stats(admin: auth.CurrentUser = Depends(auth.require_admin)):
    return review_service.get_stats(admin.clinic_id)


# ── Public review pages (no auth — patients access these) ─────────────────────

_REVIEW_PAGE = """<!doctype html><html lang="zh-TW"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>診所評分</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,'Microsoft JhengHei',sans-serif;background:#F8F9FA;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:#fff;border-radius:16px;padding:36px 28px;max-width:400px;width:100%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
h1{{font-size:22px;margin-bottom:8px}}
p{{color:#6B7280;font-size:14px;margin-bottom:28px;line-height:1.6}}
.stars{{display:flex;justify-content:center;gap:12px;margin-bottom:28px}}
.star{{font-size:40px;cursor:pointer;color:#D1D5DB;transition:color .15s;border:none;background:none;padding:4px}}
.star:hover,.star.sel{{color:#F59E0B}}
.btn{{display:block;width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;margin-top:4px}}
.btn:disabled{{opacity:.5;pointer-events:none}}
#msg{{font-size:14px;color:#DC2626;margin-top:12px;min-height:20px}}
</style></head><body>
<div class="card">
  <h1>請為我們評分</h1>
  <p>感謝您今天的來訪！<br>您的意見幫助我們持續改進。</p>
  <div class="stars" id="stars">
    <button class="star" data-v="1" onclick="rate(1)">★</button>
    <button class="star" data-v="2" onclick="rate(2)">★</button>
    <button class="star" data-v="3" onclick="rate(3)">★</button>
    <button class="star" data-v="4" onclick="rate(4)">★</button>
    <button class="star" data-v="5" onclick="rate(5)">★</button>
  </div>
  <button class="btn" id="submit-btn" onclick="submit()" disabled>送出評分</button>
  <div id="msg"></div>
</div>
<script>
let _sel = 0;
function rate(v) {{
  _sel = v;
  document.querySelectorAll('.star').forEach(s => {{
    s.classList.toggle('sel', parseInt(s.dataset.v) <= v);
  }});
  document.getElementById('submit-btn').disabled = false;
}}
async function submit() {{
  if (!_sel) return;
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = '送出中…';
  const r = await fetch('/review/{TOKEN}', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{rating: _sel}})
  }});
  const d = await r.json();
  if (d.action === 'maps' && d.google_maps_url) {{
    document.querySelector('.card').innerHTML = '<h1 style="margin-bottom:16px">感謝您的評分！</h1><p style="margin-bottom:24px">您的回饋對我們非常重要。<br>如果方便，歡迎在 Google 上留下評論！</p><a href="' + d.google_maps_url + '" target="_blank" style="display:block;padding:14px;background:#2563EB;color:#fff;border-radius:10px;font-weight:700;text-decoration:none;font-size:16px">前往 Google 評論 ★</a>';
  }} else if (d.action === 'feedback') {{
    location.href = '/feedback/{TOKEN}';
  }} else {{
    document.getElementById('msg').textContent = d.detail || '已送出，感謝您！';
  }}
}}
</script></body></html>"""

_FEEDBACK_PAGE = """<!doctype html><html lang="zh-TW"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>意見回饋</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,'Microsoft JhengHei',sans-serif;background:#F8F9FA;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:#fff;border-radius:16px;padding:36px 28px;max-width:400px;width:100%;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
h1{{font-size:20px;margin-bottom:8px}}
p{{color:#6B7280;font-size:14px;margin-bottom:20px;line-height:1.6}}
textarea{{width:100%;border:1.5px solid #E5E7EB;border-radius:10px;padding:12px;font-size:14px;font-family:inherit;resize:none;min-height:140px;outline:none}}
textarea:focus{{border-color:#2563EB}}
.btn{{display:block;width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;margin-top:14px}}
.btn:disabled{{opacity:.5;pointer-events:none}}
</style></head><body>
<div class="card">
  <h1>意見回饋</h1>
  <p>感謝您告訴我們您的感受。<br>您的意見將直接傳送給診所管理人員，幫助我們改善服務。</p>
  <textarea id="fb" placeholder="請在此輸入您的建議或感受…"></textarea>
  <button class="btn" id="btn" onclick="submit()">送出意見</button>
</div>
<script>
async function submit() {{
  const txt = document.getElementById('fb').value.trim();
  if (!txt) return;
  const btn = document.getElementById('btn');
  btn.disabled = true; btn.textContent = '送出中…';
  const r = await fetch('/feedback/{TOKEN}', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{content: txt}})
  }});
  const d = await r.json();
  document.querySelector('.card').innerHTML = '<h1 style="margin-bottom:12px">感謝您的回饋！</h1><p>您的意見已送達，我們將認真改進，期待下次能帶給您更好的體驗。</p>';
}}
</script></body></html>"""


@app.get("/review/{token}")
async def review_page(token: str):
    req = review_service.get_request_by_token(token)
    if not req:
        return Response("無效連結", status_code=404)
    html = _REVIEW_PAGE.replace("{TOKEN}", token)
    return Response(html, media_type="text/html")


@app.post("/review/{token}")
async def review_submit(token: str, request: Request):
    try:
        body = await request.json()
        rating = int(body.get("rating", 0))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid")
    result = review_service.submit_rating(token, rating)
    return result


@app.get("/feedback/{token}")
async def feedback_page(token: str):
    req = review_service.get_request_by_token(token)
    if not req:
        return Response("無效連結", status_code=404)
    html = _FEEDBACK_PAGE.replace("{TOKEN}", token)
    return Response(html, media_type="text/html")


@app.post("/feedback/{token}")
async def feedback_submit(token: str, request: Request):
    try:
        body = await request.json()
        content = str(body.get("content", "")).strip()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid")
    if not content:
        raise HTTPException(status_code=400, detail="內容不可為空")
    ok = review_service.submit_feedback(token, content)
    return {"ok": ok}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
