import sys, json, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0,'.')
import lfm
from sklearn.linear_model import LogisticRegression
import lightgbm as lgb
I=pd.read_parquet('data/t031_I.parquet'); d=pd.read_parquet('data/t031_d2.parquet'); cells=pd.read_parquet('data/t031_cells.parquet')
I['bin']=d['bin'].reindex(I.rid.values).values; I['team']=(d.served_by=='team').reindex(I.rid.values).values; I['mv']=d.mv.reindex(I.rid.values).values
bins=np.sort(cells.bin.unique()); K=6
fold_of={b:int(k*K/len(bins)) for k,b in enumerate(bins)}
I['fold']=I.bin.map(fold_of).fillna(-1).astype(int)   # bins without cells: always train
F=lfm.FEATS
def lin(feats):
    def f(tr,te,seg):
        cols=feats+['ls']
        m=LogisticRegression(C=10,max_iter=3000).fit(tr[cols],tr.clk,sample_weight=np.where(tr.buy==1,3.0,1.0))
        z=tr[cols].values@m.coef_[0]+m.intercept_[0]; c=LogisticRegression(C=100,max_iter=3000).fit(z.reshape(-1,1),tr.buy)
        zt=te[cols].values@m.coef_[0]+m.intercept_[0]; return c.predict_proba(zt.reshape(-1,1))[:,1]
    return f
def gbm(feats,label='clk',**kw):
    def f(tr,te,seg):
        cols=feats+['slot']
        p=dict(objective='binary',learning_rate=0.05,num_leaves=15,min_data_in_leaf=200,feature_fraction=0.8,lambda_l2=10,verbose=-1,num_threads=4); p.update(kw)
        m=lgb.train(p,lgb.Dataset(tr[cols],tr[label],weight=np.where(tr.buy==1,3.0,1.0) if label=='clk' else None),200)
        z=m.predict(tr[cols],raw_score=True); c=LogisticRegression(C=100,max_iter=3000).fit(z.reshape(-1,1),tr.buy)
        return c.predict_proba(m.predict(te[cols],raw_score=True).reshape(-1,1))[:,1]
    return f
def run(name,fitter,extra=None):
    J=I if extra is None else extra
    p=np.zeros(len(J))
    for k in range(K):
        for seg,new in (('known',False),('new',True)):
            a=(J.new_user==new).values; tr=J[a&(J.fold!=k).values&(J.dead==0).values]; tem=a&(J.fold==k).values
            if tem.sum(): p[tem]=fitter(tr,J[tem],seg)
    p[J.dead.values==1]=0
    v=pd.DataFrame(dict(bin=J.bin.values,mv=J.mv.values,v=p,team=J.team.values,buy=J.buy.values))
    v=v[v.team&(J.fold.values>=0)].groupby(['bin','mv']).v.sum().rename('pred').reset_index()
    m=cells.merge(v,on=['bin','mv']); w=1/np.sqrt(m.N.values)
    segs=['k','n','kh','nh']
    def rss(cols):
        X=m[cols].values*w[:,None]; Y=m.hs.values*w; b,*_=np.linalg.lstsq(X,Y,rcond=None); return ((Y-X@b)**2).sum(), b
    r0,_=rss(segs); r1,b=rss(segs+['pred']); raw=(((m.hs-m.pred)*w)**2).sum()
    # impression-level realized loglik out of fold
    ok=(J.fold.values>=0)&(J.dead.values==0); pp=np.clip(p[ok],1e-9,1-1e-9); y=J.buy.values[ok]
    ll=np.sum(np.where(y==1,np.log(pp),np.log1p(-pp)))
    print(f'{name:38s} cells {len(m)} | explained beyond segments {1-r1/r0:.3f} slope {b[-1]:.2f} | raw rss {raw:.3f} (seg-only {r0:.3f}) | pred {m.pred.sum():.0f} vs hidden {m.hs.sum():.0f} | realized loglik {ll:.1f}',flush=True)
    return p
if __name__=='__main__':
    run('lfm r1 feats linear',lin(lfm.FEATS[:11]))
    run('lfm r3 feats linear',lin(lfm.FEATS[:19]))
    run('lfm all feats linear',lin(F))
    run('gbm all feats (click)',gbm(F))
    run('gbm all feats (buy label)',gbm(F,label='buy'))
    run('gbm deeper',gbm(F,num_leaves=63,min_data_in_leaf=100))
