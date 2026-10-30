import json
from groq import Groq
from app.config import settings
from app.schemas import AIResult


SYSTEM_PROMPT = """You extract meeting information. Return only the requested JSON.
Do not invent owners or dates. Use null when unknown. Keep summaries concise.
Decisions have title, description, rationale. Action items have title, description, owner,
due_date in YYYY-MM-DD or null, and priority one of low, medium, high, critical."""


def extract_recap(transcript: str) -> dict:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured. Add it in Render to enable live AI extraction.")
    schema = AIResult.model_json_schema()
    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "meeting_recap", "strict": True, "schema": schema},
        },
    )
    result = AIResult.model_validate_json(response.choices[0].message.content)
    return result.model_dump(mode="json")
