import time
import uuid
from datetime import date as date_type, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, delete as sql_delete
from sqlalchemy.orm import Session

from app.ai import extract_recap, generate_catchup_brief, link_knowledge
from app.db import Base, engine, get_db
from app.logger import log, correlation_id_var
from app.models import (
    AIRun, ActionHistory, ActionItem, CarryForward,
    Decision, KnowledgeDocument, KnowledgeLink, Meeting, Participant, Transcript, User,
)
from app.schemas import (
    CarryCreate, CatchupCreate, KnowledgeDocumentCreate, MeetingCreate, MeetingUpdate,
    ParticipantCreate, TaskUpdate, TranscriptCreate, UserCreate,
)

# ── App setup ──────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
app = FastAPI(title="DigiPlus")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Middleware: correlation ID + request logging ───────────────────────────────
@app.middleware("http")
async def request_logging(request: Request, call_next):
    cid = str(uuid.uuid4())
    correlation_id_var.set(cid)
    log.info(
        "request_start",
        extra={"event": "request_start", "correlation_id": cid,
               "method": request.method, "path": request.url.path},
    )
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Keep the request ID with unexpected failures, without including the
        # request body (which may contain private meeting notes) in the log.
        log.exception(
            "request_failed",
            extra={"event": "request_failed", "correlation_id": cid,
                   "method": request.method, "path": request.url.path},
        )
        raise
    latency = int((time.perf_counter() - t0) * 1000)
    log.info(
        "request_end",
        extra={"event": "request_end", "correlation_id": cid,
               "status": response.status_code, "latency_ms": latency},
    )
    response.headers["X-Correlation-ID"] = cid
    return response


# ── Shared helpers ─────────────────────────────────────────────────────────────
def _task_dict(t: ActionItem) -> dict:
    return {
        "id": t.id, "title": t.title, "description": t.description,
        "owner_name": t.owner_name,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "status": t.status, "priority": t.priority, "outcome": t.outcome,
    }


def meeting_payload(db: Session, meeting: Meeting) -> dict:
    tasks      = db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.created_at.desc())).all()
    decisions  = db.scalars(select(Decision).where(Decision.meeting_id == meeting.id)).all()
    transcripts = db.scalars(select(Transcript).where(Transcript.meeting_id == meeting.id)).all()
    carries = db.scalars(
        select(CarryForward).where(CarryForward.to_meeting_id == meeting.id)
        .order_by(CarryForward.created_at.desc())
    ).all()
    carried_items = []
    for carry in carries:
        item = db.get(ActionItem, carry.action_item_id)
        if item:
            item_data = _task_dict(item)
            item_data.update({"carried_from_meeting_id": item.meeting_id, "carry_note": carry.note})
            carried_items.append(item_data)
    participants = db.execute(
        select(Participant, User).join(User, Participant.user_id == User.id)
        .where(Participant.meeting_id == meeting.id)
    ).all()
    knowledge_rows = db.execute(
        select(KnowledgeLink, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeLink.document_id == KnowledgeDocument.id)
        .where(KnowledgeLink.meeting_id == meeting.id)
        .order_by(KnowledgeLink.created_at.desc())
    ).all()
    return {
        "id": meeting.id, "title": meeting.title, "type": meeting.type,
        "status": meeting.status,
        "scheduled_at": meeting.scheduled_at.isoformat(),
        "timezone": meeting.timezone,
        "agenda": meeting.agenda, "manual_notes": meeting.manual_notes,
        "approved_summary": meeting.approved_summary,
        "tasks":     [_task_dict(t) for t in tasks],
        # A carried item remains owned by its original meeting so its full
        # audit history is intact; this projection makes it actionable in the
        # next meeting as well.
        "carried_forward_items": carried_items,
        "participants": [
            {"id": user.id, "name": user.name, "email": user.email,
             "role": user.role, "attendance_status": participant.attendance_status}
            for participant, user in participants
        ],
        "knowledge_links": [
            {"id": link.id, "document_id": doc.id, "title": doc.title,
             "source_type": doc.source_type, "relevance_note": link.relevance_note}
            for link, doc in knowledge_rows
        ],
        "decisions": [{"id": d.id, "title": d.title, "description": d.description, "rationale": d.rationale} for d in decisions],
        "transcript_count": len(transcripts),
    }


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── Dashboard ──────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    meetings   = db.scalars(select(Meeting).order_by(Meeting.scheduled_at.desc())).all()
    open_count = db.scalar(
        select(func.count()).select_from(ActionItem)
        .where(ActionItem.status.not_in(["completed", "cancelled"]))
    ) or 0
    return {"meetings": [meeting_payload(db, m) for m in meetings], "open_tasks": open_count}


