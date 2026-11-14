import numpy as np, pandas as pd, sys, glob
sys.path.insert(0,'.')
import cold_items
cat=pd.read_parquet('data/lfm_cat.parquet').set_index('product_id')
pidx={p:k for k,p in enumerate(cat.index)}; N=len(cat)
A=np.zeros((N,20),dtype=np.float32)
for p,d in cat.description.items(): A[pidx[p],list(cold_items.attrs(d))]=1
at=np.array([np.flatnonzero(r) for r in A])
cc,cats=pd.factorize(cat.category); sc,subs=pd.factorize(cat['sub']); bc,_=pd.factorize(cat.brand)
a=pd.read_parquet('data/user_item_A.parquet'); a=a[a.i.isin(pidx)]
users=pd.Index(a.u.unique()); uc=users.get_indexer(a.u); ik=a.i.map(pidx).values; n=len(users)
v,c,p=(a[x].values.astype(np.float32) for x in 'vap')
def agg(w):
    M=np.zeros((n+1,20),dtype=np.float32); np.add.at(M,uc,A[ik]*w[:,None]); return M
def aggc(w,code,k):
    M=np.zeros((n+1,k),dtype=np.float32); np.add.at(M,(uc,code[ik]),w); return M
V,C,P=agg(v),agg(c),agg(p); VC,CC,PC=aggc(v,cc,len(cats)),aggc(c,cc,len(cats)),aggc(p,cc,len(cats)); VS=aggc(v,sc,len(subs))
import scipy.sparse as sp
st=sp.csr_matrix((1+ (c>0)*1+ (p>0)*2,(uc,ik)),shape=(n+1,N))  # 1 viewed, 2 carted, 3 bought only, 4 carted+bought
iv=np.bincount(ik,weights=v,minlength=N); ip=np.bincount(ik,weights=p,minlength=N); ic=np.bincount(ik,weights=c,minlength=N)
iq=np.log((ip+2)/(iv+50)); 
files=sorted(glob.glob('data/t031_hs_*.parquet'))
out=[]
for f in files:
    h=pd.read_parquet(f); h=h[h.u.isin(users)]   # known users only (history has no new users)
    R=len(h); sh=np.array([[pidx.get(x,-1) for x in s.split(',')] for s in h.shown.values]); ok=(sh>=0).all(1)&(sh.shape[1]==10)
    h=h[ok]; sh=sh[ok]; R=len(h)
    u=users.get_indexer(h.u.values); U=np.repeat(u,10); Iy=sh.ravel(); slot=np.tile(np.arange(1,11),R)
    clk=np.array([pidx.get(x,-2) for x in h.clicked.values]); buy=np.array([pidx.get(x,-2) for x in h.purchased.values])
    rv=[[pidx[x] for x in s.split(',') if x in pidx] if s else [] for s in h.rv.values]
    last=np.array([r[-1] if r else -1 for r in rv]); L=np.repeat(last,10); hasl=L>=0; Ls=np.where(hasl,L,0)
    inrv=np.zeros(R*10,dtype=bool)
    for k,r in enumerate(rv):
        if r: inrv[k*10:(k+1)*10]=np.isin(sh[k],r)
    k1,k2=at[Iy,0],at[Iy,1]
    D=dict(rid=np.repeat(np.arange(R),10)+len(out)*10_000_000,u=U,i=Iy,slot=slot,clk=(Iy==np.repeat(clk,10)),buy=(Iy==np.repeat(buy,10)),home=np.repeat(h.page.values=='home',10),
      islast=(Iy==L),inrv=inrv&(Iy!=L),ssub=hasl&(sc[Iy]==sc[Ls])&~inrv,scat=hasl&(cc[Iy]==cc[Ls])&(sc[Iy]!=sc[Ls])&~inrv,na=np.where(hasl&~inrv,(A[Iy]*A[Ls]).sum(1),0),
      sbrand=hasl&(bc[Iy]==bc[Ls]),iq=iq[Iy],state=np.asarray(st[U,Iy]).ravel(),
      v1=V[U,k1],v2=V[U,k2],c1=C[U,k1],c2=C[U,k2],p1=P[U,k1],p2=P[U,k2],vt=V[U].sum(1)/2,ct=C[U].sum(1)/2,pt=P[U].sum(1)/2,
      vc=VC[U,cc[Iy]],ccn=CC[U,cc[Iy]],pc=PC[U,cc[Iy]],vs=VS[U,sc[Iy]])
    out.append(pd.DataFrame(D)); print(f,R,flush=True)
X=pd.concat(out,ignore_index=True); X.to_parquet('data/t031_HS.parquet'); print(X.shape, X.clk.mean(), X.buy.mean())
