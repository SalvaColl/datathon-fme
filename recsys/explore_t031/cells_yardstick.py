import sys, json, numpy as np, pandas as pd
sys.path.insert(0,'.')
import lfm, lfm_build
I=pd.read_parquet('data/t031_I.parquet'); d=pd.read_parquet('data/t031_d.parquet'); B=pd.read_parquet('data/t031_lb_bins.parquet').rename(columns={'n':'N'})
d['t']=pd.to_datetime(d.ts).astype('datetime64[ns]').astype('int64')/1e9; d['bin']=(d.t//300*300).astype(int); d['buy']=(d.purchased!='').astype(int)
d['seg']=np.where(d.new_user,'n','k')+np.where(d.page=='home','h','')
team=d.served_by=='team'
def value(coef):
    v=np.zeros(len(I))
    for seg,new in (('known',False),('new',True)):
        m=(I.new_user==new).values
        v[m]=lfm_build.p_buy(coef,seg,I.loc[m,lfm.FEATS].values,I.loc[m,'slot'].values)
    v[I.dead.values==1]=0
    return pd.Series(v).groupby(I.rid.values).sum().reindex(d.index).fillna(0).values
coefs={n:json.loads(open(f).read()) for n,f in (('r1','lfm_coef.json'),('r2','lfm_coef_r2.json'),('r3','lfm_coef_r3.json'),('r5','lfm_coef_r5.json'))}
for n,c in coefs.items(): d['v_'+n]=value(c)
dd=d[team]
g=dd.groupby(['bin','mv']).agg(n2=('buy','size'),buys=('buy','sum'),**{c:(c,'sum') for c in d.columns if c.startswith('v_')}).reset_index()
sg=dd.groupby(['bin','mv','seg']).size().unstack(fill_value=0).reset_index()
m=B.merge(g,on=['bin','mv']).merge(sg,on=['bin','mv']); m=m[(m.N==m.n2)&(m.N>=30)]
print('cells',len(m),'requests',int(m.N.sum()),'hidden buys',m.hs.sum().round(1),'realized',m.buys.sum(), {c:m[c].sum().round(1) for c in m if c.startswith('v_')})
w=1/np.sqrt(m.N.values)
def r2(cols,y='hs'):
    X=m[cols].values*w[:,None]; Y=m[y].values*w
    b,*_=np.linalg.lstsq(X,Y,rcond=None); r=Y-X@b
    return 1-(r**2).sum()/((Y)**2).sum(), (r**2).sum(), b
segs=['k','n','kh','nh']
_,rss0,b0=r2(segs); print('segment counts only: rss',round(rss0,4),'rates',b0.round(4))
for c in ['v_r1','v_r2','v_r3','v_r5','buys']:
    _,rss,b=r2(segs+[c]); print(f'{c:6s} + seg counts: residual variance explained {1-rss/rss0:.3f} slope {b[-1]:.3f}')
    _,rss,b=r2([c]); print(f'{c:6s} alone: rss/rss0 {rss/rss0:.3f} slope {b[-1]:.3f}')
m.to_parquet('data/t031_cells.parquet'); d.to_parquet('data/t031_d2.parquet')
# by time-era
m['era']=pd.cut(m.bin,[0,1794666780,1794675000,2e9],labels=['<14:33','14:33-16:50','>16:50'])
print(m.groupby('era',observed=True).agg(cells=('N','size'),n=('N','sum'),hs=('hs','sum'),buys=('buys','sum'),r3=('v_r3','sum')))
