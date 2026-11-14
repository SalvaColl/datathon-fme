import sys, json, zlib; sys.path.insert(0,'.')
import numpy as np, pandas as pd, lfm
I=pd.read_parquet("data/t032_I.parquet").reset_index(drop=True); E=pd.read_parquet("data/t032_E.parquet")
fb=pd.read_parquet("data/lfm_fb.parquet"); fb["ts"]=pd.to_datetime(fb.ts); fb=fb.sort_values("ts").reset_index(drop=True)
I=pd.concat([I,E],axis=1); I["uh"]=I.rid.map(fb.user_id.map(lambda u: zlib.crc32(u.encode())%4))
base=json.load(open("lfm_coef_r5.json"))
F={}
F["rep2"]=(I.cnt>=2)*1.0
F["back1"]=(I.back==1)*1.0
F["back2p"]=(I.back>=2)*1.0
F["psub"]=I.psub*1.0
F["sub2nd"]=I.sub2nd*1.0
F["ssub_run2"]=I.ssub2*(I.run>=2)
F["ssub_run3"]=I.ssub2*(I.run>=3)
F["ssub_old"]=I.ssub2*(I.age>60)
F["ssub_fresh"]=I.ssub2*(I.age<5)
F["last_old"]=I.islast*(I.age>60)
F["last_rep"]=I.islast*(I.cnt>=2)
F["last_longdwell"]=I.islast*(I.dwell>30)
F["last_cart"]=I.islast*I.cl
F["ssub_lastcarted"]=I.ssub2*I.lastcarted
F["scat_lastcarted"]=I.scat2*I.lastcarted
F["ssub_multi"]=I.ssub2*(I.nsubs>1)
F["subshare_notrv"]=I.subshare*(I.cnt==0)
cut=fb.ts.quantile(0.7); print("cut",cut,"requests",len(fb))
def newton(Z,off,y,sw):
    th=np.zeros(Z.shape[1]); pen=np.r_[0,0,np.ones(Z.shape[1]-2)/10.0]
    for _ in range(60):
        p=1/(1+np.exp(-(off+Z@th))); g=Z.T@(sw*(y-p))-pen*th; H=(Z*(sw*p*(1-p))[:,None]).T@Z+np.diag(pen)+1e-9*np.eye(len(th)); st=np.linalg.solve(H,g); th+=st
        if abs(st).max()<1e-8: break
    return th,np.sqrt(np.diag(np.linalg.inv(H)))
def ll(Z,off,th,y,sw): 
    p=np.clip(1/(1+np.exp(-(off+Z@th))),1e-12,1-1e-12); return float(np.sum(sw*(y*np.log(p)+(1-y)*np.log(1-p))))
rows=[]
for seg,new in (("known",False),("new",True)):
    a=I[(I.new_user==new)&(I.dead==0)]
    off=a[lfm.FEATS].values@np.array([base[seg]["w"].get(f,0) for f in lfm.FEATS])+base[seg]["b"]
    y=a.clk.values.astype(float); sw=np.where(a.buy==1,3.0,1.0)
    tr=((a.ts<cut)&(a.uh!=0)).values | ((a.uh>=2)).values*False
    tr=((a.ts<cut)).values & (a.uh!=0).values
    te=((a.ts>=cut)).values                       # later time (all users) ; te2 = later time AND held-out users
    te2=te & (a.uh==0).values
    Z0=np.column_stack([np.ones(len(a)),a.ls.values])
    th0,_=newton(Z0[tr],off[tr],y[tr],sw[tr]); l0=ll(Z0[te],off[te],th0,y[te],sw[te]); l02=ll(Z0[te2],off[te2],th0,y[te2],sw[te2])
    for name,f in F.items():
        x=f.loc[a.index].values.astype(float); nz=x>0
        Z=np.column_stack([Z0,x]); th,se=newton(Z[tr],off[tr],y[tr],sw[tr])
        rows.append((seg,name,int(nz.sum()),int(a.clk.values[nz].sum()),int(a.buy.values[nz].sum()),round(1e4*a.buy.values[nz].mean(),1) if nz.any() else 0,
                     round(th[2],3),round(se[2],3),round(th[2]/se[2],1),round(ll(Z[te],off[te],th,y[te],sw[te])-l0,2),round(ll(Z[te2],off[te2],th,y[te2],sw[te2])-l02,2)))
R=pd.DataFrame(rows,columns=["seg","feat","imp","clicks","buys","buys/10k","w","se","z","dLL_later","dLL_later_heldout_users"])
print(R.to_string(index=False))
a=I[I.dead==0]
print("\nbase rates buys/10k: all %.1f | islast %.1f | oinrv %.1f | ssub2 %.1f | scat2 %.1f"%(1e4*a.buy.mean(),1e4*a[a.islast==1].buy.mean(),1e4*a[a.oinrv==1].buy.mean(),1e4*a[a.ssub2==1].buy.mean(),1e4*a[a.scat2==1].buy.mean()))
print(a[a.back>=0].groupby(["new_user",a.back.clip(upper=3),a.cnt.clip(upper=2)]).agg(imp=("buy","size"),clk=("clk","sum"),buy=("buy","sum"),slot=("slot","mean")).assign(b10k=lambda x:(1e4*x.buy/x.imp).round(0)).to_string())
print(a[a.ssub2==1].groupby(["new_user",a.run.clip(upper=4)]).agg(imp=("buy","size"),clk=("clk","sum"),buy=("buy","sum"),slot=("slot","mean")).assign(b10k=lambda x:(1e4*x.buy/x.imp).round(1),c10k=lambda x:(1e4*x.clk/x.imp).round(1)).to_string())
print(a[a.ssub2==1].groupby(["new_user",pd.cut(a.age,[-2,5,20,60,120,1e4])]).agg(imp=("buy","size"),clk=("clk","sum"),buy=("buy","sum"),slot=("slot","mean")).assign(b10k=lambda x:(1e4*x.buy/x.imp).round(1),c10k=lambda x:(1e4*x.clk/x.imp).round(1)).to_string())
