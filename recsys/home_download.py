"""T-013 data pulls (git-ignored outputs in data/):
  data/home_hs.parquet  - all historical `home` carousel sessions (400k)
  data/uid.parquet      - organic events aggregated per (user, product, day): v, a, p  (~10M rows)
  data/live_fb.parquet, live_ev.parquet, live_item.parquet - live validation snapshots (read-only queries)
Usage: python home_download.py [hs|uid|live|all]
"""
import sys, time
import pandas as pd
from rt import q

def hs():
    cols = ("request_id::String rid, ts::String ts, user_id::String u, context.device::String device, context.region::String region, "
            "toJSONString(shown) shown, toJSONString(propensity) prop, ifNull(clicked::Nullable(String),'') clicked, "
            "ifNull(purchased::Nullable(String),'') purchased")
    parts = [q(f"SELECT {cols} FROM shop.history_sessions WHERE context.page::String='home' AND cityHash64(user_id::String)%8={m}") for m in range(8)]
    df = pd.concat(parts); df.to_parquet("data/home_hs.parquet"); print("home_hs", len(df), flush=True)

def uid(N=48):
    parts = []; t = time.time()
    for m in range(N):
        for attempt in range(3):
            try:
                d = q(f"""SELECT user_id::String u, product_id::String i, toString(toDate(ts::DateTime64(3))) d,
                  toUInt16(countIf(event_type::String='view')) v, toUInt16(countIf(event_type::String='add_to_cart')) a, toUInt16(countIf(event_type::String='purchase')) p
                  FROM shop.history_events WHERE cityHash64(user_id::String)%{N}={m} GROUP BY u,i,d"""); break
            except Exception as e: print("retry", m, str(e)[:200], flush=True); time.sleep(3)
        for c in "uid": d[c] = d[c].astype("category")
        parts.append(d); print(m, len(d), round(time.time() - t), flush=True)
    df = pd.concat(parts); 
    for c in "uid": df[c] = df[c].astype(str)
    df.to_parquet("data/uid.parquet"); print("uid", len(df), flush=True)


def live():
    """Live snapshots for validation (read-only): our feedback joined with requests, and live organic cart/purchase events."""
    fb = pd.concat([q(f"""SELECT f.request_id::String rid, r.user_id::String u, r.is_new_user::Bool nu, r.context.page::String page, r.context.device::String device,
      toJSONString(r.recent_views) rv, toJSONString(f.shown) shown, f.clicked::String clicked, f.purchased::String purchased, f.served_by::String sb, r.ts::String ts
      FROM team_26.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String
      WHERE f.request_id::String!='__init__' AND cityHash64(f.request_id::String)%6={m}""") for m in range(6)])
    fb.to_parquet("data/live_fb.parquet"); print("live_fb", len(fb), fb.ts.min(), fb.ts.max(), flush=True)
    ev = pd.concat([q(f"""SELECT user_id::String u, product_id::String i, event_type::String e, ts::String ts FROM shop.events
      WHERE event_type::String!='view' AND cityHash64(user_id::String)%4={m}""") for m in range(4)])
    ev.to_parquet("data/live_ev.parquet"); print("live_ev", len(ev), flush=True)
    it = q("SELECT product_id::String i, countIf(event_type::String='view') v, countIf(event_type::String='add_to_cart') a, countIf(event_type::String='purchase') p FROM shop.events GROUP BY i")
    it.to_parquet("data/live_item.parquet"); print("live_item", len(it), flush=True)

if __name__ == "__main__":
    w = sys.argv[1] if len(sys.argv) > 1 else "all"
    if w in ("hs", "all"): hs()
    if w in ("uid", "all"): uid()
    if w in ("live", "all"): live()
