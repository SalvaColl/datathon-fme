"""Day replay of the shipped detector: trends.compute (15-min rule) + trends.fast_hot, every minute."""
import sys; sys.path.insert(0,"/home/user/datathon-fme/recsys")
import pandas as pd, numpy as np, trends
cat=pd.read_pickle("cat.pkl").set_index("i"); E=pd.read_pickle("ev.pkl"); E["m"]=pd.to_datetime(E.m); E["sub"]=E.i.map(cat["sub"])
M=E.pivot_table(index="m",columns="sub",values="v",aggfunc="sum",fill_value=0).asfreq("min",fill_value=0)
ident={k:k for k in M.columns}
B={"Aquariums":"09:30","Kettles":"11:30","Cutting Boards":"13:30","Bike Helmets":"15:30","Game Consoles":"19:30","Face Cream":"21:30","Vitamins":"23:30"}
truth={s:pd.Timestamp("2026-11-14 "+t) for s,t in B.items()}
on={}; slow={}; fp=[]; prev=set()
for t in pd.date_range("2026-11-14 09:40","2026-11-15 00:50",freq="min"):
    w=M[(M.index<t)&(M.index>=t-pd.Timedelta(minutes=195))]
    age=np.ceil((t-w.index)/pd.Timedelta(minutes=5)).astype(int)-1
    c=w.assign(age=age).groupby("age").sum().stack().reset_index(); c.columns=["age","i","v"]
    s=trends.compute(c,ident)
    rec=w.iloc[-3:].sum().reset_index(); rec.columns=["i","v"]
    hot=trends.fast_hot(s.share,rec,ident,prev); prev=set(hot)
    for name,hs,d in (("fast",hot,on),("slow",s.hot,slow)):
        for x in hs:
            t0=truth.get(x)
            if t0 is not None and t0<=t<=t0+pd.Timedelta(minutes=75): d.setdefault(x,[]).append((t-t0).total_seconds()/60)
            elif name=="fast": fp.append((str(t)[11:16],x))
print("fast false-positive minutes:",len(fp),fp)
for s in B:
    if s in on: print("%-15s fast on +%d..+%d (%d of 45 burst min, %d after) | 15-min rule on +%d..+%d"%(s,min(on[s]),max(on[s]),sum(x<=45 for x in on[s]),sum(x>45 for x in on[s]),min(slow.get(s,[-1])),max(slow.get(s,[-1]))))
