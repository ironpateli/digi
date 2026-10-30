import time
from datetime import date, datetime
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, delete as sql_delete
from sqlalchemy.orm import Session
from app.ai import extract_recap
from app.db import Base, engine, get_db
from app.models import AIRun, ActionHistory, ActionItem, CarryForward, Decision, Meeting, Participant, Transcript
from app.schemas import CarryCreate, MeetingCreate, MeetingUpdate, TaskUpdate, TranscriptCreate

Base.metadata.create_all(bind=engine)
app = FastAPI(title="DigiPlus")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def meeting_payload(db: Session, meeting: Meeting):
    tasks = db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.created_at.desc())).all()
    decisions = db.scalars(select(Decision).where(Decision.meeting_id == meeting.id)).all()
    transcripts = db.scalars(select(Transcript).where(Transcript.meeting_id == meeting.id).order_by(Transcript.created_at.desc())).all()
    return {
        "id": meeting.id, "title": meeting.title, "type": meeting.type, "status": meeting.status,
        "scheduled_at": meeting.scheduled_at.isoformat(), "timezone": meeting.timezone, "agenda": meeting.agenda,
        "manual_notes": meeting.manual_notes, "approved_summary": meeting.approved_summary,
        "tasks": [{"id": x.id, "title": x.title, "description": x.description, "owner_name": x.owner_name,
                   "due_date": x.due_date.isoformat() if x.due_date else None, "status": x.status,
                   "priority": x.priority, "outcome": x.outcome} for x in tasks],
        "decisions": [{"id": x.id, "title": x.title, "description": x.description, "rationale": x.rationale} for x in decisions],
        "transcript_count": len(transcripts),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    meetings = db.scalars(select(Meeting).order_by(Meeting.scheduled_at.desc())).all()
    open_count = db.scalar(select(func.count()).select_from(ActionItem).where(ActionItem.status.not_in(["completed", "cancelled"]))) or 0
    return {"meetings": [meeting_payload(db, m) for m in meetings], "open_tasks": open_count}


@app.post("/api/meetings", status_code=201)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    if data.type not in {"meeting", "handover", "work_transfer"}:
        raise HTTPException(422, "Invalid meeting type")
    meeting = Meeting(**data.model_dump())
    db.add(meeting); db.commit(); db.refresh(meeting)
    return meeting_payload(db, meeting)


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting: raise HTTPException(404, "Meeting not found")
    return meeting_payload(db, meeting)


@app.post("/api/meetings/{meeting_id}/transcripts")
def process_transcript(meeting_id: str, data: TranscriptCreate, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting: raise HTTPException(404, "Meeting not found")
    transcript = Transcript(meeting_id=meeting.id, content=data.content)
    db.add(transcript); db.flush()
    run = AIRun(meeting_id=meeting.id, transcript_id=transcript.id)
    db.add(run); db.commit(); db.refresh(run)
    started = time.perf_counter()
    try:
        result = extract_recap(data.content)
        run.output_json, run.status = result, "review_required"
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        meeting.status = "review_required"
        db.commit()
        return {"run_id": run.id, "status": run.status, "proposal": result}
    except Exception as exc:
        run.status, run.error_message = "failed", str(exc)[:1000]
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        meeting.status = "failed"
        db.commit()
        raise HTTPException(502, f"AI extraction failed: {run.error_message}")


@app.post("/api/ai-runs/{run_id}/approve")
def approve_ai_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AIRun, run_id)
    if not run or not run.output_json: raise HTTPException(404, "AI proposal not found")
    if run.status == "approved": return {"status": "approved"}
    proposal = run.output_json
    meeting = db.get(Meeting, run.meeting_id)
    meeting.approved_summary = proposal["summary"]
    for item in proposal.get("decisions", []):
        db.add(Decision(meeting_id=meeting.id, title=item["title"], description=item["description"], rationale=item.get("rationale"), created_by_ai=True))
    for item in proposal.get("action_items", []):
        due_date = date.fromisoformat(item["due_date"]) if item.get("due_date") else None
        action = ActionItem(meeting_id=meeting.id, title=item["title"], description=item.get("description"), owner_name=item.get("owner"), due_date=due_date, priority=item.get("priority", "medium"), created_by_ai=True)
        db.add(action); db.flush(); db.add(ActionHistory(action_item_id=action.id, event_type="approved_from_ai", detail="Approved from AI recap"))
    run.status, meeting.status = "approved", "completed"
    db.commit()
    return meeting_payload(db, meeting)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, data: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(ActionItem, task_id)
    if not task: raise HTTPException(404, "Task not found")
    if data.status not in {"open", "in_progress", "blocked", "completed", "cancelled"}: raise HTTPException(422, "Invalid status")
    if data.status in {"completed", "cancelled"} and not data.outcome: raise HTTPException(422, "An outcome is required when closing a task")
    old = task.status; task.status = data.status
    if data.outcome: task.outcome = data.outcome
    db.add(ActionHistory(action_item_id=task.id, event_type="status_changed", detail=f"{old} -> {task.status}"))
    db.commit()
    return {"id": task.id, "status": task.status, "outcome": task.outcome}


@app.post("/api/tasks/{task_id}/carry-forward")
def carry_forward(task_id: str, data: CarryCreate, db: Session = Depends(get_db)):
    task, target = db.get(ActionItem, task_id), db.get(Meeting, data.to_meeting_id)
    if not task or not target: raise HTTPException(404, "Task or target meeting not found")
    if task.status in {"completed", "cancelled"}: raise HTTPException(422, "Only open tasks can be carried forward")
    db.add(CarryForward(action_item_id=task.id, to_meeting_id=target.id, note=data.note))
    db.add(ActionHistory(action_item_id=task.id, event_type="carried_forward", detail=f"Carried to {target.title}"))
    db.commit()
    return {"status": "carried_forward"}


@app.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: str, data: MeetingUpdate, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting: raise HTTPException(404, "Meeting not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(meeting, field, value or None)
    db.commit()
    return meeting_payload(db, meeting)


@app.delete("/api/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting: raise HTTPException(404, "Meeting not found")
    items = db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting_id)).all()
    for item in items:
        db.execute(sql_delete(ActionHistory).where(ActionHistory.action_item_id == item.id))
        db.execute(sql_delete(CarryForward).where(CarryForward.action_item_id == item.id))
    db.execute(sql_delete(CarryForward).where(CarryForward.to_meeting_id == meeting_id))
    db.execute(sql_delete(ActionItem).where(ActionItem.meeting_id == meeting_id))
    db.execute(sql_delete(Decision).where(Decision.meeting_id == meeting_id))
    db.execute(sql_delete(AIRun).where(AIRun.meeting_id == meeting_id))
    db.execute(sql_delete(Transcript).where(Transcript.meeting_id == meeting_id))
    db.execute(sql_delete(Participant).where(Participant.meeting_id == meeting_id))
    db.delete(meeting)
    db.commit()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")
