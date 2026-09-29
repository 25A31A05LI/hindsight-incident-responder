import streamlit as st
import agent
import memory

st.set_page_config(page_title="Hindsight Incident Responder", page_icon="🧠", layout="wide")

ss = st.session_state
ss.setdefault("last_triage", None)
ss.setdefault("last_alert", "")
ss.setdefault("feedback", {})
ss.setdefault("next_id", 100)
ss.setdefault("pattern_q", "")

EXAMPLE_ALERTS = {
    "Payment 502s (recurring)":
        "ALERT: PaymentService 5xx rate > 5% (currently 11%). 502 on POST /checkout.\n"
        "Postgres payments-db log: 'FATAL: remaining connection slots are reserved for non-replication superuser connections'.\n"
        "Deploy v2.52 went out 20 minutes ago.",
    "Payment 502s (look-alike)":
        "ALERT: PaymentService 5xx rate > 5%. 502 on POST /checkout.\n"
        "payment-service log: 'x509: certificate has expired or is not yet valid' calling psp-gateway.internal. DB metrics normal.",
    "Search pods restarting":
        "ALERT: search-api restarts > 5 in 1h. Pods show OOMKilled exit 137. Memory graph is a sawtooth up to the 1Gi limit.",
    "Errors with no deploy":
        "ALERT: checkout-web error rate 24%. Sentry: TypeError: Cannot read properties of undefined (reading 'total'). No deploy in the last 6 hours.",
}

# ---------------- sidebar ----------------
with st.sidebar:
    st.title("🧠 Incident Responder")
    st.caption(f"Hindsight bank: `{memory.BANK}` · backend: `{memory.BACKEND}`")
    compare = st.toggle("Compare: Amnesia vs Hindsight", value=True,
                        help="Run the same alert with and without memory, side by side")
    st.divider()
    st.subheader("Memory trace (live)")
    if st.button("Clear trace"):
        memory.TRACE.clear()
    for t in list(memory.TRACE)[:12]:
        icon = {"retain": "💾", "recall": "🔍", "reflect": "🧩"}.get(t["op"], "•")
        with st.expander(f"{icon} {t['op']} · {t['time']} · {t['ms']} ms"):
            st.json({"payload": t["payload"], "result": t["result"]})

tab_triage, tab_resolve, tab_patterns = st.tabs(["🚨 Triage", "✅ Resolve & Learn", "📈 Patterns"])


def render_plan(plan: dict, mems: list, title: str):
    st.markdown(f"### {title}")
    if "error" in plan:
        st.error(plan.get("raw", plan["error"]))
        return
    st.info(f"**Diagnosis:** {plan.get('diagnosis', '')}  \n**Confidence:** {plan.get('confidence', '?')}%")
    if plan.get("matched_incidents"):
        st.markdown("**Matched past incidents**")
        for m in plan["matched_incidents"]:
            st.markdown(f"- `{m.get('id')}` — {m.get('why')}")
    st.markdown("**Fix plan (ranked by what worked before)**")
    for i, s in enumerate(plan.get("fix_steps", []), 1):
        st.markdown(f"{i}. {s.get('step')}  \n   <sub>source: `{s.get('source')}` · ~{s.get('expected_min', '?')} min</sub>",
                    unsafe_allow_html=True)
    if plan.get("do_not_try"):
        st.markdown("**⛔ Don't bother trying**")
        for d in plan["do_not_try"]:
            st.markdown(f"- ~~{d.get('action')}~~ — {d.get('reason')}")
    if plan.get("escalate_if"):
        st.warning(f"Escalate if: {plan['escalate_if']}")
    if mems:
        with st.expander(f"Raw memories recalled from Hindsight ({len(mems)})"):
            for m in mems:
                st.code(m["text"])


# ---------------- TRIAGE ----------------
with tab_triage:
    st.subheader("Paste an alert, log snippet, or describe what's broken")
    cols = st.columns(len(EXAMPLE_ALERTS))
    for col, (name, text) in zip(cols, EXAMPLE_ALERTS.items()):
        if col.button(name):
            ss.last_alert = text
    alert = st.text_area("Alert", value=ss.last_alert, height=140, label_visibility="collapsed")

    if st.button("🔎 Triage", type="primary", disabled=not alert.strip()):
        ss.last_alert = alert
        ss.feedback = {}
        try:
            with st.spinner("Recalling similar incidents from Hindsight and building a plan..."):
                with_mem = agent.triage(alert, use_memory=True)
                without = agent.triage(alert, use_memory=False) if compare else None
            ss.last_triage = {"with": with_mem, "without": without}
        except Exception as e:
            st.error(f"Triage failed: {e}")

    if ss.last_triage:
        if ss.last_triage["without"]:
            c1, c2 = st.columns(2)
            with c1:
                render_plan(ss.last_triage["without"]["plan"], [], "🙈 Amnesia mode (no memory)")
            with c2:
                render_plan(ss.last_triage["with"]["plan"], ss.last_triage["with"]["memories"],
                            "🧠 Hindsight mode (with memory)")
        else:
            render_plan(ss.last_triage["with"]["plan"], ss.last_triage["with"]["memories"],
                        "🧠 Hindsight mode (with memory)")

        st.divider()
        st.markdown("#### Did the suggested steps work? (this feeds back into memory)")
        for i, s in enumerate(ss.last_triage["with"]["plan"].get("fix_steps", [])):
            ss.feedback[i] = st.radio(s.get("step", f"step {i}"), ["not tried", "worked", "failed"],
                                      horizontal=True, key=f"fb_{i}")
        st.caption("Next: go to **Resolve & Learn** to record the post-mortem.")

# ---------------- RESOLVE ----------------
with tab_resolve:
    st.subheader("Record what actually happened")
    st.caption("Free text is fine — the agent structures it and retains it into Hindsight.")
    default = ""
    if ss.last_triage:
        default = f"Alert: {ss.last_alert}\n\nWhat we found:\n\nWhat fixed it:\n\nWhat we tried that failed:\n"
    pm_text = st.text_area("Post-mortem", value=default, height=220)
    if st.button("💾 Retain to memory", type="primary", disabled=not pm_text.strip()):
        fb = []
        if ss.last_triage:
            steps = ss.last_triage["with"]["plan"].get("fix_steps", [])
            fb = [{"step": steps[i]["step"], "result": r} for i, r in ss.feedback.items()
                  if i < len(steps) and r != "not tried"]
        try:
            with st.spinner("Structuring post-mortem and retaining into Hindsight..."):
                inc = agent.resolve(pm_text, fb, alert=ss.last_alert, next_id=f"INC-{ss.next_id}")
            ss.next_id += 1
            st.success(f"Retained {inc.get('id')} — {inc.get('title')}. "
                       f"Re-run the same alert in Triage to see the agent use it.")
            st.json(inc)
        except Exception as e:
            st.error(f"Retain failed: {e}")

# ---------------- PATTERNS ----------------
with tab_patterns:
    st.subheader("Ask the memory what it has learned")
    questions = [
        "Why does payment-service keep going down? What is the recurring pattern?",
        "Which runbook has the best track record and which one gets misapplied?",
        "What mistakes do on-call engineers repeat across incidents?",
        "Which failures happened without a deploy, and what should be checked first?",
    ]
    for q in questions:
        if st.button(q):
            ss.pattern_q = q
    q = st.text_input("Question", value=ss.pattern_q)
    if st.button("🧩 Reflect", type="primary", disabled=not q.strip()):
        try:
            with st.spinner("Hindsight is reflecting over all incidents..."):
                st.markdown(agent.patterns(q))
        except Exception as e:
            st.error(f"Reflect failed: {e}")