from datetime import datetime, date
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeetingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    type: str = "meeting"
    scheduled_at: datetime
    timezone: str = "Asia/Kolkata"
    agenda: str | None = None
    manual_notes: str | None = None


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member", max_length=50)


class ParticipantCreate(BaseModel):
    user_id: str
    attendance_status: str = "invited"


class MeetingUpdate(BaseModel):
    agenda: str | None = None
    manual_notes: str | None = None


class TranscriptCreate(BaseModel):
    content: str = Field(min_length=20, max_length=100000)


class TaskUpdate(BaseModel):
    status: str | None = None
    outcome: str | None = None
    owner_name: str | None = None


class CarryCreate(BaseModel):
    to_meeting_id: str
    note: str | None = None


class CatchupCreate(BaseModel):
    target_name: str | None = None


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    content: str = Field(min_length=20, max_length=100000)
    source_type: str = "team_document"


class AIAction(StrictModel):
    title: str
    description: str | None
    owner: str | None
    due_date: date | None
    priority: str


class AIDecision(StrictModel):
    title: str
    description: str
    rationale: str | None


class AIResult(StrictModel):
    summary: str
    decisions: list[AIDecision]
    action_items: list[AIAction]
    risks_or_open_questions: list[str]
