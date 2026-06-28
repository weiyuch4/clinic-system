from datetime import date
from typing import Literal
from pydantic import BaseModel

MsptStage = Literal["收案", "追1", "追2", "追3", "年度追蹤"]


class Patient(BaseModel):
    chart_number: str  # 病歷號
    name: str          # 姓名
    birth_date: date   # 出生日期


class FollowupEntry(BaseModel):
    patient: Patient
    disease_name: str
    due_date: date
    days_overdue: int
    category: Literal["慢簽", "代謝症候群", "B肝"]
    mspt_stage: MsptStage | None = None      # MSPT entries only — the NEXT stage due
    needs_blood_test: bool | None = None     # MSPT entries only — whether mspt_stage needs a fresh blood draw
    last_stage: str | None = None            # stage completed at last_visit_date (str to support hep values)
    chronic_stage: str | None = None         # 慢簽 only — next prescription type: 'IC01', 'IC02', or 'IC03'
    contact_reason: str | None = None        # e.g. "需回診+抽血" or "需抽血"
    call_required: bool = False              # True when re-surfaced after 7 days
    line_unlinked: bool = False              # True if a LINE send was attempted but this patient hasn't linked LINE to Alleypin
    recently_sent_days_ago: int | None = None  # set if the applicable LINE template was already sent within RECENT_SEND_THRESHOLD_DAYS
    last_visit_date: date | None = None      # date of most recent relevant visit
    contacted_at: date | None = None         # set only on already-contacted entries
    contacted_time: str | None = None        # HH:MM when contact was recorded
    nurse: str = ""                          # who recorded this action (print history only)


class MsptSubmittableEntry(BaseModel):
    patient: Patient
    mspt_stage: MsptStage                    # always 追1, 追2, or 追3
    blood_report_date: date                  # date of eligible 抽血報告
    days_since_last_stage: int


class MsptWaitingEntry(BaseModel):
    patient: Patient
    mspt_stage: MsptStage
    blood_draw_date: date


class ExcludedEntry(BaseModel):
    patient: Patient
    category: Literal["慢簽", "代謝症候群", "B肝"]
    mspt_stage: MsptStage | None = None
    due_date: date | None = None
    last_visit_date: date | None = None
    last_stage: str | None = None
    reason: str
    note: str = ""
    excluded_at: date
    auto: bool = False  # True = auto-generated from long-inactive called entry
    nurse: str = ""


class ManualPickupEntry(BaseModel):
    chart_number: str
    name: str
    birth_date: date
    pickup_date: date
    ps_days: int
    next_due: date
    nurse: str = ""


class OnHoldEntry(BaseModel):
    hold_id: int
    patient: Patient | None = None             # None for manual entries
    category: Literal["慢簽", "代謝症候群", "B肝"] | None = None
    due_date: date | None = None
    days_overdue: int | None = None
    mspt_stage: MsptStage | None = None
    last_stage: str | None = None
    last_visit_date: date | None = None
    disease_name: str | None = None
    note: str
    held_at: date
    nurse: str = ""
    is_manual: bool = False
    manual_name: str = ""                      # display name for manual entries


class MsptManualEntry(BaseModel):
    chart_number: str
    name: str
    birth_date: date
    mspt_stage: MsptStage
    completed_date: date
    nurse: str = ""
    marked_at: date


class DailyReport(BaseModel):
    report_date: date
    chronic_prescriptions: list[FollowupEntry]
    mspt_followups: list[FollowupEntry]
    mspt_inactive: list[FollowupEntry] = []   # need 收案 restart but no clinic visit in >1 year
    mspt_submittable: list[MsptSubmittableEntry]
    mspt_waiting: list[MsptWaitingEntry]
    hep_followups: list[FollowupEntry] = []   # B/C hepatitis patients overdue for 161-day follow-up
    hep_inactive: list[FollowupEntry] = []    # 結案/再收案 — internal handoff field; merged into
                                               # hep_followups in main.py before reaching the client
    hep_returned: list[FollowupEntry] = []    # hepatitis patients who recently visited, pending VPN entry
    # Populated from contacts.db, not IC data
    contacted: list[FollowupEntry] = []
    called: list[FollowupEntry] = []
    submitted: list[MsptSubmittableEntry] = []
    excluded: list[ExcludedEntry] = []
    mspt_completed: list[FollowupEntry] = []
    mspt_checkedin: list[FollowupEntry] = []
    chronic_manual_pickups: list[ManualPickupEntry] = []
    on_hold: list[OnHoldEntry] = []
    mspt_manual: list[MsptManualEntry] = []
    hep_returned_completed: list[FollowupEntry] = []  # archived 完成B肝 (VPN entered) records


class NurseEntryRequest(BaseModel):
    entry: FollowupEntry
    nurse: str = ""


class ManualPickupRequest(BaseModel):
    entry: FollowupEntry
    pickup_date: date
    ps_days: int
    nurse: str = ""


class ChartNumberRequest(BaseModel):
    chart_number: str


class ContactRequest(BaseModel):
    chart_number: str
    category: Literal["慢簽", "代謝症候群", "B肝"]
    due_date: date


class ExcludeRequest(BaseModel):
    entry: FollowupEntry
    reason: str
    note: str = ""
    nurse: str = ""


class UnexcludeRequest(BaseModel):
    chart_number: str
    category: Literal["慢簽", "代謝症候群", "B肝"]


class MsptCompleteRequest(BaseModel):
    chart_number: str
    mspt_stage: MsptStage
    due_date: date


class HepReturnedCompleteRequest(BaseModel):
    chart_number: str
    last_visit_date: date


class SendLineNotificationsRequest(BaseModel):
    category: Literal["慢簽", "代謝症候群", "B肝"]
    nurse: str = ""
    dry_run: bool = False
    chart_numbers: list[str] | None = None  # restrict to specific patients (e.g. for a test send)
    limit: int | None = None  # cap to the first N patients in the pending list, e.g. for a small test batch


class UndoLineNotificationRequest(BaseModel):
    nurse: str = ""
    dry_run: bool = False


class ClinicContactRequest(BaseModel):
    name: str
    category: str = ""
    phone: str = ""
    note: str = ""
    nurse: str = ""


class SubmitRequest(BaseModel):
    chart_number: str
    mspt_stage: MsptStage


class OnHoldRequest(BaseModel):
    entry: FollowupEntry
    note: str
    nurse: str = ""


class ManualOnHoldRequest(BaseModel):
    name: str
    note: str
    nurse: str = ""
    category: Literal["慢簽", "代謝症候群", "B肝"] | None = None


class OnHoldRemoveRequest(BaseModel):
    hold_id: int


class MsptManualRequest(BaseModel):
    entry: FollowupEntry
    mspt_stage: MsptStage
    completed_date: date
    nurse: str = ""


class MsptManualRemoveRequest(BaseModel):
    chart_number: str
