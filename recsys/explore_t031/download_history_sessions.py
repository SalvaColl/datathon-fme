import pandas as pd, sys, time
from rt import q
from concurrent.futures import ThreadPoolExecutor
days=pd.date_range('2026-10-15','2026-11-14',freq='D')
def one(d):
    a=d.strftime('%Y-%m-%d'); b=(d+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    for k in range(4):
        try:
            x=q(f"""SELECT ts::String ts, user_id::String u, context.page::String page, context.device::String device, context.region::String region,
              arrayStringConcat(arrayMap(x->x.product_id::String, recent_views::Array(JSON)),',') rv, arrayStringConcat(shown::Array(String),',') shown,
              ifNull(clicked::Nullable(String),'') clicked, ifNull(purchased::Nullable(String),'') purchased
              FROM shop.history_sessions WHERE ts::DateTime64(3) >= toDateTime64('{a} 00:00:00',3) AND ts::DateTime64(3) < toDateTime64('{b} 00:00:00',3)""")
            x.to_parquet(f'data/t031_hs_{a}.parquet'); print(a,len(x),flush=True); return
        except Exception as e: print(a,'ERR',str(e)[:300],flush=True); time.sleep(3)
if len(sys.argv)>1: one(days[0]); sys.exit()
with ThreadPoolExecutor(3) as ex: list(ex.map(one,days))
print('DONE',flush=True)
