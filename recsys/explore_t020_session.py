"""T-020 (E-202, E-203, E-205): shoppers who already bought today, home by product group, price by shopper type.
Run after `python lfm_build.py --pull --no-write` and `python explore_t020.py --pull`. Read-only."""

import numpy as np, pandas as pd, json
import lfm, lfm_build
from lfm_build import DATA
d, LF, aff, carts, buys = lfm_build.load()
I = lfm_build.impressions(d, LF, aff, carts, buys)
S=LF.snap
cat = pd.read_parquet(DATA/"lfm_cat.parquet").set_index("product_id")
cp = pd.read_parquet(DATA/"t020_cp.parquet"); cp["ts"]=pd.to_datetime(cp.ts)
ub={}
for u,i,t,e in zip(cp.u.values,cp.i.values,cp.ts.values,cp.e.values):
    if e=="purchase": ub.setdefault(u,[]).append((t,i))
sub=cat["sub"].to_dict(); cc=cat["category"].to_dict(); price=cat["price"].to_dict()
ex=[]
for r in d.itertuples():
    ts=np.datetime64(r.ts); b=[i for t,i in ub.get(r.user_id,()) if t<ts]
    bs={sub.get(i) for i in b}; bc={cc.get(i) for i in b}
    rows=[S.row[i] for i in b if i in S.row]
    v = S.A[rows].sum(0)/max(len(rows),1) if rows else None
    for p in r.shown:
        k=S.row.get(p)
        ph = float(S.A[k]@v) if (v is not None and k is not None) else 0.0
        ex.append((len(b), int(sub.get(p) in bs), int(cc.get(p) in bc), ph, price.get(p,np.nan)))
E_=pd.DataFrame(ex,columns=["nb","bsub","bcat","bph","price"]); I=pd.concat([I.reset_index(drop=True),E_],axis=1)
I["seg"]=np.where(I.new_user,"new","known"); A=I[I.dead==0].copy()
coef=lfm_build.fit(A)
A["p"]=0.0
for seg in ("known","new"):
    m=A.seg==seg; A.loc[m,"p"]=lfm_build.p_buy(coef,seg,A.loc[m,lfm.FEATS].values,A.loc[m,"slot"].values)
def rate(g): return pd.Series(dict(imps=len(g),clicks=int(g.clk.sum()),buys=int(g.buy.sum()),exp=round(g.p.sum(),1),per10k=round(1e4*g.buy.mean(),1),oe=round(g.buy.sum()/max(g.p.sum(),1e-9),2)))
pd.set_option("display.width",200)
A["grp"]=np.select([A.cl==1,A.chn>0,A.islast==1,A.oinrv==1,A.ssub2==1,A.scat2==1],["cart_today","cart_hist","last_view","other_rv","same_sub","same_cat"],"other")
A["nbg"]=np.where(A.nb==0,"0",np.where(A.nb==1,"1","2+"))
print("E0: by group x bought-today"); print(A[A.home==0].groupby(["seg","nbg","grp"]).apply(rate).to_string())
B=A[(A.nb>0)&(A.cl==0)&(A.islast==0)&(A.oinrv==0)]
print("E1: shoppers who bought today, product not carted/not in rv: same subcategory as something bought today"); print(B.groupby(["seg","bsub"]).apply(rate).to_string())
print("same category:"); print(B.groupby(["seg","bcat"]).apply(rate).to_string())
B=B.assign(phg=pd.cut(B.bph,[-1,0.01,0.6,1.1,3],labels=["0","1 shared-ish","~1","2"]))
print("phrase overlap with today's purchases (mean shared phrases):"); print(B.groupby(["seg","phg"],observed=True).apply(rate).to_string())
print("F: home, by group"); print(A[A.home==1].groupby(["seg","grp"]).apply(rate).to_string())
H=A[(A.home==1)&(A.grp=="other")].copy(); H["lqg"]=pd.qcut(H.lq,4,duplicates="drop"); H["affg"]=pd.cut(H.aff10,[-9,0.01,0.5,1,9])
print(H.groupby(["seg","lqg"],observed=True).apply(rate).to_string()); print(H.groupby(["seg","affg"],observed=True).apply(rate).to_string())
print("G: price terciles, live impressions non-home 'generic' (same_sub/same_cat/other)")
G=A[(A.home==0)&A.grp.isin(["same_sub","same_cat","other"])].copy(); G["pg"]=pd.cut(G.price,[0,15,40,80,1e9])
print(G.groupby(["seg","pg"],observed=True).apply(rate).to_string())
# hold-out for bsub/bph
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
cut=d.ts.quantile(0.7); A["bsubx"]=((A.bsub==1)&(A.cl==0)).astype(float); A["nb1"]=(A.nb>0).astype(float)
for seg in ("known","new"):
    a=A[A.seg==seg]; tr=a[a.ts<cut]; te=a[a.ts>=cut]
    for name,cols in (("lfm",[]),("+bsub",["bsubx"]),("+bph",["bph"]),("+nb1",["nb1"]),("+nb1,bsub,bph",["nb1","bsubx","bph"])):
        c=lfm.FEATS+cols+["ls"]; m=LogisticRegression(C=10.,max_iter=5000).fit(tr[c],tr.clk,sample_weight=np.where(tr.buy==1,3.,1.))
        p=np.clip(m.predict_proba(te[c])[:,1],1e-9,1); y=te.clk.values
        # within-request rank metric: hit@1 of purchased among shown, slot removed
        z=te[c[:-1]].values@m.coef_[0][:-1]; t2=te.assign(z=z); bq=t2[t2.rid.isin(t2[t2.buy==1].rid)]
        h=(bq.sort_values("z",ascending=False).groupby("rid").head(1).buy.mean())
        print(seg,name,"click ll %.1f AUC buy %.4f hit@1(buy reqs, n=%d) %.3f"%((y*np.log(p)+(1-y)*np.log(1-p)).sum(),roc_auc_score(te.buy,p),bq.rid.nunique(),h),dict(zip(cols,m.coef_[0][len(lfm.FEATS):-1].round(2))))
