# Hindsight Incident Responder

An on-call agent that remembers every past production incident — root causes,
what fixed it, and what did NOT — using Hindsight agent memory, and gets smarter
after every post-mortem.

## Run
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in Hindsight Cloud + Groq keys
3. `python test_memory.py`   (smoke test)
4. `python seed.py`          (load past incidents into Hindsight)
5. `streamlit run app.py`

## How Hindsight memory is used
- `memory.py` — every incident is retained as two focused memories (diagnosis + resolution).
- Triage: `recall()` fetches similar incidents; the LLM ranks fixes by what worked and lists known dead ends.
- Resolve & Learn: post-mortems and step feedback are `retain()`ed, so the next triage is better.
- Patterns: `reflect()` reasons over all incidents to surface recurring root causes.