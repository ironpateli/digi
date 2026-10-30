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


class MeetingUpdate(BaseModel):
    agenda: str | None = None
    manual_notes: str | None = None


class TranscriptCreate(BaseModel):
    content: str = Field(min_length=20, max_length=100000)


class TaskUpdate(BaseModel):
    status: str
    outcome: str | None = None


class CarryCreate(BaseModel):
    to_meeting_id: str
    note: str | None = None


class CatchupCreate(BaseModel):
    target_name: str | None = None


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
