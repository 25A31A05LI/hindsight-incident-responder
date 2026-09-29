import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import streamlit as st
import agent
import memory

st.set_page_config(page_title="Hindsight Incident Responder", page_icon="🧠", layout="wide")

# ---------------- style ----------------
st.markdown("""
<style>
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;margin-right:6px}
.sev1{background:#7f1d1d;color:#fecaca}.sev2{background:#7c2d12;color:#fed7aa}.sev3{background:#374151;color:#e5e7eb}
.inc{background:#1e3a5f;color:#bfdbfe;font-family:monospace}
.src{color:#9ca3af;font-size:0.78rem}
.step{padding:8px 12px;border-left:3px solid #22c55e;background:#111827;margin:6px 0;border-radius:4px}
.dont{padding:8px 12px;border-left:3px solid #ef4444;background:#1f1214;margin:6px 0;border-radius:4px}
.hero{font-size:2rem;font-weight:700;margin-bottom:0}
.sub{color:#9ca3af;margin-top:0}
</style>
""", unsafe_allow_html=True)

ss = st.session_state
for k, v in {"last_triage": None, "last_alert": "", "feedback": {}, "next_id": 100,
             "pattern_q": "", "pending_incident": None, "chat": []}.items():
    ss.setdefault(k, v)

INCIDENTS = json.loads(Path("data/incidents.json").read_text(encoding="utf-8"))
ss.setdefault("session_incidents", [])   # incidents retained during this session
TYPICAL_UNASSISTED_MTTR = 45              # industry-typical MTTR for a SEV-2, labelled as assumption in UI


def all_incidents():
    return INCIDENTS + ss.session_incidents


def time_saved_line(plan: dict) -> str:
    ids = {m.get("id") for m in plan.get("matched_incidents", [])}
    ttrs = [i["time_to_resolve_min"] for i in all_incidents()
            if i["id"] in ids and isinstance(i.get("time_to_resolve_min"), (int, float)) and i["time_to_resolve_min"] > 0]
    if not ttrs:
        return ""
    avg, first = round(sum(ttrs) / len(ttrs)), max(ttrs)
    saved = max(TYPICAL_UNASSISTED_MTTR - avg, 0)
    return (f"⏱️ **Past matches resolved in ~{avg} min** on average "
            f"(first time this class occurred: {first} min · typical unassisted MTTR ≈ {TYPICAL_UNASSISTED_MTTR} min, assumed). "
            f"Following the proven fix saves an estimated **{saved} min**.")
SERVICES = sorted({i["service"] for i in INCIDENTS})

PAGES = [
    {"sev": "SEV-2", "service": "payment-service", "title": "5xx rate 11% on /checkout after deploy v2.52",
     "alert": "ALERT: PaymentService 5xx rate > 5% (currently 11%). 502 on POST /checkout.\n"
              "Postgres payments-db log: 'FATAL: remaining connection slots are reserved for non-replication superuser connections'.\n"
              "Deploy v2.52 went out 20 minutes ago."},
    {"sev": "SEV-1", "service": "payment-service", "title": "5xx on /checkout — x509 errors to psp-gateway",
     "alert": "ALERT: PaymentService 5xx rate > 5%. 502 on POST /checkout.\n"
              "payment-service log: 'x509: certificate has expired or is not yet valid' calling psp-gateway.internal. DB metrics normal."},
    {"sev": "SEV-2", "service": "search-api", "title": "Pods OOMKilled, sawtooth memory",
     "alert": "ALERT: search-api restarts > 5 in 1h. Pods show OOMKilled exit 137. Memory graph is a sawtooth up to the 1Gi limit."},
    {"sev": "SEV-2", "service": "search-api", "title": "Pods OOMKilled, memory tracks traffic (2x campaign)",
     "alert": "ALERT: search-api restarts > 5 in 1h. OOMKilled exit 137. Memory climbs steadily with request rate, no sawtooth. Traffic is 2x normal since this morning's campaign."},
    {"sev": "SEV-1", "service": "checkout-web", "title": "Error rate 24%, no deploy in 6h",
     "alert": "ALERT: checkout-web error rate 24%. Sentry: TypeError: Cannot read properties of undefined (reading 'total'). No deploy in the last 6 hours."},
    {"sev": "SEV-2", "service": "auth-service", "title": "401 rate 34% after IdP key rotation",
     "alert": "ALERT: auth-service 401 rate 34%. Logs: 'JWSError: key with kid=2026-03 not found in JWKS cache'. Identity team says they rotated keys an hour ago."},
]


