import os
from dotenv import load_dotenv

load_dotenv()

# ---- Streamlit Cloud secrets (optional) ----
try:
    import streamlit as _st
    _SECRETS = dict(_st.secrets)
except Exception:
    _SECRETS = {}


def _get(key: str, default: str = "") -> str:
    """Env var first (.env / local), then Streamlit secrets (cloud)."""
    val = os.getenv(key)
    if val is None or val == "":
        val = _SECRETS.get(key, default)
    return str(val).strip()


# ---- Hindsight ----
HINDSIGHT_BASE_URL = _get("HINDSIGHT_BASE_URL").rstrip("/")
HINDSIGHT_API_KEY = _get("HINDSIGHT_API_KEY") or None
HINDSIGHT_BANK_ID = _get("HINDSIGHT_BANK_ID", "incident-memory")

# ---- LLM ----
LLM_PROVIDER = _get("LLM_PROVIDER", "groq").lower()
LLM_API_KEY = _get("LLM_API_KEY")
LLM_MODEL = _get("LLM_MODEL", "openai/gpt-oss-120b")

_BASE_URLS = {
    "openai": None,
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
LLM_BASE_URL = _BASE_URLS.get(LLM_PROVIDER)

if not HINDSIGHT_BASE_URL:
    raise RuntimeError("HINDSIGHT_BASE_URL is missing — set it in .env (local) or Streamlit Secrets (cloud)")
if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY is missing — set it in .env (local) or Streamlit Secrets (cloud)")