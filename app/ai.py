import json
from groq import Groq
from app.config import settings
from app.schemas import AIResult


SYSTEM_PROMPT = """\
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


def extract_recap(transcript: str) -> dict:
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to your .env or Render environment."
        )
    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract the meeting information from this transcript:\n\n{transcript}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    result = AIResult.model_validate_json(raw)
    return result.model_dump(mode="json")
