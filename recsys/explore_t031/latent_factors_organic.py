import numpy as np, pandas as pd, sys, scipy.sparse as sp
from scipy.sparse.linalg import svds
sys.path.insert(0,'.')
import cold_items
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
cat=pd.read_parquet('data/lfm_cat.parquet').set_index('product_id')
pidx={p:k for k,p in enumerate(cat.index)}; N=len(cat)
A=np.zeros((N,20))
for p,d in cat.description.items(): A[pidx[p],list(cold_items.attrs(d))]=1
a=pd.read_parquet('data/user_item_A.parquet'); al=pd.read_parquet('data/user_item_all.parquet')
a=a[a.i.isin(pidx)]; al=al[al.i.isin(pidx)]
m=al.merge(a,on=['u','i'],how='left',suffixes=('','A')).fillna(0)
b=m[(m.vA==0)&(m.aA==0)&(m.pA==0)&(m.v>0)]
users=pd.Index(a.u.unique()); uc=users.get_indexer(a.u); ik=a.i.map(pidx).values; n=len(users)
w=np.log1p(a.v.values+3*a.a.values+6*a.p.values)
M=sp.csr_matrix((w,(uc,ik)),shape=(n,N))
V=np.zeros((n,20)); np.add.at(V,uc,A[ik]*a.v.values[:,None])
cc,cats=pd.factorize(cat.category); sc,subs=pd.factorize(cat['sub'])
VC=np.zeros((n,len(cats))); np.add.at(VC,(uc,cc[ik]),a.v.values); VS=np.zeros((n,len(subs))); np.add.at(VS,(uc,sc[ik]),a.v.values)
b=b[b.u.isin(users)]; bu=users.get_indexer(b.u); bi=b.i.map(pidx).values
y=(b.p>0).values.astype(float)
t=VC.sum(1)
aff=((V[bu]*A[bi]).sum(1)+2.0)/(V[bu].sum(1)+20)
ucat=(VC[bu,cc[bi]]+.5)/(t[bu]+5); usub=(VS[bu,sc[bi]]+5/90)/(t[bu]+5)
iv=np.bincount(ik,weights=a.v.values,minlength=N); ip=np.bincount(ik,weights=a.p.values,minlength=N)
ir=np.log((ip+2)/(iv+50))[bi]
ub=np.log((np.bincount(uc,weights=a.p.values,minlength=n)+1)/(t+20))[bu]
tr=np.random.default_rng(0).random(len(y))<.5
def ev(name,*f):
    X=np.column_stack(f); mdl=LogisticRegression(max_iter=2000).fit(X[tr],y[tr]); p=mdl.predict_proba(X[~tr])[:,1]
    ll=np.mean(np.where(y[~tr]==1,np.log(p),np.log1p(-p)))
    print(f'{name:40s} auc {roc_auc_score(y[~tr],p):.4f} ll {ll:.5f} coef {mdl.coef_[0].round(2)}',flush=True)
basef=(aff,ucat,usub,ir,ub)
ev('attrs+cat+sub+item rate+user rate',*basef)
for k in (16,64):
    U,S,Vt=svds(M.astype(np.float32),k=k)
    mf=np.einsum('ij,ij->i',U[bu]*S,Vt.T[bi])
    ev(f'svd k={k} alone',mf,ub); ev(f'base + svd k={k}',*basef,mf)
# residual MF: remove user and item means and attr structure? item-item cosine to the user's viewed items within same subcategory
Mn=sp.csr_matrix((np.ones(len(w)),(uc,ik)),shape=(n,N)); 
co=(Mn.T@Mn).toarray(); dg=np.sqrt(np.diag(co))+1e-9; co=co/dg[:,None]/dg[None,:]; np.fill_diagonal(co,0)
# user's item-item score: mean cosine between candidate and user's history items
sc_ii=np.zeros(len(b)); 
order=np.argsort(bu); 
Mc=Mn.tocsr()
start=0
bus=bu[order]; bis=bi[order]
bounds=np.flatnonzero(np.diff(bus))+1; bounds=np.r_[0,bounds,len(bus)]
for s,e in zip(bounds[:-1],bounds[1:]):
    u=bus[s]; h=Mc.indices[Mc.indptr[u]:Mc.indptr[u+1]]
    if len(h): sc_ii[order[s:e]]=co[np.ix_(bis[s:e],h)].mean(1)
ev('base + item-item cosine',*basef,sc_ii)
