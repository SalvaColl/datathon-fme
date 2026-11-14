"""T-020 (E-204): the android x (Andalucia, Canarias, Murcia) segment and its price sensitivity on live feedback.
Run after `python lfm_build.py --pull --no-write` and `python explore_t020.py --pull`. Read-only."""

import numpy as np, pandas as pd
import lfm, lfm_build
from lfm_build import DATA
d, LF, aff, carts, buys = lfm_build.load()
I = lfm_build.impressions(d, LF, aff, carts, buys)
cat = pd.read_parquet(DATA/"lfm_cat.parquet").set_index("product_id"); price=cat.price.to_dict()
ctx=pd.read_parquet(DATA/"t020_ctx.parquet").drop_duplicates("request_id").set_index("request_id")
d=d.join(ctx,on="request_id")
I["price"]=[price.get(p,np.nan) for r in d.itertuples() for p in r.shown]
I=I.merge(d[["dev","reg"]],left_on="rid",right_index=True)
I["seg"]=np.where(I.new_user,"new","known"); A=I[I.dead==0].copy()
coef=lfm_build.fit(A); A["p"]=0.0
for seg in ("known","new"):
    m=A.seg==seg; A.loc[m,"p"]=lfm_build.p_buy(coef,seg,A.loc[m,lfm.FEATS].values,A.loc[m,"slot"].values)
def rate(g): return pd.Series(dict(imps=len(g),clicks=int(g.clk.sum()),buys=int(g.buy.sum()),exp=round(g.p.sum(),1),per10k=round(1e4*g.buy.mean(),1),clk10k=round(1e4*g.clk.mean(),1),oe=round(g.buy.sum()/max(g.p.sum(),1e-9),2)))
A["ps"]=np.where(A.dev.eq("android")&A.reg.isin(["Andalucía","Canarias","Murcia"]),"android+ACM","rest")
A["pb"]=pd.cut(A.price,[0,10,20,40,1e9],labels=["<10","10-20","20-40","40+"])
pd.set_option("display.width",200)
print(A[A.home==0].groupby(["ps","pb"],observed=True).apply(rate).to_string())
print(A[A.home==0].groupby(["ps","seg","pb"],observed=True).apply(rate).to_string())
R=I.groupby("rid").agg(buy=("buy","max"),dev=("dev","first"),reg=("reg","first"),page=("page","first"))
R["ps"]=np.where(R.dev.eq("android")&R.reg.isin(["Andalucía","Canarias","Murcia"]),"android+ACM","rest")
print(R[R.page!="home"].groupby("ps").agg(n=("buy","size"),buys=("buy","sum"),conv=("buy",lambda s:round(100*s.mean(),2))))
print(R[R.page!="home"].groupby(["dev"]).agg(n=("buy","size"),buys=("buy","sum"),conv=("buy",lambda s:round(100*s.mean(),2))))
# hold-out: add price interaction
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
cut=d.ts.quantile(0.7); A["lp"]=np.log(A.price.fillna(20)/20); A["sens"]=(A.ps=="android+ACM").astype(float); A["lp_s"]=A.lp*A.sens
for seg in ("known","new"):
    a=A[A.seg==seg]; tr=a[a.ts<cut]; te=a[a.ts>=cut]
    for name,cols in (("lfm",[]),("+lp",["lp"]),("+lp,sens,lp_s",["lp","sens","lp_s"])):
        c=lfm.FEATS+cols+["ls"]; m=LogisticRegression(C=10.,max_iter=5000).fit(tr[c],tr.clk,sample_weight=np.where(tr.buy==1,3.,1.))
        p=np.clip(m.predict_proba(te[c])[:,1],1e-9,1); y=te.clk.values
        z=te[c[:-1]].values@m.coef_[0][:-1]; t2=te.assign(z=z); bq=t2[t2.rid.isin(t2[t2.buy==1].rid)]
        h=bq.sort_values("z",ascending=False).groupby("rid").head(1).buy.mean()
        print(seg,name,"click ll %.1f AUC buy %.4f click %.4f hit@1(n=%d) %.3f"%((y*np.log(p)+(1-y)*np.log(1-p)).sum(),roc_auc_score(te.buy,p),roc_auc_score(te.clk,p),bq.rid.nunique(),h),dict(zip(cols,m.coef_[0][len(lfm.FEATS):-1].round(2))))
