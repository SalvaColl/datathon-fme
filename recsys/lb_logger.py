"""Append every new leaderboard snapshot (public /api/state) to data/lb_history.jsonl. Run in background."""
import json, time, requests
last = None
while True:
    try:
        d = requests.get("https://datathon.rawtree.dev/api/state", timeout=10).json()
        if d.get("updated_at") != last:
            last = d["updated_at"]
            with open("data/lb_history.jsonl", "a") as f: f.write(json.dumps(d) + "\n")
            t = {x["team_id"]: x for x in d["teams"]}.get("team_26", {})
            print(time.strftime("%H:%M"), "team_26", t.get("model_version"), "conv", round(t.get("conversion", 0), 4),
                  "cold", round(t.get("cold_conversion", 0), 4), "on_time", round(t.get("on_time", 0), 1),
                  "| baseline", round(d["baseline"]["conversion"], 4), "ref", round(d["reference"]["conversion"], 4), flush=True)
    except Exception as e: print("lb error", e, flush=True)
    time.sleep(60)
