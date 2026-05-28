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
    category: Literal["慢簽", "代謝症候群"]
    mspt_stage: MsptStage | None = None      # MSPT entries only — the NEXT stage due
    last_stage: MsptStage | None = None      # the stage completed at last_visit_date
    contact_reason: str | None = None         # e.g. "需回診+抽血" or "需抽血"
    call_required: bool = False              # True when re-surfaced after 7 days
    last_visit_date: date | None = None      # MSPT: date of most recent stage visit
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
    category: Literal["慢簽", "代謝症候群"]
    mspt_stage: MsptStage | None = None
    due_date: date | None = None
    last_visit_date: date | None = None
    last_stage: MsptStage | None = None
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


class DailyReport(BaseModel):
    report_date: date
    chronic_prescriptions: list[FollowupEntry]
    mspt_followups: list[FollowupEntry]
    mspt_inactive: list[FollowupEntry] = []   # need 收案 restart but no clinic visit in >1 year
    mspt_submittable: list[MsptSubmittableEntry]
    mspt_waiting: list[MsptWaitingEntry]
    # Populated from contacts.db, not IC data
    contacted: list[FollowupEntry] = []
    called: list[FollowupEntry] = []
    submitted: list[MsptSubmittableEntry] = []
    excluded: list[ExcludedEntry] = []
    mspt_completed: list[FollowupEntry] = []
    chronic_manual_pickups: list[ManualPickupEntry] = []


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
    category: Literal["慢簽", "代謝症候群"]
    due_date: date


class ExcludeRequest(BaseModel):
    entry: FollowupEntry
    reason: str
    note: str = ""
    nurse: str = ""


class UnexcludeRequest(BaseModel):
    chart_number: str
    category: Literal["慢簽", "代謝症候群"]


class MsptCompleteRequest(BaseModel):
    chart_number: str
    mspt_stage: MsptStage
    due_date: date


class SubmitRequest(BaseModel):
    chart_number: str
    mspt_stage: MsptStage
