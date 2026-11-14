import numpy as np, pandas as pd, sys
sys.path.insert(0,'.')
import cold_items
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
cat=pd.read_parquet('data/lfm_cat.parquet').set_index('product_id')
pidx={p:k for k,p in enumerate(cat.index)}
A=np.zeros((len(cat),20))
for p,d in cat.description.items(): A[pidx[p],list(cold_items.attrs(d))]=1
at=np.array([np.flatnonzero(r) for r in A])
a=pd.read_parquet('data/user_item_A.parquet'); al=pd.read_parquet('data/user_item_all.parquet')
a=a[a.i.isin(pidx)]; al=al[al.i.isin(pidx)]
m=al.merge(a,on=['u','i'],how='left',suffixes=('','A')).fillna(0)
b=m[(m.vA==0)&(m.aA==0)&(m.pA==0)&(m.v>0)]
users=pd.Index(a.u.unique()); uc=users.get_indexer(a.u); ik=a.i.map(pidx).values; n=len(users)
def agg(w): 
    M=np.zeros((n,20)); np.add.at(M,uc,A[ik]*w[:,None]); return M
V=agg(a.v.values.astype(float)); P=agg(a.p.values.astype(float)); C=agg(a.a.values.astype(float))
cc,cats=pd.factorize(cat.category); sc,subs=pd.factorize(cat['sub'])
def aggc(w,code,k):
    M=np.zeros((n,k)); np.add.at(M,(uc,code[ik]),w); return M
VC=aggc(a.v.values.astype(float),cc,len(cats)); VS=aggc(a.v.values.astype(float),sc,len(subs))
b=b[b.u.isin(users)]; bu=users.get_indexer(b.u); bi=b.i.map(pidx).values
y=(b.p>0).values.astype(float)
base=A.mean(0)/2
k1,k2=at[bi,0],at[bi,1]
ub=np.log((P.sum(1)/2+1)/(V.sum(1)/2+20))[bu]   # user base buy-rate control
tr=np.random.default_rng(0).random(len(y))<.5
def ev(name,*f):
    X=np.column_stack(f+(ub,)); mdl=LogisticRegression(max_iter=2000).fit(X[tr],y[tr]); p=mdl.predict_proba(X[~tr])[:,1]
    ll=np.mean(np.where(y[~tr]==1,np.log(p),np.log1p(-p)))
    print(f'{name:50s} auc {roc_auc_score(y[~tr],p):.4f} ll {ll:.5f} coef {mdl.coef_[0].round(2)}')
ev('user base only')
for s in (5,20,60):
    W=V; t=W.sum(1)/2
    sh=(W+s*base)/(t[:,None]+s)     # per-phrase share, shrunk
    s1,s2=sh[bu,k1],sh[bu,k2]
    ev(f'lin share s={s}',s1+s2)
    ev(f'log share sum s={s}',np.log(s1)+np.log(s2))
    ev(f'log shares + min/max s={s}',np.log(np.minimum(s1,s2)),np.log(np.maximum(s1,s2)))
    ev(f'lin + product s={s}',s1+s2,s1*s2)
for wc,wp in ((3,6),(5,15)):
    W=V+wc*C+wp*P; t=W.sum(1)/2; sh=(W+20*base)/(t[:,None]+20); s1,s2=sh[bu,k1],sh[bu,k2]
    ev(f'weighted v+{wc}c+{wp}p lin',s1+s2); ev(f'weighted v+{wc}c+{wp}p log',np.log(s1)+np.log(s2))
# category forms
t=VC.sum(1)
for s in (2,10):
    c=(VC[bu,cc[bi]]+s/10)/(t[bu]+s); sb=(VS[bu,sc[bi]]+s/90)/(t[bu]+s)
    sh=(V+20*base)/(V.sum(1)[:,None]/2+20); L=np.log(sh[bu,k1])+np.log(sh[bu,k2])
    ev(f'phr log + cat lin s={s}',L,c); ev(f'phr log + cat log s={s}',L,np.log(c)); ev(f'phr log + cat log + sub log s={s}',L,np.log(c),np.log(sb))
    ev(f'phr log + cat log + interaction s={s}',L,np.log(c),L*np.log(c))
