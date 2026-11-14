from rt import q
import pandas as pd, time
t=time.time()
cols="request_id, ts::String ts, user_id::String user_id, context.device::String device, context.region::String region, context.page::String page, toJSONString(recent_views) rv, toJSONString(shown) shown, toJSONString(propensity) prop, ifNull(clicked::Nullable(String),'') clicked, ifNull(purchased::Nullable(String),'') purchased, revenue_eur::Float64 rev"
parts=[]
for d in range(0,60,5):
    df=q(f"SELECT {cols} FROM shop.history_sessions WHERE toDate(ts::DateTime64(3)) >= toDate('2026-09-15')+{d} AND toDate(ts::DateTime64(3)) < toDate('2026-09-15')+{d+5}")
    parts.append(df); print(d,len(df),time.time()-t,flush=True)
df=pd.concat(parts); df.to_parquet("data/hs.parquet"); print(len(df))