def badge(text, cls):
    return f'<span class="badge {cls}">{text}</span>'


def sev_cls(sev):
    return {"SEV-1": "sev1", "SEV-2": "sev2"}.get(sev, "sev3")


# ---------------- header ----------------
st.markdown('<p class="hero">🧠 Hindsight Incident Responder</p>', unsafe_allow_html=True)
st.markdown('<p class="sub">An on-call agent that remembers every incident your team ever had — '
            'what caused it, what fixed it, and what wasted time.</p>', unsafe_allow_html=True)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Incidents in memory", len(all_incidents()))
m2.metric("Services covered", len(SERVICES))
m3.metric("Memory calls this session", len(memory.TRACE))
m4.metric("Memory bank", memory.BANK)

# ---------------- sidebar ----------------
with st.sidebar:
    st.subheader("Settings")
    compare = st.toggle("Compare: Amnesia vs Hindsight", value=True)
    st.divider()
    st.subheader("Memory trace (live)")
    st.caption("Every retain / recall / reflect against Hindsight, as it happens.")
    if st.button("Clear trace"):
        memory.TRACE.clear()
    for t in list(memory.TRACE)[:12]:
        icon = {"retain": "💾", "recall": "🔍", "reflect": "🧩"}.get(t["op"], "•")
        with st.expander(f"{icon} {t['op']} · {t['time']} · {t['ms']} ms"):
            st.json({"payload": t["payload"], "result": t["result"]})

tab_pager, tab_resolve, tab_insights, tab_bank = st.tabs(
    ["📟 Pager & Triage", "✅ Resolve & Learn", "📈 Team Insights", "🗂️ Memory Bank"])


# ---------------- plan renderer ----------------
def render_plan(plan: dict, mems: list, title: str, accent: str):
    with st.container(border=True):
        st.markdown(f"#### {title}")
        if "error" in plan:
            st.error(plan.get("raw", plan["error"]))
            return
        conf = plan.get("confidence", "?")
        (st.success if accent == "green" else st.info)(
            f"**Diagnosis** · confidence {conf}%\n\n{plan.get('diagnosis', '')}")
        if accent == "green":
            line = time_saved_line(plan)
            if line:
                st.markdown(line)
        if plan.get("matched_incidents"):
            st.markdown("**Matched past incidents**")
            for m in plan["matched_incidents"]:
                st.markdown(f"{badge(m.get('id'), 'inc')} {m.get('why')}", unsafe_allow_html=True)
        else:
            st.caption("No past incidents available — answering from general knowledge only.")
        st.markdown("**Fix plan** <span class='src'>(ranked by what worked before)</span>", unsafe_allow_html=True)
        for i, s in enumerate(plan.get("fix_steps", []), 1):
            st.markdown(f"<div class='step'><b>{i}.</b> {s.get('step')}<br>"
                        f"<span class='src'>source: {s.get('source')} · ~{s.get('expected_min', '?')} min</span></div>",
                        unsafe_allow_html=True)
        if plan.get("do_not_try"):
            st.markdown("**⛔ Don't bother trying**")
            for d in plan["do_not_try"]:
                st.markdown(f"<div class='dont'><s>{d.get('action')}</s><br><span class='src'>{d.get('reason')}</span></div>",
                            unsafe_allow_html=True)
        if plan.get("escalate_if"):
            st.warning(f"**Escalate if:** {plan['escalate_if']}")
        if mems:
            with st.expander(f"🔍 {len(mems)} memories recalled from Hindsight"):
                for m in mems:
                    st.code(m["text"])


