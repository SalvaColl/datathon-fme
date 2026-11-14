import pandas as pd, numpy as np, joblib
from fe import FEATS
X=pd.read_parquet("data/train_X.parquet"); te=X[X.ts>="2026-11-04"].copy()
m=joblib.load("data/model_buy.joblib")
Z=te[FEATS].copy(); Z["slot"]=0
te["s"]=m.predict_proba(Z)[:,1]
b=te[te.sid.isin(te.loc[te.y==1,"sid"])].copy()
def rank_of(score):
    b["_r"]=b.groupby("sid")[score].rank(ascending=False,method="first")
    r=b.loc[b.y==1,"_r"]; return dict(hit1=(r==1).mean().round(3),mrr=(1/r).mean().round(3))
b["logged"]=-b.slot
b["h_view"]=b.in_rv*10+b.same_sub*2+b.cr*10
b["h_cart"]=b.ui_a*5+b.in_rv*10+b.same_sub*2+b.cart*20
b["rand"]=np.random.rand(len(b))
for s in ["rand","logged","h_view","h_cart","s"]: print(s, rank_of(s))
print("buy sessions",b.sid.nunique())
# within-session model: train on buying sessions of train split
tr=X[(X.ts<"2026-11-04")]; tr=tr[tr.sid.isin(tr.loc[tr.y==1,"sid"])]
from sklearn.ensemble import HistGradientBoostingClassifier
F2=[f for f in FEATS if f not in ("ut_v","ut_p","known","new_user","page_home","n_rv")]
m2=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,min_samples_leaf=100,early_stopping=False).fit(tr[F2],tr.y)
Z=b[F2].copy(); Z["slot"]=0; b["s2"]=m2.predict_proba(Z)[:,1]; print("within model",rank_of("s2"))
Z=b[F2].copy(); b["s2slot"]=m2.predict_proba(Z)[:,1]; print("within model w/ logged slot",rank_of("s2slot"))
from sklearn.inspection import permutation_importance
r=permutation_importance(m2,tr[F2].sample(100000,random_state=0),tr.y.sample(100000,random_state=0),scoring="roc_auc",n_repeats=2)
print(pd.Series(r.importances_mean,F2).sort_values(ascending=False).round(4).head(15))
joblib.dump((m2,F2),"data/model_within.joblib")
