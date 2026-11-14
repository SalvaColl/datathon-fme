import numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
X=pd.read_parquet('data/t031_HS.parquet')
base=0.05
f=pd.DataFrame(index=X.index)
f['ls']=np.log(X.slot); f['home']=X.home*1.; f['islast']=X.islast*1.; f['inrv']=X.inrv*1.; f['ssub']=X.ssub*1.; f['scat']=X.scat*1.; f['na']=X.na; f['sbrand']=X.sbrand*1.; f['iq']=X.iq
f['cart']=(X.state==2)*1.; f['bought']=(X.state>=3)*1.; f['viewed']=(X.state==1)*1.
f['aff10']=(np.minimum((X.v1+X.v2+2.0)/(2*X.vt+20),.35)-.10)*10
f['ucat']=(X.vc+.5)/(X.vt+5)-.1; f['usub']=(X.vs+5/90)/(X.vt+5)-1/90
f['hcart']=f.home*f.cart
# candidates
for nm,(wc,wp) in dict(w36=(3,6),w515=(5,15)).items():
    t=X.vt+wc*X.ct+wp*X.pt; s1=(X.v1+wc*X.c1+wp*X.p1+10*base)/(t+10); s2=(X.v2+wc*X.c2+wp*X.p2+10*base)/(t+10)
    f['L'+nm]=np.log(s1/base)+np.log(s2/base)
    f['C'+nm]=np.log(((X.vc+wc*X.ccn+wp*X.pc+.5)/(t+5))/.1)
s1=(X.v1+10*base)/(X.vt+10); s2=(X.v2+10*base)/(X.vt+10); f['Lv']=np.log(s1/base)+np.log(s2/base); f['Lmin']=np.log(np.minimum(s1,s2)/base)
f['Cv']=np.log(f.ucat+.1)-np.log(.1)
ru=(X.pt+1)/(X.vt+20); f['tb']=np.log(((X.p1+5*ru)/(X.v1+5))/ru)+np.log(((X.p2+5*ru)/(X.v2+5))/ru)
rc=(X.ct+2)/(X.vt+20); f['tcb']=np.log(((X.c1+5*rc)/(X.v1+5))/rc)+np.log(((X.c2+5*rc)/(X.v2+5))/rc)
f['tcat']=np.log(((X.pc+X.ccn+5*(ru+rc))/(X.vc+5))/(ru+rc))
f['ubuy']=np.log(ru); f['uact']=np.log1p(X.vt)
f['aff_iq']=f.aff10*f.iq; f['ucat_iq']=f.ucat*f.iq; f['aff_ucat']=f.aff10*f.ucat; f['cart_iq']=f.cart*f.iq; f['cart_aff']=f.cart*f.aff10; f['cart_ucat']=f.cart*f.ucat
tr=(X.u%2==0).values; te=~tr
y=X.buy.values.astype(int); yc=X.clk.values.astype(int)
B=['ls','home','islast','inrv','ssub','scat','na','sbrand','iq','cart','bought','viewed','aff10','ucat','usub','hcart']
def ev(name,cols):
    m=LogisticRegression(C=10,max_iter=300).fit(f.loc[tr,cols],yc[tr],sample_weight=np.where(y[tr]==1,3.,1.))
    z=f[cols].values@m.coef_[0]+m.intercept_[0]
    c=LogisticRegression(C=100,max_iter=300).fit(z[tr].reshape(-1,1),y[tr]); p=c.predict_proba(z[te].reshape(-1,1))[:,1]
    ll=np.sum(np.where(y[te]==1,np.log(p),np.log1p(-p)))
    zs=z-m.coef_[0][0]*f.ls.values   # serving score
    g=pd.DataFrame(dict(r=X.rid.values[te],z=zs[te],b=y[te],k=yc[te])); g['rank']=g.groupby('r').z.rank(ascending=False)
    # policy value proxy: IPS-free "regret": among requests with a buy, share where bought item ranked top1/top3
    gb=g[g.b==1]; gk=g[g.k==1]
    print(f'{name:34s} buy ll {ll:10.1f} | bought item rank: top1 {np.mean(gb["rank"]<=1):.4f} top3 {np.mean(gb["rank"]<=3):.4f} mrr {np.mean(1/gb["rank"]):.4f} | click mrr {np.mean(1/gk["rank"]):.4f}',flush=True)
    return dict(zip(cols,m.coef_[0].round(3)))
print('test buys',y[te].sum(),'clicks',yc[te].sum())
print(ev('base (lfm r3-like)',B))
print(ev('+ user buy propensity',B+['ubuy','uact']))
B2=B+['ubuy','uact']
print(ev('+ weighted log taste 3/6',B2+['Lw36','Cw36']))
print(ev('+ weighted log taste 5/15',B2+['Lw515','Cw515']))
print(ev('+ view log taste',B2+['Lv','Cv','Lmin']))
print(ev('+ buy/cart-rate taste',B2+['tb','tcb','tcat']))
print(ev('+ interactions',B2+['aff_iq','ucat_iq','aff_ucat','cart_iq','cart_aff','cart_ucat']))
print(ev('+ everything',B2+['Lw36','Cw36','Lv','Cv','Lmin','tb','tcb','tcat','aff_iq','ucat_iq','aff_ucat','cart_iq','cart_aff','cart_ucat']))
f.assign(buy=y,clk=yc,rid=X.rid.values,u=X.u.values,slot=X.slot.values).to_parquet('data/t031_HSF.parquet')
