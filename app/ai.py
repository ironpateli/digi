import re
from groq import Groq
from app.config import settings
from app.logger import log
from app.schemas import AIResult


_SYSTEM_EXTRACT = """\
You extract meeting information and return JSON only — no explanation, no markdown, just the JSON object.

Return exactly this structure:
{
  "summary": "<2-3 sentence summary of the meeting>",
  "decisions": [
    {"title": "...", "description": "...", "rationale": "..." or null}
  ],
  "action_items": [
    {
      "title": "...",
      "description": "..." or null,
      "owner": "<person name>" or null,
      "due_date": "YYYY-MM-DD" or null,
      "priority": "low" | "medium" | "high" | "critical"
    }
  ],
  "risks_or_open_questions": ["...", "..."]
}

Rules:
- Do not invent owners or dates. Use null when unknown.
- Keep summaries concise.
- priority must be exactly one of: low, medium, high, critical
- due_date must be YYYY-MM-DD or null
- Return valid JSON only — no code fences, no extra text.
"""

_SYSTEM_BRIEF = """\
You write concise, clear catch-up briefs for team members who missed meetings.
Be direct and informative. No fluff. Max 200 words.
"""


def _client() -> Groq:
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to your .env or Render environment."
        )
    return Groq(api_key=settings.groq_api_key)


def _strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks that Qwen3 may emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_recap(transcript: str) -> dict:
    c = _client()
    response = c.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system",  "content": _SYSTEM_EXTRACT},
            {"role": "user",    "content": f"Extract the meeting information from this transcript:\n\n{transcript}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = _strip_thinking(response.choices[0].message.content)
    result = AIResult.model_validate_json(raw)
    log.debug("ai_extraction_parsed", extra={"event": "ai_extract", "decisions": len(result.decisions), "action_items": len(result.action_items)})
    return result.model_dump(mode="json")


def generate_catchup_brief(meeting: dict, target_name: str | None = None) -> str:
    c = _client()
    who = f" for {target_name}" if target_name else ""

    tasks_text = "\n".join(
        f"- {t['title']} (owner: {t['owner_name'] or 'unassigned'}, "
        f"status: {t['status']}, due: {t['due_date'] or 'no date'})"
        for t in meeting.get("tasks", [])
    ) or "None recorded"

    decisions_text = "\n".join(
        f"- {d['title']}: {d['description']}"
        for d in meeting.get("decisions", [])
    ) or "None recorded"

    context = (
        f"Meeting: {meeting['title']}\n"
        f"Type: {meeting['type']}\n"
        f"Agenda: {meeting.get('agenda') or 'N/A'}\n"
        f"Approved summary: {meeting.get('approved_summary') or 'N/A'}\n\n"
        f"Decisions:\n{decisions_text}\n\n"
        f"Action items:\n{tasks_text}"
    )

    prompt = (
        f"Write a concise catch-up brief{who} who missed this meeting. "
        "Cover: what was discussed, key decisions, action items to know about, and any risks. "
        "Max 200 words."
    )

    response = c.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": _SYSTEM_BRIEF},
            {"role": "user",   "content": f"{prompt}\n\nMeeting context:\n{context}"},
        ],
        temperature=0.3,
    )
    return _strip_thinking(response.choices[0].message.content)
