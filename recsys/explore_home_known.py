"""T-021: home de usuario conocido, solo lectura (E-134). Requiere `lfm_I.parquet` / `lfm_d.parquet` generados por
`lfm_build.py --pull --no-write` de la rama `javi/lfm-v2` (PR #11) y `lfm_coef_r2.json`. Uso: `cd recsys && python explore_home_known.py`.
Ajusta un modelo solo-home (split temporal 70/30) y lo compara en hold-out con la puntuación de servicio de lfm r2."""
import pandas as pd, numpy as np, json, warnings; warnings.filterwarnings("ignore")
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score as auc
import lfm
I=pd.read_parquet("data/lfm_I.parquet"); d=pd.read_parquet("data/lfm_d.parquet")
I=I.merge(d[["served_by"]],left_on="rid",right_index=True)
H=I[(I.page=="home")&(~I.new_user)&(I.dead==0)&(I.served_by=="team")].copy()
H["cart"]=((H.chn>0)|(H.cl>0)).astype(float); H["clq"]=H.cart*H.lq; H["nlq"]=(1-H.cart)*H.lq; H["caff"]=H.cart*H.aff10; H["naff"]=(1-H.cart)*H.aff10
print("home known live impressions",len(H),"req",H.rid.nunique(),"clicks",H.clk.sum(),"buys",H.buy.sum(), "cart share",H.cart.mean().round(3))
print(H.groupby("cart").agg(n=("clk","size"),clk=("clk","sum"),buy=("buy","sum"),aff=("aff10","mean"),lq=("lq","mean")))
print("non-cart by aff10"); print(H[H.cart==0].groupby(pd.cut(H.aff10,[-2,0,.5,1,1.5,2.6])).agg(n=("clk","size"),clk=("clk","sum"),buy=("buy","sum")).assign(bp=lambda x:1e4*x.clk/x.n))
print("cart by aff10"); print(H[H.cart==1].groupby(pd.cut(H.aff10,[-2,0,.5,1,1.5,2.6])).agg(n=("clk","size"),clk=("clk","sum"),buy=("buy","sum"),slot=("slot","mean")).assign(bp=lambda x:1e4*x.clk/x.n))
print("cart by lq"); print(H[H.cart==1].groupby(pd.qcut(H.lq,4)).agg(n=("clk","size"),clk=("clk","sum"),buy=("buy","sum"),slot=("slot","mean")).assign(bp=lambda x:1e4*x.clk/x.n))
cut=H.ts.quantile(0.7); tr=H[H.ts<cut]; te=H[H.ts>=cut]
r2=json.load(open("lfm_coef_r2.json")); w2=np.array([r2["known"]["w"].get(f,0) for f in lfm.FEATS])
def run(cols,C=1.0,D=tr):
    m=LogisticRegression(C=C,max_iter=5000).fit(D[cols+["ls"]],D.clk,sample_weight=np.where(D.buy==1,3.0,1.0)); return m
for name,cols in [("A cart+chn+cl+lq+aff",["cart","chn","cl","lq","aff10","p40"]),("B split lq/aff by cart",["cart","chn","cl","clq","nlq","caff","naff","p40"]),("C cart only",["cart"])]:
    m=run(cols); z=te[cols].values@m.coef_[0][:-1]
    g=pd.DataFrame(dict(rid=te.rid.values,z=z,clk=te.clk.values,buy=te.buy.values)); g["rank"]=g.groupby("rid").z.rank(ascending=False,method="average")
    print(name,dict(zip(cols+["ls"],m.coef_[0].round(2))),"| test AUC click %.3f (n clicks %d, buys %d) mrr_click %.3f"%(auc(te.clk,z),te.clk.sum(),te.buy.sum(),(1/g[g.clk==1]["rank"]).mean()))
z=te[lfm.FEATS].values@w2; g=pd.DataFrame(dict(rid=te.rid.values,z=z,clk=te.clk.values)); g["rank"]=g.groupby("rid").z.rank(ascending=False,method="average")
print("r2 serving score: test AUC click %.3f mrr_click %.3f"%(auc(te.clk,z),(1/g[g.clk==1]["rank"]).mean()))
m=run(["cart","chn","cl","lq","aff10","p40"],D=H); print("FULL fit A",dict(zip(["cart","chn","cl","lq","aff10","p40","ls"],m.coef_[0].round(3))),m.intercept_.round(3))
m=run(["cart","chn","cl","clq","nlq","caff","naff","p40"],D=H); print("FULL fit B",dict(zip(["cart","chn","cl","clq","nlq","caff","naff","p40","ls"],m.coef_[0].round(3))),m.intercept_.round(3))
