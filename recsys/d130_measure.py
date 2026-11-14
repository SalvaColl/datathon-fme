"""Read-only measurement of the D-130 live blocks.
  python d130_measure.py lb        # leaderboard snapshots (data/lb_history.jsonl from lb_logger.py): team vs baseline per snapshot,
                                   # and the implied 10-min block:  block_new - block_dropped = 6 * (snapshot_t - snapshot_t-1)
  python d130_measure.py fb [min]  # realized feedback per model_version x page (noisy; attribution check)
"""
import sys, json, time
import pandas as pd

def lb():
    rows = []
    for l in open("data/lb_history.jsonl"):
        d = json.loads(l); t = {x["team_id"]: x for x in d["teams"]}.get("team_26")
        if not t: continue
        rows.append(dict(utc=time.strftime("%H:%M:%S", time.gmtime(d["updated_at"])), version=t["model_version"], team=t["conversion"], base=d["baseline"]["conversion"],
                         ref=d["reference"]["conversion"], cold=t["cold_conversion"], base_cold=d["baseline"]["cold_conversion"], on_time=t["on_time"]))
    x = pd.DataFrame(rows).drop_duplicates("utc")
    x["lift"] = x.team - x.base                         # hourly expected conversion above baseline (points)
    x["norm"] = 100 * (x.team - x.base) / (x.ref - x.base)
    x["block_delta"] = 6 * x.lift.diff()                # (new 10-min block lift) - (block that left the hour)
    x["cold_block_delta"] = 6 * (x.cold - x.base_cold).diff()
    print(x.round(3).to_string(index=False))

def fb(mins=90):
    from rt import q
    print(q(f"""SELECT s.mv version, if(r.context.page::String='home','home','other') page, count() n, countIf(f.purchased::String!='') buys,
      round(100*buys/n,2) conv_pct, round(100*countIf(f.clicked::String!='')/n,2) ctr_pct, round(quantile(0.95)(f.latency_ms::Float64)) p95_ms,
      min(f.ts::String) t0, max(f.ts::String) t1
      FROM team_26.feedback f INNER JOIN (SELECT request_id::String rid, any(model_version::String) mv FROM team_26.submissions GROUP BY rid) s ON s.rid=f.request_id::String
      INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String
      WHERE f.served_by::String='team' AND f.ts::DateTime64(3) > now() - INTERVAL {int(mins)} MINUTE GROUP BY version, page ORDER BY version, page""").to_string())

if __name__ == "__main__":
    lb() if sys.argv[1] == "lb" else fb(*sys.argv[2:3])
