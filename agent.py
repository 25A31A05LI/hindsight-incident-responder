from datetime import date
from typing import Dict, List, Optional
import memory
import llm
import prompts


def _format_memories(mems: List[Dict]) -> str:
    if not mems:
        return "(none)"
    lines = []
    for i, m in enumerate(mems):
        meta = m.get("metadata") or {}
        tag = f" (incident {meta['incident_id']}, service {meta.get('service', '?')})" if meta.get("incident_id") else ""
        when = f" [when: {m['timestamp'][:10]}]" if m.get("timestamp") else ""
        lines.append(f"[memory {i+1}]{tag}{when} {m['text']}")
    return "\n\n".join(lines)


def triage(alert: str, use_memory: bool = True) -> Dict:
    """Alert text -> {memories, plan, mode}. use_memory=False is 'Amnesia mode'."""
    mems = memory.recall(alert, max_tokens=6000, top_k=12) if use_memory else []
    system = prompts.TRIAGE_WITH_MEMORY if use_memory else prompts.TRIAGE_AMNESIA
    user = prompts.TRIAGE_USER.format(alert=alert, memories=_format_memories(mems))
    plan = llm.chat_json(system, user)
    return {"memories": mems, "plan": plan, "mode": "hindsight" if use_memory else "amnesia"}


def structure_postmortem(free_text: str, step_feedback: Optional[List[Dict]] = None,
                         alert: str = "", next_id: Optional[str] = None) -> Dict:
    """Free-text post-mortem -> structured incident dict. Nothing is saved yet."""
    feedback_txt = ""
    if step_feedback:
        worked = [f["step"] for f in step_feedback if f["result"] == "worked"]
        failed = [f["step"] for f in step_feedback if f["result"] == "failed"]
        feedback_txt = (f"\n\nOriginal alert: {alert}\nSteps that WORKED: {worked}\n"
                        f"Steps that FAILED: {failed}")
    hint = f"\nUse id {next_id}. Today's date is {date.today().isoformat()}."
    structured = llm.chat_json(prompts.STRUCTURE_POSTMORTEM + hint, free_text + feedback_txt)
    if "error" in structured:
        raise RuntimeError(f"Could not structure post-mortem: {structured.get('raw', '')[:300]}")
    defaults = {"id": next_id or "INC-NEW", "date": date.today().isoformat(), "severity": "SEV-3",
                "service": "unknown-service", "title": "Untitled incident", "symptoms": "",
                "root_cause": "", "resolution_steps": [], "failed_attempts": [], "tags": []}
    for k, v in defaults.items():
        structured.setdefault(k, v)
    return structured


def resolve(free_text: str, step_feedback: Optional[List[Dict]] = None,
            alert: str = "", next_id: Optional[str] = None) -> Dict:
    """Structure AND save in one go (used by scripts, not the UI)."""
    inc = structure_postmortem(free_text, step_feedback, alert, next_id)
    memory.retain_incident(inc)
    return inc


def patterns(question: str) -> str:
    """Reasoning over accumulated incident memory (Hindsight reflect)."""
    return memory.reflect(question)