def run_triage(alert_text: str):
    ss.last_alert = alert_text
    ss.feedback, ss.chat = {}, []
    try:
        with st.spinner("Recalling similar incidents from Hindsight and building both plans in parallel..."):
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_with = ex.submit(agent.triage, alert_text, True)
                f_without = ex.submit(agent.triage, alert_text, False) if compare else None
                with_mem = f_with.result()
                without = f_without.result() if f_without else None
        ss.last_triage = {"with": with_mem, "without": without}
    except Exception as e:
        st.error(f"Triage failed: {e}")


# ---------------- PAGER & TRIAGE ----------------
with tab_pager:
    st.markdown("#### 📟 Incoming pages")
    st.caption("Simulated alert feed. Acknowledge a page to triage it — or paste your own below.")
    cols = st.columns(3)
    for i, p in enumerate(PAGES):
        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(badge(p["sev"], sev_cls(p["sev"])) + badge(p["service"], "sev3"), unsafe_allow_html=True)
                st.markdown(f"**{p['title']}**")
                if st.button("Acknowledge & triage", key=f"page_{i}", use_container_width=True):
                    run_triage(p["alert"])

    with st.expander("✍️ Paste a custom alert / log snippet"):
        custom = st.text_area("Alert", value=ss.last_alert, height=120, label_visibility="collapsed")
        if st.button("🔎 Triage custom alert", type="primary", disabled=not custom.strip()):
            run_triage(custom)

    if ss.last_triage:
        st.divider()
        st.markdown("#### 🚨 Active incident")
        st.code(ss.last_alert)
        if ss.last_triage["without"]:
            c1, c2 = st.columns(2)
            with c1:
                render_plan(ss.last_triage["without"]["plan"], [], "🙈 Same LLM, no memory", "grey")
            with c2:
                render_plan(ss.last_triage["with"]["plan"], ss.last_triage["with"]["memories"],
                            "🧠 Same LLM + Hindsight memory", "green")
        else:
            render_plan(ss.last_triage["with"]["plan"], ss.last_triage["with"]["memories"],
                        "🧠 With Hindsight memory", "green")

        # ---- follow-up chat with the agent ----
        st.markdown("#### 💬 Ask the agent about this plan")
        for h in ss.chat:
            with st.chat_message(h["role"]):
                st.markdown(h["content"])
        q = st.chat_input("e.g. Why INC-044 and not INC-017? What did the last engineer try first?")
        if q:
            ss.chat.append({"role": "user", "content": q})
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                with st.spinner("Checking memory..."):
                    try:
                        ans = agent.followup(q, ss.last_alert, ss.last_triage["with"]["plan"],
                                             ss.last_triage["with"]["memories"], ss.chat)
                    except Exception as e:
                        ans = f"Follow-up failed: {e}"
                st.markdown(ans)
            ss.chat.append({"role": "assistant", "content": ans})

        st.divider()
        st.markdown("#### ✔️ Outcome — which steps did you actually try?")
        st.caption("This feedback becomes part of the incident's memory.")
        for i, s in enumerate(ss.last_triage["with"]["plan"].get("fix_steps", [])):
            ss.feedback[i] = st.radio(s.get("step", f"step {i}"), ["not tried", "worked", "failed"],
                                      horizontal=True, key=f"fb_{i}")
        st.info("Next → **Resolve & Learn** to record the post-mortem so the agent remembers this one.")

