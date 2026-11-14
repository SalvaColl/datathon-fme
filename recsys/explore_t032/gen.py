import pandas as pd, numpy as np, collections
e=pd.read_parquet("data/seq_ev10.parquet"); e["t"]=pd.to_datetime(e.t)
cat=pd.read_parquet("data/catalog.parquet"); print(cat.columns.tolist()); 
cat=cat.set_index("product_id"); subc=[c for c in cat.columns if c.startswith("sub")][0]
e["sub"]=e.i.map(cat[subc]); e["cat"]=e.i.map(cat["category"])
e=e.sort_values(["u","t"]).reset_index(drop=True)
for src in ("history_events","events"):
    d=e[e.src==src]
    print("\n==",src,len(d),d.e.value_counts().to_dict(),"sessions",d.s.nunique(),"users",d.u.nunique())
    v=d[d.e=="view"].copy()
    v["pi"]=v.groupby("s").i.shift(); v["ps"]=v.groupby("s")["sub"].shift(); v["pc"]=v.groupby("s")["cat"].shift(); v["dt"]=(v.t-v.groupby("s").t.shift()).dt.total_seconds()
    v["n"]=v.groupby("s").cumcount()
    w=v[v.pi.notna()]
    print("views/session", v.groupby("s").size().describe().round(2).to_dict())
    print("next view: same item %.3f  same sub %.3f  same cat %.3f | dt median %.0fs"%((w.i==w.pi).mean(),(w["sub"]==w.ps).mean(),(w["cat"]==w.pc).mean(),w.dt.median()))
    # item-level structure within same-sub transitions: is next item predicted by prev item beyond sub popularity?
    ss=w[(w["sub"]==w.ps)&(w.i!=w.pi)]
    pc=ss.groupby(["pi","i"]).size(); tot=len(ss)
    # split half: train pair counts -> test hit rate of top1 next given prev vs top1 popular in sub
    rng=np.random.default_rng(0); m=rng.random(len(ss))<0.5; tr,te=ss[m],ss[~m]
    top_pair=tr.groupby(["pi","i"]).size().reset_index(name="c").sort_values("c",ascending=False)
    pop=tr.groupby(["sub","i"]).size().reset_index(name="c").sort_values("c",ascending=False)
    def hitk(k):
        tp=top_pair.groupby("pi").head(k).groupby("pi").i.agg(set); pp=pop.groupby("sub").head(k+1).groupby("sub").i.agg(list)
        h1=np.mean([i in tp.get(p,()) for p,i in zip(te.pi,te.i)])
        h2=np.mean([i in [x for x in pp.get(s,[]) if x!=p][:k] for p,i,s in zip(te.pi,te.i,te["sub"])])
        return h1,h2
    for k in (1,5): print(" same-sub next-item hit@%d: markov %.3f vs sub-popularity %.3f"%((k,)+hitk(k)))
    # cross-sub transitions: structure?
    cs=w[w["sub"]!=w.ps]; m=rng.random(len(cs))<0.5; tr,te=cs[m],cs[~m]
    t1=tr.groupby(["ps","sub"]).size().reset_index(name="c").sort_values("c",ascending=False).groupby("ps").head(3).groupby("ps")["sub"].agg(set)
    g=tr["sub"].value_counts().index[:3]
    print(" cross-sub next-sub hit@3: markov %.3f vs global %.3f ; same-cat share %.3f"%(np.mean([s in t1.get(p,()) for p,s in zip(te.ps,te["sub"])]),te["sub"].isin(g).mean(),(cs["cat"]==cs.pc).mean()))
    # purchases: relation to views in the same session
    rows=[]
    for s,g in d.groupby("s"):
        if not (g.e=="purchase").any(): continue
        ii=g.i.values; ee=g.e.values
        for k in np.where(ee=="purchase")[0]:
            pv=[ii[j] for j in range(k) if ee[j]=="view"]; pcart=[ii[j] for j in range(k) if ee[j]=="add_to_cart"]
            p=ii[k]
            rows.append((len(pv), p in pv, (len(pv)-1-max(j for j,x in enumerate(pv) if x==p)) if p in pv else -1, pv.count(p), p in pcart, ee[k-1] if k else "", ii[k-1]==p if k else False))
    R=pd.DataFrame(rows,columns=["nv","inv","back","cnt","carted","prev_e","prev_same"])
    print(" purchases",len(R),"| viewed before in session %.3f | carted before in session %.3f | prev event %s | prev same item %.3f"%(R.inv.mean(),R.carted.mean(),R.prev_e.value_counts(normalize=True).round(3).to_dict(),R.prev_same.mean()))
    print(" purchased item position back from last view:",R[R.inv].back.clip(upper=5).value_counts(normalize=True).sort_index().round(3).to_dict())
    print(" times viewed before purchase:",R.cnt.clip(upper=4).value_counts(normalize=True).sort_index().round(3).to_dict(), " prior views in session:",R.nv.describe().round(1).to_dict())
    # baseline: distribution of repeat counts for viewed items that were NOT bought
    c=d[d.e=="add_to_cart"]
    # per (session,item): views, carted, bought
    a=d.groupby(["s","i"]).e.agg(v=lambda x:(x=="view").sum(),a=lambda x:(x=="add_to_cart").sum(),p=lambda x:(x=="purchase").sum())
    print(" P(buy in session | views of item in session):",a.groupby(a.v.clip(upper=4)).p.agg(lambda x:(x>0).mean()).round(4).to_dict(), "n",a.groupby(a.v.clip(upper=4)).size().to_dict())
    print(" P(buy | carted in session) %.3f  P(buy | viewed, not carted) %.4f"%((a[a.a>0].p>0).mean(),(a[(a.a==0)&(a.v>0)].p>0).mean()))
