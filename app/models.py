from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def uid() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(50), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(30), default="meeting")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Participant(Base):
    __tablename__ = "meeting_participants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    attendance_status: Mapped[str] = mapped_column(String(30), default="attended")


class Transcript(Base):
    __tablename__ = "meeting_transcripts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), default="pasted_text")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    transcript_id: Mapped[str] = mapped_column(ForeignKey("meeting_transcripts.id"))
    operation: Mapped[str] = mapped_column(String(40), default="transcript_extraction")
    status: Mapped[str] = mapped_column(String(30), default="processing")
    provider: Mapped[str] = mapped_column(String(50), default="groq")
    model: Mapped[str] = mapped_column(String(100), default="openai/gpt-oss-20b")
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)


class ActionItem(Base):
    __tablename__ = "action_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActionHistory(Base):
    __tablename__ = "action_item_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CarryForward(Base):
    __tablename__ = "action_item_carry_forwards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id"))
    to_meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
