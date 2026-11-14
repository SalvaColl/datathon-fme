import pandas as pd, json, numpy as np
df=pd.read_parquet("data/hs.parquet")
C=pd.read_parquet("data/catalog.parquet").set_index("product_id")
sub=C["sub"].to_dict(); catd=C.category.to_dict()
df["rv"]=df.rv.map(lambda s:[x["product_id"] for x in json.loads(s)])
df["shown"]=df.shown.map(json.loads)
df["last"]=df.rv.map(lambda l:l[-1] if l else None)
df["buy"]=df.purchased!=""
print("shown ids not in catalog:", sum(x not in catd for sh in df.shown.head(100000) for x in sh))
print("rv ids not in catalog:", sum(x not in catd for r in df.rv.head(100000) for x in r))
lc=df["last"].map(lambda l:catd.get(l) if l else None)
df["n_samecat"]=[sum(catd.get(x)==c for x in sh) if c else -1 for sh,c in zip(df.shown,lc)]
print(df.groupby("n_samecat").agg(n=("buy","size"),conv=("buy","mean")))
# for views sessions: is purchase in category of ANY view, or specifically last?
v=df[(df.buy)&(df.rv.map(len)>1)]
print("multi-view buys",len(v),"same cat first view",np.mean([catd.get(p)==catd.get(r[0]) for p,r in zip(v.purchased,v.rv)]))
print("are all views same category?", np.mean([len({catd.get(x) for x in r})==1 for r in df.rv[df.rv.map(len)>1].head(200000)]))
# clicks
c=df[(df.clicked!="")&(df.rv.map(len)>0)]
print("click same cat as last", np.mean([catd.get(p)==catd.get(l) for p,l in zip(c.clicked,c["last"])]))
# no-view sessions: who buys?
nv=df[df.rv.map(len)==0]
print("no-view sessions", len(nv), nv.buy.mean(), nv.page.value_counts().to_dict())
print("page x hasview conv"); print(df.assign(hv=df.rv.map(len)>0).groupby(["page","hv"]).buy.agg(["size","mean"]))
# purchased == clicked?
b=df[df.buy]; print("purchased==clicked",(b.purchased==b.clicked).mean())
