import json
import re
from openai import OpenAI
import config

_client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)


def chat(system: str, user: str, json_mode: bool = False, temperature: float = 0.1) -> str:
    kwargs = dict(
        model=config.LLM_MODEL,
        temperature=temperature,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = _client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("response_format", None)      # some models reject json mode -> retry plain
        resp = _client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def chat_json(system: str, user: str) -> dict:
    """Ask for JSON and parse it defensively (handles ```json fences and stray prose)."""
    raw = chat(system, user, json_mode=True)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"error": "LLM returned non-JSON", "raw": raw}