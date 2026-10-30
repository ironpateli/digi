# DigiPlus - AI-Powered Knowledge & Task Management

## Purpose

DigiPlus captures meeting and work-transfer context, turns unstructured notes or transcripts into a reviewable structured recap, and keeps action items visible until they are closed. It prevents knowledge from being lost when a meeting is missed or work changes hands.

## Product outcomes

- Create and persist meetings and work transfers, including agenda, participants, notes, decisions, and action items.
- Track each action item's owner, due date, status, reassignment history, and final outcome.
- Carry unresolved items into a subsequent meeting or handover without duplicating or losing the original context.
- Use AI to extract a summary, decisions, action items, and suggested owners from unstructured content.
- Produce short AI-generated catch-up and handover briefs.
- Maintain a small knowledge base of team documents and historical meeting material, then link relevant content to work items.
- Validate input, preserve original source material, handle AI failures gracefully, and log meaningful events.

## Architecture decisions

### Application shape

The first version is a modular monolith:

```text
Web frontend
    |
    v
FastAPI application  <---->  PostgreSQL
    |
    +----> LLM provider
```

The backend owns all database access and LLM calls. The browser never receives an LLM API key. For the first version, AI extraction happens in the API request while the frontend displays a loading state. This is appropriate for normal pasted meeting transcripts and removes queue/worker infrastructure.

### Transcript to approved record flow

```text
1. User creates a meeting or handover.
2. User enters notes or uploads/pastes a transcript.
3. API stores the raw source and creates an AI run.
4. API calls the LLM and requires schema-constrained JSON.
5. API validates the JSON and creates proposed decisions and action items.
6. Frontend displays proposals for edit, approval, or rejection.
7. Approved proposals are written as official decisions and action items.
8. Future summaries, handovers, dashboards, and knowledge retrieval use approved data.
```

AI output is proposed content, not a source of truth. This protects against extraction errors and makes manual correction explicit. When an AI call fails, the raw transcript remains available, the run is marked failed, and a user can retry or enter items manually.

### Dates and auditability

- Store instants such as a meeting time in `TIMESTAMPTZ` and retain the IANA timezone selected by the user.
- Store task-only deadlines in `DATE`.
- Write every action-item lifecycle change to an immutable history table.
- Store a correlation/request ID and sanitized AI outcome for each AI run and application log event.
- Do not log secrets, credentials, or unnecessary raw content.

## Core data model

### `users`

| Column | Notes |
| --- | --- |
| `id` | UUID primary key |
| `name`, `email` | `email` is unique |
| `role` | Team role |
| `is_active` | Supports departed users without deleting history |
| `created_at`, `updated_at` | Audit timestamps |

### `meetings`

| Column | Notes |
| --- | --- |
| `id` | UUID primary key |
| `title`, `agenda`, `manual_notes` | Meeting content entered by people |
| `type` | `meeting`, `handover`, or `work_transfer` |
| `status` | Lifecycle state |
| `scheduled_at`, `timezone` | Time-aware scheduling |
| `approved_summary` | Reviewed final recap |
| `previous_meeting_id` | Optional continuity link |
| `created_by_user_id`, `created_at`, `updated_at` | Audit fields |

### `meeting_participants`

Join table: `meeting_id`, `user_id`, `attendance_status`, `participant_role`, `created_at`.

### `meeting_transcripts`

| Column | Notes |
| --- | --- |
| `id`, `meeting_id` | Primary key and meeting relationship |
| `content` | Immutable submitted transcript/source text |
| `source_type` | Pasted text, uploaded file, recording transcript, or email import |
| `uploaded_by_user_id`, `created_at` | Audit fields |

### `ai_runs`

| Column | Notes |
| --- | --- |
| `id`, `meeting_id`, `transcript_id` | Context of the request |
| `operation`, `status` | AI operation and lifecycle |
| `provider`, `model`, `prompt_version` | Reproducible configuration |
| `output_json` | Validated structured response |
| `error_code`, `error_message` | Sanitized failure information |
| `latency_ms`, `correlation_id` | Observability |
| `created_at`, `completed_at` | Audit timestamps |

### `proposed_decisions` and `proposed_action_items`

These staging tables contain AI-extracted content awaiting review. Both include `ai_run_id`, `meeting_id`, content fields, `confidence`, `review_status`, `reviewed_by_user_id`, `reviewed_at`, and `created_at`.

`proposed_action_items` additionally stores `suggested_owner_text`, `suggested_owner_user_id`, `suggested_due_date`, and `priority`. Unknown owner names remain unresolved rather than creating an incorrect user.

### `decisions`

Official reviewed decisions: `id`, `meeting_id`, `title`, `description`, `rationale`, `status`, `decided_by_user_id`, `created_by_ai`, `ai_confidence`, `created_at`, `updated_at`.

### `action_items`

| Column | Notes |
| --- | --- |
| `id`, `meeting_id`, `decision_id` | Identity and origin |
| `title`, `description` | Task content |
| `owner_user_id`, `due_date` | Ownership and deadline |
| `status`, `priority` | Task lifecycle and urgency |
| `completed_at`, `closed_at`, `closed_by_user_id` | Closure tracking |
| `outcome`, `outcome_recorded_at` | Required for completion/cancellation |
| `created_by_ai`, `ai_confidence` | Extraction traceability |
| `created_at`, `updated_at` | Audit fields |

### `action_item_history`

Immutable changes: `id`, `action_item_id`, `event_type`, `old_value`, `new_value`, `changed_by_user_id`, `created_at`.

### `action_item_carry_forwards`

