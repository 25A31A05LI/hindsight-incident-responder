import time
import memory

print(f"Hindsight backend: {memory.BACKEND} | bank: {memory.BANK}")
memory.ensure_bank()

print("\n[1/3] retain")
memory.retain(
    "INCIDENT INC-TEST | 2025-01-01 | SEV-3 | service: demo-service | smoke test. "
    "Symptoms: demo-service returns HTTP 500 with 'config key MISSING_URL not set'. "
    "Root cause: bad config. Resolution steps that WORKED: 1) add MISSING_URL 2) restart pods. "
    "Attempts that FAILED: scaling pods did nothing.",
    metadata={"incident_id": "INC-TEST", "service": "demo-service"},
    timestamp="2025-01-01T00:00:00Z",
    context="smoke test",
)
print("  ok")

print("\n[2/3] recall (waiting 5s for extraction)")
time.sleep(5)
hits = memory.recall("demo-service returning 500 errors")
print(f"  {len(hits)} memories")
for h in hits:
    print("  -", h["text"][:110].replace("\n", " "))

print("\n[3/3] reflect")
print(" ", memory.reflect("What happened with demo-service and what fixed it?")[:400])

print("\nTRACE (latest 3):")
for t in list(memory.TRACE)[:3]:
    print(" ", t["time"], t["op"], f"{t['ms']}ms")