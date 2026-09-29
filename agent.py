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
    mems = memory.recall(alert) if use_memory else []
    system = prompts.TRIAGE_WITH_MEMORY if use_memory else prompts.TRIAGE_AMNESIA
    user = prompts.TRIAGE_USER.format(alert=alert, memories=_format_memories(mems))
    plan = llm.chat_json(system, user)
    return {"memories": mems, "plan": plan, "mode": "hindsight" if use_memory else "amnesia"}


def resolve(free_text: str, step_feedback: Optional[List[Dict]] = None,
            alert: str = "", next_id: Optional[str] = None) -> Dict:
    """Free-text post-mortem (+ worked/failed feedback) -> structured incident -> retained in Hindsight."""
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

    structured.setdefault("id", next_id or "INC-NEW")
    structured.setdefault("date", date.today().isoformat())
    structured.setdefault("severity", "SEV-3")
    structured.setdefault("service", "unknown-service")
    structured.setdefault("title", "Untitled incident")
    structured.setdefault("symptoms", "")
    structured.setdefault("root_cause", "")
    structured.setdefault("resolution_steps", [])
    structured.setdefault("failed_attempts", [])
    structured.setdefault("tags", [])
    memory.retain_incident(structured)
    return structured


def patterns(question: str) -> str:
    """Reasoning over accumulated incident memory (Hindsight reflect)."""
    return memory.reflect(question)