import sys, json; sys.path.insert(0,'.')
import numpy as np, pandas as pd, lfm, lfm_build as B
d, LF, aff, carts, buys = B.load()
raw = pd.read_parquet(B.DATA/"lfm_fb.parquet"); raw["ts"]=pd.to_datetime(raw.ts); raw=raw.sort_values("ts").reset_index(drop=True)
assert (raw.request_id.values==d.request_id.values).all()
rvfull=[json.loads(s) if s else [] for s in raw.rv]
I = B.impressions(d, LF, aff, carts, buys)
I.to_parquet("data/t032_I.parquet")
S=LF.snap; sub=S.sub; row=S.row
ex=[]
for r,rvf in zip(d.itertuples(), rvfull):
    rv=[x["product_id"] for x in rvf]; ts=[pd.Timestamp(x["ts"]) for x in rvf]
    rows=[row.get(p,-1) for p in rv]; subs=[sub[k] if k>=0 else -9 for k in rows]
    n=len(rv); last_sub=subs[-1] if n else -9
    run=0
    for s in reversed(subs):
        if s==last_sub: run+=1
        else: break
    age=(r.ts-ts[-1]).total_seconds() if n else -1
    dwell=(ts[-1]-ts[-2]).total_seconds() if n>1 else -1
    span=(ts[-1]-ts[0]).total_seconds() if n>1 else 0
    lc={i for i,t in carts.get(r.user_id,{}).items() if t<np.datetime64(r.ts)}
    distinct=list(dict.fromkeys(reversed(rv)))  # most recent first
    for p in r.shown:
        k=row.get(p,-1); ps=sub[k] if k>=0 else -8
        cnt=rv.count(p); back=distinct.index(p) if p in distinct else -1
        prevsubs=[s for s in subs if s!=last_sub]
        ex.append((n,cnt,back,run,age,dwell,span,int(ps in prevsubs and ps!=last_sub and cnt==0), (subs.count(ps)/n if n else 0.0), int(n>0 and rv[-1] in lc), len(set(subs)),
                   int(n>1 and ps==subs[-2] and ps!=last_sub and cnt==0)))
E=pd.DataFrame(ex,columns=["nrv","cnt","back","run","age","dwell","span","psub","subshare","lastcarted","nsubs","sub2nd"])
E.to_parquet("data/t032_E.parquet"); print(len(I),len(E))
print(E.describe().round(2).T)
