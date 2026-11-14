import json, numpy as np, pandas as pd
I=pd.read_parquet('data/t031_I.parquet')
d=pd.read_parquet('data/lfm_fb.parquet'); d['shown']=d.shown.map(json.loads); d['ts']=pd.to_datetime(d.ts); d=d.sort_values('ts').reset_index(drop=True)
print('requests',len(d),'users',d.user_id.nunique(),'req/user quantiles',d.groupby('user_id').size().quantile([.5,.75,.9,.99]).to_dict())
prev={}; pclk={}; nprev=[]; nclk=[]; ureq={}; ur=[]
for r in d.itertuples():
    k=ureq.get(r.user_id,0); ureq[r.user_id]=k+1
    for p in r.shown:
        key=(r.user_id,p); nprev.append(prev.get(key,0)); nclk.append(pclk.get(key,0)); ur.append(k)
        prev[key]=prev.get(key,0)+1
    if r.clicked and r.clicked!=r.purchased: pclk[(r.user_id,r.clicked)]=pclk.get((r.user_id,r.clicked),0)+1
I['nprev']=nprev; I['nclk']=nclk; I['ureq']=ur
I.to_parquet('data/t031_I2.parquet')
J=I[I.dead==0]
ty=np.select([J.cl>0,J.chn>0,J.islast>0,J.oinrv>0],['cart_today','cart_hist','last','inrv'],'fresh'); J=J.assign(ty=ty,seg=np.where(J.new_user,'N','K'),e=np.minimum(J.nprev,4),top=J.slot<=3)
t=J[J.page!='home'].groupby(['seg','ty','top','e']).agg(imp=('buy','size'),clk=('clk','sum'),buy=('buy','sum'))
t['buy_per_10k']=(1e4*t.buy/t.imp).round(1); t['clk_per_10k']=(1e4*t.clk/t.imp).round(1)
print(t[t.imp>1500].to_string())
print('\nprevious click without purchase on this product:')
t=J.groupby(['seg',np.minimum(J.nclk,1)]).agg(imp=('buy','size'),clk=('clk','sum'),buy=('buy','sum')); t['buy_per_10k']=(1e4*t.buy/t.imp).round(1); print(t.to_string())
