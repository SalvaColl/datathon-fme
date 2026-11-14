import pandas as pd, numpy as np, json, time, joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from fe import build_tables, featurize, FEATS
t=time.time()
T=build_tables(pd.read_parquet("data/user_item_A.parquet")); print("tables",time.time()-t,flush=True)
hs=pd.read_parquet("data/hs.parquet"); hs=hs[hs.ts>="2026-10-15 07:00"]
hs=hs.sample(250000,random_state=2)
hs["rv"]=hs.rv.map(lambda s:[x["product_id"] for x in json.loads(s)]); hs["shown"]=hs.shown.map(json.loads)
hs["sid"]=np.arange(len(hs))
P=hs[["sid","user_id","rv","page","shown","purchased","clicked","ts"]].explode("shown").rename(columns={"user_id":"u","shown":"i"})
P["slot"]=P.groupby("sid").cumcount(); P["new_user"]=0
P["y"]=(P.i==P.purchased).astype(int); P["yc"]=(P.i==P.clicked).astype(int)
X=featurize(P,T,"2026-10-15"); print("feat",time.time()-t,len(X),flush=True)
X.to_parquet("data/train_X.parquet")
tr=X[X.ts<"2026-11-04"]; te=X[X.ts>="2026-11-04"]
m=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,l2_regularization=1.0,early_stopping=False)
m.fit(tr[FEATS],tr.y)
from sklearn.metrics import roc_auc_score
p=m.predict_proba(te[FEATS])[:,1]; print("AUC buy",roc_auc_score(te.y,p), "logloss-ish mean p",p.mean(),te.y.mean())
from sklearn.inspection import permutation_importance
s=te.sample(200000,random_state=0)
r=permutation_importance(m,s[FEATS],s.y,scoring="roc_auc",n_repeats=2,random_state=0)
print(pd.Series(r.importances_mean,FEATS).sort_values(ascending=False).round(4).head(20))
joblib.dump(m,"data/model_buy.joblib")
