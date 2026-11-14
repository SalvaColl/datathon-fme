import pandas as pd, json, numpy as np
from rt import q
df=pd.read_parquet("data/hs.parquet")
cat=q("SELECT product_id::String product_id, category::String category, subcategory::String sub, brand::String brand, price_eur::Float64 price, created_at::String created FROM shop.catalog")
cat.to_parquet("data/catalog.parquet")
C=cat.set_index("product_id")
df["rv"]=df.rv.map(lambda s:[x["product_id"] for x in json.loads(s)])
df["shown"]=df.shown.map(json.loads)
df["last"]=df.rv.map(lambda l:l[-1] if l else None)
sub=C["sub"].to_dict(); catd=C.category.to_dict()
b=df[df.purchased!=""].copy()
b["has_rv"]=b.rv.map(len)>0
bb=b[b.has_rv]
print("purch w/ views",len(bb),"of",len(b))
print("bought==a viewed", np.mean([p in r for p,r in zip(bb.purchased,bb.rv)]))
print("same sub as last", np.mean([sub[p]==sub[l] for p,l in zip(bb.purchased,bb["last"])]))
print("same cat as last", np.mean([catd[p]==catd[l] for p,l in zip(bb.purchased,bb["last"])]))
print("same sub as any view", np.mean([sub[p] in {sub[x] for x in r} for p,r in zip(bb.purchased,bb.rv)]))
# baseline: fraction of shown items same sub as last
s=df[df.rv.map(len)>0].sample(50000,random_state=0)
print("shown items same sub as last (base rate)", np.mean([np.mean([sub[x]==sub[l] for x in sh]) for sh,l in zip(s.shown,s["last"])]))
print("shown includes a viewed item", np.mean([any(x in r for x in sh) for sh,r in zip(s.shown,s.rv)]))
# conversion per page x whether slate has same-sub items
df["n_same"]=[sum(sub[x]==sub[l] for x in sh) if l else -1 for sh,l in zip(df.shown,df["last"])]
print(df.groupby("n_same").agg(n=("rev","size"),conv=("purchased",lambda x:(x!="").mean())).head(12))
print(df.groupby(["page"]).rv.apply(lambda x:(x.map(len)>0).mean()))
print("rv length dist", df.rv.map(len).value_counts().sort_index().head(10))
print(df.groupby(["device"]).purchased.apply(lambda x:(x!="").mean()))
print(df.groupby(["region"]).purchased.apply(lambda x:(x!="").mean()))
