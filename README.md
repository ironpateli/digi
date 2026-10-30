# DigiPlus — AI-Powered Knowledge & Task Management

DigiPlus prevents context from disappearing after a meeting or work handover. It stores the source conversation, turns it into a reviewable AI recap, and keeps action items visible until there is a recorded outcome.

## What is included

- Meetings, handovers, and work transfers with agenda, notes, type, date, and lifecycle status.
- AI extraction of a concise summary, decisions, action items, proposed owners, dates, priority, and open questions from pasted source text.
- A review-before-save workflow: AI output is only saved as official data after approval.
- Action-item status management (`open`, `in progress`, `blocked`, `completed`, `cancelled`) with a mandatory outcome when closing work.
- Carry-forward links: unresolved work remains in the source meeting for audit history and is surfaced in the destination meeting for follow-up.
- A shared People directory with meeting attendance and logged action-item reassignment.
- A knowledge library for team documents, notes, emails, and chat context, with AI-generated meeting links and relevance notes.
- AI catch-up briefs for colleagues who missed the meeting or are taking work over.
- **Handover Risk Radar** (the special feature): one view for overdue, blocked, unassigned, and undated work—the gaps most likely to cause context loss.
- Seeded demonstration data, responsive single-page UI, validation, error feedback, and structured JSON logs.

## Technology and architecture

The application is a small modular monolith:

```text
Browser (vanilla HTML/CSS/JS)
       │
       ▼
FastAPI application ── SQLAlchemy ── SQLite locally / PostgreSQL on Render
       │
       └── Groq API (Qwen 3.8 27B)
```

The browser never receives the model API key. FastAPI owns validation, persistence, the model call, and audit logging. SQLite makes the demo easy to run locally; `DATABASE_URL` can point to Render PostgreSQL without application changes.

## Run locally

Requirements: Python 3.12+ and a Groq API key.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
pip install -r requirements.txt
Copy-Item .env.example .env       # or create .env from the example below
python -m app.seed --if-empty
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. For a Docker/Render-style startup, use `scripts/start.sh`.

Create a local `.env` (it is gitignored):

```dotenv
DATABASE_URL=sqlite:///./digiplus.db
GROQ_API_KEY=your_key_here
SECRET_KEY=local-development-only
APP_ENV=development
```

## AI configuration and reliability

`app/ai.py` uses Groq with `qwen/qwen3.8-27b`.

1. A pasted transcript is persisted before the model is called.
2. The model is instructed to return JSON only, with a fixed recap structure.
3. Pydantic validates the response before it can become a proposal.
4. A user reviews and approves the proposal before decisions and action items are written.
5. If configuration, a network call, malformed output, or validation fails, the AI run is marked failed, the source remains stored, a safe error is returned, and the UI permits manual notes or a retry.

The product does not fabricate dates or owners: the prompt requires the model to use `null` where the source does not name them.

## Data and lifecycle

Key persisted tables are `users`, `meeting_participants`, `meetings`, `meeting_transcripts`, `ai_runs`, `decisions`, `action_items`, `action_item_history`, `action_item_carry_forwards`, `knowledge_documents`, and `knowledge_links`.

An action item is not copied when it is carried forward. A link records the destination meeting and optional reason; the item keeps its original identity and history. This avoids conflicting duplicates while making the next meeting accountable for follow-up.

## Logging

Logs are newline-delimited JSON in `logs/digiplus.log` (and INFO+ events on stdout). Each HTTP request receives a UUID correlation ID returned in `X-Correlation-ID`.

Recorded events include request start/end/error, meeting create/update/delete, people/attendance updates, task reassignment and closure, AI outcome and latency, proposal approval, knowledge-link generation, and carry-forward operations. Logs deliberately omit secrets and raw notes/transcripts.

## Validation and known limitations

- Title, meeting type, transcript size, task status, and close-out outcomes are validated at the API boundary.
- This assessment version has no authentication or multi-tenant authorization; it is intended for a trusted demo team.
- Pasted text is supported for meeting capture and knowledge documents; binary file upload, calendar integration, and recording transcription are out of scope.
- Knowledge linking is AI-generated from saved document text. Embeddings and semantic search would be the next extension for a large library.
- AI is synchronous for a concise assessment flow. In production, longer recordings should move the same `ai_runs` workflow to a background worker.

## Deployment

`render.yaml` and the `Dockerfile` define a Render web service plus PostgreSQL database. Set `GROQ_API_KEY` as a Render secret, then deploy from the repository. The start script seeds only an empty database, so a new deployment opens with usable demo data.

## Verification

```bash
python -m compileall -q app tests
python tests/test_api.py
```

The test client can be restricted in some locked-down desktop environments. The API test suite is designed for a normal local Python environment; the application modules and carry-forward persistence flow are also verified directly during development.