# ---------------- RESOLVE ----------------
with tab_resolve:
    st.markdown("#### ✅ Close the loop")
    st.caption("Write what really happened. The agent structures it, you review it, and only then is it "
               "retained into Hindsight — memory is permanent, so nothing enters it unreviewed.")
    template = "What we found:\n\nWhat fixed it:\n\nWhat we tried that failed:\n"
    pm_text = st.text_area("Post-mortem", value=template, height=200)

    def _has_content(txt: str) -> bool:
        for label in ("What we found:", "What fixed it:", "What we tried that failed:", "Alert:"):
            txt = txt.replace(label, "")
        return len(txt.strip()) >= 40

    if st.button("🧾 Structure post-mortem", type="primary", disabled=not pm_text.strip()):
        if not _has_content(pm_text):
            st.error("Describe what happened first (at least what fixed it). Empty templates are not saved.")
        else:
            fb = []
            if ss.last_triage:
                steps = ss.last_triage["with"]["plan"].get("fix_steps", [])
                fb = [{"step": steps[i]["step"], "result": r} for i, r in ss.feedback.items()
                      if i < len(steps) and r != "not tried"]
            try:
                with st.spinner("Structuring post-mortem..."):
                    ss.pending_incident = agent.structure_postmortem(
                        pm_text, fb, alert=ss.last_alert, next_id=f"INC-{ss.next_id}")
            except Exception as e:
                st.error(f"Structuring failed: {e}")

    if ss.pending_incident:
        inc = ss.pending_incident
        with st.container(border=True):
            st.markdown(badge(inc.get("id"), "inc") + badge(inc.get("severity", ""), sev_cls(inc.get("severity", "")))
                        + badge(inc.get("service", ""), "sev3") + f" **{inc.get('title', '')}**", unsafe_allow_html=True)
            st.markdown(f"**Root cause:** {inc.get('root_cause') or '—'}")
            st.markdown("**Resolution steps:** " + (" → ".join(inc.get("resolution_steps") or []) or "—"))
            st.markdown("**Failed attempts:** " + ("; ".join(inc.get("failed_attempts") or []) or "none"))
            st.markdown(f"**Lesson:** {inc.get('lesson') or '—'}")
            with st.expander("Full JSON"):
                st.json(inc)
        c1, c2 = st.columns(2)
        if c1.button("💾 Confirm & retain to Hindsight", type="primary"):
            try:
                with st.spinner("Retaining into Hindsight..."):
                    memory.retain_incident(inc)
                ss.next_id += 1
                ss.session_incidents.append(inc)
                st.success(f"Retained {inc['id']}. Re-run the same page in Pager & Triage — the agent now cites it.")
                ss.pending_incident = None
            except Exception as e:
                st.error(f"Retain failed: {e}")
        if c2.button("Discard"):
            ss.pending_incident = None

# ---------------- INSIGHTS ----------------
with tab_insights:
    st.markdown("#### 📈 What has the team learned?")
    st.caption("Answered by Hindsight reflect — reasoning across every incident in memory, not a single lookup.")
    questions = [
        "Why does payment-service keep going down? What is the recurring pattern?",
        "Which runbook has the best track record and which one gets misapplied?",
        "What mistakes do on-call engineers repeat across incidents?",
        "Which failures happened without a deploy, and what should be checked first?",
    ]
    qcols = st.columns(2)
    for i, q in enumerate(questions):
        if qcols[i % 2].button(q, use_container_width=True):
            ss.pattern_q = q
    q = st.text_input("Or ask your own question", value=ss.pattern_q)
    if st.button("🧩 Reflect", type="primary", disabled=not q.strip()):
        try:
            with st.spinner("Hindsight is reflecting over all incidents..."):
                ans = agent.patterns(q)
            with st.container(border=True):
                st.markdown(ans)
        except Exception as e:
            st.error(f"Reflect failed: {e}")

# ---------------- MEMORY BANK ----------------
with tab_bank:
    st.markdown(f"#### 🗂️ What lives in Hindsight bank `{memory.BANK}`")
    st.caption("Each incident is retained as two focused memories (diagnosis + resolution) with metadata and a timestamp; "
               "Hindsight extracts facts and entities from them for recall.")
    per_service = {}
    for i in INCIDENTS:
        per_service[i["service"]] = per_service.get(i["service"], 0) + 1
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Incidents per service**")
        st.bar_chart(per_service)
    with c2:
        st.markdown("**Seeded incident history**")
        st.dataframe(
            [{"ID": i["id"], "Date": i["date"], "Sev": i["severity"], "Service": i["service"],
              "Title": i["title"], "Runbook": i.get("runbook", ""), "TTR (min)": i.get("time_to_resolve_min", "")}
             for i in sorted(INCIDENTS, key=lambda x: x["date"])],
            use_container_width=True, hide_index=True, height=420)
    with st.expander("How one incident becomes memories (memory.py → incident_to_memories)"):
        sample = memory.incident_to_memories(INCIDENTS[0])
        for m in sample:
            st.code(m["text"])
            st.json(m["metadata"])