Preserves continuity rather than duplicating tasks: `id`, `action_item_id`, `from_meeting_id`, `to_meeting_id`, `carried_by_user_id`, `carry_note`, `created_at`.

### `knowledge_documents`

`id`, `title`, `content`, `source_type`, `source_url`, `embedding` (optional), `created_by_user_id`, `created_at`, `updated_at`.

Explicit link tables preserve referential integrity and explain why a reference was suggested:

- `meeting_knowledge_links`
- `decision_knowledge_links`
- `action_item_knowledge_links`

Each contains the two related IDs, `relevance_score`, `linked_by`, and `created_at`.

### `catchup_briefs`

Persisted generated brief: `id`, `meeting_id`, `target_user_id`, `brief_content`, `generated_by_ai_run_id`, `created_at`.

## Enums

```text
meeting_type: meeting, handover, work_transfer
meeting_status: draft, processing, review_required, completed, archived, failed
transcript_source_type: pasted_text, file_upload, recording_transcript, email_import
ai_operation: transcript_extraction, catchup_brief, handover_brief, risk_analysis, knowledge_linking
ai_run_status: queued, processing, succeeded, failed, validation_failed, fallback_used
review_status: pending_review, approved, edited_and_approved, rejected
action_item_status: open, in_progress, blocked, completed, cancelled
action_item_priority: low, medium, high, critical
history_event_type: created, edited, reassigned, status_changed, carried_forward, approved_from_ai, rejected_from_ai, completed, reopened
decision_status: active, superseded, reversed
```

## Validation and failure handling

- Require a meeting title, type, and scheduled time.
- Require `outcome` before an action item can be completed or cancelled.
- Reject invalid task-state transitions unless an explicit reopen operation is used.
- Validate IDs, dates, owner references, payload shape, and authorization at the API boundary.
- Require every LLM result to conform to a JSON schema before it enters proposal tables.
- Persist source content before beginning AI processing.
- On provider timeout, malformed JSON, or failed validation: mark the AI run accurately, retain the source, expose retry/manual-entry paths, and create structured error logs.

## Original feature: Handover Risk Radar

The dashboard identifies unresolved risks that commonly cause context loss: overdue work, missing owner/due date, blocked items, repeatedly carried-forward tasks, and low-confidence AI extraction. It suggests focused follow-up questions while leaving decisions with the team.

## Production technology stack and hosted deployment

The final deliverable is a public deployed application link. The reviewer must not need to install software, start services, create a database, or run any local command.

### Deployment topology

```text
Public HTTPS URL
    |
    v
Render web service
  - FastAPI API
  - compiled React single-page app
    |
    +----> Render PostgreSQL
    +----> Groq API
```

Use **Render** for one hosted FastAPI service, managed PostgreSQL, environment secrets, logs, and deployment from the Git repository. Package the React application in the same Docker image and let FastAPI serve the built static files. This gives the project one public URL and avoids CORS and multi-site deployment complexity.

The application startup command will run database migrations, then an idempotent seed command that creates a demo team, two meetings, one handover, transcripts, approved tasks, and decisions when the database is empty. The deployed link is therefore useful as soon as it opens. The only required secrets are hosted environment variables such as `DATABASE_URL`, `GROQ_API_KEY`, and `SECRET_KEY`; no secret is committed to Git.

The first version accepts pasted transcripts and notes only. File upload and object storage are deferred until they are genuinely needed.

### Backend: Python + FastAPI

**Recommendation: Python 3.12, FastAPI, SQLAlchemy 2, and Alembic.**

Python is the strongest fit because AI integration, JSON-schema validation, embeddings/retrieval, and background processing have excellent ecosystem support. FastAPI gives typed request/response contracts, automatic OpenAPI documentation, async I/O for provider calls, and concise, maintainable APIs.

No queue or worker is needed initially. The transcript endpoint creates the `ai_runs` row, calls the LLM, validates the response, and writes proposals before returning. The frontend shows a clear processing state. If processing later becomes slow or long-running, the same `ai_runs` table can support adding a worker without changing the user-facing data model.

### Database: PostgreSQL

Use PostgreSQL from the start. It provides reliable relational integrity for the task history and decision workflow, `JSONB` for raw AI responses, full-text search, and an optional `pgvector` extension for semantic knowledge retrieval.

### Frontend: React + TypeScript + Vite

Use **React, TypeScript, Vite, React Router, TanStack Query, and Tailwind CSS with a small accessible component library such as shadcn/ui.**

This keeps the UI simple and fast: a meetings list, meeting detail/review screen, action-item board, handover page, and knowledge search. The Vite build is served by the hosted FastAPI service, rather than requiring a separate frontend deployment.

### LLM integration

Use a provider adapter so the application is not tied to one model:

```text
AIService interface
  - extract_meeting_recap(transcript)
  - create_catchup_brief(context)
  - create_handover_brief(context)
  - link_knowledge(context)
```

Start with the **Groq Free tier** and `openai/gpt-oss-20b`. Groq is fast, offers an OpenAI-compatible API, and supports strict JSON-schema output with this model. Require JSON Schema output, validate it again on the server, record provider/model/prompt version in `ai_runs`, and have a clear retry/manual fallback. If the free-tier quota is exhausted, the application shows a retry/manual-entry path rather than failing silently.

The AI provider remains behind an `AIService` interface so a future provider/model change does not affect API routes, database records, or the frontend.

## Recommended first implementation slice

1. Meeting creation, participant management, manual notes, and pasted transcripts.
2. AI transcript extraction into reviewable proposed summary, decisions, and action items.
3. Approval screen and official action-item lifecycle with history/outcome.
4. Carry-forward flow and basic catch-up brief.
5. Seeded demo data and Handover Risk Radar.