# ── People and attendance ─────────────────────────────────────────────────────
@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


@app.post("/api/users", status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(409, "A user with this email already exists")
    user = User(**data.model_dump())
    db.add(user); db.commit(); db.refresh(user)
    log.info("user_created", extra={"event": "user_created", "user_id": user.id})
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


# ── Meetings ───────────────────────────────────────────────────────────────────
@app.post("/api/meetings", status_code=201)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    if data.type not in {"meeting", "handover", "work_transfer"}:
        raise HTTPException(422, "Invalid meeting type")
    meeting = Meeting(**data.model_dump())
    db.add(meeting); db.commit(); db.refresh(meeting)
    log.info("meeting_created", extra={"event": "meeting_created", "meeting_id": meeting.id, "type": meeting.type})
    return meeting_payload(db, meeting)


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting_payload(db, meeting)


@app.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: str, data: MeetingUpdate, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(meeting, field, value or None)
    db.commit()
    log.info("meeting_updated", extra={"event": "meeting_updated", "meeting_id": meeting_id})
    return meeting_payload(db, meeting)


@app.post("/api/meetings/{meeting_id}/participants", status_code=201)
def add_participant(meeting_id: str, data: ParticipantCreate, db: Session = Depends(get_db)):
    meeting, user = db.get(Meeting, meeting_id), db.get(User, data.user_id)
    if not meeting or not user:
        raise HTTPException(404, "Meeting or user not found")
    existing = db.scalar(select(Participant).where(
        Participant.meeting_id == meeting_id, Participant.user_id == data.user_id,
    ))
    if existing:
        existing.attendance_status = data.attendance_status
    else:
        db.add(Participant(meeting_id=meeting_id, user_id=data.user_id,
                           attendance_status=data.attendance_status))
    db.commit()
    log.info("participant_added", extra={"event": "participant_added", "meeting_id": meeting_id, "user_id": data.user_id})
    return meeting_payload(db, meeting)


@app.delete("/api/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
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
    log.info("meeting_deleted", extra={"event": "meeting_deleted", "meeting_id": meeting_id})
    return Response(status_code=204)


# ── Transcripts + AI extraction ────────────────────────────────────────────────
@app.post("/api/meetings/{meeting_id}/transcripts")
def process_transcript(meeting_id: str, data: TranscriptCreate, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    transcript = Transcript(meeting_id=meeting.id, content=data.content)
    db.add(transcript); db.flush()
    run = AIRun(meeting_id=meeting.id, transcript_id=transcript.id)
    db.add(run); db.commit(); db.refresh(run)
    t0 = time.perf_counter()
    try:
        result = extract_recap(data.content)
        latency = int((time.perf_counter() - t0) * 1000)
        run.output_json, run.status, run.latency_ms = result, "review_required", latency
        meeting.status = "review_required"
        db.commit()
        log.info("ai_extraction_success", extra={
            "event": "ai_extraction", "meeting_id": meeting_id,
            "run_id": run.id, "latency_ms": latency, "status": "succeeded",
            "model": "qwen/qwen3.8-27b",
        })
        return {"run_id": run.id, "status": run.status, "proposal": result}
    except Exception as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        run.status, run.error_message, run.latency_ms = "failed", str(exc)[:1000], latency
        meeting.status = "failed"
        db.commit()
        log.error("ai_extraction_failed", extra={
            "event": "ai_extraction", "meeting_id": meeting_id,
            "run_id": run.id, "latency_ms": latency, "status": "failed",
            "error": str(exc)[:200],
        })
        raise HTTPException(502, f"AI extraction failed: {run.error_message}")


# ── AI run approval ────────────────────────────────────────────────────────────
@app.post("/api/ai-runs/{run_id}/approve")
def approve_ai_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AIRun, run_id)
    if not run or not run.output_json:
        raise HTTPException(404, "AI proposal not found")
    if run.status == "approved":
        return {"status": "approved"}
    proposal = run.output_json
    meeting  = db.get(Meeting, run.meeting_id)
    meeting.approved_summary = proposal["summary"]
    for item in proposal.get("decisions", []):
        db.add(Decision(meeting_id=meeting.id, title=item["title"],
                        description=item["description"], rationale=item.get("rationale"),
                        created_by_ai=True))
    for item in proposal.get("action_items", []):
        due = date_type.fromisoformat(item["due_date"]) if item.get("due_date") else None
        action = ActionItem(
            meeting_id=meeting.id, title=item["title"],
            description=item.get("description"), owner_name=item.get("owner"),
            due_date=due, priority=item.get("priority", "medium"), created_by_ai=True,
        )
        db.add(action); db.flush()
        db.add(ActionHistory(action_item_id=action.id, event_type="approved_from_ai",
                             detail="Approved from AI recap"))
    run.status, meeting.status = "approved", "completed"
    db.commit()
    log.info("ai_run_approved", extra={"event": "ai_approved", "run_id": run_id, "meeting_id": run.meeting_id})
    return meeting_payload(db, meeting)


# ── Catch-up brief ─────────────────────────────────────────────────────────────
@app.post("/api/meetings/{meeting_id}/catchup-brief")
def catchup_brief(meeting_id: str, data: CatchupCreate, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    payload = meeting_payload(db, meeting)
    t0 = time.perf_counter()
    try:
        brief   = generate_catchup_brief(payload, data.target_name)
        latency = int((time.perf_counter() - t0) * 1000)
        log.info("catchup_brief_generated", extra={
            "event": "catchup_brief", "meeting_id": meeting_id,
            "latency_ms": latency, "status": "succeeded",
        })
        return {"brief": brief, "meeting_id": meeting_id}
    except Exception as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        log.error("catchup_brief_failed", extra={
            "event": "catchup_brief", "meeting_id": meeting_id,
            "latency_ms": latency, "error": str(exc)[:200],
        })
        raise HTTPException(502, f"Brief generation failed: {str(exc)[:200]}")


# ── Tasks ──────────────────────────────────────────────────────────────────────
@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, data: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(ActionItem, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if data.status is None and data.owner_name is None:
        raise HTTPException(422, "Provide a status or an owner")
    if data.status is not None and data.status not in {"open", "in_progress", "blocked", "completed", "cancelled"}:
        raise HTTPException(422, "Invalid status")
    if data.status in {"completed", "cancelled"} and not data.outcome:
        raise HTTPException(422, "An outcome is required when closing a task")
    old = task.status
    old_owner = task.owner_name
    if data.status is not None:
        task.status = data.status
    if data.owner_name is not None and data.owner_name.strip() != task.owner_name:
        task.owner_name = data.owner_name.strip() or None
        db.add(ActionHistory(action_item_id=task.id, event_type="reassigned",
                             detail=f"{old_owner or 'Unassigned'} -> {task.owner_name or 'Unassigned'}"))
        log.info("task_reassigned", extra={"event": "task_reassigned", "task_id": task_id,
                                            "old_owner": old_owner, "new_owner": task.owner_name})
    if data.outcome:
        task.outcome = data.outcome
    if data.status is not None:
        db.add(ActionHistory(action_item_id=task.id, event_type="status_changed",
                             detail=f"{old} -> {task.status}"))
    db.commit()
    if data.status is not None:
        log.info("task_status_changed", extra={
            "event": "task_status_changed", "task_id": task_id,
            "old_status": old, "new_status": task.status,
        })
    return _task_dict(task)


# ── Knowledge base ────────────────────────────────────────────────────────────
@app.get("/api/knowledge-documents")
def list_knowledge_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())).all()
    return [{"id": d.id, "title": d.title, "content": d.content,
             "source_type": d.source_type, "created_at": d.created_at.isoformat()} for d in docs]


@app.post("/api/knowledge-documents", status_code=201)
def create_knowledge_document(data: KnowledgeDocumentCreate, db: Session = Depends(get_db)):
    doc = KnowledgeDocument(**data.model_dump())
    db.add(doc); db.commit(); db.refresh(doc)
    log.info("knowledge_document_created", extra={"event": "knowledge_document_created", "document_id": doc.id})
    return {"id": doc.id, "title": doc.title, "content": doc.content, "source_type": doc.source_type}


@app.post("/api/meetings/{meeting_id}/knowledge-links/generate")
def generate_knowledge_links(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    documents = list_knowledge_documents(db)
    if not documents:
        raise HTTPException(422, "Add a knowledge document before generating links")
    t0 = time.perf_counter()
    try:
        suggestions = link_knowledge(meeting_payload(db, meeting), documents)
        existing = {x.document_id for x in db.scalars(select(KnowledgeLink).where(KnowledgeLink.meeting_id == meeting_id)).all()}
        for item in suggestions:
            if item["document_id"] not in existing:
                db.add(KnowledgeLink(meeting_id=meeting_id, document_id=item["document_id"],
                                     relevance_note=item["relevance"], created_by_ai=True))
        db.commit()
        latency = int((time.perf_counter() - t0) * 1000)
        log.info("knowledge_links_generated", extra={"event": "knowledge_linking", "meeting_id": meeting_id,
                                                       "latency_ms": latency, "status": "succeeded"})
        return meeting_payload(db, meeting)
    except Exception as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        log.error("knowledge_linking_failed", extra={"event": "knowledge_linking", "meeting_id": meeting_id,
                                                        "latency_ms": latency, "status": "failed", "error": str(exc)[:200]})
        raise HTTPException(502, "Knowledge linking failed. Your documents remain saved; try again later.")


@app.post("/api/tasks/{task_id}/carry-forward")
def carry_forward(task_id: str, data: CarryCreate, db: Session = Depends(get_db)):
    task   = db.get(ActionItem, task_id)
    target = db.get(Meeting, data.to_meeting_id)
    if not task or not target:
        raise HTTPException(404, "Task or target meeting not found")
    if task.status in {"completed", "cancelled"}:
        raise HTTPException(422, "Only open tasks can be carried forward")
    db.add(CarryForward(action_item_id=task.id, to_meeting_id=target.id, note=data.note))
    db.add(ActionHistory(action_item_id=task.id, event_type="carried_forward",
                         detail=f"Carried to {target.title}"))
    db.commit()
    log.info("task_carried_forward", extra={
        "event": "task_carried_forward", "task_id": task_id,
        "to_meeting_id": data.to_meeting_id,
    })
    return {"status": "carried_forward"}


# ── Risk Radar (special feature) ───────────────────────────────────────────────
@app.get("/api/risk-radar")
def risk_radar(db: Session = Depends(get_db)):
    """
    Handover Risk Radar — surfaces unresolved risks that cause context loss.
    Identifies: overdue tasks, missing owners, blocked items, tasks with no deadline.
    """
    today       = date_type.today()
    open_states = ["open", "in_progress", "blocked"]

    def _shape(t: ActionItem) -> dict:
        m = db.get(Meeting, t.meeting_id)
        return {
            "id": t.id, "title": t.title,
            "owner_name": t.owner_name,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "status": t.status, "priority": t.priority,
            "meeting_id": t.meeting_id,
            "meeting_title": m.title if m else None,
        }

    overdue  = db.scalars(select(ActionItem).where(
        ActionItem.status.in_(open_states),
        ActionItem.due_date < today,
    )).all()

    no_owner = db.scalars(select(ActionItem).where(
        ActionItem.status.in_(open_states),
        ActionItem.owner_name.is_(None),
    )).all()

    blocked  = db.scalars(select(ActionItem).where(
        ActionItem.status == "blocked",
    )).all()

    no_due   = db.scalars(select(ActionItem).where(
        ActionItem.status.in_(open_states),
        ActionItem.due_date.is_(None),
    )).all()

    all_ids      = {t.id for t in overdue + no_owner + blocked + no_due}
    total_risks  = len(all_ids)

    log.info("risk_radar_computed", extra={
        "event": "risk_radar", "total_risks": total_risks,
        "overdue": len(overdue), "no_owner": len(no_owner),
        "blocked": len(blocked), "no_due": len(no_due),
    })

    return {
        "total_risks":  total_risks,
        "overdue":      [_shape(t) for t in overdue],
        "no_owner":     [_shape(t) for t in no_owner],
        "blocked":      [_shape(t) for t in blocked],
        "no_due_date":  [_shape(t) for t in no_due],
    }


# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")
