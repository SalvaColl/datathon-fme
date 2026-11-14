import pandas as pd, json, numpy as np
from rt import q
print(q("SELECT count() n, 100*countIf(purchased!='')/n conv, 100*countIf(clicked!='')/n ctr FROM team_26.feedback WHERE request_id!='__init__'"))
df=pd.read_parquet("data/hs.parquet").sample(400000,random_state=1)
C=pd.read_parquet("data/catalog.parquet").set_index("product_id")
sub=C["sub"].to_dict(); catd=C.category.to_dict(); brand=C.brand.to_dict(); price=C.price.to_dict()
df["rv"]=df.rv.map(lambda s:[x["product_id"] for x in json.loads(s)])
df["shown"]=df.shown.map(json.loads); df["prop"]=df.prop.map(json.loads)
rows=[]
for r in df[df.rv.map(len)>0].itertuples():
    last=r.rv[-1]; vs=set(r.rv); subs={sub[x] for x in r.rv}
    for k,(it,p) in enumerate(zip(r.shown,r.prop)):
        rows.append((k,it in vs,it==last,sub[it]==sub[last],sub[it] in subs,brand[it]==brand[last],price[it],price[last],p,it==r.purchased,it==r.clicked))
X=pd.DataFrame(rows,columns="slot viewed islast samesub anysub samebrand price lastprice prop buy click".split())
X.to_parquet("data/items_sample.parquet")
print("by slot"); print(X.groupby("slot").buy.mean().round(4).to_dict())
for f in ["viewed","islast","samesub","anysub","samebrand"]:
    print(f, X.groupby(f).buy.agg(["size","mean"]).to_dict())
X["pb"]=pd.qcut(X.price,8)
print(X.groupby("pb").buy.mean())
X["rel"]=pd.cut(X.price/X.lastprice,[0,.5,.8,1.2,2,100])
print(X.groupby("rel").buy.mean())
# IPS-like: buy / prop relation
X["pq"]=pd.qcut(X.prop,8,duplicates="drop")
print(X.groupby("pq").buy.mean())
