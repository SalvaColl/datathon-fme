import sys, time, json, numpy as np, pandas as pd
sys.path.insert(0,'.')
import lfm, lfm_build
t=time.time()
d, LF, aff, carts, buys = lfm_build.load()
I = lfm_build.impressions(d, LF, aff, carts, buys)
print(len(d), len(I), time.time()-t)
I.drop(columns=['ts']).to_parquet('data/t031_I.parquet')
d[['request_id','ts','user_id','new_user','page','device','region','mv','served_by','clicked','purchased']].to_parquet('data/t031_d.parquet')
