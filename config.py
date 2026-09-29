import os
from dotenv import load_dotenv

load_dotenv()
# On Streamlit Cloud, secrets live in st.secrets; mirror them into env vars
try:
    import streamlit as _st
    for _k, _v in _st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

# ---- Hindsight ----
HINDSIGHT_BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "").strip().rstrip("/")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "").strip() or None
HINDSIGHT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "incident-memory").strip()

# ---- LLM (one OpenAI-compatible client for groq / openai / gemini) ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b").strip()

_BASE_URLS = {
    "openai": None,
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
LLM_BASE_URL = _BASE_URLS.get(LLM_PROVIDER)

if not HINDSIGHT_BASE_URL:
    raise RuntimeError("HINDSIGHT_BASE_URL is missing in .env")
if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY is missing in .env")