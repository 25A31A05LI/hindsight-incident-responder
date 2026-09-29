import json
import time
import memory


def main():
    memory.ensure_bank()
    with open("data/incidents.json", encoding="utf-8") as f:
        incidents = json.load(f)
    print(f"Seeding {len(incidents)} incidents into bank '{memory.BANK}' via {memory.BACKEND} ...")
    for inc in incidents:
        t0 = time.time()
        memory.retain_incident(inc)
        print(f"  ok {inc['id']:8} {inc['service']:22} {time.time() - t0:5.1f}s")
    print("\nDone. Quick check:")
    time.sleep(5)
    for h in memory.recall("payment-service 502 postgres connection slots")[:3]:
        print("  -", h["text"][:110].replace("\n", " "))


if __name__ == "__main__":
    main()