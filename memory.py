"""
Hindsight agent-memory layer for the Incident Responder.

- Uses the official hindsight-client SDK when installed. Every call runs on a
  worker thread with a FRESH event loop + client (the SDK binds its aiohttp
  session to the loop of the first call; Streamlit re-runs across threads, so
  reusing a client causes "Event loop is closed").
- Falls back to Hindsight's REST API (same server, same memories) otherwise,
  or when HINDSIGHT_BACKEND=rest is set in .env.
- Every retain / recall / reflect is logged to TRACE so the UI can show memory live.
"""
import asyncio
import inspect
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests
import config

BANK = config.HINDSIGHT_BANK_ID
TRACE: deque = deque(maxlen=60)

try:
    from hindsight_client import Hindsight
    BACKEND = "rest" if os.getenv("HINDSIGHT_BACKEND", "").strip().lower() == "rest" else "sdk"
except ImportError:
    Hindsight = None
    BACKEND = "rest"

_sdk_kwargs = {"base_url": config.HINDSIGHT_BASE_URL}
if config.HINDSIGHT_API_KEY:
    _sdk_kwargs["api_key"] = config.HINDSIGHT_API_KEY

_REST_BASE = f"{config.HINDSIGHT_BASE_URL}/v1/default/banks/{BANK}"
_REST_HEADERS = {"Content-Type": "application/json"}
if config.HINDSIGHT_API_KEY:
    _REST_HEADERS["Authorization"] = f"Bearer {config.HINDSIGHT_API_KEY}"

# ---- every SDK call gets its own event loop + client on a single worker thread ----
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hindsight")


def _sdk_call(fn, **kwargs):
    """Call an SDK method, dropping kwargs this SDK version doesn't accept."""
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in params and v is not None}
    except (TypeError, ValueError):
        pass
    return fn(**kwargs)


def _sdk(method: str, **kwargs):
    """Run Hindsight().<method>(**kwargs) with a fresh loop + client, on the worker thread."""
    def work():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = Hindsight(**_sdk_kwargs)
        try:
            return _sdk_call(getattr(client, method), **kwargs)
        finally:
            close = getattr(client, "close", None)
            if close:
                try:
                    r = close()
                    if asyncio.iscoroutine(r):
                        loop.run_until_complete(r)
                except Exception:
                    pass
            try:
                loop.close()
            except Exception:
                pass
    return _executor.submit(work).result()


# ---------------- internals ----------------
def _log(op: str, payload: Any, result: Any, t0: float):
    TRACE.appendleft({"time": time.strftime("%H:%M:%S"), "op": op,
                      "ms": round((time.time() - t0) * 1000),
                      "payload": payload, "result": result})


def _as_dict(obj: Any) -> Dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"text": str(obj)}


def _rest_post(path: str, body: Dict) -> Dict:
    r = requests.post(f"{_REST_BASE}{path}", json=body, headers=_REST_HEADERS, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"Hindsight {r.status_code} on {path}: {r.text[:400]}")
    return r.json() if r.text else {}


def ensure_bank():
    """Banks auto-create on first retain; try explicit creation if the SDK offers it."""
    if BACKEND == "sdk":
        for name in ("create_bank", "get_or_create_bank"):
            if hasattr(Hindsight, name):
                try:
                    _sdk(name, bank_id=BANK, name=BANK)
                except Exception:
                    pass
                return


# ---------------- RETAIN ----------------
def retain(text: str, metadata: Optional[Dict] = None,
           timestamp: Optional[str] = None, context: Optional[str] = None):
    t0 = time.time()
    if BACKEND == "sdk":
        res = _sdk("retain", bank_id=BANK, content=text,
                   metadata=metadata or {}, timestamp=timestamp, context=context)
    else:
        item = {"content": text, "metadata": metadata or {}}
        if timestamp:
            item["timestamp"] = timestamp
        if context:
            item["context"] = context
        res = _rest_post("/memories", {"items": [item]})
    _log("retain", {"text": text[:300] + ("..." if len(text) > 300 else ""),
                    "metadata": metadata}, "stored", t0)
    return res


# ---------------- RECALL ----------------
def recall(query: str, max_tokens: int = 4000, top_k: int = 8) -> List[Dict]:
    t0 = time.time()
    if BACKEND == "sdk":
        raw = _as_dict(_sdk("recall", bank_id=BANK, query=query, max_tokens=max_tokens))
    else:
        raw = _rest_post("/memories/recall", {"query": query, "max_tokens": max_tokens})
    results = raw.get("results") or raw.get("memories") or raw.get("items") or []
    out = []
    for r in results[:top_k]:
        d = _as_dict(r)
        out.append({
            "text": d.get("text") or d.get("content") or "",
            "type": d.get("type", ""),
            "metadata": d.get("metadata") or {},
            "timestamp": d.get("timestamp") or d.get("occurred_start") or "",
        })
    _log("recall", {"query": query[:300]}, [o["text"][:120] for o in out], t0)
    return out


# ---------------- REFLECT ----------------
def reflect(question: str) -> str:
    t0 = time.time()
    if BACKEND == "sdk":
        raw = _as_dict(_sdk("reflect", bank_id=BANK, query=question))
    else:
        raw = _rest_post("/memories/reflect", {"query": question})
    answer = raw.get("text") or raw.get("answer") or raw.get("content") or str(raw)
    _log("reflect", {"question": question}, answer[:200], t0)
    return answer


# ---------------- Incident -> memories ----------------
def incident_to_memories(inc: Dict) -> List[Dict]:
    """Split one incident into two focused, entity-rich memories (diagnosis + resolution).
    Small focused memories recall far better than one giant blob."""
    header = (f"INCIDENT {inc['id']} | {inc['date']} | {inc['severity']} | "
              f"service: {inc['service']} | {inc['title']}")
    tags = ", ".join(inc.get("tags", []))
    steps = " ".join(f"{i+1}) {s}" for i, s in enumerate(inc.get("resolution_steps", [])))
    failed = "; ".join(inc.get("failed_attempts", [])) or "none recorded"

    diagnosis = (f"{header}\nSymptoms: {inc['symptoms']}\n"
                 f"Root cause: {inc['root_cause']}\nTags: {tags}")
    resolution = (f"{header}\nResolution steps that WORKED: {steps} "
                  f"Runbook used: {inc.get('runbook', 'n/a')}. "
                  f"Resolved in {inc.get('time_to_resolve_min', '?')} minutes.\n"
                  f"Attempts that FAILED (do not repeat): {failed}\n"
                  f"Lesson: {inc.get('lesson', '')}\nTags: {tags}")

    meta = {"incident_id": inc["id"], "service": inc["service"],
            "severity": inc["severity"], "tags": tags}
    ts = f"{inc['date']}T00:00:00Z"
    return [
        {"text": diagnosis,  "metadata": {**meta, "kind": "diagnosis"},  "timestamp": ts},
        {"text": resolution, "metadata": {**meta, "kind": "resolution"}, "timestamp": ts},
    ]


def retain_incident(inc: Dict):
    for m in incident_to_memories(inc):
        retain(m["text"], metadata=m["metadata"], timestamp=m["timestamp"],
               context=f"post-mortem for {inc['service']}")