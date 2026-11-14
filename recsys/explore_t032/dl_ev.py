import sys; sys.path.insert(0,'.')
from rt import q
import pandas as pd
parts=[]
for m in range(10):
    for tb in ("history_events","events"):
        d=q(f"""SELECT user_id::String u, session_id::String s, product_id::String i, event_type::String e, ts::DateTime64(3)::String t
        FROM shop.{tb} WHERE cityHash64(user_id::String)%100={m}"""); d["src"]=tb; parts.append(d); print(m,tb,len(d),flush=True)
pd.concat(parts).to_parquet("data/seq_ev10.parquet")
