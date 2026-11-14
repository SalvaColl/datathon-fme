from rt import q
import pandas as pd
CUT="2026-10-15 07:00:00"
for name,cond in [("A",f"ts::DateTime64(3) < toDateTime64('{CUT}',3)"),("all","1")]:
    parts=[]
    for m in range(6):
        parts.append(q(f"""SELECT user_id::String u, product_id::String i, toUInt32(countIf(event_type='view')) v, toUInt32(countIf(event_type='add_to_cart')) a, toUInt32(countIf(event_type='purchase')) p
FROM shop.history_events WHERE {cond} AND cityHash64(user_id::String)%6={m} GROUP BY u,i"""))
    up=pd.concat(parts); print(name,len(up),flush=True); up.to_parquet(f"data/user_item_{name}.parquet")
