import pandas as pd, numpy as np
e=pd.read_parquet("data/seq_ev10.parquet"); e["t"]=pd.to_datetime(e.t)
cat=pd.read_parquet("data/catalog.parquet").set_index("product_id")
for c in ("sub","brand","price"): e[c]=e.i.map(cat[c])
e=e.sort_values(["u","t"]).reset_index(drop=True)
v=e[(e.e=="view")].copy(); g=v.groupby("s")
for c in ("i","sub","brand","price"): v["p"+c]=g[c].shift()
w=v[(v["sub"]==v.psub)&(v.i!=v.pi)].copy()
rng=np.random.default_rng(1); w["h"]=rng.random(len(w))<0.5
pop=w.groupby(["sub","i"]).size().rename("pop").reset_index(); subn=w.groupby("sub").size().rename("subn")
res=[]
for h in (True,False):
    x=w[w.h==h]; pc=x.groupby(["pi","i"]).size().rename("c"); ni=x.groupby("pi").size().rename("ni")
    res.append((pc,ni))
# residual correlation over pairs seen in either half, restricted to frequent prev items
idx=res[0][0].index.union(res[1][0].index)
D=pd.DataFrame(index=idx).reset_index(); D.columns=["pi","i"]
D["sub"]=D.i.map(cat["sub"]); D=D.merge(pop,on=["sub","i"]).merge(subn,left_on="sub",right_index=True)
for k,(pc,ni) in enumerate(res):
    D[f"c{k}"]=pd.Series(pc.reindex(pd.MultiIndex.from_frame(D[["pi","i"]])).values).fillna(0).values; D[f"n{k}"]=D.pi.map(ni).fillna(0).values
    D[f"r{k}"]=D[f"c{k}"]-D[f"n{k}"]*D["pop"]/D.subn
print("pairs",len(D),"split-half correlation of item-pair residuals (0 = no item-to-item structure):",round(np.corrcoef(D.r0,D.r1)[0,1],4))
big=D[(D.n0>=40)&(D.n1>=40)]; print(" restricted to prev items with >=40 transitions per half:",len(big),round(np.corrcoef(big.r0,big.r1)[0,1],4))
# brand / price continuity vs expectation under sub popularity
exp_b=[]; 
pb=w.groupby(["sub","brand"]).size()/w.groupby("sub").size()
w["exp_same_brand"]=[pb.get((s,b),0) for s,b in zip(w["sub"],w.pbrand)]
print("same-sub next view: same brand %.3f vs expected by popularity %.3f"%((w.brand==w.pbrand).mean(),w.exp_same_brand.mean()))
w["lr"]=np.abs(np.log(w.price/w.pprice)); sh=w.groupby("sub").price.transform(lambda s:s.sample(frac=1,random_state=0).values)
print("|log price ratio| next vs prev: %.3f ; vs random item of same sub: %.3f"%(w.lr.mean(),np.abs(np.log(sh/w.pprice)).mean()))
