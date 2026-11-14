import pandas as pd, numpy as np
e=pd.read_parquet("data/seq_ev10.parquet"); e["t"]=pd.to_datetime(e.t)
cat=pd.read_parquet("data/catalog.parquet").set_index("product_id")
e["sub"]=e.i.map(cat["sub"]); e["cat"]=e.i.map(cat["category"])
e=e.sort_values(["u","t"]).reset_index(drop=True)
for src in ("history_events","events"):
    v=e[(e.src==src)&(e.e=="view")].copy(); g=v.groupby("s")
    for k in (1,2,3): v[f"s{k}"]=g["sub"].shift(k); v[f"c{k}"]=g["cat"].shift(k)
    v["first"]=g["sub"].transform("first"); v["n"]=g.cumcount()
    print("\n==",src)
    a=v[v.s2.notna()]
    sw=a[a.s1!=a.s2]   # just switched: prev two differ
    print(" after a switch (s2!=s1): next = last sub %.3f, = previous sub %.3f, other %.3f  n=%d"%((sw["sub"]==sw.s1).mean(),(sw["sub"]==sw.s2).mean(),((sw["sub"]!=sw.s1)&(sw["sub"]!=sw.s2)).mean(),len(sw)))
    st=a[a.s1==a.s2]
    print(" after a stay (s2==s1): next = same sub %.3f n=%d"%((st["sub"]==st.s1).mean(),len(st)))
    b=v[v.s3.notna()]
    x=b[(b.s3==b.s2)&(b.s1!=b.s2)]; print(" A A B -> A %.3f  B %.3f  n=%d"%((x["sub"]==x.s2).mean(),(x["sub"]==x.s1).mean(),len(x)))
    x=b[(b.s3==b.s1)&(b.s1!=b.s2)]; print(" A B A -> A %.3f  B %.3f  n=%d"%((x["sub"]==x.s1).mean(),(x["sub"]==x.s2).mean(),len(x)))
    x=b[(b.s2==b.s1)&(b.s3!=b.s2)]; print(" A B B -> B %.3f  A %.3f  n=%d"%((x["sub"]==x.s1).mean(),(x["sub"]==x.s3).mean(),len(x)))
    print(" P(view in session's first sub) by index:",v.groupby(v.n.clip(upper=8)).apply(lambda d:(d["sub"]==d["first"]).mean()).round(3).to_dict())
    print(" P(same sub as previous) by index:",v[v.n>0].groupby(v.n.clip(upper=8)).apply(lambda d:(d["sub"]==d.s1).mean()).round(3).to_dict())
    # cart rate by whether view is in session main sub / position
    nxt=e[(e.src==src)].copy(); nxt["ne"]=nxt.groupby("s").e.shift(-1); nxt["ni"]=nxt.groupby("s").i.shift(-1)
    vv=nxt[nxt.e=="view"].copy(); vv["cart"]=(vv.ne=="add_to_cart")&(vv.ni==vv.i)
    vv["n"]=vv.groupby("s").cumcount(); vv["s1"]=vv.groupby("s")["sub"].shift(); vv["last"]=vv.groupby("s").cumcount(ascending=False)==0
    vv["seen"]=vv.groupby(["s","i"]).cumcount()
    print(" cart rate by view index:",vv.groupby(vv.n.clip(upper=8)).cart.mean().round(3).to_dict())
    print(" cart rate: same sub as prev %.3f, different %.3f; last view of session %.3f vs not %.3f; repeat view %.3f vs first %.3f"%(vv[vv.s1==vv["sub"]].cart.mean(),vv[(vv.s1!=vv["sub"])&vv.s1.notna()].cart.mean(),vv[vv["last"]].cart.mean(),vv[~vv["last"]].cart.mean(),vv[vv.seen>0].cart.mean(),vv[vv.seen==0].cart.mean()))
    print(" sessions/user",v.groupby("u").s.nunique().describe().round(1).to_dict())
